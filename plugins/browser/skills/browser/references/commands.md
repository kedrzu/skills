# agent-browser commands

A digest of agent-browser 0.43. `…` stands for the session flags: `--session "$S"` for the local
browser, `--session "$S" --cdp "$(flaneur-ctl endpoint)" --pin-tab` for flaneur. The full reference:
`agent-browser skills get core --ref commands`.

## Read

```bash
agent-browser … snapshot -i            # interactive elements with refs (preferred)
agent-browser … snapshot               # full tree;  -u link hrefs, -c compact, -s "<css>" scope
agent-browser … snapshot -i --delta    # only what changed since the last snapshot
agent-browser … read                   # rendered text of the active tab
agent-browser … get text @e1           # also: html, value, attr @e1 href, title, url, count
agent-browser … is visible @e1         # also: enabled, checked
agent-browser … diff snapshot          # what changed since the last snapshot
```

## Act

```bash
agent-browser … click @e1               # --new-tab for a link
agent-browser … fill @e2 "text"         # clear, then type;  type @e2 "more" keeps the value
agent-browser … press Enter             # Control+a etc.
agent-browser … select @e3 "label"      # check / uncheck / hover / focus / dblclick @e4
agent-browser … upload @e5 file.pdf
agent-browser … scroll down 500         # scrollintoview @e6
agent-browser … drag @e1 @e2
agent-browser … find role button click --name "Submit"   # without a ref: find text|label|placeholder|testid …
agent-browser … back | forward | reload
```

## Wait

```bash
agent-browser … wait @e1 | wait --text "Saved" | wait --url "**/done" | wait --load load
agent-browser … wait --fn "window.app?.ready === true"   # local browser only: flaneur sees no page globals
```

Not `--load networkidle` on apps with polling, SSE or WebSockets: it never settles. Waits time out
after 25 s (`--timeout`).

## Debug (local browser)

```bash
agent-browser … errors [--clear]                   # uncaught exceptions
agent-browser … console [--clear]                  # console log
agent-browser … network requests [--filter /api/]  # requests with status
agent-browser … network route "**/api/x" --body '{"ok":true}'   # mock a response; unroute to undo
agent-browser … eval --stdin <<'JS'
document.querySelectorAll("li").length
JS
agent-browser … set viewport 390 844   # also: device "iPhone 15", media dark, offline on
agent-browser … screenshot --annotate map.png   # labels [N] = ref @eN
```

## Tabs, frames, dialogs

```bash
agent-browser … tab | tab new <url> | tab t2 | tab close t2
agent-browser … frame @e3 | frame main
agent-browser … dialog status | dialog accept [text] | dialog dismiss
```

## Trouble

- `Ref not found` → the page changed: snapshot again.
- Click does nothing → something covers it (`covered by …`): dismiss it first.
- Fill has no effect → `focus @e1`, then `keyboard inserttext "text"`.
- Anything else odd → `agent-browser doctor`.
