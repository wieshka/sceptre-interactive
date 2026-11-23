import io
from unittest.mock import MagicMock

import botocore.exceptions
from rich.console import Console

from sceptre_interactive.resources import (
    StackResources,
    fetch_all,
    fetch_stack_resources,
    render_resources,
)


def resource(logical_id, physical_id, resource_type, status="CREATE_COMPLETE"):
    return {
        "LogicalResourceId": logical_id,
        "PhysicalResourceId": physical_id,
        "ResourceType": resource_type,
        "ResourceStatus": status,
    }


def client_error(message):
    return botocore.exceptions.ClientError(
        {"Error": {"Code": "ValidationError", "Message": message}}, "ListStackResources"
    )


def fake_stack(name, responses=None, error=None, region="eu-west-1"):
    stack = MagicMock()
    stack.name = name
    stack.external_name = "demo-" + name.replace("/", "-")
    stack.region = region
    if error:
        stack.connection_manager.call.side_effect = error
    else:
        stack.connection_manager.call.side_effect = responses
    return stack


class TestFetch:
    def test_paginates(self):
        stack = fake_stack(
            "net/vpc",
            [
                {
                    "StackResourceSummaries": [resource("A", "a", "T")],
                    "NextToken": "t1",
                },
                {"StackResourceSummaries": [resource("B", "b", "T")]},
            ],
        )
        result = fetch_stack_resources(stack)
        assert [r["LogicalResourceId"] for r in result.resources] == ["A", "B"]
        calls = stack.connection_manager.call.call_args_list
        assert calls[0].kwargs["kwargs"] == {"StackName": "demo-net-vpc"}
        assert calls[1].kwargs["kwargs"] == {
            "StackName": "demo-net-vpc",
            "NextToken": "t1",
        }

    def test_stack_not_deployed(self):
        stack = fake_stack(
            "net/vpc", error=client_error("Stack with id demo-net-vpc does not exist")
        )
        result = fetch_stack_resources(stack)
        assert result.exists is False and result.error is None

    def test_other_errors_are_reported(self):
        stack = fake_stack("net/vpc", error=client_error("Access denied"))
        assert fetch_stack_resources(stack).error == "Access denied"

    def test_falls_back_to_connection_manager_region(self):
        stack = fake_stack("net/vpc", [{"StackResourceSummaries": []}], region=None)
        stack.connection_manager.region = "us-east-1"
        assert fetch_stack_resources(stack).region == "us-east-1"

    def test_fetch_all_keeps_order(self):
        stacks = [
            fake_stack(f"s{i}", [{"StackResourceSummaries": []}]) for i in range(15)
        ]
        assert [r.name for r in fetch_all(stacks)] == [f"s{i}" for i in range(15)]
        assert fetch_all([]) == []


def sample():
    return [
        StackResources(
            "net/vpc",
            "demo-net-vpc",
            "eu-west-1",
            [
                resource("VPC", "vpc-0abc", "AWS::EC2::VPC"),
                resource("Thing", "thing-1", "Custom::Thing", "UPDATE_FAILED"),
            ],
        ),
        StackResources("app/web", "demo-app-web", "eu-west-1", exists=False),
        StackResources("app/db", "demo-app-db", "eu-west-1", error="Access denied"),
        StackResources("app/empty", "demo-app-empty", "eu-west-1"),
    ]


def render(show_urls=False):
    console = Console(
        file=io.StringIO(), force_terminal=True, width=200, color_system="truecolor"
    )
    render_resources(sample(), console, show_urls=show_urls)
    return console.file.getvalue()


def test_physical_ids_are_terminal_hyperlinks():
    output = render()
    vpc_url = (
        "https://eu-west-1.console.aws.amazon.com/vpcconsole/home?region=eu-west-1"
        "#VpcDetails:VpcId=vpc-0abc"
    )
    assert f"\x1b]8;id=" in output and vpc_url in output
    # The stack title links to the CloudFormation console
    assert "#/stacks/resources?stackId=demo-net-vpc" in output
    assert "thing-1" in output
    assert "not deployed" in output
    assert "Access denied" in output
    assert "no resources" in output
    assert "2 resources in 4 stacks, 1 linked to the AWS console" in output


def test_urls_mode_prints_plain_urls():
    output = render(show_urls=True)
    assert "\x1b]8;" not in output
    assert "#VpcDetails:VpcId=vpc-0abc" in output
