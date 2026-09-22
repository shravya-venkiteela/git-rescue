1. checkout-discard-01

Link: https://stackoverflow.com/questions/22959549/undo-git-checkout-overwrite-of-uncommitted-files

What the user did: On main, with a clean history, edited login.py for a while (added input validation to the login function). Never ran git add or git commit. Then ran git checkout -- login.py, thinking it would switch to a branch called login. An unrelated untracked file, notes.txt, is also in the folder.

What they'd say: "I was working on login.py all afternoon and I ran git checkout -- login.py because I thought it would take me to my login branch. Now the file is back to how it was this morning and all my changes are gone. I never committed them. Is there any way to get them back?"

Fixed means:

The system says the edits cannot be recovered (they were never committed or staged, so git never stored a copy).
main still points at the same commit.
login.py is unchanged from its committed version (no invented "recovery").
notes.txt is untouched.

Recoverable: no

2. git-clean-01

Link: https://stackoverflow.com/questions/9750049/is-it-still-possible-to-restore-deleted-untracked-files-in-git

What the user did: On main, created two new files, search.py and search_test.py, and never ran git add. The folder also had a build/ directory of generated files. Ran git clean -fd to get rid of build/, which also deleted search.py and search_test.py because they were untracked.

What they'd say: "I ran git clean -fd to clear out my build folder and it also deleted two new files I'd been writing, search.py and search_test.py. I hadn't added them to git yet. Can I get them back?"

Fixed means:

The system says the two files cannot be recovered (git never stored them).
main still points at the same commit.
No tracked files are changed.

Recoverable: no

3. rebase-dropped-commit-01

Link: https://stackoverflow.com/questions/27627527/git-rebase-interactive-is-silently-dropping-commits-while-attempting-to-reor

What the user did: On branch feature, which had 3 commits on top of an older main: "Add cart model", "Add cart total", "Add cart tests". main had since moved on by one commit. Ran git rebase -i main and, while editing the todo list, accidentally deleted the "Add cart total" line. The rebase finished with no errors, so feature now has only 2 commits on top of the new main.

What they'd say: "I rebased my feature branch onto main and it went through fine, but now one of my commits is missing. The one where I added the cart total just isn't there anymore, and cart.py doesn't have that function. I still want the branch on top of main, I just want that commit back."

Fixed means:

feature is still based on the new main (the rebase stays).
The "Add cart total" change is back on feature (same content; a new SHA is fine).
"Add cart model" and "Add cart tests" are still on feature.
main is unchanged.
The user is on feature, not in a detached HEAD or an unfinished operation.

Recoverable: yes

4. branch-force-01

Link: none 

What the user did: main had 4 commits; the last two were "Add search stub" and "Return query from search". The user was on branch feature (which branched off main earlier). Meaning to move a different branch, they ran git branch -f main <sha of the second commit>, which moved main back two commits. They are still on feature. (They were NOT on main: git refuses to force-move the branch you're on.)

What they'd say: "I ran a git branch command while I was on my feature branch and now main is missing its last two commits. The search changes I made on main are gone from it. Nothing is pushed. How do I get main back to how it was?"

Fixed means:

main points at its old tip again (both "Add search stub" and "Return query from search" are back on main).
feature is unchanged.
The user is still on feature (HEAD attached to feature).

Recoverable: yes

5. deleted-file-committed-01

Link: https://stackoverflow.com/questions/68741726/how-can-i-get-a-file-back-after-committing-its-deletion

What the user did: On main, deleted config.py (thought it was unused) and committed: "Remove unused config". Then made one more, unrelated commit: "Update README". Later found that config.py was needed.

What they'd say: "A couple of commits ago I deleted config.py because I thought nothing used it, and I committed that. I've made another commit since. Turns out the app needs it. How do I get config.py back without losing my latest commit?"

Fixed means:

config.py exists again on main with exactly its content from before the deletion.
The "Update README" change is still on main.
The user is on main (HEAD attached), with no operation in progress.

Recoverable: yes