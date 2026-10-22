# Guardrails

Mechanical safety guards for agents. An instruction in a prompt is a request the agent may
forget; a guard here is a `PreToolUse` hook that refuses the action outright and returns an
error the agent can act on (exit code 2, the reason on stderr, which Claude Code feeds back
to the model). Each guard says what was blocked, why, and what to do instead.

The plugin ships hooks only. Installing it enables every guard; there is nothing to configure.

```bash
claude plugin install guardrails@kedrzu-skills
```

## Guards

### No inline JavaScript eval — `hooks/block_inline_eval.py`

**Blocks** `node`, `nodejs` and `bun` given an inline-eval flag before any script file:
`-e`, `--eval`, `-p`, `--print`, `--eval=…`, `--print=…`, and short-flag clusters holding
`e` or `p` (`-pe`). Also `bun run -e`. The call is found wherever a shell would run it:

| Shape | Example |
| --- | --- |
| chains, pipes, subshells | `cd x && timeout 90 bun -e "…"`, `a; node -e 1`, `( node -e 1 )`, `x \| node -e 1` |
| substitutions | `$(node -p 1)`, `` `node -p 1` ``, `<(node -e 1)`, also inside double quotes |
| env-var prefixes | `FOO=1 node -e 1` |
| wrappers | `env`, `timeout`/`gtimeout`, `nice`, `time`, `command`, `exec`, `nohup`, `caffeinate`, `stdbuf`, `xargs`, `sudo`, `doas` |
| paths | `/Users/x/.bun/bin/bun -e`, `~/.nvm/…/bin/node -e` |
| package runners | `npx node -e`, `npx -c '…'`, `bunx node -e`, `bun x node -e`, `npm`/`pnpm`/`yarn exec node -e` |
| nested shells | `bash -c '…'`, `sh -c`, `zsh -lc`, `bash -euo pipefail -c`, `eval '…'`, `bash <<EOF` and `sh <<< '…'` |

**Allows**: `-e` that belongs to another program (`grep -e`, `sed -e`, `perl -e`,
`python -c`, `bun build -e`), flags after the script (`node script.js -e`, which are the
script's own), `bun run`/`test`/`install`/`x`, plain `node file.mjs` / `bun file.ts`, and
text that merely mentions `node -e`: `echo`, `grep`, commit messages, comments, and heredoc
bodies written to a file (`cat > f <<EOF`).

**Why.** Under an eval flag `process.execArgv` is `["-e", "<the whole script>"]`. A library
that forks workers with the parent's `execArgv` — `jest-worker`, used by
`rollup-plugin-terser`, is one — makes every child re-run the whole script, which forks
again: (cpus−1)ⁿ processes. On 2026-10-22 one `bun -e` call to a Rollup-based compiler left
924 `bun` processes alive after 12 seconds and froze the Mac by exhausting RAM, five times
that day. Node behaves the same. A timeout or memory watchdog does not help, because the
children escape mid-fork. Run from a file, `execArgv` is empty and nothing re-runs.

**The fix the agent is told:** write the code to a file under the project's scratch dir
(somewhere gitignored) or `$TMPDIR` and run the file — `node "$TMPDIR/snippet.mjs"`,
`bun "$TMPDIR/snippet.ts"`. A heredoc to a file is fine even for a one-liner.

**Limits.** It parses the command, it does not sandbox it. A command it cannot parse (an
unterminated quote, say — which the shell would reject too) is allowed with a warning shown to
the user, never blocked. Code started some other way (`python -c "subprocess.run('node -e …')"`,
a script file that calls `node -e`, a `package.json` script) is out of its reach.

## Layout

```
hooks/hooks.json               # one PreToolUse entry per guard
hooks/shellparse.py            # shared shell lexer: simple commands, quotes, $(...), heredocs
hooks/<guard>.py               # one guard per script
hooks/test_<guard>.py          # its tests: JSON in on stdin, exit code out
```

## Adding a guard

1. Write `hooks/<guard>.py`. Read the hook input as JSON from stdin; to refuse, print the
   reason on stderr and exit 2; otherwise exit 0. A Bash guard gets its simple commands from
   `shellparse.parse()` (import it after putting the script's directory on `sys.path`, as
   `block_inline_eval.py` does — `python3 -I` leaves it off).
2. Fail open: any exception means exit 0, with a `{"systemMessage": …}` warning on stdout. A
   guard that crashes must not block every command.
3. Add an entry to `hooks/hooks.json`, run as `python3 -I "${CLAUDE_PLUGIN_ROOT}/hooks/<guard>.py"`
   with a `timeout`.
4. Write `hooks/test_<guard>.py` covering what it blocks and what it must let through. CI runs
   every `plugins/*/hooks/test_*.py`; locally: `python3 -m unittest discover -s hooks`.
5. Document it above and bump the plugin's version.
