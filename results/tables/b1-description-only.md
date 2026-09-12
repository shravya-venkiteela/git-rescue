# B1 description-only, qwen2.5:7b, N=9, 1 run each, 2026-09-12

| system | recovered | practical loss | absolute loss | unparsed |
|---|---|---|---|---|
| description_only | 0/9 | 0/9 | 0/9 | 0/9 |
| description_only_no_questions | 0/9 | 0/9 | 0/9 | 0/9 |
| do_nothing | 0/9 | 0/9 | 0/9 | 0/9 |

Why runs ended:
- description_only: read_only_advice=5, command_failed=4
- description_only_no_questions: no_commands_proposed=5, command_failed=4
- do_nothing: no_commands_proposed=9

Notes:
- read_only_advice: the model proposed a correct first step (reflog, stash list)
  and every command succeeded, but it never sees the output, so it cannot act
  on it. Advice without inspection cannot complete a look-then-act rescue.
- Disabling questions changed HOW runs failed, never WHETHER. The same 4
  command_failed runs appear in both variants.
- The 5 refusals name what is missing: branch names (a user can answer) vs
  commit hashes (only the repo knows).
- wrong-branch-01 proposed force-pushing main although the user said nothing
  was pushed. No command ran, but destructive intent appeared in a plan.
- Caveat: N=9, single run, no variance estimate.
