"""
AWS console URLs for CloudFormation resources, like the links on the
Resources tab of the CloudFormation console.

``console_url(resource_type, physical_id, region)`` returns a URL, or None
for resource types without a known console page. Add types to ``RESOURCE_URLS``.
"""

from typing import Callable, Dict, Optional
from urllib.parse import quote


def console_base(region: str) -> str:
    """Console origin for a region's partition (commercial, China, GovCloud)."""
    if region.startswith("cn-"):
        return f"https://{region}.console.amazonaws.cn"
    if region.startswith("us-gov-"):
        return f"https://{region}.console.amazonaws-us-gov.com"
    return f"https://{region}.console.aws.amazon.com"


def global_base(region: str) -> str:
    """Origin for global services (IAM, Route 53), per partition."""
    if region.startswith("cn-"):
        return "https://console.amazonaws.cn"
    if region.startswith("us-gov-"):
        return "https://console.amazonaws-us-gov.com"
    return "https://console.aws.amazon.com"


def _enc(value: str) -> str:
    return quote(value, safe="")


def _arn_resource(arn: str) -> str:
    """The resource part of an ARN (after the 5th colon)."""
    parts = arn.split(":", 5)
    return parts[5] if len(parts) == 6 else arn


def _service(path: str) -> Callable[[str, str], str]:
    """URL under the regional console; ``{id}`` is the physical ID, raw."""

    def build(physical_id: str, region: str) -> str:
        return f"{console_base(region)}/{path.format(id=physical_id, region=region)}"

    return build


def _service_enc(path: str) -> Callable[[str, str], str]:
    """Like _service, with the physical ID URL-encoded."""

    def build(physical_id: str, region: str) -> str:
        return (
            f"{console_base(region)}/"
            f"{path.format(id=_enc(physical_id), region=region)}"
        )

    return build


def _iam(kind: str) -> Callable[[str, str], str]:
    def build(physical_id: str, region: str) -> str:
        return f"{global_base(region)}/iam/home#/{kind}/details/{_enc(physical_id)}"

    return build


def _s3_bucket(physical_id: str, region: str) -> str:
    host = "s3.console.aws.amazon.com"
    if region.startswith("cn-"):
        host = "console.amazonaws.cn/s3"
    elif region.startswith("us-gov-"):
        host = "console.amazonaws-us-gov.com/s3"
    return f"https://{host}/s3/buckets/{physical_id}?region={region}"


def _ecs_service(physical_id: str, region: str) -> Optional[str]:
    # arn:aws:ecs:<region>:<account>:service/<cluster>/<service>
    parts = _arn_resource(physical_id).split("/")
    if len(parts) != 3:
        return None
    _, cluster, service = parts
    return (
        f"{console_base(region)}/ecs/v2/clusters/{cluster}/services/{service}"
        f"?region={region}"
    )


def _ecs_task_definition(physical_id: str, region: str) -> Optional[str]:
    # arn:aws:ecs:<region>:<account>:task-definition/<family>:<revision>
    family_revision = _arn_resource(physical_id).split("/", 1)[-1]
    if ":" not in family_revision:
        return None
    family, revision = family_revision.rsplit(":", 1)
    return (
        f"{console_base(region)}/ecs/v2/task-definitions/{family}/{revision}"
        f"?region={region}"
    )


def _log_group(physical_id: str, region: str) -> str:
    # The CloudWatch console double-encodes, with '$' in place of '%'
    name = quote(quote(physical_id, safe=""), safe="").replace("%", "$")
    return (
        f"{console_base(region)}/cloudwatch/home?region={region}"
        f"#logsV2:log-groups/log-group/{name}"
    )


def _hosted_zone(physical_id: str, region: str) -> str:
    return f"{global_base(region)}/route53/v2/hostedzones#ListRecordSets/{physical_id}"


R = "region={region}"

