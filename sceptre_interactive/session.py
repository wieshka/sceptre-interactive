"""
Hooks the live display into Sceptre's plan executor.

While interactive mode is on, SceptrePlanExecutor.execute runs inside a
rich.live.Live display. Sceptre's own log output is diverted into the display:
CloudFormation event lines update the stack/resource rows, other messages
appear in the log footer. Confirmation prompts happen before the executor
runs, so they are unaffected.
"""

import logging
from typing import Optional

from rich.console import Console
from rich.live import Live
from sceptre.plan.executor import SceptrePlanExecutor

from sceptre_interactive.model import PlanState, parse_event
from sceptre_interactive.view import PlanView, summary

SCEPTRE_LOGGER = "sceptre"


class PlanStateLogHandler(logging.Handler):
    """Routes Sceptre log records into a PlanState instead of the terminal."""

    def __init__(self, state: PlanState):
        super().__init__(level=logging.INFO)
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            event = parse_event(message)
            if event is not None and event.stack in self.state.stacks:
                self.state.add_event(event)
                return
            stack_name = message.split(" - ", 1)[0] if " - " in message else None
            if record.levelno >= logging.WARNING:
                message = f"{record.levelname}: {message}"
            self.state.add_message(message, stack_name)
        except Exception:  # pragma: no cover - never break the deployment
            self.handleError(record)


class InteractiveSession:
    """Installs/uninstalls the executor hooks for interactive mode."""

    def __init__(
        self,
        console: Optional[Console] = None,
        refresh_per_second: float = 8,
        max_resources: int = 4,
    ):
        self.console = console or Console()
        self.refresh_per_second = refresh_per_second
        self.max_resources = max_resources
        self._original_execute = None
        self._original_execute_stack = None

    @property
    def installed(self) -> bool:
        return self._original_execute is not None

    def install(self) -> None:
        if self.installed:
            return
        session = self
        original_execute = self._original_execute = SceptrePlanExecutor.execute
        original_execute_stack = self._original_execute_stack = (
            SceptrePlanExecutor._execute
        )

        def execute(executor, *args):
            return session._run(executor, original_execute, *args)

        def execute_stack(executor, stack, *args):
            state = getattr(executor, "_interactive_state", None)
            if state is None:
                return original_execute_stack(executor, stack, *args)
            state.stack_started(stack.name)
            try:
                result = original_execute_stack(executor, stack, *args)
            except Exception as error:
                state.stack_errored(stack.name, str(error) or type(error).__name__)
                raise
            state.stack_finished(stack.name, result[1])
            return result

        SceptrePlanExecutor.execute = execute
        SceptrePlanExecutor._execute = execute_stack

    def uninstall(self) -> None:
        if not self.installed:
            return
        SceptrePlanExecutor.execute = self._original_execute
        SceptrePlanExecutor._execute = self._original_execute_stack
        self._original_execute = self._original_execute_stack = None

    # -- running -------------------------------------------------------------

    def _run(self, executor, original_execute, *args):
        stacks = [stack for batch in executor.launch_order for stack in batch]
        if not stacks or not self.console.is_terminal:
            return original_execute(executor, *args)

        state = PlanState(
            executor.command,
            [[stack.name for stack in batch] for batch in executor.launch_order],
            {stack.name: getattr(stack, "external_name", None) for stack in stacks},
        )
        executor._interactive_state = state

        logger = logging.getLogger(SCEPTRE_LOGGER)
        diverted = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
        handler = PlanStateLogHandler(state)
        for h in diverted:
            logger.removeHandler(h)
        logger.addHandler(handler)

        live = Live(
            PlanView(state, max_resources=self.max_resources),
            console=self.console,
            refresh_per_second=self.refresh_per_second,
            transient=True,
        )
        try:
            with live:
                return original_execute(executor, *args)
        finally:
            state.finish()
            logger.removeHandler(handler)
            for h in diverted:
                logger.addHandler(h)
            del executor._interactive_state
            # Leave the final state on screen, without spinners/resource rows
            self.console.print(PlanView(state, max_resources=0, max_log=0))
            self.console.print(summary(state))
