"""
Shared Rich console and theme for the Over-Watch CLI.

One console instance and one palette, imported everywhere, so `doctor`, `eval`,
`demo` and `worker` all speak the same visual language:

    success / PASS      green
    error / FAIL / FOOL red
    warning             yellow
    info / labels       cyan
    secondary detail    dim
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.theme import Theme

OVERWATCH_THEME = Theme({
    "success": "bold green",
    "error": "bold red",
    "warning": "bold yellow",
    "info": "bold cyan",
    "muted": "dim",
    "heading": "bold white",
    "accent": "bold magenta",
})

console = Console(theme=OVERWATCH_THEME)

# Plain ASCII-safe status marks. No square brackets in the visible text: Rich
# would parse them as markup tags and silently drop them.
OK = "[success]PASS[/success]"
FAIL = "[error]FAIL[/error]"
WARN = "[warning]WARN[/warning]"


def banner(subtitle: str = "") -> None:
    """Print the Over-Watch title block."""
    title = "[accent]OVER-WATCH[/accent]  [muted]SRE investigation agent[/muted]"
    body = title if not subtitle else f"{title}\n[muted]{subtitle}[/muted]"
    console.print(Panel(body, border_style="magenta", padding=(0, 2)))


def section(text: str) -> None:
    """A labelled section divider."""
    console.rule(f"[info]{text}[/info]", style="cyan")


def success(text: str) -> None:
    console.print(f"[success]v[/success] {text}")


def fail(text: str) -> None:
    console.print(f"[error]x[/error] {text}")


def warn(text: str) -> None:
    console.print(f"[warning]![/warning] {text}")


def info(text: str) -> None:
    console.print(f"[info]-[/info] {text}")


def hint(text: str) -> None:
    console.print(f"  [muted]{text}[/muted]")
