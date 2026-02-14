# Notification Webhook API

## Slack Incoming Webhooks (v1)

- Overview: [Slack Incoming Webhooks](https://api.slack.com/messaging/webhooks)
- Message formatting: [Slack mrkdwn](https://api.slack.com/reference/surfaces/formatting)
- Rate limits: [Slack Rate Limits](https://api.slack.com/docs/rate-limits)

## Discord Webhooks

- Overview: [Discord Webhooks](https://discord.com/developers/docs/resources/webhook)
- Endpoint: `POST https://discord.com/api/webhooks/{webhook.id}/{webhook.token}`
- Payload: `{"content": "message text"}` (note: Slack uses `"text"`, Discord uses `"content"`)
- Message formatting: standard Markdown (differs from Slack mrkdwn)
- Rate limits: [Discord Rate Limits](https://discord.com/developers/docs/topics/rate-limits)
