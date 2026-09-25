"""git rescue: diagnose a broken repository, propose a plan, preview it, then run it.

Nothing runs without being shown first. The agent may only read while it
investigates; the plan it proposes is checked against a risk table, tried on a
copy of the repository, and (when destructive) backed up before it is applied.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import typer

from . import backup as backup_mod
from . import executor, risk
from .gitenv import use_user_environment

app = typer.Typer(no_args_is_help=False, add_completion=False)

RISK_MARK = {risk.SAFE: "safe", risk.REVERSIBLE: "reversible",
             risk.DESTRUCTIVE: "DESTRUCTIVE", risk.BLOCKED: "BLOCKED"}


def _fail(message: str) -> int:
    typer.secho(f"git rescue: {message}", fg="red")
    return 1


def _repo_root(start: Path) -> Path:
    found = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start,
                           capture_output=True, text=True)
    if found.returncode != 0:
        raise typer.Exit(code=_fail("this is not a git repository"))
    return Path(found.stdout.strip())


def _backend(provider: str, model: str | None):
    """Keys come from the environment, never from a file."""
    from .llm import build_backend

    return build_backend(provider, model)


def _show_plan(plan, review: dict) -> None:
    typer.echo("")
    typer.secho("Diagnosis", bold=True)
    typer.echo(f"  {plan.diagnosis}  (confidence: {plan.confidence})")
    if plan.unrecoverable:
        typer.secho("Cannot be recovered", bold=True)
        for item in plan.unrecoverable:
            typer.echo(f"  - {item}")
    if plan.rotate_secrets_first:
        typer.secho("  Rotate the exposed secret first: a committed secret must be treated as leaked.",
                    fg="yellow")
    if plan.steps:
        typer.secho("Plan", bold=True)
        for i, (step, row) in enumerate(zip(plan.steps, review["steps"]), start=1):
            mark = RISK_MARK.get(row["actual"], row["actual"])
            colour = {"DESTRUCTIVE": "red", "BLOCKED": "red", "reversible": "yellow"}.get(mark)
            typer.echo(f"  {i}. {step.text}")
            typer.secho(f"     {mark}: {row['why']}", fg=colour)
            typer.echo(f"     why: {step.purpose}")


@app.command()
def undo(repo: Path = typer.Option(None, help="repository to roll back")) -> None:
    """Roll back the last rescue, restoring the copy it kept."""
    root = _repo_root(repo or Path.cwd())
    saved = backup_mod.latest_for(root)
    if saved is None:
        raise typer.Exit(code=_fail("no backup found for this repository"))
    details = json.loads(saved.manifest.read_text(encoding="utf-8"))
    typer.echo(f"Restoring the copy taken at {details['created']}: {details.get('note') or 'no note'}")
    if not typer.confirm("This replaces the repository with that copy. Continue?"):
        raise typer.Exit(code=1)
    #The undo is backed up first, so an undo can itself be undone. It is marked
    #as a safety copy so the next undo does not treat it as a rescue to revert.
    backup_mod.create(root, note="before undo", kind=backup_mod.SAFETY)
    backup_mod.restore(saved, root)
    typer.secho("Restored.", fg="green")


@app.callback(invoke_without_command=True)
def rescue(
    ctx: typer.Context,
    problem: str = typer.Argument("", help="what went wrong, in your own words"),
    repo: Path = typer.Option(None, help="repository to rescue"),
    provider: str = typer.Option(os.environ.get("GIT_RESCUE_PROVIDER", "groq"),
                                 help="ollama, groq, gemini or openrouter"),
    model: str = typer.Option(None, help="model name (default depends on the provider)"),
    budget: int = typer.Option(6, help="how many read-only look-ups the agent may make"),
    dry_run: bool = typer.Option(False, "--dry-run", help="show the plan and stop"),
    yes: bool = typer.Option(False, "--yes", help="skip the confirmation prompt"),
) -> None:
    """Diagnose and fix the current repository."""
    if ctx.invoked_subcommand is not None:
        return
    #`git rescue undo` arrives here with problem="undo": this command takes a
    #free-text argument, so the parser reads that word as the problem and the
    #agent starts investigating "undo". The subcommand wins.
    if problem.strip().lower() == "undo":
        return undo(repo=repo)
    from .agent import RescueAgent

    #A real repository, so git uses the person's own config and identity.
    use_user_environment()
    root = _repo_root(repo or Path.cwd())
    if not problem:
        problem = typer.prompt("What went wrong? (in your own words)")

    typer.echo("Looking at the repository (read-only)...")
    run = RescueAgent(_backend(provider, model), budget=budget).investigate(
        root, problem,
        ask=lambda q: typer.prompt(f"  {q}"),
        log=lambda event: typer.echo(f"  ran {event['tool']}") if event["type"] == "tool_call" else None,
    )
    if run.plan is None:
        raise typer.Exit(code=_fail(run.gave_up or "could not produce a plan"))

    review = risk.review(run.plan)
    _show_plan(run.plan, review)
    if not run.plan.steps:
        return                            # "nothing can be done" is an answer
    if dry_run:
        typer.echo("\n--dry-run: nothing was run.")
        return

    def confirm(plan, review, shadow_diff) -> bool:
        typer.secho("\nWhat this would change (tried on a copy first)", bold=True)
        typer.echo("  " + shadow_diff.replace("\n", "\n  "))
        if review["overall"] == risk.DESTRUCTIVE:
            typer.secho("  The whole repository is copied before this runs;"
                        " `git rescue undo` puts it back.", fg="yellow")
        return yes or typer.confirm("Run this plan?")

    outcome = executor.execute(root, run.plan, confirm=confirm)
    if not outcome.ok:
        raise typer.Exit(code=_fail(outcome.reason))
    typer.secho(f"\nDone. {run.plan.diagnosis}", fg="green")
    if outcome.backup is not None:
        typer.echo(f"Backup: {outcome.backup.path}  (undo with `git rescue undo`)")
