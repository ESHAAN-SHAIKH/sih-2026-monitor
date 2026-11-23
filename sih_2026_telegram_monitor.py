#!/usr/bin/env python3
"""
SIH 2026 result monitor -> Telegram alerts.

Checks:
  1) The public SIH website (configurable).
  2) Google News RSS for new SIH 2026 result announcements.
  3) Optional institution/college result page(s).

This is a public-page monitor, not an official SIH API integration. It cannot see
private/login-only dashboards or guarantee detection of announcements posted only
inside the SIH portal.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

# --------------------------- Configuration ---------------------------

CHECK_EVERY_SECONDS = int(os.getenv("CHECK_EVERY_SECONDS", "300"))  # 5 minutes
STATE_FILE = Path(os.getenv("STATE_FILE", "sih_monitor_state.json"))

# SIH public site; override if its public results page has a more specific URL.
SIH_URL = os.getenv("SIH_URL", "https://www.sih.gov.in/")

# Add your college/institute's public result page URL(s), separated by commas.
# Example: INSTITUTION_URLS="https://college.edu/sih-results,https://college.edu/notices"
INSTITUTION_URLS = [
    u.strip() for u in os.getenv("INSTITUTION_URLS", "").split(",") if u.strip()
]

# Match both "Smart India Hackathon" and common SIH result wording.
RESULT_TERMS = [
    "result", "results", "selected teams", "shortlisted", "finalist",
    "grand finale", "nomination list", "qualified", "screening"
]
SIH_TERMS = ["sih 2026", "smart india hackathon 2026", "smart india hackathon"]

USER_AGENT = "Mozilla/5.0 (compatible; SIH2026ResultMonitor/1.0)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.8"})
TIMEOUT = 25


# --------------------------- Telegram ---------------------------

def telegram_api(method: str, **payload):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN before starting the monitor.")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/{method}",
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    return data["result"]


def get_chat_id() -> str:
    """Use TELEGRAM_CHAT_ID if set; otherwise detect the chat after /start."""
    configured = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if configured:
        return configured

    updates = telegram_api("getUpdates", timeout=0)
    chats = []
    for update in updates:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        if chat.get("id") is not None:
            chats.append(str(chat["id"]))
    if not chats:
        raise RuntimeError(
            "No Telegram chat found. Open your bot in Telegram, press Start/send /start, "
            "then run this script again."
        )
    return chats[-1]


def send_telegram(chat_id: str, text: str):
    telegram_api("sendMessage", chat_id=chat_id, text=text, disable_web_page_preview=True)


# --------------------------- Monitoring helpers ---------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print("Warning: state file unreadable; starting with fresh state.")
    return {"seen_rss": [], "page_hashes": {}}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def fetch(url: str) -> str:
    response = SESSION.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def looks_like_sih_result(text: str) -> bool:
    text = normalize(text)
    has_sih = any(term in text for term in SIH_TERMS)
    has_result = any(term in text for term in RESULT_TERMS)
    return has_sih and has_result


def google_news_rss_url() -> str:
    query = quote_plus('"Smart India Hackathon" "2026" (result OR results OR shortlisted OR finalist)')
    return f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"


def check_rss(state: dict, chat_id: str):
    try:
        xml_text = fetch(google_news_rss_url())
        root = ET.fromstring(xml_text)
        items = root.findall(".//item")
        seen = set(state.get("seen_rss", []))
        fresh_ids = []

        # First run: record existing feed items as baseline; only alert on later arrivals.
        if not state.get("rss_initialized"):
            for item in items:
                title = item.findtext("title", default="").strip()
                link = item.findtext("link", default="").strip()
                description = BeautifulSoup(item.findtext("description", default=""), "html.parser").get_text(" ", strip=True)
                identity = link or hashlib.sha256((title + description).encode()).hexdigest()
                fresh_ids.append(identity)
            state["seen_rss"] = fresh_ids[:500]
            state["rss_initialized"] = True
            print(f"[BASELINE] Recorded {len(fresh_ids)} existing RSS items; no old-item alerts.")
            return

        for item in items:
            title = item.findtext("title", default="").strip()
            link = item.findtext("link", default="").strip()
            description = BeautifulSoup(item.findtext("description", default=""), "html.parser").get_text(" ", strip=True)
            pub_date = item.findtext("pubDate", default="").strip()
            identity = link or hashlib.sha256((title + description).encode()).hexdigest()

            if identity in seen:
                continue
            fresh_ids.append(identity)

            if looks_like_sih_result(f"{title} {description}"):
                message = (
                    "🔔 Possible SIH 2026 result announcement\n\n"
                    f"{title}\n"
                    f"{description[:700]}\n\n"
                    f"Published: {pub_date or 'Not provided'}\n"
                    f"Source: {link}"
                )
                send_telegram(chat_id, message)
                print(f"[ALERT] {title}")
            else:
                print(f"[RSS] New item did not match result keywords: {title}")

        # Keep the most recent 500 IDs so the state file stays small.
        state["seen_rss"] = (fresh_ids + state.get("seen_rss", []))[:500]
    except Exception as exc:
        print(f"[RSS ERROR] {exc}")


def check_page(url: str, state: dict, chat_id: str):
    try:
        html = fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        digest = hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()
        previous = state.setdefault("page_hashes", {}).get(url)

        if previous is None:
            # First run establishes a baseline; do not alert on old content.
            state["page_hashes"][url] = digest
            print(f"[BASELINE] {url}")
            return

        if digest != previous:
            state["page_hashes"][url] = digest
            if looks_like_sih_result(text):
                send_telegram(
                    chat_id,
                    "🔔 SIH 2026 monitored page changed and contains result-related wording.\n\n"
                    f"Please verify the announcement:\n{url}"
                )
                print(f"[ALERT] Relevant page change: {url}")
            else:
                print(f"[CHANGE] Page changed, but result keywords were not found: {url}")
        else:
            print(f"[OK] No page change: {url}")
    except Exception as exc:
        print(f"[PAGE ERROR] {url}: {exc}")


def main():
    chat_id = get_chat_id()
    state = load_state()

    send_telegram(
        chat_id,
        "✅ SIH 2026 result monitor is running.\n"
        f"Checks every {CHECK_EVERY_SECONDS // 60} minute(s).\n"
        "I will send an alert when a new matching announcement is detected."
    )
    print("Monitor started. Press Ctrl+C to stop.")

    urls = [SIH_URL] + INSTITUTION_URLS
    while True:
        print(f"\n[{datetime.now().astimezone().isoformat(timespec='seconds')}] Checking...")
        check_rss(state, chat_id)
        for url in urls:
            check_page(url, state, chat_id)
        save_state(state)
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        print(f"Fatal error: {exc}")
        raise
