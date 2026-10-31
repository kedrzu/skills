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
| substitutions | `$(node -p 1)`, `` `node -p 1` ``, `<(node -e 1)`, also inside double quotes and heredocs with an unquoted delimiter (`<<EOF`) |
| env-var prefixes | `FOO=1 node -e 1` |
| wrappers | `env`, `timeout`/`gtimeout`, `nice`, `time`, `command`, `exec`, `nohup`, `caffeinate`, `stdbuf`, `xargs`, `sudo`, `doas` |
| paths | `/Users/x/.bun/bin/bun -e`, `~/.nvm/…/bin/node -e` |
| package runners | `npx node -e`, `npx -c '…'`, `bunx node -e`, `bun x node -e`, `npm`/`pnpm`/`yarn exec node -e`, also `pnpm --filter web exec` |
| nested shells | `bash -c '…'`, `sh -c`, `zsh -lc`, `bash -euo pipefail -c`, `eval '…'`, `bash <<EOF`, `sh <<< '…'`, and a shell fed by a pipe from `echo`, `printf` or `cat <<EOF` (`echo '…' \| bash`) |

**Allows**: `-e` that belongs to another program (`grep -e`, `sed -e`, `perl -e`,
`python -c`, `bun build -e`), flags after the script (`node script.js -e`, which are the
script's own), `bun run`/`test`/`install`/`x`, plain `node file.mjs` / `bun file.ts`, and
text that merely mentions `node -e`: `echo`, `grep`, commit messages, comments, and heredoc
bodies written to a file (`cat > f <<EOF`) — save a `$(…)` or backticks under an unquoted
delimiter, which bash runs.

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
a script file that calls `node -e`, a `package.json` script) is out of its reach, and so is what
a file, a download or a variable pipes into a shell (`cat x.sh | bash`, `curl … | sh`,
`echo "$CODE" | bash`): only `echo`, `printf` and `cat` with a heredoc are read.

### No install inside a workspace submodule — `hooks/block_submodule_install.py`

**Blocks** a package install run inside a git submodule whose packages are workspaces of the
superproject: `bun install|i|ci|add|a|remove|rm|update`, `npm install|i|in|ci|add|uninstall|un|remove|rm|r|update|up|link`,
`pnpm install|i|add|remove|rm|uninstall|un|update|up`, and `yarn` bare or with `install|add|remove|up|upgrade`.
Not `bun upgrade`, `bun run`, `bun x`, `bunx`. The directory it runs in starts at the hook input's
`cwd` and follows `cd` / `pushd` earlier in the command line, `~`, relative paths, `env -C`, and the
manager's own option (`bun --cwd`, `npm --prefix` / `-C`, `pnpm -C` / `--dir`, `yarn --cwd`). The call
is found everywhere the guard above finds its call: both walk the command line with `shellparse.walk()`.

It asks git (`rev-parse --show-superproject-working-tree`) whether that directory is in a submodule,
then reads the superproject's `package.json` `workspaces` (array or `{ "packages": [...] }`) and blocks
only if a pattern points at or into the submodule. No configuration and no hard-coded names.

**Allows** installs from the superproject root, in a plain repo, in a submodule whose packages the
superproject does not list as workspaces (it keeps its own installs), and any command that is not an
install.

**Why.** The superproject's install is the only correct one. Installing from inside the submodule
creates a second `node_modules` there and re-links the submodule's packages to it, shadowing the
superproject's dependencies: two paths to the same package, phantom TypeScript errors (TS2883), lint
that works by accident.

**The fix the agent is told:** run the install from the superproject root (`cd <superproject> && bun install`);
if a stray store already exists, delete the submodule's `node_modules` and reinstall from the superproject.

**Limits.** A directory it cannot work out (`cd -`, `cd $DIR`, `popd`) is allowed, as is anything
unparseable (with a warning).

## Layout

```
hooks/hooks.json               # one PreToolUse entry per guard
hooks/guard.py                 # shared runner: hook input in, exit code out, fail open
hooks/shellparse.py            # shared shell lexer and walker: every command a line runs, with its cwd
hooks/<guard>.py               # one guard per script
hooks/test_<guard>.py          # its tests: JSON in on stdin, exit code out
```

## Adding a guard

1. Write `hooks/<guard>.py` with a `check(command, cwd)` that returns the reason to refuse, or
   `None`, and a `main()` that returns `run_guard(check, <seconds>, "<what it checks>")` from
   `guard.py`. A Bash guard is a visitor passed to `shellparse.walk()`, which calls it on every
   command the line would run (through wrappers, package runners and nested shells) with its cwd. Import both after
   putting the script's directory on `sys.path`, as `block_inline_eval.py` does — `python3 -I`
   leaves it off.
2. `run_guard` reads the hook input from stdin, prints a returned reason on stderr and exits 2,
   and fails open: any exception means exit 0, with a `{"systemMessage": …}` warning on stdout. A
   guard that crashes must not block every command.
3. Add an entry to `hooks/hooks.json`, run as `python3 -I "${CLAUDE_PLUGIN_ROOT}/hooks/<guard>.py"`
   with a `timeout`.
4. Write `hooks/test_<guard>.py` covering what it blocks and what it must let through. CI runs
   every `plugins/*/hooks/test_*.py`; locally: `python3 -m unittest discover -s hooks`.
5. Document it above and bump the plugin's version.
