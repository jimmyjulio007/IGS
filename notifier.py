"""
IGS Notifier — Telegram push notifications for critical automation events.

Setup:
1. Create a bot via @BotFather on Telegram → get BOT_TOKEN
2. Send a message to your bot → get CHAT_ID via:
   https://api.telegram.org/bot<TOKEN>/getUpdates
3. Add both values to config.json under "telegram"
"""

import requests


class TelegramNotifier:
    """Sends push notifications to a Telegram chat via Bot API."""

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = str(chat_id)
        self._base = f"https://api.telegram.org/bot{token}"
        self.enabled = bool(token and chat_id)

    def send(self, message: str, silent: bool = False) -> bool:
        """Send a plain-text message. Returns True on success."""
        if not self.enabled:
            return False
        try:
            resp = requests.post(
                f"{self._base}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_notification": silent,
                },
                timeout=8,
            )
            return resp.status_code == 200
        except Exception:
            return False

    # ── Pre-built alert templates ──────────────────────────────────

    def alert_dictatorship(self, torrent_name: str, leechers: int, speed: str):
        self.send(
            f"👑 <b>DICTATORSHIP ENGAGED</b>\n\n"
            f"🎯 Torrent: <code>{torrent_name[:60]}</code>\n"
            f"👥 Leechers: <b>{leechers}</b>\n"
            f"⬆️ Speed: <b>{speed}</b>\n\n"
            f"All other torrents paused. 100% bandwidth focused."
        )

    def alert_dictatorship_ended(self, resumed: int):
        self.send(
            f"🕊️ <b>Dictatorship Ended</b>\n\n"
            f"Resumed <b>{resumed}</b> torrent(s). Normal seeding restored.",
            silent=True,
        )

    def alert_malware(self, torrent_name: str, filename: str):
        self.send(
            f"🚨 <b>MALWARE DETECTED — TORRENT PAUSED</b>\n\n"
            f"📦 Torrent: <code>{torrent_name[:60]}</code>\n"
            f"⚠️ Suspicious file: <code>{filename}</code>\n\n"
            f"Action: Torrent paused and tagged MALWARE-WARNING."
        )

    def alert_freeleech_added(self, torrent_name: str, size: str):
        self.send(
            f"✅ <b>Freeleech Auto-Added</b>\n\n"
            f"📥 <code>{torrent_name[:60]}</code>\n"
            f"💾 Size: <b>{size}</b>",
            silent=True,
        )

    def alert_ratio_guard(self, ratio: float):
        self.send(
            f"⚠️ <b>Low Global Ratio Warning</b>\n\n"
            f"📊 Current Ratio: <b>{ratio:.3f}</b>\n"
            f"Consider adding more seeding content.",
            silent=False,
        )


def load_notifier(config: dict) -> TelegramNotifier:
    """Build a TelegramNotifier from config dict. Returns a disabled notifier if not configured."""
    tg = config.get("telegram", {})
    return TelegramNotifier(
        token=tg.get("bot_token", ""),
        chat_id=tg.get("chat_id", ""),
    )
