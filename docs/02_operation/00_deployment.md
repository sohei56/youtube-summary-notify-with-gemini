# Deployment

## Prerequisites

- AWS account with permissions to create Lambda, EventBridge, S3, DynamoDB, Secrets Manager, and IAM resources
- AWS CLI installed and configured ([Installation guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html))
- AWS SAM CLI installed ([Installation guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html))
- Docker installed (required for building the Lambda container image)

## Step 1: Obtain API Keys

### Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Sign in with your Google account
3. Click "Create API key"
4. Copy the key — you will need it in Step 3

### YouTube Data API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Enable "YouTube Data API v3" in [API Library](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
4. Go to [Credentials](https://console.cloud.google.com/apis/credentials) → "Create Credentials" → "API key"
5. Copy the key — you will need it in Step 3

### Slack Incoming Webhook URL

1. Go to [Slack API: Apps](https://api.slack.com/apps)
2. Click "Create New App" → "From scratch"
3. Name the app (e.g., "YouTube Summary Notify") and select your workspace
4. Go to "Incoming Webhooks" → Toggle "Activate Incoming Webhooks" on
5. Click "Add New Webhook to Workspace" → Select the target channel → "Allow"
6. Copy the Webhook URL — you will need it in Step 3
7. Repeat for each notification target if configuring multiple

## Step 2: Deploy Infrastructure

```bash
git clone git@github.com:sohei56/youtube-summary-notify-with-gemini.git
cd youtube-summary-notify-with-gemini

sam build
sam deploy --guided
```

`sam deploy --guided` will prompt for:

| Parameter | Description | Example |
|---|---|---|
| Stack name | CloudFormation stack name | `yt-summary-notify` |
| AWS Region | Deployment region | `ap-northeast-1` |
| ExecutionInterval | Cron interval in minutes | `60` |

SAM provisions: Lambda function, EventBridge rule, S3 bucket, DynamoDB table, and Secrets Manager secret.

All resource names are prefixed with the stack name to avoid conflicts (e.g., stack name `yt-summary-notify` → secret `yt-summary-notify-secrets`).

## Step 3: Store Secrets

All secrets are stored in a **single** Secrets Manager entry as a JSON object. The secret name is `<stack-name>-secrets` (created by SAM).

```bash
aws secretsmanager put-secret-value \
  --secret-id "<stack-name>-secrets" \
  --secret-string '{
    "gemini_api_key": "your-gemini-api-key",
    "youtube_api_key": "your-youtube-api-key",
    "slack_webhook_team_updates": "https://hooks.slack.com/services/T.../B.../..."
  }'
```

JSON key naming:

| Key | Description |
|---|---|
| `gemini_api_key` | Gemini API key |
| `youtube_api_key` | YouTube Data API key |
| (per target) | Webhook URL for each notification target. Key must match `secret_key` in `config.yaml` |

### Updating Secrets

To update a single value without overwriting others, retrieve the current JSON, modify it, and put it back:

```bash
# Get current secrets
aws secretsmanager get-secret-value \
  --secret-id "<stack-name>-secrets" \
  --query SecretString --output text | jq '.'

# Update (replace the full JSON)
aws secretsmanager put-secret-value \
  --secret-id "<stack-name>-secrets" \
  --secret-string '{ ... updated JSON ... }'
```

## Step 4: Upload config.yaml

Create `config.yaml` from the included template and upload it to the S3 bucket created by SAM. See `docs/01_design/02_data-design.md` for the full schema reference.

```bash
cp config.yaml.template config.yaml
# Edit config.yaml with your channel IDs, model preferences, and notification settings
```

`secret_key` references a key within the `<stack-name>-secrets` JSON in Secrets Manager.

```bash
aws s3 cp config.yaml s3://<bucket-name>/config.yaml
```

The S3 bucket name is output by `sam deploy`. You can also find it in the CloudFormation stack outputs.

### Finding YouTube Channel IDs

A channel ID starts with `UC` followed by 22 characters (e.g., `UCxxxxxxxxxxxxxxxxxxxxxx`).

To find a channel ID:
1. Go to the YouTube channel page
2. View page source or use the channel URL — if the URL is `youtube.com/channel/UC...`, the ID is in the URL
3. For `youtube.com/@handle` URLs, view page source and search for `channelId`

## Step 5: Verify

The Lambda function name follows the pattern `<stack-name>-function` (e.g., `yt-summary-notify-function`).

1. **Check Lambda is scheduled**: In the AWS Console, go to Lambda → find the function → check that the EventBridge trigger is attached.
2. **Trigger a test execution**: Invoke the Lambda manually:
   ```bash
   aws lambda invoke \
     --function-name <stack-name>-function \
     --payload '{}' \
     response.json
   ```
3. **Check logs**: Go to CloudWatch Logs → find the log group `/aws/lambda/<stack-name>-function` → verify execution logs.
4. **Check Slack**: Confirm that summary notifications appear in the configured channel (if monitored channels have recent videos).

## Updating Configuration

After initial deployment, configuration changes do **not** require redeployment:

| Change | Action |
|---|---|
| Add/remove YouTube channels | Edit `config.yaml` → `aws s3 cp` |
| Change prompt or message template | Edit `config.yaml` → `aws s3 cp` |
| Change Gemini model | Edit `config.yaml` → `aws s3 cp` |
| Add notification target | Edit `config.yaml` + add key to secrets JSON |
| Rotate API key | Update secrets JSON in Secrets Manager |
| Change execution interval | `sam deploy` with new parameter |

## Cleanup

To remove all AWS resources created by this project:

```bash
# 1. Empty the S3 bucket (required before stack deletion)
aws s3 rm s3://<bucket-name> --recursive

# 2. Delete the CloudFormation stack (removes Lambda, EventBridge, S3, DynamoDB, Secrets Manager)
sam delete --stack-name <stack-name>

# 3. (Optional) Delete CloudWatch log group if not removed by stack
aws logs delete-log-group \
  --log-group-name /aws/lambda/<stack-name>-function
```

`sam delete` will prompt for confirmation. All resources provisioned by the SAM template are deleted, including the DynamoDB table and its data.

## Troubleshooting

| Symptom | Likely Cause | Resolution |
|---|---|---|
| No notifications at all | Initialization failure (bad API key, missing config) | Check CloudWatch logs for ERROR at start of execution |
| Duplicate notifications | DynamoDB write failure on previous run | Check logs for state write errors. Will self-resolve on next successful run |
| Missing videos | Video published outside the 2× interval window | Reduce execution interval or check channel publish patterns |
| Gemini timeout errors | Long videos or API congestion | Check video length. Consider increasing per-request timeout |
| Gemini 429 errors | Rate limit exceeded | Reduce number of channels or switch to paid tier |
| Slack notifications not appearing | Invalid Webhook URL | Verify Webhook URL in Secrets Manager. Test with `curl` |
| Lambda timeout (15 min) | Too many videos or long Gemini response times | Reduce channels, reduce execution interval (fewer videos per run) |
