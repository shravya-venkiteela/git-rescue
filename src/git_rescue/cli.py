import typer

app = typer.Typer(no_args_is_help=False)
@app.callback(invoke_without_command=True)
def rescue(ctx:typer.Context):
    """ Diagnose and fix the current repository. """
    if ctx.invoked_subcommand is None:
        typer.echo("git rescue:not implemented yet")

@app.command()
def undo():
    """Roll back the last rescue."""
    typer.echo("git rescue undo: not implemented yet")