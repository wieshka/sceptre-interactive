import pytest

from sceptre_interactive.console_links import (
    RESOURCE_URLS,
    console_base,
    console_url,
    stack_url,
)

REGION = "eu-west-1"
BASE = "https://eu-west-1.console.aws.amazon.com"


@pytest.mark.parametrize(
    "region,expected",
    [
        ("eu-west-1", "https://eu-west-1.console.aws.amazon.com"),
        ("cn-north-1", "https://cn-north-1.console.amazonaws.cn"),
        ("us-gov-west-1", "https://us-gov-west-1.console.amazonaws-us-gov.com"),
    ],
)
def test_console_base_per_partition(region, expected):
    assert console_base(region) == expected


@pytest.mark.parametrize(
    "resource_type,physical_id,expected",
    [
        (
            "AWS::EC2::VPC",
            "vpc-0abc",
            f"{BASE}/vpcconsole/home?region={REGION}#VpcDetails:VpcId=vpc-0abc",
        ),
        (
            "AWS::EC2::SecurityGroup",
            "sg-123",
            f"{BASE}/ec2/home?region={REGION}#SecurityGroup:groupId=sg-123",
        ),
        (
            "AWS::Lambda::Function",
            "my-fn",
            f"{BASE}/lambda/home?region={REGION}#/functions/my-fn",
        ),
        (
            "AWS::S3::Bucket",
            "my-bucket",
            f"https://s3.console.aws.amazon.com/s3/buckets/my-bucket?region={REGION}",
        ),
        (
            "AWS::IAM::Role",
            "my-role",
            "https://console.aws.amazon.com/iam/home#/roles/details/my-role",
        ),
        (
            "AWS::SQS::Queue",
            "https://sqs.eu-west-1.amazonaws.com/123456789012/q",
            f"{BASE}/sqs/v3/home?region={REGION}#/queues/"
            "https%3A%2F%2Fsqs.eu-west-1.amazonaws.com%2F123456789012%2Fq",
        ),
        (
            "AWS::ECS::Service",
            "arn:aws:ecs:eu-west-1:123456789012:service/my-cluster/my-svc",
            f"{BASE}/ecs/v2/clusters/my-cluster/services/my-svc?region={REGION}",
        ),
        (
            "AWS::ECS::TaskDefinition",
            "arn:aws:ecs:eu-west-1:123456789012:task-definition/web:7",
            f"{BASE}/ecs/v2/task-definitions/web/7?region={REGION}",
        ),
        (
            "AWS::Logs::LogGroup",
            "/aws/lambda/fn",
            f"{BASE}/cloudwatch/home?region={REGION}"
            "#logsV2:log-groups/log-group/$252Faws$252Flambda$252Ffn",
        ),
        (
            "AWS::RDS::DBCluster",
            "db-1",
            f"{BASE}/rds/home?region={REGION}#database:id=db-1;is-cluster=true",
        ),
    ],
)
def test_console_url(resource_type, physical_id, expected):
    assert console_url(resource_type, physical_id, REGION) == expected


@pytest.mark.parametrize(
    "resource_type,physical_id,region",
    [
        ("AWS::Some::Unknown", "x", REGION),
        ("AWS::EC2::VPC", "", REGION),
        ("AWS::EC2::VPC", "vpc-1", ""),
        ("AWS::ECS::Service", "not-an-arn", REGION),
        ("AWS::Some::Unknown", "arn:aws-cn:x:cn-north-1:1:thing/a", "cn-north-1"),
        ("AWS::Some::Unknown", "arn:aws-us-gov:x:us-gov-west-1:1:a", "us-gov-west-1"),
    ],
)
def test_no_url(resource_type, physical_id, region):
    assert console_url(resource_type, physical_id, region) is None


def test_every_mapping_builds_a_url():
    for resource_type in RESOURCE_URLS:
        url = console_url(resource_type, "arn:aws:x:eu-west-1:1:a/b/c:1", REGION)
        assert url is None or url.startswith("https://")


def test_stack_url():
    assert stack_url("demo-net-vpc", REGION) == (
        f"{BASE}/cloudformation/home?region={REGION}"
        "#/stacks/resources?stackId=demo-net-vpc"
    )


class TestArnFallback:
    GO = "https://console.aws.amazon.com/go/view?arn="

    def test_unknown_type_with_arn(self):
        arn = "arn:aws:glue:eu-west-1:123456789012:job/nightly"
        assert console_url("AWS::Glue::Job", arn, REGION) == (
            self.GO + "arn%3Aaws%3Aglue%3Aeu-west-1%3A123456789012%3Ajob%2Fnightly"
        )

    def test_used_when_curated_builder_cannot_parse(self):
        arn = "arn:aws:ecs:eu-west-1:123456789012:task-definition/web"
        assert console_url("AWS::ECS::TaskDefinition", arn, REGION).startswith(self.GO)

    def test_used_without_region(self):
        arn = "arn:aws:sns:eu-west-1:123456789012:topic"
        assert console_url("AWS::SNS::Topic", arn, "").startswith(self.GO)

    def test_curated_link_wins(self):
        arn = "arn:aws:sns:eu-west-1:123456789012:topic"
        assert console_url("AWS::SNS::Topic", arn, REGION) == (
            f"{BASE}/sns/v3/home?region={REGION}#/topic/{arn}"
        )
