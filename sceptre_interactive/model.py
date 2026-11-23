"""
Thread-safe state of a running Sceptre plan, fed by the plan executor and by
the CloudFormation event lines Sceptre logs while it waits for stacks.
"""

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

# Sceptre logs each CloudFormation event as:
#   "<stack name> <logical id> <resource type> <status> [<reason>]"
# (see sceptre.plan.actions.StackActions._log_new_events). Stack names,
# logical ids, types and statuses never contain spaces; the reason may.
EVENT_RE = re.compile(
    r"^(?P<stack>\S+) (?P<logical_id>\S+) (?P<type>\S+::\S+) "
    r"(?P<status>[A-Z][A-Z_]+)(?: (?P<reason>.*))?$"
)

STACK_RESOURCE_TYPE = "AWS::CloudFormation::Stack"

# Event reasons that carry no information worth showing
NOISE_REASONS = {"User Initiated", "Resource creation Initiated"}

# Stack lifecycle phases shown in the UI
QUEUED = "queued"
WAITING = "waiting"  # queued behind a dependency batch
RUNNING = "running"
COMPLETE = "complete"
FAILED = "failed"
SKIPPED = "skipped"


@dataclass
class ResourceEvent:
    stack: str
    logical_id: str
    resource_type: str
    status: str
    reason: str = ""


def parse_event(message: str) -> Optional[ResourceEvent]:
    """Parse a Sceptre CloudFormation event log line, or return None."""
    match = EVENT_RE.match(message)
    if not match:
        return None
    return ResourceEvent(
        stack=match["stack"],
        logical_id=match["logical_id"],
        resource_type=match["type"],
        status=match["status"],
        reason=(match["reason"] or "").strip(),
    )


def resource_state(status: str) -> str:
    """Classify a CloudFormation resource/stack status."""
    if status.endswith("_FAILED") or status in ("ROLLBACK_COMPLETE",):
        return FAILED
    if status.endswith("_IN_PROGRESS"):
        return RUNNING
    if status.endswith("_COMPLETE") or status.endswith("_SKIPPED"):
        return COMPLETE
    return RUNNING


@dataclass
class ResourceState:
    logical_id: str
    resource_type: str
    status: str
    reason: str = ""
    updated: float = field(default_factory=time.monotonic)

    @property
    def state(self) -> str:
        return resource_state(self.status)


@dataclass
class StackState:
    name: str
    batch: int
    phase: str = QUEUED
    cfn_status: str = ""
    message: str = ""
    started: Optional[float] = None
    finished: Optional[float] = None
    resources: Dict[str, ResourceState] = field(default_factory=dict)

    @property
    def elapsed(self) -> float:
        if self.started is None:
            return 0.0
        return (self.finished or time.monotonic()) - self.started

    @property
    def resources_done(self) -> int:
        return sum(1 for r in self.resources.values() if r.state != RUNNING)

    @property
    def resources_failed(self) -> int:
        return sum(1 for r in self.resources.values() if r.state == FAILED)

    def active_resources(self, limit: int) -> List[ResourceState]:
        """Most recently updated resources, in-progress and failed first."""
        ranked = sorted(
            self.resources.values(),
            key=lambda r: (r.state == COMPLETE, -r.updated),
        )
        return ranked[:limit]


