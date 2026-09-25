# git rescue

Git has a handful of commands that delete work without a confirmation, and most
advice about recovering from them is written by someone who can't see your
repository. `git rescue` can: it investigates read-only, proposes a plan,
previews it on a copy, and waits for you to say yes. Anything it does, it can
undo.

Then I measured it against the alternatives, because a recovery tool that's
usually right is not obviously better than nothing.

```
$ git rescue "I ran git reset --hard and lost my last commit"
Looking at the repository (read-only)...
  ran reflog

Diagnosis
  A hard reset moved HEAD back to the initial commit, leaving the last commit
  (724932c) only reachable via reflog  (confidence: high)
Cannot be recovered
  - Any uncommitted changes that existed before the reset
Plan
  1. git reset --hard 724932c
     DESTRUCTIVE: git reset --hard can make work unreachable
     why: Restore HEAD to the lost commit, bringing back its snapshot
  2. git branch recovered 724932c
     reversible: git branch changes state but leaves work reachable
     why: Create a permanent reference to the recovered commit

What this would change (tried on a copy first)
  - # branch.oid 8d607096779960b4f89162ecaa48cb71cf1e335f
  - refs/heads/master 8d607096779960b4f89162ecaa48cb71cf1e335f
  + # branch.oid 724932c156ffe3c76be4247b74edec75d7c8ac7e
  + refs/heads/master 724932c156ffe3c76be4247b74edec75d7c8ac7e
  + refs/heads/recovered 724932c156ffe3c76be4247b74edec75d7c8ac7e
  The whole repository is copied before this runs; `git rescue undo` puts it back.
Run this plan? [y/N]: y

Done. A hard reset moved HEAD back to the initial commit, leaving the last commit
(724932c) only reachable via reflog
Backup: ~/.git-rescue/backups/df1e0363b10c/20260924T231536  (undo with `git rescue undo`)
```

<sub>A real session, wrapped to fit. The model here is gpt-oss-120b via Groq.</sub>

## Does it actually work?

I wrote 9 scenarios from real Stack Overflow questions and used them while
building the agent. Then, once it was finished, I wrote 5 more, ran everything
on those exactly once, and reported that. The second set is the honest number:
I never saw those failures, so I couldn't tune for them.

Three systems, all on the same model (`gpt-oss-120b`), on the held-out five:

| | recovers what can be recovered | says so when it can't | destroys data |
|:---|:---:|:---:|:---:|
| **git rescue** | **8/9** | **6/6** | **0/15** |
| the same model with a shell | 7/9 | 6/6 | 0/15 |
| the same model giving advice only | 2/9 | 5/6 | 0/15 |

The first row isn't the interesting one. Giving a model a shell recovers about as
often as my agent does, and I'm not going to pretend otherwise. The difference
showed up in a single run out of 42: on the abandoned-rebase scenario, the shell
ran `git rebase --abort`, which fixed it, and then kept going. Five commands
later it ran `git reset --hard HEAD@{2}` and threw the feature branch away. It
solved the problem and then destroyed the work, in the same session, with nobody
to stop it. That's the failure my design is meant to make impossible, and it's
one incident, not a rate. I'd rather show you the transcript than quote a
percentage.

A few other things worth saying out loud:

- Against advice-only, the gap is real: **8/9 versus 2/9** on problems neither
  system had seen. Looking at the repository is worth roughly four times as much
  as guessing about it.
- The model returned a completely empty reply in 7 of my 42 runs. An agent that
  makes six model calls per problem is exposed to that more than a baseline
  making one call per turn. That's a genuine cost of the design.
- Two of the five held-out scenarios can't be recovered at all: the work was
  never committed. The only correct answer is to say so and change nothing,
  which is also the easiest thing for a tool to get wrong by inventing a fix.

<details>
<summary>The development scenarios, for completeness (9 scenarios, 3 passes each)</summary>

<br>

| system | recovered | data loss |
|---|---|---|
| git rescue | 20/27 (74%) | 0/27 |
| unrestricted shell | 19/27 (70%) | 1/27 |
| advice only | 3/27 (11%) | 0/27 |

These flatter my agent: seven of its fixes came from reading its failures on
exactly these scenarios. Every per-scenario table, per-pass number and transcript
is in [`results/tables/`](results/tables) and [`results/runs/`](results/runs).

</details>

## How it works

The whole design is one idea: the model decides *what* to do, and code decides
whether that's allowed to happen.

**1. It investigates, read-only.** The model can call `status`, `reflog`,
`dangling`, `show` and a few others. It never writes a command itself; it picks a
tool and passes parameters that get validated. Six look-ups by default.

