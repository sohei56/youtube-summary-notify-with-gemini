# YouTube Summary Notify
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

Automatically detects new videos from specified YouTube channels, generates summaries using Gemini AI, and sends notifications to configured destinations (Slack, Discord).

## How It Works

1. **Detect** new videos from monitored YouTube channels (YouTube Data API v3)
2. **Summarize** each video using Gemini AI (processes video natively — no transcript extraction needed)
3. **Notify** all configured destinations with formatted summaries (Slack, Discord)

The system runs as a scheduled AWS Lambda function. All user-editable settings (channels, prompts, templates, model) live in a single S3 config file — no redeployment needed for configuration changes.

### Example Notifications
![notification example](docs/99_images/notification-example.png)

### Architecture

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

For detailed architecture and design decisions, see [docs/01_design/](docs/01_design/).

## Cost Estimate
(This information is current as of 2026-02-21.)

This system is designed to run at minimal cost. The table below assumes **5 channels, hourly checks (default), ~30 new videos/month**.

| Service | Monthly Cost | Notes |
|---|---|---|
| **AWS Lambda** | ~$0 | 720 invocations × ~30s × 256 MB ≈ 5,400 GB-s/month. Well within the [free tier](https://aws.amazon.com/lambda/pricing/) (400,000 GB-s). |
| **EventBridge** | $0 | 720 events/month. Free tier covers 14M events. |
| **S3** | ~$0 | Single config file (~1 KB). Negligible. |
| **DynamoDB** | ~$0 | On-demand mode with ~30–60 writes/month. Well within always-free 25 WCU/RCU. |
| **Secrets Manager** | **~$0.40** | $0.40/secret/month. **Not included in the AWS Free Tier.** |
| **YouTube Data API** | $0 | `playlistItems.list` = 1 unit/request. 120 units/day for 5 channels — free quota is 10,000 units/day. |
| **Gemini API** | $0 – ~$1.50 | Gemini 2.5 Flash free tier is generous for light usage. On paid tier, ~$0.02–0.05/video depending on length. |

**Estimated total: ~$0.50–$2/month**

## Quick Start

### Prerequisites

- AWS CLI and SAM CLI installed
- Docker installed
- API keys for Gemini, YouTube Data API v3, and a webhook URL for your notification platform (e.g., Slack)

For step-by-step API key acquisition and full deployment instructions, see [docs/02_operation/00_deployment.md](docs/02_operation/00_deployment.md).

### Deploy

```bash
git clone git@github.com:sohei56/youtube-summary-notify-with-gemini.git
cd youtube-summary-notify-with-gemini

sam build --template-file infra/template.yaml
sam deploy --guided
```

Then store your secrets and upload `config.yaml` as described in the [deployment guide](docs/02_operation/00_deployment.md#step-3-store-secrets).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and contribution guidelines.

## Documentation

| Document | Contents |
|---|---|
| [Requirements](docs/00_requirement/00_requirement.md) | Functional & non-functional requirements |
| [Architecture Design](docs/01_design/00_architecture-design.md) | AWS resources, system overview |
| [Application Design](docs/01_design/01_application-design.md) | Modules, interfaces, processing flow |
| [Data Design](docs/01_design/02_data-design.md) | config.yaml schema, DynamoDB schema, Secrets Manager format |
| [Coding Standards](docs/01_design/03_coding-standards.md) | Language conventions, dependencies, formatting, testing |
| [Deployment](docs/02_operation/00_deployment.md) | Deployment, configuration, troubleshooting, cleanup |
| [YouTube Data API](docs/03_external_apis/00_youtube-data-api.md) | YouTube Data API v3 reference |
| [Gemini API](docs/03_external_apis/01_gemini-api.md) | Gemini API reference |
| [Notification Webhook API](docs/03_external_apis/02_notification-webhook-api.md) | Slack and Discord webhook specs |

## License

[MIT](LICENSE)
