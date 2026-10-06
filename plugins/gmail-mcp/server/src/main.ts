#!/usr/bin/env bun
// gmail-mcp: the MCP server (stdio) and the commands that set it up.
//
//   serve                          run the MCP server for --project (default command)
//   auth [--client NAME]           sign a mailbox in through the browser
//   accounts                       accounts this project can use
//   check                          config, OAuth clients and tokens, with a live token refresh
//   remove EMAIL [--client NAME]   revoke and forget a mailbox
//   client import NAME FILE        copy a downloaded OAuth client file into the store
//   version, --version             the server's version
//
// Every command takes --project DIR (default: the working directory). Commands print
// JSON on stdout and never print a secret.

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import pkg from "../package.json" with { type: "json" };
import { AccountRegistry, oauthClient } from "./accounts.js";
import { signIn } from "./auth.js";
import { importClient, type ResolvedClient } from "./clients.js";
import { accountAllowed, CONFIG_FILE, projectDirFrom } from "./config.js";
import { GmailTools, toolDefinitions } from "./tools.js";

interface Args {
  positional: string[];
  flags: Record<string, string | true>;
}

function parseArgs(argv: string[]): Args {
  const positional: string[] = [];
  const flags: Record<string, string | true> = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const [key, inline] = a.slice(2).split("=", 2);
      if (inline !== undefined) flags[key] = inline;
      else if (argv[i + 1] !== undefined && !argv[i + 1].startsWith("--")) flags[key] = argv[++i];
      else flags[key] = true;
    } else {
      positional.push(a);
    }
  }
  return { positional, flags };
}

const out = (data: unknown) => console.log(JSON.stringify(data, null, 2));

class UsageError extends Error {}

function flag(args: Args, name: string): string | undefined {
  const v = args.flags[name];
  return typeof v === "string" ? v : undefined;
}

function loadedRegistry(projectDir: string): AccountRegistry {
  const registry = new AccountRegistry(projectDir);
  registry.reload();
  if (!registry.loaded) throw new UsageError(registry.notConfiguredMessage());
  return registry;
}

// The client to use: --client, or the only one configured.
function pickClient(registry: AccountRegistry, name: string | undefined): ResolvedClient {
  const configured = Object.keys(registry.loaded!.config.clients);
  const chosen = name ?? (configured.length === 1 ? configured[0] : undefined);
  if (!chosen) throw new UsageError(`Several clients are configured (${configured.join(", ")}) - pass --client NAME`);
  if (!configured.includes(chosen)) throw new UsageError(`Unknown client '${chosen}'. Configured in ${CONFIG_FILE}: ${configured.join(", ")}`);
  const client = registry.clients.get(chosen);
  if (!client) {
    const problem = registry.problems.find((p) => p.client === chosen);
    throw new UsageError(`Client '${chosen}' cannot be read: ${problem?.message ?? "unknown error"}`);
  }
  return client;
}

async function serve(projectDir: string) {
  const registry = new AccountRegistry(projectDir);
  registry.reload();
  const tools = new GmailTools(registry);
  const server = new Server({ name: "gmail", version: pkg.version }, { capabilities: { tools: { listChanged: true } } });

  // The tool schemas depend on the project's label rules; when a call finds the config
  // changed, clients are told to fetch the list again.
  const rulesKey = () => JSON.stringify(tools.rules ?? null);
  let announced = rulesKey();

  server.setRequestHandler(ListToolsRequestSchema, async () => {
    announced = rulesKey();
    return { tools: toolDefinitions(tools.rules) };
  });
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const result = await tools.call(request.params.name, request.params.arguments ?? {});
    if (rulesKey() !== announced) {
      announced = rulesKey();
      await server.sendToolListChanged().catch(() => {});
    }
    return result;
  });

  await server.connect(new StdioServerTransport());
  const state = registry.loaded
    ? `${registry.accounts.size} account(s): ${[...registry.accounts.keys()].join(", ") || "none"}`
    : registry.notConfiguredMessage();
  console.error(`gmail-mcp ${pkg.version} for ${projectDir} - ${state}`);
  for (const p of registry.problems) console.error(`  problem: ${p.client ?? p.email}: ${p.message}`);
}

