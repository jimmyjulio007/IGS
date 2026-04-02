# IGS - Intelligent Seeding Suite

Automated qBittorrent management, freeleech hunting, and ratio optimization for private trackers.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Edit config.json with your qBittorrent WebUI credentials

# 3. Apply performance + security settings (run once)
python main.py secure-boost

# 4. Start the automation engine
python main.py start

# 5. Open the live dashboard
python main.py dashboard
```

---

## CLI Commands

| Command | Alias | Description |
|---|---|---|
| `python main.py start` | | Run automation engine + freeleech hunters (foreground) |
| `python main.py status` | | Show live seeding stats |
| `python main.py dashboard` | | Launch Streamlit web UI at `http://localhost:8501` |
| `python main.py list` | `ls` | List all torrents with ratio/state |
| `python main.py add <target>` | | Add torrent by magnet, URL, or `.torrent` file |
| `python main.py remove <hash>` | `rm` | Remove torrent(s) (`--files` to also delete data) |
| `python main.py trackers` | | Per-tracker stats breakdown |
| `python main.py secure-boost` | | Inject performance + IP blocklist settings |

---

## Automation Rules (10 Rules)

All rules run every 5 minutes (configurable). Each can be toggled individually in `config.json`.

| Rule | What it does |
|---|---|
| **RaceRule** | Enables Super-Seeding + forced reannounce on torrents < 2h old with leechers |
| **ISPEvasionRule** | Toggles alternative speed limits during peak hours (default 18:00-23:00) |
| **SniperRule** | Throttles low-demand torrents to free bandwidth for high-demand ones (3+ leechers) |
| **DictatorshipRule** | Pauses everything to focus 100% on a torrent where you're the sole seeder |
| **HealingRule** | Detects tracker errors and forces reannounce to self-repair |
| **AntiSpywareRule** | Scans torrent files for suspicious extensions (`.exe`, `.bat`, `.vbs`), pauses + tags `MALWARE-WARNING` |
| **CleanupRule** | H&R-safe removal: won't delete until ratio >= 2.0 AND seeding time >= 72h |
| **StaleSeederRule** | Pauses torrents idle > 48h with ratio >= 1.0 |
| **RatioGuardRule** | Tags torrents below 0.5 ratio as `low-ratio` |
| **AutoCategoryRule** | Auto-categorize torrents by tracker hostname (disabled by default) |

---

## Freeleech Hunters

### Generic Hunter (`freeleech_hunter`)

Scrapes any tracker's freeleech page via configurable CSS selectors. Requires:
- `freeleech_url` — page listing freeleech torrents
- `download_url_pattern` — URL template with `{torrent_id}`
- `cookies` — session cookies from your browser

### Torr9 Hunter (`torr9_hunter`)

Dedicated hunter for torr9.net using their REST API with JWT authentication.

**Setup:**
1. Log into torr9.net
2. Open DevTools (F12) > Network tab
3. Find a request to `api.torr9.net` > copy the `Authorization: Bearer <TOKEN>`
4. Paste the token in `config.json` under `torr9.jwt_token`

**Modes:**
- `notify_only: true` (default) — sends Telegram alerts only, no auto-download
- `notify_only: false` — auto-downloads freeleech torrents into qBittorrent with category `Freeleech-Torr9`

---

## Telegram Notifications

Get push alerts for critical events:
- Dictatorship mode engaged/ended
- Malware detected and paused
- Freeleech torrents found (Torr9)
- Low ratio warnings

**Setup:**
1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram
2. Send a message to your bot, then get your `chat_id` via `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Add `bot_token` and `chat_id` to `config.json` under `telegram`

---

## Secure Boost (`secure-boost`)

One-time command that injects optimized settings into qBittorrent:

| Setting | Value |
|---|---|
| Max Global Connections | 2000 |
| Max Connections/Torrent | 500 |
| Half-Open Connections | 100 |
| Choking Algorithm | Rate-Based (Fastest Download) |
| IP Blocklist | BT_BlockLists (gov + anti-piracy IPs) |

---

## Dashboard

Dark-themed Streamlit dashboard with:

- **Live Alert Panel** — Dictatorship mode, malware warnings, H&R pending status
- **5 Live Metrics** — Upload/download speed, global ratio, seeding count, ISP mode
- **Per-Tracker Breakdown** — Upload totals grouped by tracker
- **Historical Upload Chart** — Up to 30 days of data
- **Top Seeders Table** — Sorted by upload with state badges
- **All Torrents** — Expandable table with full details
- **Auto-refresh** — 30-second polling

---

## Project Structure

```
IGS/
├── main.py              # CLI entry point (Click)
├── automation.py        # 10 automation rules + engine
├── qbit_client.py       # qBittorrent WebAPI wrapper (20+ methods)
├── freeleech_hunter.py  # Generic tracker freeleech scraper
├── torr9_hunter.py      # Torr9.net dedicated freeleech hunter
├── notifier.py          # Telegram Bot API notifications
├── dashboard.py         # Streamlit web UI (dark theme)
├── database.py          # SQLite stats storage
├── tracker_stats.py     # Analytics & formatting utilities
├── config.json          # Configuration (auto-generated on first run)
├── igs_stats.db         # Historical stats database (auto-created)
└── requirements.txt     # Python dependencies
```

---

## Configuration

```json
{
    "qbittorrent": {
        "host": "http://localhost",
        "port": 8080,
        "username": "admin",
        "password": "adminadmin"
    },
    "automation": {
        "enabled": true,
        "interval_sec": 300,
        "rules": {
            "race_rule":         { "enabled": true, "max_age_hours": 2, "min_leechers": 1 },
            "isp_evasion":       { "enabled": true, "peak_start_hour": 18, "peak_end_hour": 23 },
            "sniper_rule":       { "enabled": true, "min_speed_kbps": 50, "demand_leechers": 3 },
            "dictatorship_rule": { "enabled": true, "trigger_leechers": 2 },
            "healing_rule":      { "enabled": true },
            "anti_spyware":      { "enabled": true },
            "stale_seeder":      { "enabled": true, "max_idle_hours": 48 },
            "cleanup":           { "enabled": true, "min_ratio": 2.0, "min_active_seed_hours": 72 },
            "ratio_guard":       { "enabled": true, "warn_ratio": 0.5 },
            "auto_category":     { "enabled": false, "tracker_map": {} }
        }
    },
    "telegram": {
        "bot_token": "",
        "chat_id": ""
    },
    "freeleech_hunter": {
        "enabled": false,
        "interval_sec": 600,
        "max_per_run": 5,
        "trackers": {}
    },
    "torr9": {
        "enabled": true,
        "jwt_token": "YOUR_JWT_TOKEN_HERE",
        "interval_sec": 600,
        "max_per_run": 5,
        "notify_only": true
    }
}
```

---

## Requirements

- Python 3.10+
- qBittorrent with WebUI enabled (Options > Web UI)
- Dependencies: `requests`, `click`, `streamlit`, `plotly`, `beautifulsoup4`
