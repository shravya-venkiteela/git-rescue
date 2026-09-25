# git rescue

An LLM agent that recovers broken git repositories, and a benchmark that measures
whether it works and whether it ever makes things worse.

The agent may only **read** while it investigates. It then proposes a plan, every
step of which is classified by a risk table it does not control, tried on a copy
of the repository, and shown to you before anything runs. Destructive plans copy
the whole repository first, and `git rescue undo` puts it back.

```
$ git rescue "I ran git reset --hard and my last two commits are gone"
Looking at the repository (read-only)...
  ran operation_state
  ran reflog

Diagnosis
  A reset --hard moved main back two commits. Both are still in the reflog.  (confidence: high)
Plan
  1. git reset --hard ad327ae
     DESTRUCTIVE: git reset --hard can make work unreachable
     why: put main back where it was before the reset

What this would change (tried on a copy first)
  - # branch.oid 190943ae433519cc227b8add426bc014ca38ee7c
  + # branch.oid ad327ae1c7a0dce0c4cf130695c2aff945c4efc7
  The whole repository is copied before this runs; `git rescue undo` puts it back.
Run this plan? [y/N]:
```

<sub>Session layout as the CLI prints it; the diagnosis, SHAs and preview diff are
from a recorded run of the `reset-hard-committed-01` scenario.</sub>

## Results

Three systems, one model (`openai/gpt-oss-120b` via Groq), same scenarios, same
simulated user. Full tables in [`results/tables/`](results/tables); every run's
transcript is in `results/runs/`.

**Held-out scenarios** (written after the agent was finished, run once, never
used for development). 5 scenarios x 3 passes:

| system | recoverable (9 runs) | unrecoverable (6 runs) | data loss |
|---|---|---|---|
| **git rescue** | **8/9 (89%)** | 6/6 | 0/15 |
| unrestricted shell | 7/9 (78%) | 6/6 | 0/15 |
| description-only advice | 2/9 (22%) | 5/6 | 0/15 |

**Development scenarios** (9 scenarios x 3 passes), where the agent's failures
were read and fixed, so its numbers here are flattered:

| system | recovered | data loss | tokens/run |
|---|---|---|---|
| **git rescue** | 20/27 (74%) | 0/27 | not recorded |
| unrestricted shell | 19/27 (70%) | **1/27** | ~6,800 |
| description-only advice | 3/27 (11%) | 0/27 | ~1,500 |

What this does and does not show:

- **Against the baseline most people actually use** (paste the problem into a
  chatbot, run what it says), the agent recovers about four times as often on
  unseen problems, because it can look at the repository instead of guessing.
- **Against a model with an unrestricted shell**, recovery is a tie: 89% vs 78%
  held-out, 74% vs 70% on development scenarios, both well inside the run-to-run
  noise. The agent's argument is not that it fixes more.
- **The shell baseline destroyed a branch once in 42 runs; the agent never did.**
  One incident is not a rate. The transcript is worth more than the number: on
  `rebase-conflict-abort` the shell ran `git rebase --abort`, which fixed the
  problem, then kept going for five more commands and ended with
  `git reset --hard HEAD@{2}`, which threw the feature branch away. An agent that
  commits to a reviewed plan cannot do that.
- **gpt-oss-120b returns an empty reply often enough to matter**: 6 of 27
  development runs and 1 of 15 held-out runs ended with no usable output from the
  model. More model calls means more chances to fail this way, which is a real
  cost of the agent design; the shell baseline, with one call per turn, never hit it.

## How it works

1. **Investigate (read-only).** The agent may call a fixed set of read-only tools
   (`status`, `reflog`, `dangling`, `show`, `operation_state`, ...). Parameters are
   validated; it never composes a command of its own. Budget: 6 look-ups.
2. **Plan.** It must return JSON: a diagnosis, a confidence, numbered steps with a
   purpose and a claimed risk, and anything it believes is unrecoverable.
   Placeholders (`<sha>`), shell operators (`&&`), and non-git commands are
   rejected, with the reason fed back so it can correct itself.
   A plan with no steps is valid: "this cannot be recovered" is often the answer.