class PlanState:
    """Shared state for one executor run; all methods are thread-safe."""

    def __init__(
        self,
        command: str,
        batches: Iterable[Iterable[str]],
        external_names: Optional[Dict[str, str]] = None,
    ):
        """
        :param command: The Sceptre command being run (e.g. 'launch')
        :param batches: Stack names grouped in dependency order
        :param external_names: Stack name -> CloudFormation stack name, used to
            tell the stack's own status events apart from nested stacks
        """
        self.command = command
        self.external_names = external_names or {}
        self.started = time.monotonic()
        self.finished: Optional[float] = None
        self.log: List[str] = []
        self._lock = threading.RLock()
        self.stacks: Dict[str, StackState] = {}
        for batch_index, batch in enumerate(batches):
            for name in sorted(batch):
                self.stacks[name] = StackState(
                    name=name,
                    batch=batch_index,
                    phase=QUEUED if batch_index == 0 else WAITING,
                )

    # -- updates -----------------------------------------------------------

    def stack_started(self, name: str) -> None:
        with self._lock:
            stack = self._stack(name)
            stack.phase = RUNNING
            stack.started = time.monotonic()

    def stack_finished(self, name: str, result: Optional[str]) -> None:
        """Record a stack's final sceptre StackStatus (or None on error)."""
        with self._lock:
            stack = self._stack(name)
            stack.finished = time.monotonic()
            # sceptre.stack_status.StackStatus values; other commands (e.g.
            # change sets) return other things and count as done on success.
            if result not in ("failed", "in progress"):
                stack.message = ""  # drop stale progress messages
            if result == "failed":
                stack.phase = FAILED
            elif result == "in progress":
                stack.phase = FAILED
                stack.message = stack.message or "timed out waiting for stack"
            elif result == "pending":
                stack.phase = SKIPPED
            else:
                stack.phase = COMPLETE
            self._release_next_batch()

    def stack_errored(self, name: str, error: str) -> None:
        with self._lock:
            stack = self._stack(name)
            stack.finished = time.monotonic()
            stack.phase = FAILED
            stack.message = error
            self._release_next_batch()

    def add_event(self, event: ResourceEvent) -> None:
        with self._lock:
            stack = self._stack(event.stack)
            external_name = self.external_names.get(event.stack)
            if event.resource_type == STACK_RESOURCE_TYPE and (
                external_name is None or event.logical_id == external_name
            ):
                stack.cfn_status = event.status
                # Keep a failed resource's reason: it's the root cause, while
                # the stack's own reason is a generic "resource(s) failed".
                if (
                    event.reason
                    and event.reason not in NOISE_REASONS
                    and not stack.resources_failed
                ):
                    stack.message = event.reason
                return
            resource = stack.resources.get(event.logical_id)
            if resource is None:
                resource = stack.resources[event.logical_id] = ResourceState(
                    event.logical_id, event.resource_type, event.status
                )
            resource.status = event.status
            resource.updated = time.monotonic()
            resource.reason = "" if event.reason in NOISE_REASONS else event.reason
            if resource.state == FAILED and event.reason:
                stack.message = f"{event.logical_id}: {event.reason}"

    def add_message(self, message: str, stack_name: Optional[str] = None) -> None:
        with self._lock:
            if stack_name and stack_name in self.stacks:
                prefix = f"{stack_name} - "
                self.stacks[stack_name].message = message.removeprefix(prefix)
            self.log.append(message)
            del self.log[:-50]

    def finish(self) -> None:
        with self._lock:
            self.finished = time.monotonic()

    # -- reads -------------------------------------------------------------

    def snapshot(self):
        """Return (stacks, log) copies that are safe to render."""
        with self._lock:
            stacks = [
                StackState(
                    name=s.name,
                    batch=s.batch,
                    phase=s.phase,
                    cfn_status=s.cfn_status,
                    message=s.message,
                    started=s.started,
                    finished=s.finished,
                    resources={
                        k: ResourceState(**vars(v)) for k, v in s.resources.items()
                    },
                )
                for s in self.stacks.values()
            ]
            return stacks, list(self.log)

    @property
    def elapsed(self) -> float:
        return (self.finished or time.monotonic()) - self.started

    # -- internals ---------------------------------------------------------

    def _stack(self, name: str) -> StackState:
        stack = self.stacks.get(name)
        if stack is None:
            stack = self.stacks[name] = StackState(name=name, batch=0)
        return stack

    def _release_next_batch(self) -> None:
        """Mark the next batch as queued once the current one is all done."""
        pending_batches = sorted(
            {
                s.batch
                for s in self.stacks.values()
                if s.phase in (QUEUED, WAITING, RUNNING)
            }
        )
        if not pending_batches:
            return
        current = pending_batches[0]
        for stack in self.stacks.values():
            if stack.batch == current and stack.phase == WAITING:
                stack.phase = QUEUED
