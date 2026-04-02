# IGS - Intelligent Seeding Suite

Automated qBittorrent management, freeleech hunting, and ratio optimization for private trackers.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Edit config.json with your qBittorrent WebUI credentials

# 3. Start Beast Mode (one command to rule them all)
python main.py beast
```

Or for a more controlled approach:

```bash
# Apply performance + security settings (run once)
python main.py secure-boost

# Start normal automation engine
python main.py start

# Open the live dashboard
python main.py dashboard
```

---

## Philosophy: Swarm Mastery vs Ratio Spoofer

**Why IGS does not use "Ghost Seeding" or Ratio Spoofing:**

Classic tools like *Ratio Master* intercept network traffic to send false "uploaded 10 GB" HTTP requests to trackers. Today, elite trackers (like Torr9 or Ygg) use **Peer-Cross-Referencing** Anti-Cheats. If you claim to have uploaded 10 GB, but no real peers confirm receiving data from your IP, your account is permanently banned.

**The IGS Approach (0% Ban Risk):** 
IGS uses local **Swarm Mastery**. It injects extreme performance constraints into qBittorrent (such as 4000 connections and Fastest Download chokes) and aggressively dominates the swarm. By pausing competitors and forcing Super-Seeding, IGS genuinely transfers the data, making it 100% legitimate and impossible to ban, while skyrocketing your ratio.

---

## CLI Commands

| Command | Alias | Description |
|---|---|---|
| `python main.py beast` | | **BEAST MODE** — All rules ON, 60s cycles, 4000 connections, full throttle |
| `python main.py start` | | Run automation engine + freeleech hunters (foreground) |
| `python main.py status` | | Show live seeding stats |
| `python main.py dashboard` | | Launch Streamlit web UI at `http://localhost:8501` |
| `python main.py goal` | | Track progress toward the 1 TB Upload Goal with phase & ETA |
| `python main.py list` | `ls` | List all torrents with ratio/state |
| `python main.py add <target>` | | Add torrent by magnet, URL, or `.torrent` file |
| `python main.py remove <hash>` | `rm` | Remove torrent(s) (`--files` to also delete data) |
| `python main.py trackers` | | Per-tracker stats breakdown |
| `python main.py secure-boost` | | Inject performance + IP blocklist settings |

---

## Beast Mode (`python main.py beast`)

One command that turns IGS into an upload monster:

| What it does | Value |
|---|---|
| Max Global Connections | **4000** |
| Max Connections/Torrent | **1000** |
| Max Uploads | **750** |
| Half-Open Connections | **200** |
| Queue Limits | **DISABLED** (all torrents active) |
| DHT + PeX + LSD | **ENABLED** |
| All Speed Limits | **REMOVED** |
| Automation Interval | **60 seconds** |
| Rules Active | **15 rules** |
| IP Blocklist | **Active** |

Beast Mode also force-starts all seeders, resumes paused torrents, and sends a Telegram notification confirming activation.

---

## Automation Rules (15 Rules)

All rules run every 5 minutes in `start` mode (60s in `beast` mode). Each can be toggled individually in `config.json`.

### Core Rules (11)

| Rule | What it does |
|---|---|
| **UploadGoalRule** | 3-phase adaptive engine (**Cruise** / **Assault** / **Beast**) that escalates aggression as you approach the 1 TB target. Uncaps uploads, force-starts queued torrents, throttles/kills downloads, boosts connections to 3000, enables DHT/PeX/LSD, and resumes all paused seeders in Beast phase. |
| **RaceRule** | Enables Super-Seeding + forced reannounce on torrents < 2h old with leechers. |
| **ISPEvasionRule** | Toggles alternative speed limits during peak hours (default 18:00-23:00) to protect your home bandwidth. |
| **SniperRule** | Throttles low-demand torrents to free bandwidth for high-demand ones (3+ leechers). |
| **DictatorshipRule** | Pauses everything to focus 100% on a torrent where you're the sole seeder. |
| **HealingRule** | Detects tracker errors and forces reannounce to self-repair. |
| **AntiSpywareRule** | Scans torrent files for suspicious extensions (`.exe`, `.vbs`), pauses + tags `MALWARE-WARNING`. |
| **CleanupRule** | H&R-safe removal: won't delete until ratio >= 2.0 AND seeding time >= 72h. |
| **StaleSeederRule** | Pauses torrents idle > 48h with ratio >= 1.0. |
| **RatioGuardRule** | Tags torrents below 0.5 ratio as `low-ratio`. |
| **AutoCategoryRule** | Auto-categorize torrents by tracker hostname (disabled by default). |

### Beast Rules (4 new)

| Rule | What it does |
|---|---|
| **NightRaidRule** | Full throttle at night (00:00-07:00). Removes ALL speed limits, force-starts every torrent, reannounces periodically. Overrides ISP evasion during raid hours. |
| **SwarmDominatorRule** | Detects swarms where you are one of very few seeders (1-3) with many leechers. Enables Super-Seed, force-start, unlimited share ratio, and tags torrents `DOMINATED` for dashboard visibility. |
| **TrackerBoosterRule** | Injects 6 well-known public UDP trackers into every torrent to maximize peer discovery. Runs once per torrent. |
| **RevengeRule** | Identifies torrents where you downloaded a lot but have a bad ratio (< 0.5). Force-seeds them aggressively to recover ratio. Tags `REVENGE` and notifies when ratio is recovered. |