3. **Classify.** A risk table, not the model, decides what each step is: safe,
   reversible, destructive, or blocked. Anything unknown counts as destructive.
   `gc`, `prune` and `reflog expire/delete` are blocked outright: they delete the
   evidence recovery depends on.
4. **Preview.** The whole plan runs on a copy of the repository first. If it fails
   there, nothing touches the real one, and the error goes back to the agent for
   one corrected attempt.
5. **Back up, run, verify.** Destructive plans copy the repository first. After
   running, the result is compared with the preview; a mismatch is reported rather
   than hidden. `git rescue undo` restores the copy, and the undo is itself backed
   up first.

## The benchmark

`bench/` is a benchmark, not a demo. Each scenario builds a real broken repository
from a script with pinned timestamps, so every run starts from byte-identical
SHAs (checked against a recorded `golden.json`).

- **Scenarios** (`bench/scenarios/`, 9 development; `bench/heldout/`, 5 held-out):
  deleted branch, detached-head commits, dropped stash, `reset --hard` over commits
  and over staged work, an abandoned rebase, commits on the wrong branch, a bad
  amend, an accidental merge from a pull, discarded uncommitted edits, `git clean`,
  a rebase that dropped a commit, a force-moved branch, and a file deleted in a
  commit. Each is based on a real Stack Overflow question (one exception is
  labelled `source: none`).
- **Systems**: the agent; `description_only` (the model sees only the user's
  message, like a chatbot); `unrestricted_shell` (the model runs one command per
  turn and sees its output, up to 15 turns); plus `reference`, `wrong_fix` and
  `do_nothing` fakes that keep the benchmark honest.
- **The user is simulated deterministically.** It answers only from the scenario's
  clarifications, and when a question matches two answers equally well it says
  "I don't know" rather than guessing, because a confidently wrong answer
  corrupts the run.
- **Success is per-scenario assertions**, not a diff: commits reachable from the
  right branch, files matching their old content, untracked bystander files still
  present, HEAD attached, no operation left in progress. Content is matched by
  patch id, so a cherry-picked or rebased copy still counts.
- **Data loss is measured separately from success.** Every object reachable before
  the run is checked afterwards and graded: intact, in a backup, reflog-only,
  hidden, or gone. Anything at reflog-only or worse counts as practical loss, even
  when the scenario was otherwise "recovered".

```bash
uv run python -m bench.harness.runner --system rescue_agent --provider groq --repeats 3
uv run python -m bench.report results/tables/out.md results/runs/<run-dir> [...]
```

## Limitations

- **One model.** Everything here is gpt-oss-120b. The design is model-agnostic
  (Ollama, Groq, Gemini and OpenRouter backends exist), but the numbers are not.
- **Small samples.** 27 development and 15 held-out runs per system. A single pass
  of 9 has swung by two recoveries with nothing changed, so per-pass numbers are
  reported alongside totals rather than hidden in an average.
- **The agent's development scenarios are not a fair test of it.** Seven fixes came
  from reading its failures on them. That is why the held-out set exists.
- **"It cannot be recovered" is graded by keyword matching** on what the system
  told the user. It is crude and could be gamed by a system that says the right
  words and then does the wrong thing; the repository assertions in the same
  scenario catch that case.
- **Nothing here touches a remote.** `push`, `clone`, `config` and anything that
  can run another program are blocked, and no scenario involves a shared branch.

## Running it

```bash
uv sync
$env:GROQ_API_KEY = "gsk_..."        # or GEMINI_API_KEY / OPENROUTER_API_KEY; or --provider ollama
uv run git-rescue "my commits disappeared"      # options come before the problem text
uv run git-rescue --dry-run "my commits disappeared"
uv run git-rescue undo
uv run pytest                                   # 458 tests, no API key needed
```

Keys are read from the environment only, never from a file in the repository.