**2. It writes a plan, in strict JSON.** A diagnosis, numbered steps with a
purpose and a claimed risk, and a list of anything it believes is gone for good.
Placeholders like `<sha>`, shell operators, and anything that isn't a git command
get rejected, with the reason handed back so it can fix its own plan.

**3. A risk table classifies every step.** Not the model: a table it doesn't
control. Safe, reversible, destructive, or blocked, and anything unrecognised
counts as destructive. `gc`, `prune` and `reflog expire` are blocked outright,
because they delete the very thing recovery reads.

**4. The plan runs on a copy first.** If it fails there, your repository is never
touched, and the error goes back to the model for one corrected attempt. This is
also where a plan that "looks fine" gets caught: one model added a tidy-up step
that deleted the branch it had just created.

**5. Then it backs up, runs, and checks.** Destructive plans copy the whole
repository first. Afterwards the result is compared against the preview, and a
mismatch is reported rather than hidden. `git rescue undo` restores the copy, and
the undo takes its own copy first.

One thing I had to fix twice: **"this cannot be recovered" has to be a valid
answer.** Work that was never committed or staged is genuinely gone, and a tool
that invents a recovery for it is worse than useless. My plan validator used to
reject a plan with no steps as malformed, so the agent literally could not say
it.

## The benchmark

Every scenario builds a real broken repository from a script, with pinned
timestamps, so the commit SHAs come out byte-identical on every machine. They're
checked against a recorded `golden.json`, so a scenario that drifts fails loudly
instead of quietly changing what I'm measuring.

```bash
uv run python -m bench.harness.runner --system rescue_agent --provider groq --repeats 3
uv run python -m bench.report results/tables/out.md results/runs/<run-dir> [...]
```

<details>
<summary>What's in it: scenarios, baselines, and how I decide a run succeeded</summary>

<br>

**Scenarios.** 9 development ([`bench/scenarios/`](bench/scenarios)), 5 held-out
([`bench/heldout/`](bench/heldout)): a deleted branch, commits made on a detached
HEAD, a dropped stash, `reset --hard` over commits and over staged work, an
abandoned rebase, commits on the wrong branch, a bad amend, an accidental merge
from a pull, discarded uncommitted edits, `git clean -fd`, a rebase that silently
dropped a commit, a force-moved branch, and a file deleted in a commit. Each one
links the Stack Overflow question it came from; one has no good match and says so.

**Baselines.** `description_only` sees only your message, like pasting into a
chatbot. `unrestricted_shell` runs one command per turn and sees its output, up
to 15 turns. There are also `reference`, `wrong_fix` and `do_nothing` fakes,
which exist to catch a benchmark that passes things it shouldn't.

**The simulated user is deterministic.** It answers from the scenario's
clarifications, and if a question matches two answers equally well it says "I
don't know" instead of picking one. It used to pick alphabetically, which meant
it answered "I'm on main" to "what's your feature branch called?" four times in
a row and sank a run that deserved better.

**Success is per-scenario assertions**, never a diff: are the commits reachable
from the right branch, does the file match its old content, is the untracked file
the user never mentioned still there, is HEAD attached, is there an operation
left half-finished. Content is matched by patch id, so a cherry-picked copy of a
commit still counts.

**Data loss is scored separately from success.** Everything reachable before the
run is graded afterwards: intact, in a backup, reflog-only, hidden, or gone.
Reflog-only or worse counts as loss even if the scenario otherwise passed, since
a reflog entry is a thing that expires.

</details>

## What I'd want a reviewer to push on

- **It's one model.** Everything here is `gpt-oss-120b` through Groq. The
  backends are swappable (Ollama, Gemini, OpenRouter), the numbers aren't.
- **The samples are small.** 15 held-out runs per system. A single pass of 9 has
  swung by two recoveries with nothing changed, which is why I report every pass
  rather than an average that hides it.
- **The development set is tuned-on**, and I say so rather than quoting 74% as if
  it meant the same thing as the held-out number.
- **"It can't be recovered" is graded by keyword matching** on what the system
  said. It's crude. A system could say the right words and do the wrong thing,
  though the repository assertions in the same scenario would catch that.
- **I tested the library well and the command-line entry point not at all**,
  until I finally ran it by hand. Five bugs were waiting there, two of which
  could damage someone's repository, including an undo that deleted the folder it
  was restoring. They all have tests now, but the lesson was the seam, not the
  bugs.

## Running it

```bash
uv sync
$env:GROQ_API_KEY = "gsk_..."     # or GEMINI_API_KEY / OPENROUTER_API_KEY, or --provider ollama

uv run git-rescue "my commits disappeared"        # options go before the problem text
uv run git-rescue --dry-run "my commits disappeared"
uv run git-rescue undo

uv run pytest                                     # 465 tests, no API key needed
```

Keys are read from the environment, never from a file in the repo.
