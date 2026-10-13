#!/usr/bin/env bun
// playwright-mcp: the stock @playwright/mcp tools plus browser_session, as an MCP server on stdio.
//
//   --project DIR   the project whose .claude/playwright.json sets the startup profile
//                   (default: the working directory)
//   --version       the server's version
//
// The browser and the VPN containers belong to this process: they are closed when the client goes
// away (stdin ends) and on SIGTERM / SIGINT. Docker is needed only for a VPN region; without it
// the server starts and serves as usual.

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import * as path from "path";
import pkg from "../package.json" with { type: "json" };
import { ConfigError, loadProjectConfig, readCredentials } from "./config.js";
import { BrowserSession } from "./session.js";
import { TunnelPool } from "./tunnels.js";

// Stock's exit watchdog gives a graceful close this long before exiting anyway.
const SHUTDOWN_GRACE_MS = 15_000;

class UsageError extends Error {}

interface Args {
  project: string;
  version: boolean;
}

function parseArgs(argv: string[]): Args {
  const args: Args = { project: process.cwd(), version: false };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--version") args.version = true;
    else if (arg === "--project" || arg.startsWith("--project=")) {
      const value = arg === "--project" ? argv[++i] : arg.slice("--project=".length);
      if (!value) throw new UsageError("--project needs a directory");
      args.project = path.resolve(value);
    } else throw new UsageError(`Unknown argument '${arg}'`);
  }
  return args;
}

function log(message: string): void {
  console.error(`playwright-mcp: ${message}`);
}

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

async function serve(projectDir: string): Promise<void> {
  const config = loadProjectConfig(projectDir);
  const geo = config.geo;
  const tunnels = geo && new TunnelPool({ provider: geo.provider, credentials: () => readCredentials(geo.credentials), log });
  const session = new BrowserSession({
    initial: { profile: config.profile },
    serverInfo: { name: pkg.name, version: pkg.version },
    log,
    tunnels,
  });
  // Best effort, in the background: no Docker must not delay or fail the start.
  tunnels
    ?.pruneOrphans()
    .then((removed) => removed.length && log(`removed orphaned VPN containers: ${removed.join(", ")}`))
    .catch((e: unknown) => log(`looking for orphaned VPN containers failed: ${errorMessage(e)}`));

  let shuttingDown = false;
  const shutdown = (reason: string) => {
    if (shuttingDown) return;
    shuttingDown = true;
    log(`shutting down (${reason})`);
    setTimeout(() => process.exit(0), SHUTDOWN_GRACE_MS).unref();
    const closing = [session.close(), tunnels?.close()].map((p) => p?.catch((e: unknown) => log(`shutdown failed: ${errorMessage(e)}`)));
    void Promise.all(closing).finally(() => process.exit(0));
  };
  process.stdin.on("end", () => shutdown("stdin closed"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));
  process.on("SIGINT", () => shutdown("SIGINT"));
  session.server.onclose = () => shutdown("connection closed");

  await session.connect(new StdioServerTransport());
  console.error(`playwright-mcp ${pkg.version} for ${projectDir} - profile ${config.profile}${geo ? `, VPN regions of ${geo.provider}` : ""}`);
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  if (args.version) {
    console.log(pkg.version);
    return;
  }
  await serve(args.project);
}

main().catch((e: unknown) => {
  const known = e instanceof ConfigError || e instanceof UsageError;
  console.error(`playwright-mcp: ${known ? e.message : e instanceof Error ? (e.stack ?? e.message) : String(e)}`);
  process.exit(1);
});
