"""qBittorrent WebAPI client wrapper — Beast Edition."""

import json
import requests


class QBitClient:
    """Communicates with qBittorrent's WebAPI (v2.x)."""

    def __init__(self, host="http://localhost", port=8080, username="admin", password="adminadmin"):
        self.base_url = f"{host}:{port}/api/v2"
        self.session = requests.Session()
        self.authenticated = False
        self._login(username, password)

    def _login(self, username, password):
        resp = self.session.post(f"{self.base_url}/auth/login", data={
            "username": username,
            "password": password,
        })
        if resp.text == "Ok.":
            self.authenticated = True
        else:
            raise ConnectionError(f"Failed to authenticate with qBittorrent: {resp.text}")

    def _get(self, endpoint, **params):
        resp = self.session.get(f"{self.base_url}/{endpoint}", params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, endpoint, **data):
        resp = self.session.post(f"{self.base_url}/{endpoint}", data=data)
        resp.raise_for_status()
        return resp

    # ── Torrent Info ──────────────────────────────────────────────

    def get_torrents(self, filter_status=None, category=None, sort=None, tag=None):
        """List all torrents, optionally filtered."""
        params = {}
        if filter_status:
            params["filter"] = filter_status
        if category:
            params["category"] = category
        if sort:
            params["sort"] = sort
        if tag:
            params["tag"] = tag
        return self._get("torrents/info", **params)

    def get_torrent(self, torrent_hash):
        """Get details for a single torrent."""
        torrents = self._get("torrents/info", hashes=torrent_hash)
        return torrents[0] if torrents else None

    def get_trackers(self, torrent_hash):
        """Get tracker list for a torrent."""
        return self._get("torrents/trackers", hash=torrent_hash)

    def get_torrent_files(self, torrent_hash):
        """Get contents (files) of a specific torrent."""
        return self._get("torrents/files", hash=torrent_hash)

    def get_torrent_properties(self, torrent_hash):
        """Get detailed properties for a torrent (creation date, piece size, etc)."""
        return self._get("torrents/properties", hash=torrent_hash)

    # ── Transfer & Speed Limits ───────────────────────────────────

    def get_global_transfer_info(self):
        """Get global upload/download speed and totals."""
        return self._get("transfer/info")

    def toggle_speed_limits_mode(self):
        """Toggle between Global and Alternative speed limits."""
        self._post("transfer/toggleSpeedLimitsMode")

    def get_speed_limits_mode(self):
        """Returns 1 if Alternative Mode is enabled, 0 if Global Mode."""
        info = self.get_global_transfer_info()
        return info.get("use_alt_speed_limits", 0)

    def set_global_upload_limit(self, limit_bytes):
        """Set global upload speed limit. 0 = unlimited."""
        self._post("transfer/setUploadLimit", limit=limit_bytes)

    def set_global_download_limit(self, limit_bytes):
        """Set global download speed limit. 0 = unlimited."""
        self._post("transfer/setDownloadLimit", limit=limit_bytes)

    # ── Torrent Actions ───────────────────────────────────────────

    def add_torrent(self, urls=None, torrent_file=None, category=None, paused=False):
        """Add torrent(s) by URL/magnet or file path."""
        data = {"paused": "true" if paused else "false"}
        files = None

        if urls:
            data["urls"] = urls if isinstance(urls, str) else "\n".join(urls)
        if category:
            data["category"] = category

        if torrent_file:
            import os
            filename = os.path.basename(torrent_file)
            with open(torrent_file, "rb") as f:
                content = f.read()
            files = {"torrents": (filename, content, "application/x-bittorrent")}
            resp = self.session.post(f"{self.base_url}/torrents/add", data=data, files=files)
        else:
            resp = self.session.post(f"{self.base_url}/torrents/add", data=data)

        resp.raise_for_status()
        return resp.text == "Ok."

    def pause(self, hashes):
        """Pause torrents. Use 'all' for everything."""
        self._post("torrents/pause", hashes=hashes)

    def resume(self, hashes):
        """Resume torrents. Use 'all' for everything."""
        self._post("torrents/resume", hashes=hashes)

    def delete(self, hashes, delete_files=False):
        """Delete torrents. Optionally remove files from disk."""
        self._post("torrents/delete", hashes=hashes,
                   deleteFiles="true" if delete_files else "false")

    def reannounce(self, hashes):
        """Force reannounce to trackers."""
        self._post("torrents/reannounce", hashes=hashes)

    def set_category(self, hashes, category):
        """Assign a category to torrents."""
        self._post("torrents/setCategory", hashes=hashes, category=category)

    def add_tags(self, hashes, tags):
        """Add tags to torrents."""
        tag_str = tags if isinstance(tags, str) else ",".join(tags)
        self._post("torrents/addTags", hashes=hashes, tags=tag_str)

    def remove_tags(self, hashes, tags):
        """Remove tags from torrents."""
        tag_str = tags if isinstance(tags, str) else ",".join(tags)
        self._post("torrents/removeTags", hashes=hashes, tags=tag_str)

    def set_super_seeding(self, hashes, value=True):
        """Toggle super seeding mode for given torrents."""
        self._post("torrents/setSuperSeeding", hashes=hashes, value="true" if value else "false")

    def set_upload_limit(self, hashes, limit_bytes):
        """Set individual upload limit for torrent(s). Set to 0 for unlimited."""
        self._post("torrents/setUploadLimit", hashes=hashes, limit=limit_bytes)

    def set_download_limit(self, hashes, limit_bytes):
        """Set individual download limit for torrent(s). Set to 0 for unlimited."""
        self._post("torrents/setDownloadLimit", hashes=hashes, limit=limit_bytes)

    # ── Tracker Management ────────────────────────────────────────

    def add_trackers(self, torrent_hash, urls):
        """Add tracker URLs to a torrent. urls: list of tracker URLs or newline-separated string."""
        if isinstance(urls, list):
            urls = "\n".join(urls)
        self._post("torrents/addTrackers", hash=torrent_hash, urls=urls)

    def remove_trackers(self, torrent_hash, urls):
        """Remove tracker URLs from a torrent."""
        if isinstance(urls, list):
            urls = "|".join(urls)
        self._post("torrents/removeTrackers", hash=torrent_hash, urls=urls)

    # ── Peer Management ───────────────────────────────────────────

    def get_peer_data(self, torrent_hash):
        """Get connected peers for a torrent."""
        try:
            return self._get("sync/torrentPeers", hash=torrent_hash)
        except Exception:
            return {}

    def add_peers(self, hashes, peers):
        """Manually add peers to torrent(s). peers: list of 'host:port' strings."""
        peer_str = "|".join(peers) if isinstance(peers, list) else peers
        self._post("torrents/addPeers", hashes=hashes, peers=peer_str)

    def ban_peers(self, peers):
        """Ban peers by IP. peers: list of 'host:port' strings."""
        peer_str = "|".join(peers) if isinstance(peers, list) else peers
        self._post("transfer/banPeers", peers=peer_str)

    # ── Advanced Torrent Control ─────────────────────────────────

    def set_force_start(self, hashes, value=True):
        """Force start torrents, bypassing queue limits."""
        self._post("torrents/setForceStart", hashes=hashes, value="true" if value else "false")

    def set_torrent_priority(self, hashes, priority):
        """Set torrent priority. priority: 'increasePrio', 'decreasePrio', 'topPrio', 'bottomPrio'."""
        self._post(f"torrents/{priority}", hashes=hashes)

    def set_share_limits(self, hashes, ratio_limit=-2, seeding_time_limit=-2):
        """Set share ratio/time limits. -2=global, -1=unlimited, 0+=value."""
        self._post("torrents/setShareLimits", hashes=hashes,
                   ratioLimit=ratio_limit, seedingTimeLimit=seeding_time_limit)

    # ── Application Preferences ───────────────────────────────────

    def get_preferences(self):
        """Get application preferences."""
        return self._get("app/preferences")

    def set_preferences(self, prefs: dict):
        """Set application preferences."""
        self._post("app/setPreferences", json=json.dumps(prefs))

    # ── Categories ────────────────────────────────────────────────

    def get_categories(self):
        return self._get("torrents/categories")

    def create_category(self, name, save_path=""):
        self._post("torrents/createCategory", category=name, savePath=save_path)

    # ── App Info ──────────────────────────────────────────────────

    def get_app_version(self):
        resp = self.session.get(f"{self.base_url}/app/version")
        return resp.text
