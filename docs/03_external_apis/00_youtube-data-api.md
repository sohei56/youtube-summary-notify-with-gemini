# YouTube Data API v3

## Overview

This system uses YouTube Data API v3 to detect new videos from monitored channels.

- API Reference: [YouTube Data API v3](https://developers.google.com/youtube/v3)
- Quota Calculator: [Quota Cost](https://developers.google.com/youtube/v3/determine_quota_cost)

## Usage in This System

- **Endpoint**: `playlistItems.list` — fetches videos from each channel's "Uploads" playlist
- **Channel ID → Playlist ID**: replace leading `UC` with `UU` (e.g., `UCxxxx` → `UUxxxx`)
- **Filtering**: only videos published within 2× the execution interval are relevant

## Quota

- **Free quota**: 10,000 units/day
- **Cost**: `playlistItems.list` = 1 unit/request (returns up to 50 items)
- For the latest quota details, see [Quota Calculator](https://developers.google.com/youtube/v3/determine_quota_cost)
