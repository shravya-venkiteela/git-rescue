| system | runs | recovered | data loss | unparsed replies | tokens/run |
|---|---|---|---|---|---|
| description_only | 27 | 3/27 (11%) (1, 2, 0 per pass) | 0/27 | 0/27 | 1,477 |
| rescue_agent | 27 | 20/27 (74%) (7, 7, 6 per pass) | 0/27 | 6/27 | n/a |
| unrestricted_shell | 27 | 19/27 (70%) (7, 7, 5 per pass) | 1/27 | 0/27 | 6,800 |

Recovered per scenario (one column per system):

| scenario | description_only | rescue_agent | unrestricted_shell |
|---|---|---|---|
| accidental-pull-merge-01 | 2/3 | 2/3 | 1/3 |
| bad-amend-01 | 0/3 | 1/3 | 3/3 |
| deleted-branch-01 | 0/3 | 2/3 | 2/3 |
| detached-head-01 | 0/3 | 2/3 | 3/3 |
| dropped-stash-01 | 0/3 | 2/3 | 3/3 |
| rebase-conflict-abort-01 | 0/3 | 3/3 | 0/3 |
| reset-hard-committed-01 | 0/3 | 3/3 | 3/3 |
| reset-hard-staged-01 | 0/3 | 2/3 | 2/3 |
| wrong-branch-01 | 1/3 | 3/3 | 2/3 |

Why runs ended:

- **description_only**: no_commands_proposed=11, read_only_advice=11, recovered=3, command_failed=2
- **rescue_agent**: recovered=20, unparsable_output=6, wrong_fix=1
- **unrestricted_shell**: recovered=19, read_only_advice=5, command_failed=3

Runs that lost data:

- **unrestricted_shell** on `rebase-conflict-abort-01` (pass 1): 2 item(s) unreachable afterwards; ended as `command_failed`.
