from rich.console import Console

from sceptre_interactive.model import PlanState, ResourceEvent
from sceptre_interactive.view import PlanView, format_duration, summary


def render(renderable) -> str:
    console = Console(width=140, record=True, file=open("/dev/null", "w"))
    console.print(renderable)
    return console.export_text()


def make_state():
    state = PlanState(
        "launch", [["net/vpc"], ["app/web", "app/db"]], {"net/vpc": "p-net-vpc"}
    )
    state.stack_started("net/vpc")
    state.add_event(
        ResourceEvent(
            "net/vpc", "p-net-vpc", "AWS::CloudFormation::Stack", "CREATE_IN_PROGRESS"
        )
    )
    state.add_event(ResourceEvent("net/vpc", "VPC", "AWS::EC2::VPC", "CREATE_COMPLETE"))
    state.add_event(
        ResourceEvent("net/vpc", "Subnet", "AWS::EC2::Subnet", "CREATE_IN_PROGRESS")
    )
    state.add_message("net/vpc - Creating Stack", "net/vpc")
    return state


def test_format_duration():
    assert format_duration(5) == "00:05"
    assert format_duration(125) == "02:05"
    assert format_duration(3725) == "1:02:05"


def test_running_plan():
    output = render(PlanView(make_state()))
    assert "sceptre launch" in output
    assert "0/3 done" in output and "1 running" in output
    assert "CREATE_IN_PROGRESS 1/2" in output
    assert "↳ Subnet" in output and "↳ VPC" in output
    assert output.count("waiting on dependencies") == 2
    assert "net/vpc - Creating Stack" in output


def test_resource_rows_limited_and_hidden_when_done():
    state = make_state()
    assert "↳ VPC" not in render(PlanView(state, max_resources=1))

    state.stack_finished("net/vpc", "complete")
    output = render(PlanView(state, max_log=0))
    assert "↳" not in output
    assert "Creating Stack" not in output
    assert output.count("queued") == 2


def test_failed_stack_shows_reason_and_summary():
    state = make_state()
    state.add_event(
        ResourceEvent(
            "net/vpc", "Subnet", "AWS::EC2::Subnet", "CREATE_FAILED", "bad cidr"
        )
    )
    state.stack_finished("net/vpc", "failed")
    state.finish()

    output = render(PlanView(state))
    assert "1 failed" in output
    assert "Subnet: bad cidr" in output

    text = render(summary(state))
    assert "launch: 0/3 stacks done, 1 failed" in text
    assert "✘ net/vpc: Subnet: bad cidr" in text


def test_successful_summary():
    state = PlanState("delete", [["a"]])
    state.stack_finished("a", "complete")
    assert "✔ delete: 1/1 stacks done in" in render(summary(state))
