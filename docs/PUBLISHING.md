# Scheduled social publishing

`taskfilm publish` supports Instagram Reels, Facebook Page Reels, and YouTube
uploads using their APIs. A local SQLite queue records scheduled jobs, original
asset hashes, provider resource/upload IDs, and publication receipts. It does
not launch paid advertising campaigns or spend an ad budget.

## Configure a post

Use explicit destination IDs and environment-variable names. Tokens are loaded
at execution, never stored in manifests. The worker must run where those
credentials are available. Meta requires a working token with the publishing
permissions for that asset and a public HTTPS video URL; a local file path alone
cannot be fetched by Meta. Configure the Graph API version your app supports.

Example Instagram manifest:

```json
{
  "schema": "taskfilm-publish/v1",
  "video": "portrait-ad.mp4",
  "video_url": "https://your-cdn.example/portrait-ad.mp4",
  "title": "See your studio clearly",
  "caption": "Spend less time on admin. Try Acme Studio: https://example.com",
  "audio_receipt": "mix.mix.json",
  "target": {
    "platform": "instagram",
    "account_id": "YOUR_INSTAGRAM_ACCOUNT_ID",
    "token_env": "TASKFILM_INSTAGRAM_TOKEN",
    "graph_version": "v26.0"
  },
  "scheduled_at": "2026-10-12T15:00:00Z"
}
```

Replace the example ID, URL, and version with your configured values. For
Facebook use `platform: "facebook"` and the Facebook Page ID/token. Enqueue one
manifest per destination. `audio_receipt` verifies its original mix's hash and
appends its music credits to the caption. Manual `attribution` entries can be
provided instead or in addition. Scheduling requires a timezone; omitted means
the job is due immediately.

For YouTube install `pip install 'taskfilm[publish]'`, and use:

```json
{
  "platform": "youtube",
  "account_id": "YOUR_YOUTUBE_CHANNEL_ID",
  "credentials_env": "TASKFILM_YOUTUBE_CREDENTIALS"
}
```

Set that environment variable to an existing authorized-user OAuth JSON file.
The credential needs channel read access for the identity check and upload
access. Supply `title` and optionally `privacy` (`public`, `unlisted`, `private`),
`made_for_kids`, and `contains_synthetic_media` in the manifest. YouTube verifies
the channel identity before upload and checkpoints resumable upload progress.

## Run

```bash
taskfilm publish enqueue post.json
taskfilm publish status
taskfilm publish work                 # preview due jobs; sends nothing
taskfilm publish work --execute       # process due jobs once
taskfilm publish work --execute --watch --interval 15  # unattended worker
```

Default database: `$XDG_STATE_HOME/taskfilm/publish.sqlite3`, or
`~/.local/state/taskfilm/publish.sqlite3`. Override with global `--db PATH` before
the command. Run the watching worker under your existing process manager, or
run `work --execute` periodically from cron/systemd/launchd. The persistent queue
survives restarts; an always-running worker or timer is required for schedules.

Identical target/video/caption jobs deduplicate. Use an explicit
`enqueue --idempotency-key campaign-specific-key` for an intentional repeat.
Changed/deleted video bytes fail before any upload. Concurrent workers claim a
job atomically. Processing polls preserve container/video IDs. Facebook is
marked published only after its publishing phase completes.

Confirmed temporary failures retry with backoff (maximum five failed attempts).
Expired/missing credentials stop as `failed`; after fixing them, use
`taskfilm publish retry JOB_ID`. A timeout/server error during a write, or a
worker crash during publication, stops as `needs_review`: it never blindly
reposts. Check the platform and record a verified existing result with
`taskfilm publish reconcile JOB_ID --remote-id EXISTING_POST_ID`.

## Validation and current deployment

Queue behavior and adapter request/response flows have automated tests.
Live publishing requires platform credentials and asset permissions; mocked
adapter tests are not proof of those permissions. Before enabling a live worker, check each
platform token read-only (an expired Meta access token returns HTTP 401 / code 190),
renew it if needed, and choose the destination accounts.

API references: [Instagram content publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/),
[Facebook Reels publishing](https://developers.facebook.com/docs/video-api/guides/reels-publishing/),
[YouTube video uploads](https://developers.google.com/youtube/v3/docs/videos/insert).
