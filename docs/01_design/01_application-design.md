# Application Design

## Processing Flow

Each Lambda execution follows this sequence:

```
1. Initialize
   ├── Load secrets from Secrets Manager (<stack-name>-secrets)
   └── Load config from S3 (channels, templates, model, language)

2. Detect New Videos
   ├── For each channel in config:
   │   └── Fetch recent videos from YouTube Data API (within 2× interval)
   ├── Check video IDs against DynamoDB (video_state)
   └── Filter to only unnotified videos

3. Summarize Videos
   ├── For each new video (concurrently, limited by semaphore):
   │   ├── Pass video as media part + substituted prompt to Gemini API
   │   └── Collect result (success or error)
   └── Separate successes and failures

4. Send Notifications
   ├── For each successful summary:
   │   ├── For each notification target:
   │   │   ├── Substitute variables into message template
   │   │   └── POST to Webhook
   └── If any failures: send error message to all targets

5. Update State
   └── Write successfully notified video IDs to DynamoDB
```

### Error Behavior

- Step 1 failure (Secrets Manager / S3 config): log error, abort execution immediately. No notification is sent (notification credentials may be unavailable).
- Step 2 failure (YouTube API): log error, skip that channel, continue others.
- Step 3 failure (Gemini API): log error, skip that video. Do NOT write to state — will retry next execution.
- Step 4 failure (Webhook): log error. Video state is still written to avoid repeated summarization of the same video. A failure in one target does not block others.
- Step 5 failure (DynamoDB): log error. May cause duplicate notifications on next run.

## Module Responsibilities

### main.py — Orchestrator

The Lambda handler and core orchestration logic. Implements the processing flow above. Coordinates all other modules.

- Entry point: `handler(event, context)` for Lambda
- Loads configuration, then calls youtube_client → summarizer → notifier → state store in sequence
- Manages concurrency via `asyncio.Semaphore`
- Collects results and errors for the error summary

### youtube_client.py — YouTube Data API Client

Detects new videos from monitored channels.

- Calls `playlistItems.list` with each channel's Uploads playlist ID
- Filters videos by publish date (within 2× execution interval)
- Returns list of video metadata: `{video_id, title, url, channel_name, published_at}`
- Converts channel ID to Uploads playlist ID (replace leading `UC` with `UU`)

### summarizer.py — Gemini API Summarization

Generates video summaries using Gemini.

- Passes the YouTube video as a structured media part via `Part.from_uri()`
- Substitutes `{language}` into the prompt template
- Calls Gemini API with the configured model
- Returns summary text on success, or error details on failure
- Handles Gemini-specific errors (rate limit, timeout, content filtering)

### notifiers/base.py — Abstract Notifier Interface

Defines the interface for notification platforms.

```python
@dataclass
class VideoInfo:
    channel: str
    title: str
    url: str
    published_at: str
    summary: str

class BaseNotifier(ABC):
    @abstractmethod
    async def send_summary(self, video: VideoInfo) -> bool:
        """Build message from template and send. Returns True on success."""
        ...

    @abstractmethod
    async def send_error(self, message: str) -> bool:
        """Send error message. Returns True on success."""
        ...
```

Each notifier instance holds its own message template (from its `notifications[]` entry in config) and constructs the final message internally by substituting `VideoInfo` fields.

### notifiers/slack.py — Slack Notifier

Sends notifications via Slack Incoming Webhooks.

- `send_summary(video)`: substitutes `VideoInfo` fields into message template, POSTs to Webhook URL, returns `bool`
- `send_error(message)`: POSTs error message to Webhook URL, returns `bool`

### store/config_store.py — S3 Configuration Store

Reads and parses the `config.yaml` file from S3.

- Returns typed configuration: channels list, summarization settings (prompt template, model, language), notification targets (each with name, platform, secret_key, message template)
- Validates required fields on load
- Caches within a single execution (config does not change mid-run)

### store/video_state_store.py — DynamoDB Video State Store

Tracks which videos have been notified.

- `get_notified_ids() -> set[str]`: returns set of known video IDs
- `put_notified_ids(video_ids: list[str])`: writes new IDs, enforcing 500-entry limit
- Uses conditional writes to prevent race conditions
- Auto-deletes oldest entries when exceeding 500

### config.py — Configuration Loader

Aggregates configuration from multiple sources.

- Loads secrets from Secrets Manager (`<stack-name>-secrets` — single JSON containing all API keys and Webhook URLs)
- Loads user config from S3 via config_store
- Reads SAM-injected environment variables (S3 bucket name, DynamoDB table name, execution interval)
- Provides a unified config object to main.py

## Concurrency Model

```
main.py
  │
  ├── asyncio.gather (per channel)
  │     └── youtube_client.fetch_recent_videos(channel)
  │
  ├── asyncio.gather (per video, bounded by Semaphore)
  │     └── summarizer.summarize(video)
  │
  └── sequential
        ├── notifier.send_summary(video)  # per video, per target
        └── notifier.send_error(message)  # once if needed, all targets
```

- **Video detection**: concurrent per channel (YouTube API calls are independent).
- **Summarization**: concurrent with `asyncio.Semaphore(5)` to respect Gemini free tier rate limits (10 RPM). Semaphore size is configurable.
- **Notification**: sequential to preserve message ordering in Slack.

## Notification Dispatch

For each video, `main.py` calls `send_summary` on **all** notifier instances. For error notifications, `send_error` is called on all instances.

A failure in one target does not block others — each target is called independently, and failures are logged per target.

## Notifier Extensibility

To add a new notification platform:

1. Create `notifiers/<platform>.py` implementing `BaseNotifier`.
2. Register the platform in the notifier factory.
3. Users add a new entry to `notifications` list in `config.yaml` with the new platform name.
4. Users add the platform's secret (e.g., Webhook URL) to Secrets Manager.
