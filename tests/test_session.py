import io
import logging
from unittest.mock import patch

import pytest
from rich.console import Console
from sceptre.plan.executor import SceptrePlanExecutor
from sceptre.stack_status import StackStatus

from sceptre_interactive import demo
from sceptre_interactive.session import InteractiveSession, PlanStateLogHandler


@pytest.fixture
def sceptre_stream_handler():
    """A StreamHandler on the sceptre logger, as sceptre's setup_logging adds."""
    logger = logging.getLogger("sceptre")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield handler, stream
    logger.removeHandler(handler)


@pytest.fixture
def fast_demo():
    demo.FakeStackActions.speed = 1000
    demo.FakeStackActions.failing_stack = None
    yield demo
    demo.FakeStackActions.failing_stack = None


def run_plan(session, failing_stack=None):
    demo.FakeStackActions.failing_stack = failing_stack
    launch_order = [{demo.FakeStack(name) for name in batch} for batch in demo.PLAN]
    session.install()
    try:
        with patch("sceptre.plan.executor.StackActions", demo.FakeStackActions):
            return SceptrePlanExecutor("launch", launch_order, None).execute()
    finally:
        session.uninstall()


def terminal_console():
    return Console(
        file=io.StringIO(), force_terminal=True, width=140, color_system=None
    )


def test_install_and_uninstall_restore_executor():
    original = (SceptrePlanExecutor.execute, SceptrePlanExecutor._execute)
    session = InteractiveSession(console=terminal_console())
    session.install()
    session.install()  # idempotent
    assert session.installed
    assert SceptrePlanExecutor.execute is not original[0]
    session.uninstall()
    session.uninstall()
    assert (SceptrePlanExecutor.execute, SceptrePlanExecutor._execute) == original


def test_live_run_diverts_logs_and_prints_summary(fast_demo, sceptre_stream_handler):
    handler, stream = sceptre_stream_handler
    console = terminal_console()

    responses = run_plan(InteractiveSession(console=console))

    assert set(responses.values()) == {StackStatus.COMPLETE}
    output = console.file.getvalue()
    assert "launch: 6/6 stacks done in" in output
    # Sceptre's own log output was diverted while live, and restored after
    assert stream.getvalue() == ""
    logger = logging.getLogger("sceptre")
    assert handler in logger.handlers
    assert not any(isinstance(h, PlanStateLogHandler) for h in logger.handlers)


def test_failed_stack_in_summary(fast_demo, sceptre_stream_handler):
    console = terminal_console()
    responses = run_plan(InteractiveSession(console=console), "app/service")
    assert StackStatus.FAILED in responses.values()
    assert "✘ app/service: The following resource(s) failed to create" in (
        console.file.getvalue()
    )


def test_non_terminal_falls_back_to_plain_logs(fast_demo, sceptre_stream_handler):
    _, stream = sceptre_stream_handler
    console = Console(file=io.StringIO(), force_terminal=False)

    run_plan(InteractiveSession(console=console))

    assert console.file.getvalue() == ""
    assert "network/vpc VPC AWS::EC2::VPC CREATE_COMPLETE" in stream.getvalue()


def test_stack_exception_is_recorded_and_raised(fast_demo, sceptre_stream_handler):
    console = terminal_console()

    def explode(self):
        raise RuntimeError("no credentials")

    with patch.object(demo.FakeStackActions, "launch", explode):
        with pytest.raises(RuntimeError, match="no credentials"):
            run_plan(InteractiveSession(console=console))

    output = console.file.getvalue()
    assert "✘ network/vpc: no credentials" in output
    assert not any(
        isinstance(h, PlanStateLogHandler)
        for h in logging.getLogger("sceptre").handlers
    )


def test_warnings_go_to_log_footer():
    from sceptre_interactive.model import PlanState

    state = PlanState("launch", [["a"]])
    handler = PlanStateLogHandler(state)
    record = logging.LogRecord(
        "sceptre", logging.WARNING, "", 0, "a - careful", None, None
    )
    handler.emit(record)
    assert state.log == ["WARNING: a - careful"]
    assert state.stacks["a"].message == "WARNING: a - careful"
