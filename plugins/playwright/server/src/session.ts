// The MCP server the client talks to: every stock @playwright/mcp tool, forwarded unchanged to an
// in-process stock server, plus browser_session, which relaunches the browser in another state.
//
// One state at a time. Each state gets its own stock connection (createConnection over an
// in-memory transport) whose contextGetter hands it the browser this server launched, so
// switching state means preparing a new connection and browser, then swapping the old ones out.
// The tool list is read from the current stock server on every request, because stock adds tools
// at runtime (WebMCP tools registered by the page) and announces them with tools/list_changed.

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import {
  CallToolRequestSchema,
  CallToolResultSchema,
  ListRootsRequestSchema,
  ListToolsRequestSchema,
  ListToolsResultSchema,
  ToolListChangedNotificationSchema,
  type CallToolRequest,
  type CallToolResult,
  type Root,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { createConnection } from "@playwright/mcp";
import { launchBrowser, profileDir, rootPathFromRoots, type BrowserState, type OwnedBrowser } from "./browser.js";
import { PROFILE_MODES, type Env, type ProfileMode } from "./config.js";
import type { TunnelInfo, TunnelSource } from "./tunnels.js";

export const SESSION_TOOL = "browser_session";

// Forwarded calls must not end at the SDK's 60 s default: a slow page or a long evaluate is the
// stock server's business, and the outer client enforces its own limit. Under setTimeout's cap.
const FORWARD_TIMEOUT_MS = 24 * 60 * 60 * 1000;

export interface SessionOptions {
  // The state the session starts in; the browser itself launches on the first tool call.
  initial: BrowserState;
  serverInfo: { name: string; version: string };
  env?: Env;
  log?: (message: string) => void;
  // VPN regions, when the project configures geo; without them browser_session has no `region`.
  tunnels?: TunnelSource;
}

// Where the browser's traffic goes: a VPN region's tunnel, or directly (region null).
export interface Route {
  region: string | null;
  tunnel?: TunnelInfo;
}

const DIRECT: Route = { region: null };

export interface SessionStatus extends Route {
  profile: ProfileMode;
}

// One stock server and the browser it drives, both for a single state.
interface Inner {
  readonly state: BrowserState;
  readonly route: Route;
  readonly client: Client;
  owned: OwnedBrowser | undefined;
}

function sessionTool({ regions }: { regions: boolean }): Tool {
  return {
    name: SESSION_TOOL,
    title: "Browser session",
    description:
      `Relaunch the browser in the given profile${regions ? " and VPN region" : ""}; open tabs close. ` +
      '"fresh": a clean, independent session that keeps nothing - use it for testing applications and reproducible checks; calling it again resets the state. ' +
      '"persistent": this project\'s saved profile with the user\'s logins, kept across restarts - use it only when the work needs accounts the user is signed into; another session in the same project may hold it. ' +
      (regions
        ? "A region sends only the browser through a VPN; the result's tunnel.ipGeolocation is ipinfo's database as seen by the VPN container and may differ from the location the tested service sees - confirm the location with the service itself. "
        : "") +
      "Omitted parameters keep their current value. Returns the active settings.",
    inputSchema: {
      type: "object",
      properties: {
        profile: { type: "string", enum: [...PROFILE_MODES], description: "Browser profile to use" },
        ...(regions && {
          region: {
            type: ["string", "null"],
            description:
              'VPN region name of the project\'s provider, e.g. "US Texas"; null connects directly. An unknown name fails with the valid ones. The first start may take a few minutes (image and server list download).',
          },
        }),
      },
      additionalProperties: false,
    },
    annotations: { title: "Browser session", readOnlyHint: false, destructiveHint: true, openWorldHint: false },
  };
}

export class BrowserSession {
  readonly server: Server;
  private readonly env: Env;
  private readonly log: (message: string) => void;
  private readonly initial: BrowserState;
  private readonly serverInfo: { name: string; version: string };
  private readonly tunnels: TunnelSource | undefined;
  private current: Inner | undefined;
  // Launching, closing and swapping run one at a time: a persistent profile admits one browser.
  private queue: Promise<void> = Promise.resolve();
  private closing: Promise<void> | undefined;

  constructor(options: SessionOptions) {
    this.initial = options.initial;
    this.serverInfo = options.serverInfo;
    this.env = options.env ?? process.env;
    this.tunnels = options.tunnels;
    this.log = options.log ?? ((message) => console.error(`playwright-mcp: ${message}`));
    this.server = new Server(options.serverInfo, { capabilities: { tools: { listChanged: true } } });

    this.server.setRequestHandler(ListToolsRequestSchema, async (request, extra) => {
      const result = await this.inner().client.request({ method: "tools/list", params: request.params }, ListToolsResultSchema, {
        signal: extra.signal,
      });
      return { ...result, tools: [...result.tools, sessionTool({ regions: this.tunnels !== undefined })] };
    });

    this.server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
      if (request.params.name === SESSION_TOOL) return this.callSessionTool(request.params.arguments);
      const inner = this.inner();
      const result = await this.forward(inner, request.params, extra.signal);
      // Stock only disposes its backend on browser_close; closing the context makes it start
      // over on the next call, in the current state.
      if (request.params.name === "browser_close") await this.exclusive(async () => inner.owned?.close());
      return result;
    });
  }

  get state(): BrowserState {
    return this.inner().state;
  }

  // The running browser, if any. It launches on demand, so undefined until a tool needs it.
  get browser(): OwnedBrowser | undefined {
    return this.current?.owned;
  }

  get route(): Route {
    return this.inner().route;
  }

  get status(): SessionStatus {
    const { region, tunnel } = this.route;
    return { profile: this.state.profile, region, ...(tunnel && { tunnel }) };
  }

  async connect(transport: Transport): Promise<void> {
    this.current = await this.createInner(this.initial, DIRECT);
    await this.server.connect(transport);
  }

  // Relaunches the browser in `target` and makes it current. Atomic: when the new browser does
  // not start, the previous state stays current, with its browser running again if it had to stop.
  // `route` describes target.proxy; a tunnel is acquired before, as it is the only step whose
  // failure must not touch the running browser.
  switchTo(target: BrowserState, route: Route = DIRECT): Promise<void> {
    return this.exclusive(async () => {
      this.assertOpen();
      const old = this.inner();
      const rootPath = await this.rootPath();
      const oldBrowser = old.owned;
      // Chrome locks a persistent profile, so the old browser has to go before the new one starts.
      const releasedFirst =
        target.profile === "persistent" && oldBrowser?.profileDir !== undefined && oldBrowser.profileDir === profileDir(rootPath, this.env);
      if (releasedFirst) await oldBrowser.close();

      let owned: OwnedBrowser | undefined;
      let next: Inner;
      try {
        owned = await launchBrowser(target, { rootPath, env: this.env });
        next = await this.createInner(target, route);
      } catch (e) {
        await owned?.close().catch((closeError: unknown) => this.log(`closing the browser failed: ${message(closeError)}`));
        if (releasedFirst) await this.restore(old, rootPath, e);
        throw e;
      }
      this.adopt(next, owned);
      this.current = next;
      await this.dispose(old);
      await this.server.sendToolListChanged().catch((e: unknown) => this.log(`tools/list_changed failed: ${message(e)}`));
    });
  }

  // Ends the session: the stock server, the browser and the MCP connection. Safe to call twice.
  close(): Promise<void> {
    this.closing ??= this.exclusive(async () => {
      const inner = this.current;
      if (inner) await this.dispose(inner);
    }).finally(() => this.server.close());
    return this.closing;
  }

  private async callSessionTool(args: Record<string, unknown> | undefined): Promise<CallToolResult> {
    const request = this.parseSessionArgs(args ?? {});
    if (typeof request === "string") return errorResult(`Invalid arguments for ${SESSION_TOOL}:\n- ${request}`);
    const region = request.region === undefined ? this.route.region : request.region;
    try {
      let proxy: BrowserState["proxy"];
      let route = DIRECT;
      if (region !== null) {
        if (!this.tunnels) throw new Error("VPN regions are not configured for this project");
        // Even the current region: the pool checks its tunnel and reports its current IP.
        const tunnel = await this.tunnels.acquire(region, this.route.region);
        proxy = tunnel.proxy;
        route = { region: tunnel.region, tunnel: { publicIp: tunnel.publicIp, ipGeolocation: tunnel.ipGeolocation } };
      }
      await this.switchTo({ profile: request.profile, proxy }, route);
    } catch (e) {
      return errorResult(`${this.stays()} ${message(e)}`);
    }
    return { content: [{ type: "text", text: JSON.stringify(this.status) }] };
  }

  // The requested profile and region (undefined: keep the current one), or the problems found.
  private parseSessionArgs(args: Record<string, unknown>): { profile: ProfileMode; region: string | null | undefined } | string {
    const problems: string[] = [];
    for (const key of Object.keys(args)) {
      if (key === "profile") continue;
      if (key === "region" && this.tunnels) continue;
      problems.push(
        key === "region"
          ? "region: VPN regions are not configured for this project (geo in .claude/playwright.json)"
          : `${key}: unknown parameter`
      );
    }
    const profile = args.profile === undefined ? this.state.profile : PROFILE_MODES.find((m) => m === args.profile);
    if (profile === undefined) problems.push(`profile: expected one of ${PROFILE_MODES.map((m) => `"${m}"`).join(", ")}`);
    let region: string | null | undefined;
    if (this.tunnels && args.region !== undefined) {
      if (args.region === null) region = null;
      else if (typeof args.region === "string" && args.region.trim()) region = args.region.trim();
      else problems.push("region: expected a region name or null");
    }
    if (problems.length || profile === undefined) return problems.join("\n- ");
    return { profile, region };
  }

  // What a failed browser_session leaves in place.
  private stays(): string {
    const { region } = this.route;
    const where = !this.tunnels ? "" : region ? ` via ${region}` : ", connected directly";
    return `The browser stays in the ${this.state.profile} profile${where}.`;
  }

  private async forward(inner: Inner, params: CallToolRequest["params"], signal: AbortSignal): Promise<CallToolResult> {
    try {
      return await inner.client.request({ method: "tools/call", params }, CallToolResultSchema, { timeout: FORWARD_TIMEOUT_MS, signal });
    } catch (e) {
      // Stock reports failures as tool errors; so does the wrapper when the stock server is gone
      // (a switch closed it mid-call).
      return errorResult(message(e));
    }
  }

  private async createInner(state: BrowserState, route: Route): Promise<Inner> {
    const client = new Client(this.serverInfo, { capabilities: { roots: {} } });
    const inner: Inner = { state, route, client, owned: undefined };
    // Stock computes its output directory from the client's roots; it sees the outer client's.
    client.setRequestHandler(ListRootsRequestSchema, async () => ({ roots: await this.roots() }));
    client.setNotificationHandler(ToolListChangedNotificationSchema, async () => {
      if (this.current !== inner) return;
      await this.server.sendToolListChanged().catch((e: unknown) => this.log(`tools/list_changed failed: ${message(e)}`));
    });
    // Never `browser.isolated`: stock would ask the getter's browser for a new context, which it refuses.
    const server = await createConnection({}, async () => (await this.browserFor(inner)).context);
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    await server.connect(serverTransport);
    await client.connect(clientTransport);
    return inner;
  }

  // The stock contextGetter: the inner's browser, launched now if it is not running.
  private async browserFor(inner: Inner): Promise<OwnedBrowser> {
    if (inner.owned) return inner.owned;
    return this.exclusive(async () => {
      this.assertOpen();
      if (inner.owned) return inner.owned;
      if (this.current !== inner) throw new Error("The browser session was switched; call the tool again.");
      const owned = await launchBrowser(inner.state, { rootPath: await this.rootPath(), env: this.env });
      this.adopt(inner, owned);
      return owned;
    });
  }

  // The browser belongs to `inner` until its context closes, however that happens: close(),
  // browser_close, the user quitting the browser, a crash. Released on the context's close event
  // itself, as stock drops its backend then: a fresh browser still shutting down must not be
  // handed out again.
  private adopt(inner: Inner, owned: OwnedBrowser): void {
    inner.owned = owned;
    owned.context.once("close", () => {
      if (inner.owned === owned) inner.owned = undefined;
    });
    owned.closed.catch((e: unknown) => this.log(`shutting the browser down failed: ${message(e)}`));
  }

  private async restore(old: Inner, rootPath: string, cause: unknown): Promise<void> {
    try {
      this.adopt(old, await launchBrowser(old.state, { rootPath, env: this.env }));
    } catch (e) {
      // The state is still the old one; the next browser tool tries to launch it again.
      throw new Error(`${message(cause)} Reopening the ${old.state.profile} profile failed as well: ${message(e)}`, { cause });
    }
  }

  private async dispose(inner: Inner): Promise<void> {
    await inner.client.close().catch((e: unknown) => this.log(`closing the Playwright server failed: ${message(e)}`));
    await inner.owned?.close().catch((e: unknown) => this.log(`closing the browser failed: ${message(e)}`));
  }

  // The outer client's roots, asked anew each time like stock does; none if it has no roots.
  private async roots(): Promise<Root[]> {
    if (!this.server.getClientCapabilities()?.roots) return [];
    const { roots } = await this.server.listRoots().catch((e: unknown) => {
      this.log(`roots/list failed: ${message(e)}`);
      return { roots: [] };
    });
    return roots;
  }

  private async rootPath(): Promise<string> {
    return rootPathFromRoots(await this.roots());
  }

  private inner(): Inner {
    if (!this.current) throw new Error("The browser session is not connected");
    return this.current;
  }

  private assertOpen(): void {
    if (this.closing) throw new Error("The browser session is closing");
  }

  private exclusive<T>(fn: () => Promise<T>): Promise<T> {
    const run = this.queue.then(fn);
    this.queue = run.then(
      () => undefined,
      () => undefined
    );
    return run;
  }
}

function errorResult(text: string): CallToolResult {
  return { content: [{ type: "text", text: `### Error\n${text}` }], isError: true };
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
