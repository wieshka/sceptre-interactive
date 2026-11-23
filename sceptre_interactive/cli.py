"""
Adds ``-i/--interactive`` to the Sceptre CLI.

Sceptre has no plugin hook for CLI options yet, so ``sceptre-interactive`` is
the regular ``sceptre`` CLI with the option added. ``register`` is also
exposed under the ``sceptre.cli.plugins`` entry point group, ready for
Sceptre to load directly if such a hook is added.
"""

import click
from rich.console import Console

from sceptre_interactive.session import InteractiveSession

COMMANDS = ("create", "update", "launch", "delete")
SESSION_KEY = "sceptre_interactive.session"


def _enable_interactive(ctx: click.Context, param: click.Parameter, value: bool):
    if not value:
        return
    root = ctx.find_root()
    if SESSION_KEY in root.meta:
        return
    no_colour = bool((root.params or {}).get("no_colour"))
    session = InteractiveSession(console=Console(no_color=no_colour or None))
    session.install()
    root.meta[SESSION_KEY] = session
    root.call_on_close(session.uninstall)


def interactive_option() -> click.Option:
    return click.Option(
        ["-i", "--interactive"],
        is_flag=True,
        expose_value=False,
        callback=_enable_interactive,
        help="Show a live progress display instead of a log of stack events.",
    )


def _has_option(command: click.Command, name: str) -> bool:
    return any(name in getattr(p, "opts", []) for p in command.params)


def register(cli: click.Group) -> click.Group:
    """Add -i/--interactive to the root group and to create/update/launch/delete."""
    targets = [cli] + [cli.commands[name] for name in COMMANDS if name in cli.commands]
    for command in targets:
        if not _has_option(command, "--interactive") and not _has_option(command, "-i"):
            command.params.append(interactive_option())
    return cli


def main():  # pragma: no cover - thin console script wrapper
    from sceptre.cli import cli

    register(cli)
    cli(prog_name="sceptre-interactive")
