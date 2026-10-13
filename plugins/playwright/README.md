# Playwright

The browser every skill in this marketplace uses: stock [`@playwright/mcp`](https://github.com/microsoft/playwright-mcp)
(pinned to 0.0.83) behind a small bun server. Every stock tool keeps its name
(`mcp__plugin_playwright_playwright__browser_*`); one tool is added, `browser_session`,
which switches the browser's profile and, optionally, its country.

Needs [bun](https://bun.sh) and nothing else; dependencies are fetched on first start. Docker is
needed only for VPN regions.

## Profiles

`browser_session({ profile })` relaunches the browser; open tabs close. Omitted parameters keep
their current value.

- **`persistent`** — the project's saved profile, the one stock Playwright MCP uses
  (`ms-playwright-mcp/mcp-chrome-<hash of project root>` in the OS cache directory). Logins
  survive restarts. One session per project at a time: Chrome locks the directory.
- **`fresh`** — in-memory, independent of everything else, nothing kept. Calling it again resets
  the state. Use it for testing applications and reproducible checks.

Use `persistent` only when the work needs accounts the user is signed into.

## Project config

`.claude/playwright.json` is optional and committed. It sets the profile the browser starts in
(default `persistent`). An invalid file stops the server with a readable error instead of
falling back silently.

```json
{
  "profile": "fresh",
  "geo": {
    "provider": "private internet access",
    "credentials": { "userKey": "PIA_USER", "passwordKey": "PIA_PASSWORD" }
  }
}
```

Of stock's `PLAYWRIGHT_MCP_*` variables only `PLAYWRIGHT_MCP_HEADLESS` is honoured; stock's
command-line flags are not supported.

## Geo: a browser in another country

With `geo` configured, `browser_session` gains `region` (a server-location name of the provider,
e.g. `"US Texas"`; `null` goes direct) and returns `tunnel: { publicIp, ipGeolocation }`.
Only the browser is routed through the VPN. `ipGeolocation` is ipinfo's guess as seen from the VPN
container and can differ from what the tested service sees (a "US Kansas" server was reported as
Texas while the service saw Kansas), so confirm the location with the service itself.

- **Docker is required.** Each region runs in its own
  [gluetun](https://github.com/qdm12/gluetun) container (`provider` is gluetun's
  `VPN_SERVICE_PROVIDER`). Ports are bound to 127.0.0.1, with a random proxy login and API key per
  container. The host's network and DNS are never touched, so a failing tunnel cannot take the
  machine offline.
- **Credentials** are named by key in the config, never stored in it. They come from an
  environment variable of that name, else from a `KEY=value` file: `credentials.file` (relative
  paths resolve from the project, `~` works), by default
  `${CLAUDE_CONFIG_DIR:-~/.claude}/secrets/.env`, the store of the `secrets` plugin. They are read
  only when a region is requested and passed to the container by variable name, never on a command
  line.
- **First use is slow.** The image is pulled once, and gluetun's built-in server list goes stale,
  so a refreshed list is cached in the Docker volume `playwright-mcp-servers-<provider>` and renewed
  when older than 24 hours (about a minute for PIA; one refresh at a time across sessions).
- **Pool of 4 regions**, least recently used stopped first; a tunnel that is not healthy within
  90 seconds fails the call with the reason.
- **Cleanup.** Containers carry the owner process's PID and start time and are removed when the
  server shuts down. Orphans of dead servers are swept in the background when a geo-configured
  server starts.

## Why the wrapper owns the browser

Stock cannot change profile or proxy at runtime, and it does not close its browser when its
connection closes, which leaves the profile locked. The wrapper therefore launches Chrome itself
(same settings and profile directory as stock), hands the context to stock's `createConnection`,
and relaunches it on every `browser_session`.

## Development

```bash
cd plugins/playwright/server
bun install
bun test
bunx tsc --noEmit
```