async function auth(projectDir: string, args: Args) {
  const registry = loadedRegistry(projectDir);
  const client = pickClient(registry, flag(args, "client"));
  const port = flag(args, "port");
  const token = await signIn(client, {
    loginHint: flag(args, "login-hint"),
    port: port ? Number(port) : undefined,
    openBrowser: args.flags["no-open"] !== true,
  });
  registry.store.write(token);
  const allowed = accountAllowed(registry.loaded!.config, token.email, client.name);
  out({
    status: "signed-in",
    email: token.email,
    client: client.name,
    usableInThisProject: allowed,
    note: allowed ? undefined : `${token.email} does not match 'accounts' in ${CONFIG_FILE} - add it there to use it in this project`,
  });
}

async function accounts(projectDir: string) {
  const registry = loadedRegistry(projectDir);
  out({
    project: projectDir,
    accounts: [...registry.accounts.values()].map((a) => ({ email: a.email, client: a.client.name })),
    notAllowedHere: registry.hidden,
    problems: registry.problems,
  });
}

async function check(projectDir: string) {
  const registry = new AccountRegistry(projectDir);
  registry.reload();
  if (!registry.loaded) {
    out({ project: projectDir, ok: false, config: registry.configError ? "invalid" : "missing", message: registry.notConfiguredMessage() });
    process.exitCode = 1;
    return;
  }
  const clients = Object.entries(registry.loaded.config.clients).map(([name, src]) => {
    const resolved = registry.clients.get(name);
    return {
      name,
      source: src.file ? "file" : src.envFile ? "envFile" : "store",
      file: resolved?.sourceFile,
      ok: !!resolved,
      clientId: resolved?.clientId,
      type: resolved?.type,
      error: registry.problems.find((p) => p.client === name)?.message,
    };
  });
  const accountsReport = await Promise.all(
    [...registry.accounts.values()].map(async (a) => {
      try {
        await a.auth.getAccessToken();
        return { email: a.email, client: a.client.name, ok: true };
      } catch (e) {
        return { email: a.email, client: a.client.name, ok: false, error: (e as Error).message };
      }
    })
  );
  const ok = clients.every((c) => c.ok) && accountsReport.every((a) => a.ok) && accountsReport.length > 0;
  out({
    project: projectDir,
    ok,
    configFiles: registry.loaded.files,
    store: registry.store.root,
    clients,
    accounts: accountsReport,
    notAllowedHere: registry.hidden,
    problems: registry.problems.filter((p) => !p.client),
    labelRules: registry.loaded.config.labels ? Object.keys(registry.loaded.config.labels) : [],
    next: accountsReport.length === 0 ? "No mailbox signed in yet - run the auth command" : undefined,
  });
  if (!ok) process.exitCode = 1;
}

async function remove(projectDir: string, args: Args) {
  const email = args.positional[1];
  if (!email) throw new UsageError("Usage: remove EMAIL [--client NAME]");
  const registry = loadedRegistry(projectDir);
  const client = pickClient(registry, flag(args, "client"));
  const stored = registry.store.read(client.clientId, email);
  if (!stored) throw new UsageError(`${email} is not signed in under client '${client.name}'`);
  let revoked = false;
  if (stored.token.refresh_token) {
    try {
      await oauthClient(client).revokeToken(stored.token.refresh_token);
      revoked = true;
    } catch {
      // already revoked or offline: forgetting it locally is what matters
    }
  }
  registry.store.remove(client.clientId, email);
  out({ status: "removed", email, client: client.name, revokedAtGoogle: revoked });
}

async function clientCommand(args: Args) {
  const [, sub, name, file] = args.positional;
  if (sub !== "import" || !name || !file) throw new UsageError("Usage: client import NAME FILE");
  const dest = importClient(name, file);
  out({ status: "imported", name, file: dest, configEntry: { [name]: { store: name } } });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  // parseArgs files `--version` under flags, so it cannot reach the switch as a command.
  if (args.flags.version) return out({ version: pkg.version });
  const command = args.positional[0] ?? "serve";
  const projectDir = projectDirFrom(flag(args, "project"));
  switch (command) {
    case "serve":
      return serve(projectDir);
    case "auth":
      return auth(projectDir, args);
    case "accounts":
      return accounts(projectDir);
    case "check":
      return check(projectDir);
    case "remove":
      return remove(projectDir, args);
    case "client":
      return clientCommand(args);
    case "version":
      return out({ version: pkg.version });
    default:
      throw new UsageError(`Unknown command '${command}'. Commands: serve, auth, accounts, check, remove, client import`);
  }
}

main().catch((error) => {
  if (error instanceof UsageError) {
    out({ status: "error", error: error.message });
  } else {
    console.error(error);
    out({ status: "error", error: error instanceof Error ? error.message : String(error) });
  }
  process.exit(1);
});
