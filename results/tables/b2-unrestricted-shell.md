# B2 unrestricted shell, qwen2.5:7b, N=9, 2026-09-12

Same model as B1, but it runs one command per turn and SEES the output
before choosing the next. No backup, no dry run, no confirmation.

| run | recovered | practical loss | distinct/total commands |
|---|---|---|---|
| first (15-turn cap, repeats allowed) | 1/9 | 2/9 | ~73/135 |
| second (repeats refused, turns shown) | 1/9 | 2/9 | 73/73 |

Why runs ended:
- first:  command_failed=6, wrong_fix=2, recovered=1
- second: wrong_fix=4, command_failed=4, recovered=1

Findings:
- Inspection alone is not the bottleneck. On deleted-branch-01 the model ran
  git reflog, saw the correct SHA in the output, and then used a different
  one (main_tip instead of the branch tip).
- In the first run EVERY scenario hit the 15-turn cap and only ~54% of
  commands were distinct: it filled its budget repeating itself. Refusing
  repeats removed all waste (73/73) and changed nothing about recovery, so
  the budget was never the binding constraint.
- Run-to-run variance is real: at temperature 0 with a fixed seed, the two
  runs recovered DIFFERENT scenarios (accidental-pull-merge vs
  reset-hard-committed), and pull-merge went from clean recovery to loss=2.
  Single-run numbers must not be quoted alone.
- 2/9 runs destroyed work with no backup: the case git rescue exists for.

Caveat: N=9, single run per configuration, no confidence intervals.
Go/no-go: B2 did not clear the 85% threshold, so the safety design still has
something to prove. But at ~11% it is a weak opponent, so 'beats B2' is not
a strong headline on its own.
