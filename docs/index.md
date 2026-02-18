---
layout: default
---

YouTube Summary Notify automatically detects new videos from your favorite YouTube channels, generates concise summaries using Gemini AI, and delivers them straight to your Slack or Discord.

## Features

- **Zero transcript extraction** — Gemini processes video natively
- **Multi-channel monitoring** — watch as many YouTube channels as you want
- **Multi-destination notifications** — send to Slack, Discord, or both
- **Single config file** — change channels, prompts, templates, and model without redeploying
- **Self-hostable** — runs in your own AWS account with your own API keys

## Example Notifications

![notification example](99_images/notification-example.png)

## How It Works

1. **Detect** new videos via YouTube Data API v3
2. **Summarize** each video with Gemini AI
3. **Notify** all configured destinations with formatted summaries

## Architecture

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

## Quick Start

```bash
git clone git@github.com:sohei56/youtube-summary-notify-with-gemini.git
cd youtube-summary-notify-with-gemini

sam build --template-file infra/template.yaml
sam deploy --guided
```

Then store your secrets and upload `config.yaml` — see the [deployment guide](https://github.com/sohei56/youtube-summary-notify-with-gemini/blob/main/docs/02_operation/00_deployment.md) for full instructions.

## Links

- [GitHub Repository](https://github.com/sohei56/youtube-summary-notify-with-gemini)
- [Deployment Guide](https://github.com/sohei56/youtube-summary-notify-with-gemini/blob/main/docs/02_operation/00_deployment.md)
- [Contributing](https://github.com/sohei56/youtube-summary-notify-with-gemini/blob/main/CONTRIBUTING.md)
