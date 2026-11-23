from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner
from sceptre.cli import cli

from sceptre_interactive import register
from sceptre_interactive.cli import COMMANDS, SESSION_KEY


def interactive_opts(command):
    return [p for p in command.params if "--interactive" in getattr(p, "opts", [])]


@pytest.fixture(scope="module", autouse=True)
def registered():
    register(cli)
    register(cli)  # idempotent


def test_option_added_once_to_root_and_commands():
    for command in [cli] + [cli.commands[name] for name in COMMANDS]:
        options = interactive_opts(command)
        assert len(options) == 1
        assert options[0].opts == ["-i", "--interactive"]


def test_other_commands_untouched():
    assert interactive_opts(cli.commands["validate"]) == []


def test_skips_commands_that_already_use_dash_i():
    @click.group()
    def group():
        pass

    @group.command(name="launch")
    @click.option("-i", "--ignore")
    def launch(ignore):
        pass

    register(group)
    assert interactive_opts(group.commands["launch"]) == []
    assert len(interactive_opts(group)) == 1


@pytest.mark.parametrize(
    "args",
    [["-i", "launch", "dev", "-y"], ["launch", "dev", "-y", "--interactive"]],
)
def test_flag_installs_session_and_cleans_up(args, tmp_path):
    (tmp_path / "config").mkdir()
    seen = {}

    def fake_launch(launcher, prune):
        ctx = click.get_current_context().find_root()
        session = ctx.meta.get(SESSION_KEY)
        seen["installed"] = session is not None and session.installed
        seen["session"] = session
        return 0

    with (
        patch("sceptre.cli.launch.Launcher.print_operations"),
        patch("sceptre.cli.launch.Launcher.launch", fake_launch),
    ):
        result = CliRunner().invoke(cli, ["--dir", str(tmp_path)] + args)

    assert result.exit_code == 0, result.output
    assert seen["installed"] is True
    assert seen["session"].installed is False  # uninstalled on exit


def test_without_flag_no_session(tmp_path):
    (tmp_path / "config").mkdir()
    seen = {}

    def fake_launch(launcher, prune):
        seen["session"] = click.get_current_context().find_root().meta.get(SESSION_KEY)
        return 0

    with (
        patch("sceptre.cli.launch.Launcher.print_operations"),
        patch("sceptre.cli.launch.Launcher.launch", fake_launch),
    ):
        result = CliRunner().invoke(
            cli, ["--dir", str(tmp_path), "launch", "dev", "-y"]
        )

    assert result.exit_code == 0, result.output
    assert seen["session"] is None
