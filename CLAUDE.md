# CLAUDE.md - YouTube Summary Notify

## Project Overview

YouTube Summary Notify is a system that automatically detects new videos from specified YouTube channels, generates summaries using Gemini AI, and sends notifications to configured destinations.

- Repository: `youtube-summary-notify-with-gemini`
- Package: `youtube_summary_notify`

### Design Philosophy

This project is designed as a self-hostable OSS tool. Users deploy it to their own AWS account with their own API keys. The design prioritizes:

- **Easy deployment**: single `sam deploy --guided` to provision all infrastructure
- **Easy configuration**: all user-editable settings (channels, prompts, templates, model) in a single S3 YAML file — no redeployment needed for configuration changes
- **Clear documentation**: step-by-step setup guide with API key acquisition instructions

## Tech Stack

- **Language**: Python 3.12+
- **Video Summarization**: Gemini API
- **New Video Detection**: YouTube Data API v3
- **Notification**: Slack Incoming Webhooks, Discord Webhooks
- **Execution**: AWS Lambda + EventBridge
- **Infrastructure as Code**: AWS SAM
- **Storage**: Amazon S3 (config) + Amazon DynamoDB (state)
- **Secrets**: AWS Secrets Manager

For detailed language conventions, dependencies, and tooling, see `docs/01_design/03_coding-standards.md`.

## Directory Structure

```
youtube-summary-notify-with-gemini/
├── CLAUDE.md                      # This file (project hub)
├── docs/
│   ├── 00_requirement/
│   │   └── 00_requirement.md
│   ├── 01_design/
│   │   ├── 00_architecture-design.md
│   │   ├── 01_application-design.md
│   │   ├── 02_data-design.md
│   │   └── 03_coding-standards.md
│   ├── 02_operation/
│   │   └── 00_deployment.md
│   └── 03_external_apis/
│       ├── 00_youtube-data-api.md
│       ├── 01_gemini-api.md
│       └── 02_notification-webhook-api.md
├── youtube_summary_notify/
│   ├── __init__.py
│   ├── main.py                    # Core orchestration logic
│   ├── youtube_client.py          # YouTube Data API client
│   ├── summarizer.py              # Gemini API summarization
│   ├── notifiers/
│   │   ├── __init__.py
│   │   ├── base.py                # Abstract notifier interface
│   │   ├── slack.py               # Slack notifier (Incoming Webhooks)
│   │   └── discord.py             # (future scope)
│   ├── store/
│   │   ├── __init__.py
│   │   ├── config_store.py        # S3: config.yaml
│   │   └── video_state_store.py   # DynamoDB: notified video state
│   └── config.py                  # Configuration loader (Secrets Manager + S3)
├── infra/
│   └── template.yaml              # SAM template
├── tests/
│   ├── conftest.py                # Shared fixtures (moto AWS, constants)
│   ├── unit/                      # Unit tests (one file per module)
│   └── e2e/                       # E2E tests (full pipeline)
├── Dockerfile
├── pyproject.toml
├── README.md
└── .gitignore
```

## Required Reading Before Implementation

The following documents contain detailed specs, design decisions, and constraints. **Read all of them before starting any implementation work.**

1. [docs/00_requirement/00_requirement.md](docs/00_requirement/00_requirement.md) — Functional & non-functional requirements
2. [docs/01_design/00_architecture-design.md](docs/01_design/00_architecture-design.md) — System-level: AWS resources, infrastructure
3. [docs/01_design/01_application-design.md](docs/01_design/01_application-design.md) — Code-level: modules, interfaces, processing flow
4. [docs/01_design/02_data-design.md](docs/01_design/02_data-design.md) — Data schemas: config.yaml, DynamoDB, Secrets Manager
5. [docs/01_design/03_coding-standards.md](docs/01_design/03_coding-standards.md) — Language, dependencies, formatting, testing
6. [docs/02_operation/00_deployment.md](docs/02_operation/00_deployment.md) — Deployment, configuration, troubleshooting, cleanup
7. [docs/03_external_apis/00_youtube-data-api.md](docs/03_external_apis/00_youtube-data-api.md) — YouTube Data API v3
8. [docs/03_external_apis/01_gemini-api.md](docs/03_external_apis/01_gemini-api.md) — Gemini API
9. [docs/03_external_apis/02_notification-webhook-api.md](docs/03_external_apis/02_notification-webhook-api.md) — Notification webhook API (Slack, Discord)
