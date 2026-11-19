# flaneur in detail

[flaneur](https://github.com/kedrzu/flaneur) (npm `flaneur`) is a real Chrome with a persistent
profile, behind a CDP proxy that keeps the agent's commands out of what page scripts can observe,
brands every page as Google Chrome and holds each site to a human pace. `flaneur-ctl` (this
plugin's `bin/`) runs it so that one browser serves every agent on the machine.

## flaneur-ctl

| Command | Does |
|---|---|
| `flaneur-ctl start [--chrome-for-testing]` | Starts the browser, or reuses the running one. Waits until it is ready (up to 2 min). |
| `flaneur-ctl start --vpn "<region>" --vpn-provider "<provider>"` | A separate browser for that region (up to 5 min on the first start). |
| `flaneur-ctl endpoint [--vpn "<region>"]` | The CDP endpoint — only ever inside `--cdp "$(…)"`. |
| `flaneur-ctl status` | Which browsers run, with their log files. |
| `flaneur-ctl stop [--vpn "<region>"]` | Closes that browser. Only when the user asks: other agents share it. |

State lives in `~/.claude/browser/flaneur/<default|vpn-region>/`: the endpoint (never read it into the
chat), the PID and the log. The default browser uses flaneur's own profile
(`~/Library/Application Support/flaneur` on macOS); each VPN region has its own profile next to
its state, so logins made there stay there.

## When the start fails

`start` prints the last lines of flaneur's log. The common causes:

- **No Google Chrome installed** → `flaneur-ctl start --chrome-for-testing`: downloads a pinned,
  checksummed Chrome for Testing once.
- **A Chrome already uses the profile** (a flaneur started by hand) → `flaneur-ctl status`; ask the
  user before stopping a browser you did not start.
- **No Node** → flaneur runs on Node.js 22+ through `npx`; tell the user.

## Another country (VPN)

When the task needs a site as seen from elsewhere:

```bash
flaneur-ctl start --vpn "US Texas" --vpn-provider "private internet access"
agent-browser --session "$S" --cdp "$(flaneur-ctl endpoint --vpn 'US Texas')" --pin-tab open https://…
```

- Needs Docker running. Only the browser goes through the tunnel (a gluetun container); the rest
  of the machine stays on its network.
- **The login** is `FLANEUR_VPN_USER` / `FLANEUR_VPN_PASSWORD`, taken from the environment, else
  from the `secrets` plugin's file. When `start` exits with code 3 the login is missing: collect
  both with the `secrets` skill (`secret.py set FLANEUR_VPN_USER --hint …`), never in chat. Ask the
  user for the provider name, never for the password.
- The log shows the address the tunnel got and where ipinfo places it; confirm the location on the
  site itself, its own geolocation may differ.
- An unknown region fails with the list of valid ones. Never fall back to browsing without the
  VPN: the task needed the other country — fix what the log names or tell the user.
