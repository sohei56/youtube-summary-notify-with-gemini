# Gemini API

## Overview

This system uses the Gemini API to summarize YouTube videos. Gemini is the only major LLM that accepts YouTube URLs directly — it processes visual frames, audio, and subtitles natively without any preprocessing.

- SDK: `google-genai` ([Documentation](https://ai.google.dev/gemini-api/docs))
- Pricing: [Google AI Pricing](https://ai.google.dev/pricing)
- Rate Limits: [Rate Limits Documentation](https://ai.google.dev/gemini-api/docs/rate-limits)

## Usage in This System

- **Default model**: `gemini-2.5-flash` (configurable in `config.yaml`)
- **Input**: prompt template with `{video_url}` and `{language}` substituted at runtime
- **Concurrency**: limited by `asyncio.Semaphore(5)` to stay within rate limits

## Prompt Template

Stored in `config.yaml` under `summarization.prompt_template`. The system substitutes only two variables:

- `{video_url}` — the YouTube video URL
- `{language}` — the summary language from `summarization.language`

See `docs/01_design/02_data-design.md` for the default template and full schema.

## Error Handling

| Error | Handling |
|---|---|
| Rate limit (429) | Skip video, retry next execution |
| Timeout | Skip video, retry next execution |
| Content filtering (blocked) | Skip video, log warning |
| Invalid model name | Abort execution |
| Authentication failure | Abort execution |
| Video unavailable (private, deleted, region-locked) | Skip video, log warning |

No automatic retry within a single execution — this keeps Lambda execution time predictable.

## Known Constraints

- **Public videos only**: Gemini cannot access private or unlisted YouTube videos.
- **Video age**: Some reports indicate timeout issues with recently uploaded videos, though not consistently reproducible.
- **Maximum video length**: Limited by context window. Videos over 2 hours may experience degraded quality or timeouts.
- **Free tier volatility**: Google has reduced free tier quotas without notice in the past. Refer to the [official rate limits page](https://ai.google.dev/gemini-api/docs/rate-limits) for current values.
