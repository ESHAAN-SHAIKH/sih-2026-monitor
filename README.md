# SIH 2026 Telegram Result Monitor (Railway)

A Python background worker that checks the public SIH website and Google News RSS for possible Smart India Hackathon 2026 result announcements, then sends Telegram alerts.

## Files to upload to your GitHub repository

Upload **all files in this folder** to the root of a new repository:
- `sih_2026_telegram_monitor.py`
- `requirements.txt`
- `railway.json`
- `README.md`

No Git command line is required. You can create a repository on GitHub and use **Add file → Upload files** in the browser.

## Deploy on Railway

1. In Railway, create a new project or use an existing one.
2. Choose **Deploy from GitHub repo** and select the repository you created.
3. Railway reads `railway.json`, installs `requirements.txt`, and runs `python sih_2026_telegram_monitor.py` as a background worker.
4. Open the service's **Variables** tab and add the required variables below.
5. Redeploy if Railway does not automatically redeploy after variables are saved.
6. Check deployment logs. The worker should start and send a Telegram startup message.

## Required Railway variables

- `TELEGRAM_BOT_TOKEN`: token created with Telegram's `@BotFather`.
- `TELEGRAM_CHAT_ID`: your Telegram chat ID. Recommended to set explicitly.

Optional variables:

- `CHECK_EVERY_SECONDS`: polling interval in seconds; default is `300` (5 minutes).
- `SIH_URL`: public SIH page to monitor; default is `https://www.sih.gov.in/`.
- `INSTITUTION_URLS`: comma-separated public college notice/result page URLs.
- `STATE_FILE`: state file path; default is `sih_monitor_state.json` in the service working directory.

## Telegram setup

1. Open Telegram and message `@BotFather`.
2. Create a bot using `/newbot` and copy the token.
3. Open your new bot and send `/start`.
4. Get your chat ID by opening `https://api.telegram.org/botYOUR_TOKEN/getUpdates` in a browser (replace `YOUR_TOKEN` locally; never share it in chat). Find `message` → `chat` → `id`.
5. Add both values in Railway Variables. Do not commit the token to GitHub.

## Persistence warning

The monitor stores seen RSS items and page hashes in `sih_monitor_state.json`. Without a persistent Railway Volume mounted at the directory containing that file, a redeploy or container replacement can reset the baseline. If you attach a volume, set `STATE_FILE` to a path inside its mount directory, for example `/data/sih_monitor_state.json` if the volume is mounted at `/data`.

## Important limitations

- This is not an official SIH API integration. It checks public pages and Google News RSS only.
- It cannot see private/login-only dashboards and cannot guarantee detection of every announcement.
- On its first run, it records the current RSS/page content as a baseline and does not alert on old items. It alerts on new matching RSS items and later changes to monitored pages.
- Keyword matching can produce false positives or miss announcements worded differently. Verify every alert against the linked source.
