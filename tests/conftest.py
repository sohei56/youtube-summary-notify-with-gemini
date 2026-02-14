"""Shared test fixtures for AWS service mocking."""

import json
import os

import boto3
import pytest
import yaml
from moto import mock_aws

VALID_CONFIG = {
    "channels": [
        {"id": "UCxxxxxxxxxxxxxxxxxxxxxx", "name": "Test Channel"},
        {"id": "UCyyyyyyyyyyyyyyyyyyyyyyyy"[:24], "name": "Another Channel"},
    ],
    "summarization": {
        "model": "gemini-2.5-flash",
        "language": "en",
        "prompt_template": ("Watch this video and provide a summary in {language}.\n"),
    },
    "notifications": [
        {
            "name": "team-updates",
            "platform": "slack",
            "secret_key": "slack_webhook_team",
            "message_template": "*{title}*\n{summary}\n{url}",
        },
    ],
}

TEST_BUCKET = "test-config-bucket"
TEST_TABLE = "test-video-state"
TEST_SECRETS_ARN = "test-secrets"
TEST_DEPLOYMENT_ID = "test-deployment"

VALID_SECRETS = {
    "gemini_api_key": "test-gemini-key",
    "youtube_api_key": "test-youtube-key",
    "slack_webhook_team": "https://hooks.slack.com/services/T00/B00/xxx",
}


@pytest.fixture()
def aws_credentials():
    """Set dummy AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    yield
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SECURITY_TOKEN",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
    ):
        os.environ.pop(key, None)


@pytest.fixture()
def s3_bucket(aws_credentials):
    """Create a moto-mocked S3 bucket with a valid config.yaml."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=TEST_BUCKET)
        s3.put_object(
            Bucket=TEST_BUCKET,
            Key="config.yaml",
            Body=yaml.dump(VALID_CONFIG).encode(),
        )
        yield s3


@pytest.fixture()
def dynamodb_table(aws_credentials):
    """Create a moto-mocked DynamoDB table with the correct schema."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName=TEST_TABLE,
            KeySchema=[
                {"AttributeName": "deployment_id", "KeyType": "HASH"},
                {"AttributeName": "video_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "deployment_id", "AttributeType": "S"},
                {"AttributeName": "video_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        yield table


@pytest.fixture()
def secrets_manager(aws_credentials):
    """Create a moto-mocked Secrets Manager secret."""
    with mock_aws():
        client = boto3.client("secretsmanager", region_name="us-east-1")
        client.create_secret(
            Name=TEST_SECRETS_ARN,
            SecretString=json.dumps(VALID_SECRETS),
        )
        yield client


@pytest.fixture()
def all_aws(aws_credentials):
    """Create all mocked AWS services together in a single mock context."""
    with mock_aws():
        # S3
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=TEST_BUCKET)
        s3.put_object(
            Bucket=TEST_BUCKET,
            Key="config.yaml",
            Body=yaml.dump(VALID_CONFIG).encode(),
        )

        # DynamoDB
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName=TEST_TABLE,
            KeySchema=[
                {"AttributeName": "deployment_id", "KeyType": "HASH"},
                {"AttributeName": "video_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "deployment_id", "AttributeType": "S"},
                {"AttributeName": "video_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()

        # Secrets Manager
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        sm.create_secret(
            Name=TEST_SECRETS_ARN,
            SecretString=json.dumps(VALID_SECRETS),
        )

        yield {"s3": s3, "dynamodb_table": table, "secretsmanager": sm}
