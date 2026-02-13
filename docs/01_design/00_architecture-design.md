# Architecture Design

## System Overview

```
┌──────────────────────────────────────────────┐
│ AWS Account (user-owned)                      │
│                                               │
│  EventBridge            Lambda                │
│  (cron rule) ────────▶ (Docker)               │
│                         │    │                │
│           ┌─────────────┘    │                │
│           ▼                  │                │
│     S3 (config)              │                │
│     DynamoDB (state)         │                │
│     Secrets Manager          │                │
│                              │                │
└──────────────────────────────│────────────────┘
                               │
                 ┌─────────────┼──────────────┐
                 ▼             ▼              ▼
            YouTube       Gemini API    Notification
            Data API                    Webhooks
```

The system runs as a single Lambda function triggered on a schedule. It reads configuration from S3, detects new videos via YouTube Data API, summarizes them via Gemini API, and sends notifications via configured webhooks (currently Slack; pluggable for future platforms).

## AWS Resource Summary

| Resource | Naming | Purpose |
|---|---|---|
| Lambda (Docker) | `<stack-name>-function` | Runs the summarization pipeline on schedule |
| EventBridge | `<stack-name>-schedule` | Triggers Lambda on a cron schedule (default: every 60 min) |
| S3 Bucket | `<stack-name>-config-*` | Stores `config.yaml` |
| DynamoDB Table | `<stack-name>-video-state` | Stores notified video state |
| Secrets Manager | `<stack-name>-secrets` | Stores all API keys and Webhook URLs (single JSON) |

All resources are provisioned by the SAM template (`infra/template.yaml`). All resource names are prefixed with the stack name to avoid conflicts.

## External APIs

| API | Direction | Purpose |
|---|---|---|
| YouTube Data API v3 | Read | Fetch recent videos from monitored channels |
| Gemini API | Read | Generate video summaries from YouTube URLs |
| Notification Webhooks (e.g., Slack) | Write | Send summary and error notifications |

## Data Schemas

See `docs/01_design/02_data-design.md` for full schemas of config.yaml, DynamoDB, and Secrets Manager.
