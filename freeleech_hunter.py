"""
IGS Freeleech Hunter — Automatically scrapes and adds Freeleech torrents.

Supports configurable tracker profiles via config.json under "freeleech_hunter".
Each tracker profile needs:
  - base_url: tracker homepage
  - freeleech_url: page listing freeleech torrents
  - cookies: dict of session cookies (grab from your browser DevTools)
  - download_url_pattern: string template to build .torrent download URL with {torrent_id}
"""

import time
import threading
import re
import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from tracker_stats import format_bytes

logger = logging.getLogger("freeleech_hunter")


class TrackerProfile:
    """Defines how to scrape a specific tracker for Freeleech torrents."""

    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.freeleech_url = cfg["freeleech_url"]
        self.download_pattern = cfg["download_url_pattern"]   # e.g. "https://tracker.tld/download.php?id={torrent_id}"
        self.cookies = cfg.get("cookies", {})
        self.torrent_link_selector = cfg.get("torrent_link_selector", "a[href*='download']")
        self.name_selector = cfg.get("name_selector", "a.torrent-name")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
            "Referer": cfg.get("base_url", self.freeleech_url),
        }

    def fetch_freeleech_list(self) -> list[dict]:
        """Scrape the freeleech page and return a list of {id, name, url} dicts."""
        try:
            resp = requests.get(
                self.freeleech_url,
                cookies=self.cookies,
                headers=self.headers,
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to fetch freeleech page: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        torrents = []

        for link in soup.select(self.torrent_link_selector):
            href = link.get("href", "")
            # Try to extract a numeric ID from the link
            match = re.search(r"[?&/](?:id|torrent_id|tid)=?(\d+)", href)
            if not match:
                continue
            torrent_id = match.group(1)
            
            # Try to find the name from sibling/parent element
            name_el = link.find_parent("tr")
            name = name_el.select_one(self.name_selector) if name_el else None
            torrent_name = name.get_text(strip=True) if name else f"Torrent-{torrent_id}"

            download_url = self.download_pattern.format(torrent_id=torrent_id)
            torrents.append({"id": torrent_id, "name": torrent_name, "url": download_url})

        return torrents

    def download_torrent_bytes(self, url: str) -> bytes | None:
        """Download the raw .torrent file content."""
        try:
            resp = requests.get(
                url,
                cookies=self.cookies,
                headers=self.headers,
                timeout=20,
            )
            if resp.status_code == 200 and b"info" in resp.content:
                return resp.content
            logger.warning(f"[{self.name}] Got unexpected response for {url}: {resp.status_code}")
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to download torrent: {e}")
        return None


class FreeleechHunter:
    """
    Polls configured trackers for new Freeleech torrents and auto-adds them to qBittorrent.
    """

    def __init__(self, client, profiles: list[TrackerProfile], interval_sec=600, notifier=None, max_per_run=5):
        self.client = client
        self.profiles = profiles
        self.interval = interval_sec
        self.notifier = notifier
        self.max_per_run = max_per_run
        self._seen_ids: set[str] = set()
        self._stop = threading.Event()
        self._thread = None

    def _run_once(self):
        total_added = 0
        for profile in self.profiles:
            if total_added >= self.max_per_run:
                break

            freeleech = profile.fetch_freeleech_list()
            logger.info(f"[FreeleechHunter] {profile.name}: found {len(freeleech)} freeleech")

            for t in freeleech:
                if total_added >= self.max_per_run:
                    break
                uid = f"{profile.name}:{t['id']}"
                if uid in self._seen_ids:
                    continue

                torrent_bytes = profile.download_torrent_bytes(t["url"])
                if not torrent_bytes:
                    continue

                try:
                    resp = self.client.session.post(
                        f"{self.client.base_url}/torrents/add",
                        data={"category": "Freeleech"},
                        files={"torrents": (f"{t['id']}.torrent", torrent_bytes, "application/x-bittorrent")},
                    )
                    if resp.ok:
                        self._seen_ids.add(uid)
                        total_added += 1
                        msg = f"[FreeleechHunter] ✅ Added: {t['name'][:60]}"
                        print(msg)

                        if self.notifier:
                            self.notifier.alert_freeleech_added(t["name"], "Unknown size")
                    else:
                        logger.warning(f"[FreeleechHunter] qBittorrent rejected {t['name']}: {resp.text[:100]}")
                except Exception as e:
                    logger.warning(f"[FreeleechHunter] Failed to add {t['name']}: {e}")

        return total_added

    def _loop(self):
        while not self._stop.is_set():
            try:
                added = self._run_once()
                if added:
                    print(f"[FreeleechHunter] Cycle complete — {added} torrent(s) added.")
            except Exception as e:
                logger.error(f"[FreeleechHunter] Error: {e}")
            self._stop.wait(self.interval)

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="FreeleechHunter")
        self._thread.start()
        print(f"[FreeleechHunter] Started ({len(self.profiles)} tracker(s), interval: {self.interval}s)")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        print("[FreeleechHunter] Stopped.")


def build_profiles(config: dict) -> list[TrackerProfile]:
    """Load tracker profiles from config.json."""
    raw = config.get("freeleech_hunter", {}).get("trackers", {})
    return [TrackerProfile(name, cfg) for name, cfg in raw.items() if cfg.get("enabled", True)]
