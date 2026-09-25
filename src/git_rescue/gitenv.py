"""The environment git runs in.

The benchmark needs a sealed environment: no user config, no hooks, a fixed
identity, so every scenario builds byte-identical SHAs. A person's own
repository needs the opposite: their config and their name on any commit this
tool makes. Both live here so the difference is a decision, not an accident.
"""
from __future__ import annotations

import os
from pathlib import Path

#Git must never stop to ask a question or open an editor: this runs unattended.
NON_INTERACTIVE = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
    "GIT_EDITOR": ":",
    "GIT_SEQUENCE_EDITOR": ":",
    "GIT_MERGE_AUTOEDIT": "no",
}

_USE_USER_ENVIRONMENT = False


def use_user_environment(enabled: bool = True) -> None:
    """Called by the CLI. From then on git runs with the person's own config
    and identity instead of the benchmark's sealed one."""
    global _USE_USER_ENVIRONMENT
    _USE_USER_ENVIRONMENT = enabled


def isolated_env(home: Path) -> dict[str, str]:
    """Env for git with every source of outside config removed."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "Scenario Author",
        "GIT_AUTHOR_EMAIL": "author@example.com",
        "GIT_COMMITTER_NAME": "Scenario Author",
        "GIT_COMMITTER_EMAIL": "author@example.com",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
    })
    return env


def user_env() -> dict[str, str]:
    """The person's own environment: their git config, their identity. A commit
    this tool makes on their repository must not be signed "Scenario Author"."""
    env = dict(os.environ)
    env.update(NON_INTERACTIVE)
    return env


def env_for(home: Path) -> dict[str, str]:
    """What the agent's tools and executor should use: the person's environment
    when running for real, the sealed one when running the benchmark."""
    return user_env() if _USE_USER_ENVIRONMENT else isolated_env(home)
