---
name: skill-improve
description: Revise an existing skill so the agent behaves as intended, without the skill swelling.
disable-model-invocation: true
---

# Skill improve

A skill is not a leash the agent walks along — it is there to help it decide well. That is where the
real cost of a rule comes from: not the tokens, but the judgement the rule displaces. Every rail you
add takes a decision away from a model that could have made it, and leaves it worse at the
situations nobody foresaw. So improving a skill usually means saying *why* more clearly rather than
adding one more condition.

He comes here because the behaviour was not what he wanted. The goal is that behaviour **at the
smallest skill that produces it**. Distillation, not accretion — and accretion is the default. In the
repository this skill grew up in, skill files gained 22,766 lines against 13,069 removed, and 61% of
those removals came from three commits somebody sat down to write. Ordinary work adds; shrinking
takes an effort someone has to intend.

## Load `skill-creator` before you open the file

It is the craft manual — anatomy, progressive disclosure, how a description earns its triggering,
why explaining beats musty MUSTs — and it is the machinery: evals, the review viewer, feedback,
packaging. You need the craft while writing the revision, not after it.

What it cannot give you is resistance to adding, because **it is written for the blank page**, where
every sentence is an addition and adding is simply correct. Revision is the opposite situation, so
where its default answer is "write another section", this skill governs.

## Look at what the skill actually did

Guessing why an agent misbehaved is how a rule gets written for a cause that was never there. Real
runs are on disk and grepping the whole corpus takes about 0.03s, so there is no reason to skip it.

```bash
# sessions where skill X really ran — two mechanisms: the Skill tool and slash-commands
grep -lE '"skill":"X"|<command-name>/X\b' ~/.claude/projects/*/*.jsonl

# only his own turns: Paseo and task notifications are user-role too (even with promptSource
# "sdk"), and what he typed while the agent was busy arrives as a queued_command attachment
jq -r 'select(.isMeta | not) | if .type=="user" then .message.content | if type=="string" then .
       else (.[]? | select(.type=="text").text) end elif .attachment.type=="queued_command"
       then .attachment.prompt[]?.text else empty end
       | select(test("^<(task-notification|paseo-system|system-reminder|local-command)") | not)' <file>

# where he interrupted the agent
grep -o '\[Request interrupted by user[^]]*\]' <file>
```

Look for his frustration, his corrections mid-run, and anything he had to say twice — a repeat marks
a rule that does not catch. Plain grep on the skill's name is 3-9x noisier than the patterns above.
Claude Code deletes transcripts after `cleanupPeriodDays` (30 by default); Codex keeps its own in
`~/.codex/sessions/` and `~/.codex/archived_sessions/`. The `retro` plugin's `sessions.py` reads both.

Transcripts carry whatever the work touched: production records, personal data, secret-shaped
strings, and the odd file that is half base64 image. Extract `.text` fields, never paste raw lines,
and keep what you read local.

## Start from the text that is already there

"What is missing?" is the wrong opening question, and it is the one that grows skills. Ask **which
instruction should have caught this**. The answer carries its own cure:

- **Nothing covers it** — a real knowledge gap. Write it, unless a check can catch it (below).
- **Something covers it and lost** — buried, drowned out by a louder neighbour, or worded so it
  reads as optional. A second copy makes it quieter still; cut or sharpen whatever is drowning it.
  Two shapes lose often: a prohibition ("Do NOT X" keeps X in view, so name the behaviour you want
  instead), and a completion bound so vague that the agent stops early (sharpen the bound rather
  than add a step). A sentence the model would obey anyway changes nothing and only adds noise;
  delete it whole.
- **Something covers it and was followed** — then the rule is wrong. Rewrite it instead of fencing
  it with an exception.

The impulse this question guards against: asked to stop running the critic on his own imperative
comment and just fix it, a revision answered with a two-axis `askOrigin` × `askIntent` taxonomy plus
a new rule inserted ahead of the existing ones — rather than repairing the rule that already decided
that case.

Before writing text for either of the first two, ask whether the wrong move is visible in the act
itself — a command, a file it writes, a shape in the diff. Then a check catches it every time, where
text catches it only when it wins the agent's attention: a `PreToolUse` hook in a Claude Code plugin
(the `guardrails` plugin collects them), a lint rule, a CI step — preferably in a mechanism the repo
already runs. Propose that to him instead; the check's error message is where the *why* goes, and
the prose rule it replaces can go. Text stays the remedy when spotting the mistake takes judgement.

When he asks for something larger — a new reach, a different artefact — no rule failed, so the
question becomes **which text is now false**. The passage describing the old scope or output is not
incomplete, it is out of date: replace it rather than parking a new section beside it. And when the
ask is about how the skill writes, show an example instead of legislating prose — a complaint about
jargon has been answered with sixty lines of rules about being concise.

## Knowledge may grow. Procedure asks him.

A fact the model cannot get by itself — a path, a command, an API signature, a policy this company
chose — goes in without discussion; one that `--help`, a config file or a `package.json` script
gives in a single lookup stays there, where it cannot go stale. Procedure is the other thing:
phases, gates, checklists, orderings, "if A then first B", another "Do NOT". When your revision adds
any of it, **stop and ask him**, showing what you are adding and which decision it takes away from
the model. Whether that trade is worth it is his call, not yours.

**Write the fact, not a pointer to it.** The skill carries everything the agent needs in order to
act, so no rule may rest on something the agent has to go and look up to understand it. A task id is
the usual way this goes wrong: it is not a shorter way of stating the reason, it is an invitation to
archaeology — what was that task, what happened there, why — and the agent comes back with what the
sentence should have said. State the mechanism, and the id becomes unnecessary rather than
forbidden.

A request to delete is carried out, not negotiated. If you see a reason to keep something, say it in
one sentence and delete it anyway — never hand him a choice in which deleting is not the
recommendation — "możemy to spokojnie wywalić" has come back as +86 / −0.

Facts may not leave quietly either. When a revision removes any — a path, a command, an identifier,
a citation — list them when you report back; a shrink drops them out of live rules in good faith,
and the list is what makes that visible.

## Nothing is also an answer

A one-off slip, a model too small for the job, something belonging in the prompt, in `CLAUDE.md`, in
a different skill or in a check — none of those are changes to this skill. Say so and stop.

Evidence cuts both ways here: finding the real mechanism is not a licence to write a rule about it.
When the cause turns out to sit in run state, in a prompt, or in another skill, that is where the
fix belongs and this file does not change.

Then run `skill-creator`'s eval loop, with the rewritten skill as candidate and the current one as
baseline.
