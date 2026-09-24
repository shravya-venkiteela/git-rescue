| system | runs | recovered | data loss | unparsed replies | tokens/run |
|---|---|---|---|---|---|
| description_only | 15 | 7/15 (46%) (3, 2, 2 per pass) | 0/15 | 0/15 | 1,535 |
| rescue_agent | 15 | 14/15 (93%) (4, 5, 5 per pass) | 0/15 | 1/15 | 3,822 |
| unrestricted_shell | 15 | 13/15 (86%) (4, 4, 5 per pass) | 0/15 | 0/15 | 4,331 |

Recovered per scenario (one column per system):

| scenario | description_only | rescue_agent | unrestricted_shell |
|---|---|---|---|
| branch-force-01 | 0/3 | 3/3 | 1/3 |
| checkout-discard-01 | 2/3 | 3/3 | 3/3 |
| deleted-file-committed-01 | 2/3 | 3/3 | 3/3 |
| git-clean-01 | 3/3 | 3/3 | 3/3 |
| rebase-dropped-commit-01 | 0/3 | 2/3 | 3/3 |

Why runs ended:

- **description_only**: recovered=7, no_commands_proposed=5, read_only_advice=3
- **rescue_agent**: recovered=14, unparsable_output=1
- **unrestricted_shell**: recovered=13, read_only_advice=1, wrong_fix=1
