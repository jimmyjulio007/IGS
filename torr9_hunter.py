"""
IGS Torr9 Hunter — Adaptateur pour torr9.net (API REST + JWT)

Trois modes de chasse:
  1. Freeleech — Cible les torrents is_freeleech=True (ratio gratuit)
  2. Popular   — Cible les torrents recents (gros fichiers)
  3. Smart     — Analyse seeders/leechers pour trouver les swarms favorables
                 (peu de seeders + beaucoup de leechers = upload garanti)

### Comment extraire votre token JWT :
1. Ouvrez torr9.net dans votre navigateur et connectez-vous
2. Ouvrez DevTools (F12) > onglet "Network"
3. Rechargez la page ou cliquez sur un torrent
4. Cherchez une requete vers "api.torr9.net"
5. Cliquez dessus > Headers > trouvez "Authorization: Bearer <VOTRE_TOKEN>"
6. Copiez ce TOKEN et collez-le dans config.json sous torr9.jwt_token
"""

import requests
import logging
import threading

logger = logging.getLogger("torr9_hunter")


class Torr9Hunter:
    """Auto-telechargeur de torrents pour torr9.net."""

    API_BASE = "https://api.torr9.net/api/v1"

    def __init__(self, jwt_token: str, client, notifier=None, interval_sec=600,
                 max_per_run=5, notify_only=True, hunt_popular=True,
                 smart_hunt=True, max_size_gb=0):
        self.jwt_token = jwt_token
        self.client = client
        self.notifier = notifier
        self.interval_sec = interval_sec
        self.max_per_run = max_per_run
        self.notify_only = notify_only
        self.hunt_popular = hunt_popular
        self.smart_hunt = smart_hunt
        self.max_size_bytes = int(max_size_gb * 1024**3) if max_size_gb > 0 else 0
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

    def _fetch_torrents(self, params: dict) -> list[dict]:
        """Fetch torrents from the API with given params."""
        try:
            resp = self._session.get(
                f"{self.API_BASE}/torrents",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, dict):
                torrents = data.get("data", data.get("torrents", []))
            else:
                torrents = data

            return torrents if isinstance(torrents, list) else []
        except Exception as e:
            logger.warning(f"[Torr9] API fetch failed: {e}")
            return []

    def get_torrent_details(self, torrent_id: int) -> dict | None:
        """Fetch individual torrent details (includes seeders/leechers)."""
        try:
            resp = self._session.get(
                f"{self.API_BASE}/torrents/{torrent_id}",
                timeout=10,
            )
            if resp.ok:
                return resp.json()
        except Exception as e:
            logger.warning(f"[Torr9] Failed to get details for #{torrent_id}: {e}")
        return None

    def fetch_freeleech(self) -> list[dict]:
        """Fetch torrents and filter to actual freeleech (is_freeleech=True)."""
        raw = self._fetch_torrents({
            "freeleech": 1,
            "sort": "created_at",
            "order": "desc",
            "limit": 50,
        })
        return [t for t in raw if t.get("is_freeleech", False)]

    def fetch_popular(self) -> list[dict]:
        """Fetch recent popular torrents."""
        return self._fetch_torrents({
            "sort": "created_at",
            "order": "desc",
            "limit": 50,
        })

    def fetch_smart(self) -> list[dict]:
        """Fetch recent torrents and score them by upload opportunity.

        Score = leechers / (seeders + 1) * size_factor
        High score = few seeders, many leechers, decent size = GOLD for uploading.
        """
        raw = self._fetch_torrents({
            "sort": "created_at",
            "order": "desc",
            "limit": 50,
        })

        scored = []
        for t in raw:
            tid = t.get("id")
            if not tid or tid in self._seen_ids:
                continue

            size = t.get("file_size_bytes", 0) or 0
            if self.max_size_bytes > 0 and size > self.max_size_bytes:
                continue

            # Get detailed info with seeders/leechers
            details = self.get_torrent_details(tid)
            if not details:
                continue

            seeders = details.get("seeders", 0) or 0
            leechers = details.get("leechers", 0) or 0

            # Skip dead torrents (no leechers = no upload possible)
            if leechers == 0:
                continue

            # Score: more leechers + fewer seeders = better opportunity
            # size_factor: prefer bigger files (more data to upload per leecher)
            size_gb = max(size / (1024 ** 3), 0.1)
            score = (leechers / (seeders + 1)) * min(size_gb, 10)

            t["_seeders"] = seeders
            t["_leechers"] = leechers
            t["_score"] = score
            scored.append(t)

        # Sort by best upload opportunity
        scored.sort(key=lambda x: x["_score"], reverse=True)
        return scored

    def download_torrent(self, torrent_id: int) -> bytes | None:
        """Telecharge le fichier .torrent brut depuis l'API."""
        try:
            resp = self._session.get(
                f"{self.API_BASE}/torrents/{torrent_id}/download",
                timeout=20,
            )
            if resp.status_code == 200 and len(resp.content) > 100:
                if resp.content.startswith(b"d"):
                    return resp.content
                logger.warning(f"[Torr9] Download for #{torrent_id} doesn't look like a .torrent file")
            else:
                logger.warning(f"[Torr9] HTTP {resp.status_code} on download #{torrent_id}")
        except Exception as e:
            logger.warning(f"[Torr9] Failed to download torrent #{torrent_id}: {e}")
        return None

    def add_to_qbittorrent(self, torrent_id: int, name: str, torrent_bytes: bytes, category: str) -> bool:
        """Ajoute le torrent dans qBittorrent."""
        try:
            resp = self.client.session.post(
                f"{self.client.base_url}/torrents/add",
                data={"category": category, "tags": "torr9,auto-hunted"},
                files={"torrents": (f"torr9_{torrent_id}.torrent", torrent_bytes, "application/x-bittorrent")},
            )
            if resp.ok or resp.text == "Ok.":
                return True
        except Exception as e:
            logger.warning(f"[Torr9] qBittorrent add failed for #{torrent_id}: {e}")
        return False

    def add_by_magnet(self, magnet: str, category: str) -> bool:
        """Add torrent by magnet link (fallback if .torrent download fails)."""
        try:
            return self.client.add_torrent(urls=magnet, category=category)
        except Exception as e:
            logger.warning(f"[Torr9] Magnet add failed: {e}")
            return False

    def _format_size(self, size_bytes) -> str:
        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError):
            return "? B"
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"

    def _process_torrent(self, t: dict, category: str) -> bool:
        """Process a single torrent: download and add to qBittorrent."""
        torrent_id = t.get("id") or t.get("torrent_id")
        name = t.get("title") or t.get("name") or f"Torrent-{torrent_id}"
        size = t.get("file_size_bytes") or t.get("size") or t.get("file_size") or 0
        magnet = t.get("magnet_link", "")
        seeders = t.get("_seeders", "?")
        leechers = t.get("_leechers", "?")
        score = t.get("_score", 0)

        if not torrent_id or torrent_id in self._seen_ids:
            return False

        if self.max_size_bytes > 0 and size > self.max_size_bytes:
            return False

        size_str = self._format_size(size)

        if self.notify_only:
            self._seen_ids.add(torrent_id)
            is_fl = t.get("is_freeleech", False)
            tag = "FL " if is_fl else ""
            score_str = f" | Score: {score:.1f}" if score else ""
            print(f"[Torr9] {tag}{name[:50]} ({size_str}) S:{seeders} L:{leechers}{score_str}")
            if self.notifier:
                self.notifier.send(
                    f"{'🆓 <b>Freeleech' if is_fl else '📦 <b>Torrent'} Torr9</b>\n\n"
                    f"📦 <code>{name[:60]}</code>\n"
                    f"💾 {size_str} | 🌱 {seeders} seeds | 👥 {leechers} leechs\n"
                    f"🔗 <a href='https://torr9.net/torrents/{torrent_id}'>Voir</a>"
                )
            return True

        # Try .torrent download first, fallback to magnet
        torrent_bytes = self.download_torrent(torrent_id)
        if torrent_bytes:
            if self.add_to_qbittorrent(torrent_id, name, torrent_bytes, category):
                self._seen_ids.add(torrent_id)
                print(f"[Torr9] Added: {name[:50]} ({size_str}) S:{seeders} L:{leechers}")
                if self.notifier:
                    self.notifier.alert_freeleech_added(name, size_str)
                return True
        elif magnet:
            if self.add_by_magnet(magnet, category):
                self._seen_ids.add(torrent_id)
                print(f"[Torr9] Added (magnet): {name[:50]} ({size_str})")
                if self.notifier:
                    self.notifier.alert_freeleech_added(name, size_str)
                return True

        logger.warning(f"[Torr9] Failed to add {name[:40]}")
        return False

    def run_once(self) -> int:
        """Execute un cycle de chasse."""
        added = 0

        # Phase 1: Freeleech (top priority — free ratio)
        freeleech = self.fetch_freeleech()
        if freeleech:
            print(f"[Torr9] Found {len(freeleech)} freeleech torrent(s)")
            for t in freeleech:
                if added >= self.max_per_run:
                    break
                if self._process_torrent(t, "Freeleech-Torr9"):
                    added += 1

        # Phase 2: Smart Hunt (best seeder/leecher ratio)
        if self.smart_hunt and added < self.max_per_run:
            smart = self.fetch_smart()
            if smart:
                print(f"[Torr9] Smart Hunt: {len(smart)} torrent(s) with leechers found")
                for t in smart:
                    if added >= self.max_per_run:
                        break
                    if self._process_torrent(t, "Smart-Torr9"):
                        added += 1
            else:
                print("[Torr9] Smart Hunt: no torrents with active leechers found")

        # Phase 3: Popular (fallback, only if smart hunt found nothing)
        if self.hunt_popular and added < self.max_per_run and not self.smart_hunt:
            popular = self.fetch_popular()
            if popular:
                popular.sort(key=lambda x: x.get("file_size_bytes", 0) or 0, reverse=True)
                for t in popular:
                    if added >= self.max_per_run:
                        break
                    tid = t.get("id")
                    if tid in self._seen_ids:
                        continue
                    if self._process_torrent(t, "Popular-Torr9"):
                        added += 1

        if added == 0 and not freeleech:
            print("[Torr9] No new torrents to add this cycle.")

        return added

    def _loop(self):
        while not self._stop.is_set():
            try:
                added = self.run_once()
                print(f"[Torr9] Cycle done — {added} torrent(s) processed.")
            except Exception as e:
                logger.error(f"[Torr9] Unexpected error: {e}")
            self._stop.wait(self.interval_sec)

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Torr9Hunter")
        self._thread.start()
        mode = "Alert Only" if self.notify_only else "Auto-Download"
        modes = []
        if self.smart_hunt:
            modes.append("Smart")
        if self.hunt_popular:
            modes.append("Popular")
        hunt_str = " + ".join(["Freeleech"] + modes)
        print(f"[Torr9] {hunt_str} Hunter started ({mode}, every {self.interval_sec}s, max {self.max_per_run}/run)")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        print("[Torr9] Stopped.")


def build_torr9_hunter(config: dict, client, notifier=None):
    """Construit un Torr9Hunter depuis config.json."""
    torr9_cfg = config.get("torr9", {})
    if not torr9_cfg.get("enabled", False):
        return None
    jwt = torr9_cfg.get("jwt_token", "")
    if not jwt:
        logger.warning("[Torr9] No jwt_token configured — skipping.")
        return None
    return Torr9Hunter(
        jwt_token=jwt,
        client=client,
        notifier=notifier,
        interval_sec=torr9_cfg.get("interval_sec", 600),
        max_per_run=torr9_cfg.get("max_per_run", 5),
        notify_only=torr9_cfg.get("notify_only", True),
        hunt_popular=torr9_cfg.get("hunt_popular", False),
        smart_hunt=torr9_cfg.get("smart_hunt", True),
        max_size_gb=torr9_cfg.get("max_size_gb", 0),
    )
