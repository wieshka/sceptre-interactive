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
    save(resources_view(), "resources.svg", "sceptre-interactive list resources dev -i")
    save(install_view(), "install.svg", "my-stacks — poetry")


# Recorded from a real `poetry add` into a fresh Poetry project (Poetry's own
# colours). The middle of the 34-package list is elided.
INSTALL_SOURCE = "git+https://github.com/wieshka/sceptre-interactive.git#v0.2.0"
INSTALL_FIRST = [
    ("six", "1.17.0"),
    ("python-dateutil", "2.9.0.post0"),
    ("urllib3", "2.8.0"),
]
INSTALL_LAST = [
    ("networkx", "2.6.3"),
    ("rich", "15.0.0"),
    ("sceptre", "4.7.0"),
    ("sceptre-interactive-plugin", "0.2.0 c6dadf1"),
]
INSTALL_TOTAL = 34


def install_view():
    from rich.text import Text

    def prompt(command):
        line = Text()
        line.append("~/my-stacks ", style="bold blue")
        line.append("$ ", style="bold green")
        line.append(command, style="bold")
        return line

    def installed(name, version):
        line = Text("  ")
        line.append("-", style="bold green")
        line.append(" Installing ")
        line.append(name, style="cyan")
        line.append(" (")
        line.append(version, style="green")
        line.append(")")
        return line

    lines = [prompt(f'poetry add "{INSTALL_SOURCE}"'), Text("")]
    lines += [Text("Updating dependencies", style="blue")]
    lines += [Text("Resolving dependencies...", style="blue"), Text("")]
    ops = Text()
    ops.append("Package operations", style="bold")
    ops.append(": ")
    ops.append(str(INSTALL_TOTAL), style="blue")
    ops.append(" installs, ")
    ops.append("0", style="blue")
    ops.append(" updates, ")
    ops.append("0", style="blue")
    ops.append(" removals")
    lines += [ops, Text("")]
    lines += [installed(*p) for p in INSTALL_FIRST]
    hidden = INSTALL_TOTAL - len(INSTALL_FIRST) - len(INSTALL_LAST)
    lines += [Text(f"  ⋮ {hidden} more", style="dim")]
    lines += [installed(*p) for p in INSTALL_LAST]
    lines += [Text(""), Text("Writing lock file", style="blue"), Text("")]
    lines += [prompt("poetry run sceptre-interactive --version")]
    lines += [Text("Sceptre, version 4.7.0"), Text("")]
    lines += [prompt("poetry run sceptre-interactive -i launch dev")]
    return Group(*lines)


def resources_view():
    from sceptre_interactive.resources import StackResources, stack_table

    def res(logical_id, physical_id, resource_type, status="CREATE_COMPLETE"):
        return {
            "LogicalResourceId": logical_id,
            "PhysicalResourceId": physical_id,
            "ResourceType": resource_type,
            "ResourceStatus": status,
        }

    stacks = [
        StackResources(
            "network/vpc",
            "demo-network-vpc",
            "eu-west-1",
            [
                res("VPC", "vpc-0a1b2c3d4e5f60718", "AWS::EC2::VPC"),
                res(
                    "InternetGateway",
                    "igw-0f1e2d3c4b5a69788",
                    "AWS::EC2::InternetGateway",
                ),
                res(
                    "GatewayAttachment",
                    "IGW|vpc-0a1b2c3d4e5f60718",
                    "AWS::EC2::VPCGatewayAttachment",
                ),
            ],
        ),
        StackResources(
            "app/service",
            "demo-app-service",
            "eu-west-1",
            [
                res("Cluster", "demo-cluster", "AWS::ECS::Cluster"),
                res("TaskRole", "demo-app-service-TaskRole-1A2B3C", "AWS::IAM::Role"),
                res("Logs", "/ecs/demo-service", "AWS::Logs::LogGroup"),
                res(
                    "Queue",
                    "https://sqs.eu-west-1.amazonaws.com/123456789012/demo-jobs",
                    "AWS::SQS::Queue",
                    "UPDATE_IN_PROGRESS",
                ),
            ],
        ),
    ]
    return Group(*(stack_table(stack) for stack in stacks))


if __name__ == "__main__":
    main()
