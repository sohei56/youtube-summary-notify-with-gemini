# Data Design

## Overview

This system uses three storage backends. This document defines the schema and structure of each.

| Storage | Purpose |
|---|---|
| S3 (`config.yaml`) | User-editable configuration (channels, prompts, templates, model) |
| DynamoDB (`video_state`) | Notified video state for duplicate prevention |
| Secrets Manager (`<stack-name>-secrets`) | API keys and Webhook URLs |

## config.yaml (S3)

Single YAML file containing all user-editable settings. Stored in the S3 bucket provisioned by SAM. Changes take effect on the next Lambda execution — no redeployment required.

### Full Schema

```yaml
channels:
  - id: "UC..."                    # YouTube channel ID
    name: "Channel Name"           # Display name (used in notifications)
  - id: "UC..."
    name: "Another Channel"

summarization:
  model: "gemini-2.5-flash"        # Gemini model name (configurable)
  language: "en"                   # Summary language
  prompt_template: |               # Prompt sent to Gemini. {language} is substituted.
    Watch this video and provide a summary in {language}.
    Summarize the main topics, conclusions, and key points in 3-5 sentences.

notifications:                     # One or more notification targets
  - name: "team-updates"           # Unique identifier (used in logs)
    platform: "slack"              # Platform type: "slack" (v1), "discord" (future)
    secret_key: "slack_webhook_team_updates"  # Key in Secrets Manager JSON
    message_template: |            # Platform-specific message template
      *{title}*
      Channel: {channel}
      Published: {published_at}
      {url}

      {summary}
```

### channels[]

| Field | Required | Description |
|---|---|---|
| `id` | Yes | YouTube channel ID (starts with `UC`, 24 characters) |
| `name` | Yes | Display name used in notification messages |

### summarization

| Field | Required | Default | Description |
|---|---|---|---|
| `model` | Yes | `gemini-2.5-flash` | Gemini model name |
| `language` | Yes | `en` | Language for generated summaries |
| `prompt_template` | Yes | (see above) | Prompt template. `{language}` is substituted at runtime. Video is passed as a media part separately |

### notifications[]

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Unique identifier for this target (used in logs and error messages) |
| `platform` | Yes | `slack` (v1), `discord` (future) |
| `secret_key` | Yes | Key within the `<stack-name>-secrets` JSON in Secrets Manager |
| `message_template` | Yes | Platform-specific message template |

#### Template Variables

Available in `message_template`:

| Variable | Description | Example |
|---|---|---|
| `{channel}` | YouTube channel name | `Google Developers` |
| `{title}` | Video title | `What's new in Gemini API` |
| `{url}` | Video URL | `https://www.youtube.com/watch?v=...` |
| `{published_at}` | Publish date | `2026-02-12T10:00:00Z` |
| `{summary}` | Generated summary text | (3-5 sentences) |

## video_state (DynamoDB)

Tracks which videos have been notified to prevent duplicates. Retains the last 500 entries per deployment.

### Table Schema

| Attribute | Type | Description |
|---|---|---|
| `deployment_id` | String (PK) | Fixed identifier per deployment (from SAM parameter or derived) |
| `video_id` | String (SK) | YouTube video ID |
| `notified_at` | Number | Unix timestamp of notification |

- Partition key `deployment_id` groups all state for one deployment.
- Sort key `video_id` enables efficient lookups and batch writes.
- `notified_at` is used to determine oldest entries for cleanup (delete oldest when count exceeds 500).

## Secrets Manager (`<stack-name>-secrets`)

Single JSON object containing all secrets. The secret name is `<stack-name>-secrets`, created by SAM.

### Schema

```json
{
  "gemini_api_key": "...",
  "youtube_api_key": "...",
  "slack_webhook_team_updates": "https://hooks.slack.com/services/..."
}
```

| Key | Required | Description |
|---|---|---|
| `gemini_api_key` | Yes | Gemini API key |
| `youtube_api_key` | Yes | YouTube Data API key |
| `<secret_key>` | Per target | Webhook URL for each notification target. Key must match `secret_key` in `config.yaml` |
