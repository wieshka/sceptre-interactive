import pytest

from sceptre_interactive.model import (
    COMPLETE,
    FAILED,
    QUEUED,
    RUNNING,
    SKIPPED,
    WAITING,
    PlanState,
    ResourceEvent,
    parse_event,
    resource_state,
)


class TestParseEvent:
    def test_event_with_reason_containing_spaces(self):
        event = parse_event(
            "dev/vpc VPC AWS::EC2::VPC CREATE_FAILED Resource handler returned message"
        )
        assert event == ResourceEvent(
            "dev/vpc",
            "VPC",
            "AWS::EC2::VPC",
            "CREATE_FAILED",
            "Resource handler returned message",
        )

    def test_event_without_reason(self):
        # Sceptre joins an empty reason with a trailing space
        event = parse_event("dev/vpc VPC AWS::EC2::VPC CREATE_COMPLETE ")
        assert event.status == "CREATE_COMPLETE"
        assert event.reason == ""

    @pytest.mark.parametrize(
        "message",
        [
            "dev/vpc - Creating Stack",
            "dev/vpc - No updates to perform.",
            "Something went wrong",
        ],
    )
    def test_non_event_messages(self, message):
        assert parse_event(message) is None


@pytest.mark.parametrize(
    "status,expected",
    [
        ("CREATE_IN_PROGRESS", RUNNING),
        ("UPDATE_COMPLETE_CLEANUP_IN_PROGRESS", RUNNING),
        ("CREATE_COMPLETE", COMPLETE),
        ("DELETE_SKIPPED", COMPLETE),
        ("CREATE_FAILED", FAILED),
        ("ROLLBACK_COMPLETE", FAILED),
    ],
)
def test_resource_state(status, expected):
    assert resource_state(status) == expected


def make_state():
    return PlanState(
        "launch",
        [["a"], ["b", "c"], ["d"]],
        {"a": "proj-a", "b": "proj-b", "c": "proj-c", "d": "proj-d"},
    )


def phases(state):
    return {name: s.phase for name, s in state.stacks.items()}


class TestPlanState:
    def test_initial_phases(self):
        assert phases(make_state()) == {
            "a": QUEUED,
            "b": WAITING,
            "c": WAITING,
            "d": WAITING,
        }

    def test_next_batch_released_when_batch_finishes(self):
        state = make_state()
        state.stack_started("a")
        assert state.stacks["a"].phase == RUNNING
        state.stack_finished("a", "complete")
        assert phases(state) == {"a": COMPLETE, "b": QUEUED, "c": QUEUED, "d": WAITING}

        state.stack_finished("b", "complete")
        assert state.stacks["d"].phase == WAITING
        state.stack_errored("c", "boom")
        assert state.stacks["c"].message == "boom"
        assert state.stacks["d"].phase == QUEUED

    @pytest.mark.parametrize(
        "result,phase",
        [
            ("complete", COMPLETE),
            ("failed", FAILED),
            ("in progress", FAILED),
            ("pending", SKIPPED),
            (None, COMPLETE),
        ],
    )
    def test_stack_finished_results(self, result, phase):
        state = make_state()
        state.stack_finished("a", result)
        assert state.stacks["a"].phase == phase

    def test_stack_level_events_set_cfn_status(self):
        state = make_state()
        state.add_event(
            ResourceEvent(
                "a",
                "proj-a",
                "AWS::CloudFormation::Stack",
                "CREATE_IN_PROGRESS",
                "User Initiated",
            )
        )
        stack = state.stacks["a"]
        assert stack.cfn_status == "CREATE_IN_PROGRESS"
        assert stack.message == ""  # noise reason suppressed
        assert stack.resources == {}

    def test_nested_stack_is_a_resource(self):
        state = make_state()
        state.add_event(
            ResourceEvent(
                "a", "Nested", "AWS::CloudFormation::Stack", "CREATE_IN_PROGRESS"
            )
        )
        assert "Nested" in state.stacks["a"].resources
        assert state.stacks["a"].cfn_status == ""

    def test_resource_progress_and_failure_message(self):
        state = make_state()
        state.add_event(
            ResourceEvent(
                "a",
                "VPC",
                "AWS::EC2::VPC",
                "CREATE_IN_PROGRESS",
                "Resource creation Initiated",
            )
        )
        state.add_event(
            ResourceEvent("a", "Subnet", "AWS::EC2::Subnet", "CREATE_IN_PROGRESS")
        )
        stack = state.stacks["a"]
        assert stack.resources["VPC"].reason == ""
        assert stack.resources_done == 0

        state.add_event(ResourceEvent("a", "VPC", "AWS::EC2::VPC", "CREATE_COMPLETE"))
        state.add_event(
            ResourceEvent(
                "a", "Subnet", "AWS::EC2::Subnet", "CREATE_FAILED", "bad cidr"
            )
        )
        assert stack.resources_done == 2
        assert stack.resources_failed == 1
        assert stack.message == "Subnet: bad cidr"
        assert [r.logical_id for r in stack.active_resources(1)] == ["Subnet"]

    def test_messages_and_log_cap(self):
        state = make_state()
        state.add_message("a - Creating Stack", "a")
        assert state.stacks["a"].message == "Creating Stack"
        for i in range(60):
            state.add_message(f"line {i}")
        assert len(state.log) == 50
        assert state.log[-1] == "line 59"

    def test_unknown_stack_is_added(self):
        state = make_state()
        state.stack_started("z")
        assert state.stacks["z"].phase == RUNNING

    def test_snapshot_is_a_copy(self):
        state = make_state()
        state.add_event(
            ResourceEvent("a", "VPC", "AWS::EC2::VPC", "CREATE_IN_PROGRESS")
        )
        stacks, _ = state.snapshot()
        snap = {s.name: s for s in stacks}
        state.add_event(ResourceEvent("a", "VPC", "AWS::EC2::VPC", "CREATE_COMPLETE"))
        assert snap["a"].resources["VPC"].status == "CREATE_IN_PROGRESS"
