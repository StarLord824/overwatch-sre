"""Allow `python -m cli` in addition to the installed `overwatch` command."""

from cli.app import app

if __name__ == "__main__":
    app()
