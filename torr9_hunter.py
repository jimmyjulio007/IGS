"""
IGS Torr9 Freeleech Hunter — Adapateur spécifique pour torr9.net

torr9.net est un tracker basé sur Next.js avec une API REST backend.
L'authentification utilise un token JWT Bearer envoyé à api.torr9.net.

### Comment extraire votre token JWT :
1. Ouvrez torr9.net dans votre navigateur et connectez-vous
2. Ouvrez DevTools (F12) → onglet "Network"
3. Rechargez la page ou cliquez sur un torrent
4. Cherchez une requête vers "api.torr9.net"
5. Cliquez dessus → Headers → trouvez "Authorization: Bearer <VOTRE_TOKEN>"
6. Copiez ce TOKEN et collez-le dans config.json sous torr9.jwt_token
"""

import requests
import logging
import threading
import json

logger = logging.getLogger("torr9_hunter")


class Torr9Hunter:
    """Auto-téléchargeur de torrents Freeleech pour torr9.net."""

    API_BASE = "https://api.torr9.net/api/v1"

    def __init__(self, jwt_token: str, client, notifier=None, interval_sec=600, max_per_run=5, notify_only=True):
        self.jwt_token = jwt_token
        self.client = client
        self.notifier = notifier
        self.interval_sec = interval_sec
        self.max_per_run = max_per_run
        self.notify_only = notify_only  # If True, only notify — never auto-download
        self._seen_ids: set[int] = set()
        self._stop = threading.Event()
        self._thread = None

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.jwt_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://torr9.net",
            "Referer": "https://torr9.net/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
        })

    def fetch_freeleech(self) -> list[dict]:
        """Récupère la liste des torrents Freeleech depuis l'API."""
        try:
            resp = self._session.get(
                f"{self.API_BASE}/torrents",
                params={
                    "freeleech": 1,
                    "sort": "created_at",
                    "order": "desc",
                    "limit": self.max_per_run * 3,  # Over-fetch to allow deduplication
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            # Handle both {"data": [...]} and direct list responses
            if isinstance(data, dict):
                torrents = data.get("data", data.get("torrents", []))
            else:
                torrents = data

            return torrents
        except Exception as e:
            logger.warning(f"[Torr9] Failed to fetch freeleech list: {e}")
            return []

    def download_torrent(self, torrent_id: int) -> bytes | None:
        """Télécharge le fichier .torrent brut depuis l'API."""
        try:
            resp = self._session.get(
                f"{self.API_BASE}/torrents/{torrent_id}/download",
                timeout=20,
            )
            if resp.status_code == 200 and len(resp.content) > 100:
                # Validate it's actually a bencoded torrent (starts with 'd')
                if resp.content.startswith(b"d"):
                    return resp.content
                logger.warning(f"[Torr9] Download for #{torrent_id} doesn't look like a .torrent file")
            else:
                logger.warning(f"[Torr9] HTTP {resp.status_code} on download #{torrent_id}")
        except Exception as e:
            logger.warning(f"[Torr9] Failed to download torrent #{torrent_id}: {e}")
        return None

    def add_to_qbittorrent(self, torrent_id: int, name: str, torrent_bytes: bytes) -> bool:
        """Ajoute le torrent dans qBittorrent via l'API et marque comme Freeleech."""
        try:
            resp = self.client.session.post(
                f"{self.client.base_url}/torrents/add",
                data={"category": "Freeleech-Torr9", "tags": "freeleech,torr9"},
                files={"torrents": (f"torr9_{torrent_id}.torrent", torrent_bytes, "application/x-bittorrent")},
            )
            if resp.ok or resp.text == "Ok.":
                return True
        except Exception as e:
            logger.warning(f"[Torr9] qBittorrent add failed for #{torrent_id}: {e}")
        return False

    def _format_size(self, size_bytes: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"

    def run_once(self) -> int:
        """Exécute un cycle de chasse Freeleech. Retourne le nombre de torrents ajoutés."""
        freeleech = self.fetch_freeleech()
        if not freeleech:
            logger.info("[Torr9] No freeleech torrents found or API error.")
            return 0

        added = 0
        for t in freeleech:
            if added >= self.max_per_run:
                break

            # Handle different possible field names from the API
            torrent_id = t.get("id") or t.get("torrent_id")
            name = t.get("name") or t.get("title") or f"Torrent-{torrent_id}"
            size = t.get("size") or t.get("file_size") or 0

            if not torrent_id or torrent_id in self._seen_ids:
                continue

            logger.info(f"[Torr9] Found freeleech: {name[:60]} (#{torrent_id})")
            size_str = self._format_size(size)

            if self.notify_only:
                # Only alert — do NOT download automatically
                self._seen_ids.add(torrent_id)
                added += 1
                print(f"[Torr9] 🔔 Freeleech Alert: {name[:60]} ({size_str}) → https://torr9.net/torrents/{torrent_id}")
                if self.notifier:
                    self.notifier.send(
                        f"🆓 <b>Freeleech Torr9</b>\n\n"
                        f"📦 <code>{name[:60]}</code>\n"
                        f"💾 {size_str}\n"
                        f"🔗 <a href='https://torr9.net/torrents/{torrent_id}'>Voir le torrent</a>"
                    )
            else:
                torrent_bytes = self.download_torrent(torrent_id)
                if not torrent_bytes:
                    continue
                if self.add_to_qbittorrent(torrent_id, name, torrent_bytes):
                    self._seen_ids.add(torrent_id)
                    added += 1
                    print(f"[Torr9] ✅ Added: {name[:60]} ({size_str})")
                    if self.notifier:
                        self.notifier.alert_freeleech_added(name, size_str)
                else:
                    logger.warning(f"[Torr9] Failed to add {name}")

        return added

    def _loop(self):
        while not self._stop.is_set():
            try:
                added = self.run_once()
                print(f"[Torr9] Cycle done — {added} torrent(s) added.")
            except Exception as e:
                logger.error(f"[Torr9] Unexpected error: {e}")
            self._stop.wait(self.interval_sec)

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Torr9Hunter")
        self._thread.start()
        print(f"[Torr9] 🟢 Freeleech Hunter started (every {self.interval_sec}s, max {self.max_per_run}/run)")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        print("[Torr9] Stopped.")


def build_torr9_hunter(config: dict, client, notifier=None):
    """Construit un Torr9Hunter depuis config.json. Renvoie None si non configuré."""
    torr9_cfg = config.get("torr9", {})
    if not torr9_cfg.get("enabled", False):
        return None
    jwt = torr9_cfg.get("jwt_token", "")
    if not jwt:
        logger.warning("[Torr9] No jwt_token configured — skipping Torr9 hunter.")
        return None
    notify_only = torr9_cfg.get("notify_only", True)  # Default: alert only, no auto-download
    return Torr9Hunter(
        jwt_token=jwt,
        client=client,
        notifier=notifier,
        interval_sec=torr9_cfg.get("interval_sec", 600),
        max_per_run=torr9_cfg.get("max_per_run", 5),
        notify_only=notify_only,
    )