RESOURCE_URLS: Dict[str, Callable[[str, str], Optional[str]]] = {
    # VPC
    "AWS::EC2::VPC": _service(f"vpcconsole/home?{R}#VpcDetails:VpcId={{id}}"),
    "AWS::EC2::Subnet": _service(f"vpcconsole/home?{R}#SubnetDetails:subnetId={{id}}"),
    "AWS::EC2::RouteTable": _service(
        f"vpcconsole/home?{R}#RouteTableDetails:RouteTableId={{id}}"
    ),
    "AWS::EC2::InternetGateway": _service(
        f"vpcconsole/home?{R}#InternetGateway:internetGatewayId={{id}}"
    ),
    "AWS::EC2::NatGateway": _service(
        f"vpcconsole/home?{R}#NatGatewayDetails:natGatewayId={{id}}"
    ),
    "AWS::EC2::VPCEndpoint": _service(
        f"vpcconsole/home?{R}#EndpointDetails:vpcEndpointId={{id}}"
    ),
    "AWS::EC2::NetworkAcl": _service(
        f"vpcconsole/home?{R}#NetworkAclDetails:networkAclId={{id}}"
    ),
    # EC2
    "AWS::EC2::SecurityGroup": _service(f"ec2/home?{R}#SecurityGroup:groupId={{id}}"),
    "AWS::EC2::Instance": _service(f"ec2/home?{R}#InstanceDetails:instanceId={{id}}"),
    "AWS::EC2::LaunchTemplate": _service(
        f"ec2/home?{R}#LaunchTemplateDetails:launchTemplateId={{id}}"
    ),
    "AWS::EC2::Volume": _service(f"ec2/home?{R}#VolumeDetails:volumeId={{id}}"),
    "AWS::AutoScaling::AutoScalingGroup": _service_enc(
        f"ec2/home?{R}#AutoScalingGroupDetails:id={{id}}"
    ),
    "AWS::ElasticLoadBalancingV2::LoadBalancer": _service(
        f"ec2/home?{R}#LoadBalancer:loadBalancerArn={{id}}"
    ),
    "AWS::ElasticLoadBalancingV2::TargetGroup": _service(
        f"ec2/home?{R}#TargetGroup:targetGroupArn={{id}}"
    ),
    # Compute / containers
    "AWS::Lambda::Function": _service(f"lambda/home?{R}#/functions/{{id}}"),
    "AWS::ECS::Cluster": _service(f"ecs/v2/clusters/{{id}}/services?{R}"),
    "AWS::ECS::Service": _ecs_service,
    "AWS::ECS::TaskDefinition": _ecs_task_definition,
    # Storage / data
    "AWS::S3::Bucket": _s3_bucket,
    "AWS::DynamoDB::Table": _service_enc(f"dynamodbv2/home?{R}#table?name={{id}}"),
    "AWS::RDS::DBInstance": _service(
        f"rds/home?{R}#database:id={{id}};is-cluster=false"
    ),
    "AWS::RDS::DBCluster": _service(f"rds/home?{R}#database:id={{id}};is-cluster=true"),
    # Messaging
    "AWS::SQS::Queue": _service_enc(f"sqs/v3/home?{R}#/queues/{{id}}"),
    "AWS::SNS::Topic": _service(f"sns/v3/home?{R}#/topic/{{id}}"),
    "AWS::StepFunctions::StateMachine": _service(
        f"states/home?{R}#/statemachines/view/{{id}}"
    ),
    # Security
    "AWS::KMS::Key": _service(f"kms/home?{R}#/kms/keys/{{id}}"),
    "AWS::IAM::Role": _iam("roles"),
    "AWS::IAM::User": _iam("users"),
    "AWS::IAM::ManagedPolicy": _iam("policies"),
    "AWS::SecretsManager::Secret": _service_enc(
        f"secretsmanager/secret?name={{id}}&{R}"
    ),
    "AWS::SSM::Parameter": _service_enc(
        f"systems-manager/parameters/{{id}}/description?{R}"
    ),
    # Observability / networking
    "AWS::Logs::LogGroup": _log_group,
    "AWS::CloudWatch::Alarm": _service_enc(
        f"cloudwatch/home?{R}#alarmsV2:alarm/{{id}}"
    ),
    "AWS::Route53::HostedZone": _hosted_zone,
    "AWS::ApiGateway::RestApi": _service(f"apigateway/home?{R}#/apis/{{id}}/resources"),
    "AWS::CloudFormation::Stack": _service_enc(
        f"cloudformation/home?{R}#/stacks/stackinfo?stackId={{id}}"
    ),
}


def console_url(resource_type: str, physical_id: str, region: str) -> Optional[str]:
    """Console URL for a resource, or None if there's no known page for it."""
    if not physical_id or not region:
        return None
    build = RESOURCE_URLS.get(resource_type)
    if build is None:
        return None
    try:
        return build(physical_id, region)
    except Exception:  # pragma: no cover - never break listing over a link
        return None


def stack_url(stack_name: str, region: str) -> str:
    """CloudFormation console page for a stack's resources."""
    return (
        f"{console_base(region)}/cloudformation/home?region={region}"
        f"#/stacks/resources?stackId={_enc(stack_name)}"
    )
