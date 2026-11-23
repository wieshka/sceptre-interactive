"""
Render the README screenshots as SVG, using the plugin's real view code so the
colours match the CLI exactly.

    python docs/render_screenshots.py
"""

from pathlib import Path
from unittest.mock import patch

from rich.console import Console, Group

from sceptre_interactive.model import PlanState, ResourceEvent
from sceptre_interactive.view import PlanView, summary

DOCS = Path(__file__).parent
NOW = 1000.0
STACK = "AWS::CloudFormation::Stack"

BATCHES = [
    ["network/vpc"],
    ["network/subnets", "security/kms"],
    ["app/database", "app/queue", "app/service"],
]
RESOURCES = {
    "network/vpc": [
        ("VPC", "AWS::EC2::VPC"),
        ("InternetGateway", "AWS::EC2::InternetGateway"),
    ],
    "network/subnets": [
        ("SubnetA", "AWS::EC2::Subnet"),
        ("SubnetB", "AWS::EC2::Subnet"),
        ("SubnetC", "AWS::EC2::Subnet"),
        ("RouteAssocA", "AWS::EC2::SubnetRouteTableAssociation"),
        ("RouteAssocB", "AWS::EC2::SubnetRouteTableAssociation"),
    ],
    "security/kms": [("Key", "AWS::KMS::Key"), ("KeyAlias", "AWS::KMS::Alias")],
    "app/database": [
        ("DBSubnetGroup", "AWS::RDS::DBSubnetGroup"),
        ("DBCluster", "AWS::RDS::DBCluster"),
    ],
    "app/queue": [
        ("Queue", "AWS::SQS::Queue"),
        ("QueuePolicy", "AWS::SQS::QueuePolicy"),
    ],
    "app/service": [
        ("Cluster", "AWS::ECS::Cluster"),
        ("TaskRole", "AWS::IAM::Role"),
        ("LoadBalancer", "AWS::ElasticLoadBalancingV2::LoadBalancer"),
    ],
}


def external(name):
    return "demo-" + name.replace("/", "-")


def new_state():
    names = [n for batch in BATCHES for n in batch]
    state = PlanState("launch", BATCHES, {n: external(n) for n in names})
    return state


def event(state, stack, logical_id, resource_type, status, reason=""):
    state.add_event(ResourceEvent(stack, logical_id, resource_type, status, reason))


def start(state, name, started_ago):
    state.stack_started(name)
    state.stacks[name].started = NOW - started_ago
    event(state, name, external(name), STACK, "CREATE_IN_PROGRESS", "User Initiated")


def complete(state, name, started_ago, took):
    start(state, name, started_ago)
    for logical_id, resource_type in RESOURCES[name]:
        event(state, name, logical_id, resource_type, "CREATE_COMPLETE")
    event(state, name, external(name), STACK, "CREATE_COMPLETE")
    state.stack_finished(name, "complete")
    state.stacks[name].finished = NOW - started_ago + took


def running_state():
    state = new_state()
    state.started = NOW - 42
    complete(state, "network/vpc", 42, 21)
    start(state, "network/subnets", 19)
    for logical_id, resource_type in RESOURCES["network/subnets"][:3]:
        event(state, "network/subnets", logical_id, resource_type, "CREATE_COMPLETE")
    for logical_id, resource_type in RESOURCES["network/subnets"][3:]:
        event(state, "network/subnets", logical_id, resource_type, "CREATE_IN_PROGRESS")
    start(state, "security/kms", 19)
    event(state, "security/kms", "Key", "AWS::KMS::Key", "CREATE_COMPLETE")
    event(state, "security/kms", "KeyAlias", "AWS::KMS::Alias", "CREATE_IN_PROGRESS")
    state.add_message("network/subnets - Creating Stack", "network/subnets")
    state.add_message("security/kms - Creating Stack", "security/kms")
    return state


def failed_state():
    state = new_state()
    state.started = NOW - 214
    complete(state, "network/vpc", 214, 21)
    complete(state, "network/subnets", 193, 38)
    complete(state, "security/kms", 193, 24)
    complete(state, "app/database", 155, 148)
    complete(state, "app/queue", 155, 17)
    start(state, "app/service", 155)
    for logical_id, resource_type in RESOURCES["app/service"][:2]:
        event(state, "app/service", logical_id, resource_type, "CREATE_COMPLETE")
    event(
        state,
        "app/service",
        "LoadBalancer",
        "AWS::ElasticLoadBalancingV2::LoadBalancer",
        "CREATE_FAILED",
        "At least two subnets in two different Availability Zones must be specified",
    )
    event(
        state,
        "app/service",
        external("app/service"),
        STACK,
        "ROLLBACK_COMPLETE",
        "The following resource(s) failed to create: [LoadBalancer].",
    )
    state.stack_finished("app/service", "failed")
    state.stacks["app/service"].finished = NOW - 155 + 61
    state.finish()
    state.finished = NOW
    return state


def save(renderable, filename, title):
    console = Console(record=True, width=110, file=open("/dev/null", "w"))
    console.print(renderable)
    console.save_svg(str(DOCS / filename), title=title)
    print(f"wrote docs/{filename}")


def main():
    with patch("sceptre_interactive.model.time.monotonic", return_value=NOW):
        save(
            PlanView(running_state()),
            "running.svg",
            "sceptre-interactive -i launch dev",
        )
        state = failed_state()
        # What stays on screen after the live display closes
        save(
            Group(PlanView(state, max_resources=0, max_log=0), summary(state)),
            "finished.svg",
            "sceptre-interactive -i launch dev",
        )


if __name__ == "__main__":
    main()
