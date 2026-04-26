import typer

app = typer.Typer(no_args_is_help=True)


@app.callback()
def _main() -> None:
    pass


@app.command()
def hello() -> None:
    typer.echo("wiki ready")


if __name__ == "__main__":
    app()
