# Mastodon to Telegram Bridge

This application bridges posts from a Mastodon account to Telegram channels.

## Setup

### For Local Development

1. Copy `.env.example` to `.env` and fill in your credentials:
   ```
   MASTODON_USER_ID=your_mastodon_user_id
   MASTODON_INSTANCE_URL=https://mastodon.social
   MASTODON_ACCESS_TOKEN=your_access_token
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_CHANNEL_IDS=channel_id1,channel_id2
   ```

2. Install dependencies:
   ```bash
   uv sync
   ```

3. Run the application:
   ```bash
   uv run python main.py
   ```

### For GitHub Actions

1. Set up the following repository secrets:
   - `MASTODON_USER_ID`: Your Mastodon user ID
   - `MASTODON_INSTANCE_URL`: Your Mastodon instance URL
   - `MASTODON_ACCESS_TOKEN`: Your Mastodon access token
   - `TELEGRAM_BOT_TOKEN`: Your Telegram bot token
   - `TELEGRAM_CHANNEL_IDS`: Comma-separated list of Telegram channel IDs
   - `PERSONAL_ACCESS_TOKEN`: GitHub Personal Access Token with repo permissions (needed to update secrets)

2. The GitHub Action will automatically:
   - Run every 5 minutes
   - Read the last sync time from the `LAST_UPDATED` secret
   - Sync new posts from that time
   - Update the `LAST_UPDATED` secret with the timestamp of the latest synced post
   - Clean up previous workflow runs (keeps only the 2 most recent runs to save storage)

## Command Line Arguments

- `--last-synced-post-time`: Only sync posts created after this time (format: YYYY-MM-DD HH:MM:SS)
- `--run-once`: Run once and exit (useful for GitHub Actions)

## How It Works

1. The application fetches recent posts from the specified Mastodon user
2. It filters out posts that were created before the specified time
3. It checks against a local SQLite database to avoid duplicate posts
4. It sends new posts to all configured Telegram channels
5. It records the post IDs in the database to prevent re-sending

In GitHub Actions mode, the database is temporary and gets destroyed after each run, but the `LAST_UPDATED` secret maintains the sync state between runs.

## GitHub Actions Cleanup

To save repository storage, the application automatically deletes old workflow runs after each successful execution. By default, it keeps the 2 most recent runs. You can adjust this by modifying the `keep_count` parameter in the `delete_previous_workflow_runs()` function call in `main.py`.

**Note:** This feature requires the `GITHUB_TOKEN` secret to be available, which is automatically provided by GitHub Actions.
