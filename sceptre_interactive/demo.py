"""
Local demo of interactive mode, no AWS needed.

Runs Sceptre's real SceptrePlanExecutor over a fake 3-batch plan. Only the
stack actions are simulated: they log CloudFormation events through Sceptre's
logger in the same format as sceptre.plan.actions, so the live display goes
through exactly the same path as a real deployment.

    sceptre-interactive-demo             # live display
    sceptre-interactive-demo --classic   # Sceptre's normal log output
    sceptre-interactive-demo --fail      # one stack fails and rolls back
"""

import logging
import random
import time
from dataclasses import dataclass
from unittest.mock import patch

import click
from rich.console import Console
from sceptre.cli.helpers import setup_logging
from sceptre.plan.executor import SceptrePlanExecutor
from sceptre.stack_status import StackStatus

from sceptre_interactive.session import InteractiveSession

PROJECT = "demo"

PLAN = [
    {"network/vpc": ["VPC", "InternetGateway", "GatewayAttachment", "RouteTable"]},
    {
        "network/subnets": [
            "SubnetA",
            "SubnetB",
            "SubnetC",
            "RouteAssocA",
            "RouteAssocB",
        ],
        "security/kms": ["Key", "KeyAlias"],
    },
    {
        "app/database": ["DBSubnetGroup", "DBSecurityGroup", "DBCluster", "DBInstance"],
        "app/service": [
            "Cluster",
            "TaskRole",
            "TaskDefinition",
            "Service",
            "LoadBalancer",
        ],
        "app/queue": ["Queue", "DeadLetterQueue", "QueuePolicy"],
    },
]

RESOURCE_TYPES = {
    "VPC": "AWS::EC2::VPC",
    "InternetGateway": "AWS::EC2::InternetGateway",
    "GatewayAttachment": "AWS::EC2::VPCGatewayAttachment",
    "RouteTable": "AWS::EC2::RouteTable",
    "SubnetA": "AWS::EC2::Subnet",
    "SubnetB": "AWS::EC2::Subnet",
    "SubnetC": "AWS::EC2::Subnet",
    "RouteAssocA": "AWS::EC2::SubnetRouteTableAssociation",
    "RouteAssocB": "AWS::EC2::SubnetRouteTableAssociation",
    "Key": "AWS::KMS::Key",
    "KeyAlias": "AWS::KMS::Alias",
    "DBSubnetGroup": "AWS::RDS::DBSubnetGroup",
    "DBSecurityGroup": "AWS::EC2::SecurityGroup",
    "DBCluster": "AWS::RDS::DBCluster",
    "DBInstance": "AWS::RDS::DBInstance",
    "Cluster": "AWS::ECS::Cluster",
    "TaskRole": "AWS::IAM::Role",
    "TaskDefinition": "AWS::ECS::TaskDefinition",
    "Service": "AWS::ECS::Service",
    "LoadBalancer": "AWS::ElasticLoadBalancingV2::LoadBalancer",
    "Queue": "AWS::SQS::Queue",
    "DeadLetterQueue": "AWS::SQS::Queue",
    "QueuePolicy": "AWS::SQS::QueuePolicy",
}


@dataclass(frozen=True)
class FakeStack:
    name: str

    @property
    def external_name(self):
        return f"{PROJECT}-{self.name.replace('/', '-')}"

    def __str__(self):
        return self.name


class FakeStackActions:
    """Stands in for sceptre.plan.actions.StackActions."""

    speed = 1.0
    failing_stack = None
    logger = logging.getLogger("sceptre.plan.actions")

    def __init__(self, stack: FakeStack):
        self.stack = stack

    def _sleep(self, low, high):
        time.sleep(random.uniform(low, high) / self.speed)

    def _event(self, logical_id, resource_type, status, reason=""):
        # Same format as StackActions._log_new_events
        parts = [self.stack.name, logical_id, resource_type, status, reason]
        self.logger.info(" ".join(parts))

    def launch(self):
        stack, external = self.stack, self.stack.external_name
        self.logger.info("%s - Launching Stack", stack.name)
        self.logger.info("%s - Creating Stack", stack.name)
        self._sleep(0.5, 1.0)
        self._event(
            external,
            "AWS::CloudFormation::Stack",
            "CREATE_IN_PROGRESS",
            "User Initiated",
        )

        resources = PLAN_RESOURCES[stack.name]
        fail_at = len(resources) - 1 if stack.name == self.failing_stack else None
        for index, logical_id in enumerate(resources):
            resource_type = RESOURCE_TYPES[logical_id]
            self._sleep(0.3, 1.2)
            self._event(logical_id, resource_type, "CREATE_IN_PROGRESS")
            self._sleep(0.2, 0.6)
            self._event(
                logical_id,
                resource_type,
                "CREATE_IN_PROGRESS",
                "Resource creation Initiated",
            )
            self._sleep(0.8, 3.0)
            if index == fail_at:
                self._event(
                    logical_id,
                    resource_type,
                    "CREATE_FAILED",
                    'Resource handler returned message: "Invalid request provided"',
                )
                return self._rollback(logical_id, resources[:index])
            self._event(logical_id, resource_type, "CREATE_COMPLETE")

        self._sleep(0.3, 0.8)
        self._event(external, "AWS::CloudFormation::Stack", "CREATE_COMPLETE")
        return StackStatus.COMPLETE

    def _rollback(self, failed, created):
        external = self.stack.external_name
        self._event(
            external,
            "AWS::CloudFormation::Stack",
            "ROLLBACK_IN_PROGRESS",
            f"The following resource(s) failed to create: [{failed}].",
        )
        for logical_id in reversed(created):
            resource_type = RESOURCE_TYPES[logical_id]
            self._event(logical_id, resource_type, "DELETE_IN_PROGRESS")
            self._sleep(0.5, 1.5)
            self._event(logical_id, resource_type, "DELETE_COMPLETE")
        self._event(external, "AWS::CloudFormation::Stack", "ROLLBACK_COMPLETE")
        return StackStatus.FAILED


PLAN_RESOURCES = {name: res for batch in PLAN for name, res in batch.items()}


@click.command()
@click.option("--classic", is_flag=True, help="Show Sceptre's normal log output.")
@click.option("--fail", "fail", is_flag=True, help="Make app/service fail.")
@click.option("--speed", default=1.0, show_default=True, help="Speed multiplier.")
def main(classic, fail, speed):
    """Simulate `sceptre launch` over a 6-stack plan without touching AWS."""
    setup_logging(debug=False, no_colour=False)
    FakeStackActions.speed = speed
    FakeStackActions.failing_stack = "app/service" if fail else None

    launch_order = [{FakeStack(name) for name in batch} for batch in PLAN]
    session = InteractiveSession(console=Console())
    if not classic:
        session.install()
    try:
        with patch("sceptre.plan.executor.StackActions", FakeStackActions):
            responses = SceptrePlanExecutor("launch", launch_order, None).execute()
    finally:
        session.uninstall()
    raise SystemExit(
        0 if all(s == StackStatus.COMPLETE for s in responses.values()) else 1
    )


if __name__ == "__main__":  # pragma: no cover
    main()
