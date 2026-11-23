"""
Adds ``-i/--interactive`` to the Sceptre CLI.

Sceptre has no plugin hook for CLI options yet, so ``sceptre-interactive`` is
the regular ``sceptre`` CLI with the option added. ``register`` is also
exposed under the ``sceptre.cli.plugins`` entry point group, ready for
Sceptre to load directly if such a hook is added.
"""

import functools

import click
from rich.console import Console

from sceptre_interactive.session import InteractiveSession

COMMANDS = ("create", "update", "launch", "delete")
SESSION_KEY = "sceptre_interactive.session"
LIST_RESOURCES_KEY = "sceptre_interactive.list_resources"
URLS_KEY = "sceptre_interactive.urls"


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


def _set_flag(key: str):
    def callback(ctx: click.Context, param: click.Parameter, value: bool):
        if value:
            ctx.find_root().meta[key] = True

    return callback


def _console(ctx: click.Context) -> Console:
    no_colour = bool((ctx.find_root().params or {}).get("no_colour"))
    return Console(no_color=no_colour or None)


def _show_resources(ctx: click.Context, path: str, console: Console, urls: bool):
    from sceptre.context import SceptreContext
    from sceptre.plan.plan import SceptrePlan

    from sceptre_interactive.resources import fetch_all, render_resources

    context = SceptreContext(
        command_path=path,
        command_params=ctx.params,
        project_path=ctx.obj.get("project_path"),
        user_variables=ctx.obj.get("user_variables"),
        options=ctx.obj.get("options"),
        output_format=ctx.obj.get("output_format"),
        ignore_dependencies=ctx.obj.get("ignore_dependencies"),
    )
    plan = SceptrePlan(context)
    plan.resolve(command="describe_resources")
    with console.status("Fetching stack resources..."):
        stacks = fetch_all(plan)
    render_resources(stacks, console, show_urls=urls)


def register_list_resources(cli: click.Group) -> None:
    """
    Add -i/--interactive and --urls to ``list resources``: a table per stack
    with physical IDs linked to the AWS console, instead of plain IDs.
    """
    group = cli.commands.get("list")
    command = getattr(group, "commands", {}).get("resources")
    if command is None or getattr(command, "_sceptre_interactive", False):
        return
    if not _has_option(command, "-i") and not _has_option(command, "--interactive"):
        command.params.append(
            click.Option(
                ["-i", "--interactive"],
                is_flag=True,
                expose_value=False,
                callback=_set_flag(LIST_RESOURCES_KEY),
                help="Show resource tables with physical IDs linked to the AWS console.",
            )
        )
    command.params.append(
        click.Option(
            ["--urls"],
            is_flag=True,
            expose_value=False,
            callback=_set_flag(URLS_KEY),
            help="With -i, print console URLs instead of terminal hyperlinks.",
        )
    )

    original = command.callback

    @functools.wraps(original)
    def callback(*args, **kwargs):
        from sceptre.cli.helpers import catch_exceptions

        ctx = click.get_current_context()
        meta = ctx.find_root().meta
        urls = bool(meta.get(URLS_KEY))
        wanted = meta.get(LIST_RESOURCES_KEY) or SESSION_KEY in meta or urls
        console = _console(ctx)
        # Piped output keeps Sceptre's format unless URLs were asked for
        if wanted and (console.is_terminal or urls):
            return catch_exceptions(_show_resources)(ctx, kwargs["path"], console, urls)
        return original(*args, **kwargs)

    command.callback = callback
    command._sceptre_interactive = True


def _has_option(command: click.Command, name: str) -> bool:
    return any(name in getattr(p, "opts", []) for p in command.params)


def register(cli: click.Group) -> click.Group:
    """
    Add -i/--interactive to the root group, to create/update/launch/delete
    (live display) and to list resources (console-linked tables).
    """
    targets = [cli] + [cli.commands[name] for name in COMMANDS if name in cli.commands]
    for command in targets:
        if not _has_option(command, "--interactive") and not _has_option(command, "-i"):
            command.params.append(interactive_option())
    register_list_resources(cli)
    return cli


def main():  # pragma: no cover - thin console script wrapper
    from sceptre.cli import cli

    register(cli)
    cli(prog_name="sceptre-interactive")
