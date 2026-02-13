# Gemini API

## Overview

This system uses the Gemini API to summarize YouTube videos. Gemini is the only major LLM that accepts YouTube URLs directly — it processes visual frames, audio, and subtitles natively without any preprocessing.

- SDK: `google-genai` ([Documentation](https://ai.google.dev/gemini-api/docs))
- Pricing: [Google AI Pricing](https://ai.google.dev/pricing)
- Rate Limits: [Rate Limits Documentation](https://ai.google.dev/gemini-api/docs/rate-limits)

## Usage in This System

- **Default model**: `gemini-2.5-flash` (configurable in `config.yaml`)
- **Input**: YouTube video passed as a media part, with text prompt containing `{language}` substituted at runtime
- **Concurrency**: limited by `asyncio.Semaphore(5)` to stay within rate limits

## Prompt Template

Stored in `config.yaml` under `summarization.prompt_template`. The video is passed as a structured media part via `Part.from_uri()`, so the prompt only needs text instructions. Available variables:

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

## Passing YouTube URLs via `contents`

When calling `generate_content`, the YouTube URL should be passed as a structured media part — not embedded as text in the prompt. This tells Gemini to actually fetch and process the video (frames, audio, subtitles) rather than just seeing the URL as a string.

### Using `Part.from_uri`

```python
from google.genai.types import Part

response = await client.aio.models.generate_content(
    model="gemini-2.5-flash",
    contents=[
        Part.from_uri(
            file_uri="https://www.youtube.com/watch?v=VIDEO_ID",
            mime_type="video/mp4",
        ),
        "Summarize this video in Japanese.",
    ],
)
```

- `contents` accepts a list of parts; strings are auto-wrapped into `Part(text=...)` by the SDK
- Place the video part **before** the text prompt
- `Part.from_uri()` constructs a `FileData(file_uri=..., mime_type=...)` internally

### Using explicit `types.Content`

```python
from google.genai import types

response = await client.aio.models.generate_content(
    model="gemini-2.5-flash",
    contents=types.Content(
        parts=[
            types.Part(
                file_data=types.FileData(
                    file_uri="https://www.youtube.com/watch?v=VIDEO_ID",
                )
            ),
            types.Part(text="Summarize this video in Japanese."),
        ]
    ),
)
```

### References

- [Video understanding | Gemini API](https://ai.google.dev/gemini-api/docs/video-understanding)
- [YouTube video sample | Vertex AI](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/samples/googlegenaisdk-textgen-with-youtube-video)

## Known Constraints

- **Public videos only**: Gemini cannot access private or unlisted YouTube videos.
- **Video age**: Some reports indicate timeout issues with recently uploaded videos, though not consistently reproducible.
- **Maximum video length**: Limited by context window. Videos over 2 hours may experience degraded quality or timeouts.
- **Free tier volatility**: Google has reduced free tier quotas without notice in the past. Refer to the [official rate limits page](https://ai.google.dev/gemini-api/docs/rate-limits) for current values.
