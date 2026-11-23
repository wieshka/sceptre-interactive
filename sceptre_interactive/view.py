"""
Rich renderables for a PlanState: one line per stack (docker pull style) with
the resources that are currently changing listed underneath.
"""

from typing import List

from rich.console import Group, RenderableType
from rich.progress_bar import ProgressBar
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from sceptre_interactive.model import (
    COMPLETE,
    FAILED,
    QUEUED,
    RUNNING,
    SKIPPED,
    WAITING,
    PlanState,
    ResourceState,
    StackState,
)

PHASE_STYLE = {
    QUEUED: "dim",
    WAITING: "dim",
    RUNNING: "cyan",
    COMPLETE: "green",
    FAILED: "bold red",
    SKIPPED: "yellow",
}

PHASE_ICON = {
    QUEUED: "·",
    WAITING: "⧗",
    COMPLETE: "✔",
    FAILED: "✘",
    SKIPPED: "↷",
}

RESOURCE_STYLE = {RUNNING: "cyan", COMPLETE: "green", FAILED: "red"}


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


class PlanView:
    """Renderable that redraws a PlanState each time Rich refreshes."""

    def __init__(self, state: PlanState, max_resources: int = 4, max_log: int = 3):
        self.state = state
        self.max_resources = max_resources
        self.max_log = max_log
        # Spinners keep their own animation clock, so reuse them per stack
        self._spinners = {}

    def __rich__(self) -> RenderableType:
        stacks, log = self.state.snapshot()
        parts: List[RenderableType] = [self._header(stacks)]
        parts.append(self._stacks_table(stacks))
        if log and self.max_log:
            parts.append(
                Text("\n".join(log[-self.max_log :]), style="dim", overflow="ellipsis")
            )
        return Group(*parts)

    # -- pieces --------------------------------------------------------------

    def _header(self, stacks: List[StackState]) -> Text:
        total = len(stacks)
        done = sum(1 for s in stacks if s.phase in (COMPLETE, SKIPPED))
        failed = sum(1 for s in stacks if s.phase == FAILED)
        running = sum(1 for s in stacks if s.phase == RUNNING)

        header = Text()
        header.append(f"sceptre {self.state.command}", style="bold")
        header.append(f"  {done}/{total} done", style="green")
        if running:
            header.append(f"  {running} running", style="cyan")
        if failed:
            header.append(f"  {failed} failed", style="bold red")
        header.append(f"  {format_duration(self.state.elapsed)}", style="dim")
        return header

    def _stacks_table(self, stacks: List[StackState]) -> Table:
        # Fixed widths for everything but the message, which is the only
        # wrappable column and so the one Rich shrinks on narrow terminals.
        name_width = min(
            40,
            max(
                [len(s.name) for s in stacks]
                + [len(r) + 4 for s in stacks for r in s.resources]
                + [8]
            ),
        )
        table = Table.grid(padding=(0, 1), expand=False)
        table.add_column(width=1, no_wrap=True)  # icon / spinner
        table.add_column(width=name_width, no_wrap=True, overflow="ellipsis")
        table.add_column(width=20, no_wrap=True, overflow="ellipsis")  # bar / type
        table.add_column(width=26, no_wrap=True, overflow="ellipsis")  # status
        table.add_column(width=5, no_wrap=True, justify="right")  # elapsed
        table.add_column(min_width=0)  # message

        for stack in sorted(stacks, key=lambda s: (s.batch, s.name)):
            style = PHASE_STYLE[stack.phase]
            table.add_row(
                self._icon(stack),
                Text(stack.name, style="bold" if stack.phase == RUNNING else style),
                self._bar(stack),
                Text(self._status_text(stack), style=style),
                Text(
                    format_duration(stack.elapsed) if stack.started else "", style="dim"
                ),
                Text(
                    stack.message,
                    style="red" if stack.phase == FAILED else "dim",
                    no_wrap=True,
                    overflow="ellipsis",
                ),
            )
            if stack.phase == RUNNING or (stack.phase == FAILED and stack.resources):
                for resource in stack.active_resources(self.max_resources):
                    table.add_row(*self._resource_row(resource))
        return table

    def _icon(self, stack: StackState) -> RenderableType:
        if stack.phase == RUNNING:
            spinner = self._spinners.get(stack.name)
            if spinner is None:
                spinner = self._spinners[stack.name] = Spinner("dots", style="cyan")
            return spinner
        return Text(PHASE_ICON[stack.phase], style=PHASE_STYLE[stack.phase])

    @staticmethod
    def _bar(stack: StackState) -> RenderableType:
        total = len(stack.resources)
        if stack.phase == RUNNING and total == 0:
            return ProgressBar(total=None, width=20, pulse_style="cyan")
        if stack.phase in (COMPLETE, SKIPPED):
            return ProgressBar(total=1, completed=1, width=20, finished_style="green")
        if stack.phase in (QUEUED, WAITING):
            return ProgressBar(total=1, completed=0, width=20)
        return ProgressBar(
            total=max(total, 1),
            completed=stack.resources_done,
            width=20,
            complete_style="red" if stack.phase == FAILED else "cyan",
            finished_style="red" if stack.phase == FAILED else "green",
        )

    @staticmethod
    def _status_text(stack: StackState) -> str:
        if stack.phase == WAITING:
            return "waiting on dependencies"
        if stack.phase == QUEUED:
            return "queued"
        if stack.phase == SKIPPED:
            return "skipped"
        status = stack.cfn_status or stack.phase
        if stack.resources and stack.phase == RUNNING:
            status += f" {stack.resources_done}/{len(stack.resources)}"
        return status

    @staticmethod
    def _resource_row(resource: ResourceState):
        style = RESOURCE_STYLE.get(resource.state, "dim")
        return (
            Text(""),
            Text(f"  ↳ {resource.logical_id}", style="dim"),
            Text(
                resource.resource_type, style="dim", overflow="ellipsis", no_wrap=True
            ),
            Text(resource.status, style=style),
            Text(""),
            Text(
                resource.reason,
                style="red" if resource.state == FAILED else "dim",
                no_wrap=True,
                overflow="ellipsis",
            ),
        )


def summary(state: PlanState) -> Text:
    """One-line summary printed after the live display closes."""
    stacks, _ = state.snapshot()
    failed = [s for s in stacks if s.phase == FAILED]
    done = sum(1 for s in stacks if s.phase in (COMPLETE, SKIPPED))
    text = Text()
    if failed:
        text.append("✘ ", style="bold red")
    else:
        text.append("✔ ", style="bold green")
    text.append(
        f"{state.command}: {done}/{len(stacks)} stacks done"
        f"{f', {len(failed)} failed' if failed else ''}"
        f" in {format_duration(state.elapsed)}"
    )
    for stack in failed:
        text.append(f"\n  ✘ {stack.name}", style="red")
        if stack.message:
            text.append(f": {stack.message}", style="dim")
    return text