### Upload Goal Phases

| Phase | Trigger | Actions |
|---|---|---|
| **CRUISE** | 0-49% uploaded | Uncap all uploads, Super-Seed, periodic reannounce, remove global caps |
| **ASSAULT** | 50-79% | + Force-start queued, throttle downloads to 512 KB/s, boost connections to 3000, priority boost top torrents, enable DHT/PeX/LSD |
| **BEAST** | 80-100% | + Resume ALL paused seeders, kill all downloads, force reannounce every cycle, max peer discovery |

---

## Automation Engine

The engine now features:

- **Adaptive Intervals** — When many actions fire (10+), interval drops to 1/3 of base. Fewer actions = slower polling. This means IGS reacts faster when the swarm is active.
- **Daily Digest** — Sends a Telegram summary at 08:00 with total uploaded, ratio, seeding count, uptime, and cycle stats.
- **Cycle Stats** — Tracks total cycles and actions for monitoring.

---

## Freeleech Hunters

Automatically scrapes private trackers for new Freeleech content.

### Torr9 Hunter (`torr9_hunter.py`)
Dedicated hunter for torr9.net using their REST API with JWT authentication.
**Setup:**
1. Log into torr9.net, open DevTools (F12) > Network tab.
2. Find a request to `api.torr9.net` > copy the `Authorization: Bearer <TOKEN>`.
3. Paste the token in `config.json` under `torr9.jwt_token`.

**Modes:**
- `notify_only: true` (default) — Sends Telegram alerts containing the torrent link (no auto-download).
- `notify_only: false` — Auto-downloads the `.torrent` and imports it into qBittorrent under category `Freeleech-Torr9`.

### Generic Hunter (`freeleech_hunter.py`)
Scrapes any tracker's freeleech HTML page via configurable CSS selectors. Requires cookies and HTML path structures.

---

## Telegram Notifications

Get push alerts for critical events:
- Beast Mode activated
- Dictatorship mode engaged/ended
- Malware detected and paused
- Freeleech torrents found (Torr9)
- Upload Goal Milestones (25%, 50%, 75%, 100%)
- Night Raid engaged/ended
- Swarm dominated
- Revenge target ratio recovered
- Daily digest (08:00)

**Setup:**
1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram.
2. Send a message to your bot, then get your `chat_id` via `https://api.telegram.org/bot<TOKEN>/getUpdates`.
3. Add `bot_token` and `chat_id` to `config.json` under `telegram`.

---

## Dashboard

Dark-themed Streamlit dashboard (`python main.py dashboard`) with:
- **Upload Goal Phase Banner** — Shows current phase (Cruise/Assault/Beast) with active tactics
- **Live Alert Panel** — Dictatorship mode, malware, H&R pending, dominated swarms, revenge targets
- **5 Live Metrics** — Upload/download speed, global ratio, seeding count, ISP mode
- **Swarm Dominance Panel** — Table of dominated swarms with live stats
- **Revenge Targets Panel** — Table of ratio recovery targets
- **Per-Tracker Breakdown** — Upload totals grouped by tracker
- **Dual Historical Charts** — Total upload + upload speed over time
- **All Torrents Table** — Full torrent list with state badges

---

## qBittorrent Client (30+ API Methods)

The `QBitClient` wrapper now supports:
- Torrent management (add, pause, resume, delete, reannounce)
- Tracker management (add/remove trackers per torrent)
- Peer management (get peers, add peers, ban peers)
- Advanced control (force-start, priority, super-seeding, share limits)
- Speed limits (global + per-torrent upload/download)
- Application preferences (get/set all qBittorrent settings)
- Tags and categories

---

## Project Structure

```
IGS/
├── main.py              # CLI entry point (Click) — 12 commands including beast
├── automation.py        # 15 automation rules + adaptive engine
├── qbit_client.py       # qBittorrent WebAPI wrapper (30+ methods)
├── freeleech_hunter.py  # Generic tracker freeleech scraper
├── torr9_hunter.py      # Torr9.net dedicated freeleech hunter
├── notifier.py          # Telegram Bot API notifications
├── dashboard.py         # Streamlit web UI (dark theme, dual charts)
├── database.py          # SQLite stats storage
├── tracker_stats.py     # Analytics & formatting utilities
├── config.json          # Configuration (auto-generated on first run)
├── igs_stats.db         # Historical stats database (auto-created)
└── requirements.txt     # Python dependencies
```

---

## Configuration

Config defaults sample:

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
            "auto_category":     { "enabled": false, "tracker_map": {} },
            "upload_goal":       { "enabled": true, "target_tb": 1.0 },
            "night_raid":        { "enabled": true, "raid_start_hour": 0, "raid_end_hour": 7 },
            "swarm_dominator":   { "enabled": true, "max_seeders": 3, "min_leechers": 3 },
            "tracker_booster":   { "enabled": true },
            "revenge_rule":      { "enabled": true, "revenge_below_ratio": 0.5, "min_downloaded_mb": 100 }
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
