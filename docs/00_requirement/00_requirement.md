# Requirements

## Functional Requirements

### F-1: YouTube Channel Monitoring

- Detect new videos from monitored YouTube channels.
- Use YouTube Data API v3 `playlistItems.list` to fetch videos from each channel's "Uploads" playlist.
- Only check videos published within **2× the execution interval** (e.g., 60 min interval → check last 120 min). This avoids unnecessary API calls while covering timing drift.
- Monitored channels are defined in the S3 config file (`config.yaml`). Users add or remove channels by editing this file directly.

### F-2: Video Summarization

- Pass each new video directly to the Gemini API as a structured media part for summarization.
- Gemini analyzes the video natively (visual frames + audio) — no transcript extraction or preprocessing required.
- **Prompt template**: stored in S3 config file (`config.yaml`). The system substitutes `{language}` into the template at runtime. Users can edit the prompt freely by updating the S3 file — no SAM redeployment required.
- **Summary language**: managed within the same S3 config file (default: `en`).
- **Gemini model**: managed within the same S3 config file (default: `gemini-2.5-flash`). Users can change the model without redeployment.
- See `docs/03_external_apis/01_gemini-api.md` for model recommendations.

### F-3: Notification

- Send generated summaries to all configured notification targets. All targets receive the same summaries.
- Multiple targets can be configured in `config.yaml` under `notifications` (e.g., two Slack channels, or Slack + Discord).
- v1 implements Slack only (Incoming Webhooks).
- **Per-target configuration**: each target specifies `name` (unique identifier), `platform`, `secret_key` (key within the `<stack-name>-secrets` JSON in Secrets Manager), and `message_template`.
- **Message template**: each target has its own template, allowing platform-specific formatting. The system substitutes video metadata variables at runtime (see `docs/01_design/02_data-design.md` for the full list of template variables).
- If one target fails, the others still receive their notifications. The failure is included in the error summary.
- On execution with errors, send a separate error message to all targets at the end (see NF-1).
- Architecture supports future platforms (Discord, etc.) via a pluggable interface (`notifiers/base.py`).

### F-4: Duplicate Prevention

- Track notified video IDs in DynamoDB (`video_state` table) to prevent duplicate notifications.
- Retain the last 500 video IDs per deployment; auto-delete older entries.
- Videos that failed summarization are NOT recorded in state — they will be retried on the next execution.

### F-5: Scheduled Execution

- Execution interval is configurable via SAM parameter (default: 60 minutes).
- Triggered by AWS EventBridge (cron rule) → Lambda.

## Non-Functional Requirements

### NF-1: Error Handling

- When an individual video fails (Gemini API error, timeout, etc.), skip that video and continue processing the remaining videos.
- At the end of execution, if any videos failed, send an error summary message to the notification platform. This message should include:
  - Number of successes and failures
  - Failed video titles, URLs, and error types
- Failed videos are not written to state — they will be retried on the next execution.

### NF-2: Logging

- Use Python's standard `logging` module with structured output.
- Log the following at each execution:
  - Start and end of execution
  - Number of channels checked
  - Number of new videos detected
  - Number of summaries succeeded / failed
  - Any errors with traceback
- Log levels: DEBUG for verbose diagnostic data (e.g., list of detected new videos, API request/response details), INFO for normal flow, WARNING for recoverable issues, ERROR for failures.

### NF-3: Performance

- Summarize multiple videos concurrently using `asyncio.gather`.
- Limit concurrency with `asyncio.Semaphore` to respect Gemini API rate limits (free tier: 10 RPM).
- Target: complete a single execution within 5 minutes under normal conditions.

### NF-4: Security

- All API keys and secrets are managed via AWS Secrets Manager.
- Non-secret configuration is managed via S3 config file or SAM template parameters.
- Never log or output API keys or secrets.

### NF-5: State Robustness

- Video state uses DynamoDB for persistence.
- Use DynamoDB conditional writes where appropriate to prevent race conditions.
- If video state cannot be read, treat as empty state and continue (may cause duplicate notifications).
- If video state cannot be written, log an error (may cause duplicate notifications on next run).

### NF-6: Deployment

- Provide a Dockerfile based on the AWS Lambda Python base image.
- Provide an AWS SAM template (`infra/template.yaml`) that provisions all required resources:
  - Lambda function
  - EventBridge rule
  - S3 bucket (config)
  - DynamoDB table (video_state)
  - Secrets Manager secret
- Deployable via `sam deploy --guided`.
- See `docs/02_operation/00_deployment.md` for the full deployment guide.
