# IGS - Intelligent Seeding Suite

Automated qBittorrent management, smart torrent hunting, and ratio optimization for private trackers.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Edit config.json with your qBittorrent WebUI credentials

# 3. IMPORTANT: Forward your listen port (see Network Setup below)

# 4. Start Beast Mode (one command to rule them all)
python main.py beast

# 5. Diagnose any issues
python main.py diagnose
```

---

## Network Setup (CRITICAL)

**If your port is not forwarded, upload will be near zero.** This is the single most important step.

Run `python main.py diagnose` to check your status. If it says `FIREWALLED`:

### Option 1: Enable UPnP (easiest)
1. Open qBittorrent WebUI > Options (gear icon) > Connection
2. Check **"Use UPnP / NAT-PMP port forwarding from my router"**
3. Save

### Option 2: Manual Port Forwarding
1. Note your listen port (shown in `diagnose` output, default: random)
2. Open your router admin page (usually `192.168.1.1`)
3. Find **Port Forwarding** / **NAT** section
4. Add rule: Port **TCP+UDP** > your PC's local IP
5. Save

### Security
- Only the BitTorrent port is exposed — peers cannot access your PC or files
- IGS activates an IP blocklist (government + anti-piracy IPs) via `secure-boost`
- The AntiSpywareRule scans torrents for malicious files (.exe, .vbs)
- Private trackers (Torr9) keep your torrents off public DHT

---

## Philosophy: Swarm Mastery vs Ratio Spoofer

**Why IGS does not use "Ghost Seeding" or Ratio Spoofing:**

Classic tools like *Ratio Master* send false "uploaded 10 GB" HTTP requests to trackers. Today, elite trackers (Torr9, Ygg) use **Peer-Cross-Referencing** Anti-Cheats. If you claim 10 GB uploaded but no real peers confirm it, your account is permanently banned.

**The IGS Approach (0% Ban Risk):**
IGS uses local **Swarm Mastery**. It injects extreme performance settings (4000 connections, rate-based choking) and uses smart hunting to find torrents where you'll dominate the swarm. By forcing Super-Seeding and targeting low-seeder/high-leecher swarms, IGS genuinely transfers data — 100% legitimate, impossible to ban, skyrocketing your ratio.

---

## CLI Commands

| Command | Alias | Description |
|---|---|---|
| `python main.py beast` | | **BEAST MODE** — All rules ON, 60s cycles, 4000 connections, full throttle |
| `python main.py diagnose` | | **Diagnostic** — Checks every bottleneck (firewall, leechers, limits, ports) |
| `python main.py start` | | Run automation engine + hunters (foreground) |
| `python main.py status` | | Show live seeding stats |
| `python main.py dashboard` | | Launch Streamlit web UI at `http://localhost:8501` |
| `python main.py goal` | | Track Upload Goal progress with phase & ETA |
| `python main.py list` | `ls` | List all torrents with ratio/state |
| `python main.py add <target>` | | Add torrent by magnet, URL, or `.torrent` file |
| `python main.py remove <hash>` | `rm` | Remove torrent(s) (`--files` to also delete data) |
| `python main.py trackers` | | Per-tracker stats breakdown |
| `python main.py secure-boost` | | Inject performance + IP blocklist settings |

---

## Diagnose Command

`python main.py diagnose` checks **every possible bottleneck** in one shot:

| Check | What it detects |
|---|---|
| **Firewall/NAT** | Port not forwarded = peers can't connect to you |
| **Leechers** | Zero leechers = nobody to upload to |
| **Speed limits** | Global caps, alt-speed mode, per-torrent caps |
| **Queue limits** | Torrents stuck in queue doing nothing |
| **Paused/Errored** | Inactive torrents |
| **DHT/PeX/LSD** | Peer discovery disabled |
| **Tracker errors** | Broken tracker connections |
| **Connection settings** | Low connection limits |

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
| Alt Speed Limits | **DISABLED** at launch |
| DHT + PeX + LSD | **ENABLED** |
| All Speed Limits | **REMOVED** |
| Automation Interval | **60 seconds** (adaptive) |
| IP Blocklist | **Active** |

Beast Mode also:
- Force-starts all seeders and resumes paused torrents
- Disables alt-speed if currently active
- Respects config for ISP evasion (can be disabled)
- Sends Telegram notification on activation

---

## Automation Rules (15 Rules)

All rules run every 5 minutes in `start` mode (60s in `beast` mode). Each toggleable in `config.json`.

### Core Rules (11)

| Rule | What it does |
|---|---|
| **UploadGoalRule** | 3-phase adaptive engine (**Cruise** / **Assault** / **Beast**) that escalates aggression as you approach the 1 TB target |
| **RaceRule** | Super-Seeding + forced reannounce on torrents < 2h old with leechers |
| **ISPEvasionRule** | Toggles alt speed limits during peak hours (default 18:00-23:00) |
| **SniperRule** | Throttles low-demand torrents to free bandwidth for high-demand ones |
| **DictatorshipRule** | Pauses everything to focus 100% on a torrent where you're the sole seeder |
| **HealingRule** | Detects tracker errors and forces reannounce to self-repair |
| **AntiSpywareRule** | Scans for suspicious extensions (.exe, .vbs), pauses + tags `MALWARE-WARNING` |
| **CleanupRule** | H&R-safe removal: ratio >= 2.0 AND seeding time >= 72h required |
| **StaleSeederRule** | Pauses torrents idle > 48h with ratio >= 1.0 |
| **RatioGuardRule** | Tags torrents below 0.5 ratio as `low-ratio` |
| **AutoCategoryRule** | Auto-categorize by tracker hostname (disabled by default) |

### Beast Rules (4)

| Rule | What it does |
|---|---|
| **NightRaidRule** | Full throttle at night (00:00-07:00). Removes ALL limits, force-starts everything |
| **SwarmDominatorRule** | Detects swarms where you're one of few seeders with many leechers. Super-Seed + force-start + unlimited ratio. Tags `DOMINATED` |
| **TrackerBoosterRule** | Injects 6 public UDP trackers for peer discovery. **Skips private torrents** (useless on private trackers) |
| **RevengeRule** | Force-seeds torrents where your ratio < 0.5. Tags `REVENGE`, notifies when recovered |

### Upload Goal Phases

| Phase | Trigger | Actions |
|---|---|---|
| **CRUISE** | 0-49% | Uncap uploads, Super-Seed, periodic reannounce |
| **ASSAULT** | 50-79% | + Force-start queued, throttle DL to 512 KB/s, boost connections to 3000, enable DHT/PeX/LSD |
| **BEAST** | 80-100% | + Resume ALL paused seeders, kill downloads, reannounce every cycle |

---

## Torr9 Smart Hunter

The Torr9 Hunter has 3 hunting modes, executed in priority order:

### 1. Freeleech Hunt (Priority 1)
Targets torrents marked `is_freeleech=True`. Download doesn't count against your ratio = free upload.

### 2. Smart Hunt (Priority 2)
Queries the Torr9 API for each torrent's **seeders and leechers count**, then scores them:

```
Score = leechers / (seeders + 1) x size_factor
```

High score = few seeders + many leechers + decent size = **guaranteed upload**.

Example Smart Hunt output:
```
Score | Seeds | Leechs | Size     | Name
  2.9 |     1 |      4 |  5.8 GB  | A.Thousand.Blows.S01
  1.8 |     1 |      3 |  1.2 GB  | Planet.Terror.2007
  0.7 |     1 |      4 |  373 MB  | Maid.Sama.T05
```

A torrent with 1 seeder and 4 leechers means you take **50% of all upload**. Compare with XO Kitty (166 seeders, 3 leechers) where you get almost nothing.

### 3. Popular Hunt (Fallback)
Fetches recent torrents sorted by size. Used when Smart Hunt is disabled.

### Configuration

```json
"torr9": {
    "enabled": true,
    "notify_only": true,       // true = alert only, false = auto-download
    "smart_hunt": true,        // Score torrents by seeder/leecher ratio
    "hunt_popular": false,     // Fallback: recent torrents by size
    "max_size_gb": 8.0,        // Skip torrents larger than this
    "max_per_run": 2,          // Max torrents added per cycle
    "interval_sec": 600        // Check every 10 minutes
}
```

### Setup
1. Log into torr9.net, open DevTools (F12) > Network tab
2. Find a request to `api.torr9.net` > copy the `Authorization: Bearer <TOKEN>`
3. Paste the token in `config.json` under `torr9.jwt_token`

---

## Key Concepts: How Upload Works

```
1. Download a torrent    →  You now have the file
2. qBittorrent seeds it  →  Tracker announces you as a seeder
3. Leechers connect      →  They request pieces from you
4. You send pieces       →  Your upload counter increases
5. Ratio = upload / download
```

**No leechers = no upload.** IGS solves this with Smart Hunt (finds torrents with active leechers) and Swarm Dominator (maximizes upload on low-seeder swarms).

**Freeleech** torrents are special: download doesn't count, but upload does. Pure ratio gain.

**Private torrents** (Torr9) disable DHT/PeX/LSD — only the official tracker works. Public tracker injection (TrackerBoosterRule) is automatically skipped for private torrents.

---

## Automation Engine

- **Adaptive Intervals** — 10+ actions = interval drops to 1/3. Fewer actions = slower polling
- **Daily Digest** — Telegram summary at 08:00 (total uploaded, ratio, seeding count, uptime)
- **Cycle Stats** — Tracks total cycles and actions

---

## Telegram Notifications

Push alerts for:
- Beast Mode activated
- Dictatorship mode engaged/ended
- Malware detected and paused
- Freeleech torrents found
- Upload Goal Milestones (25%, 50%, 75%, 100%)
- Night Raid engaged/ended
- Swarm dominated
- Revenge target ratio recovered
- Daily digest (08:00)

**Setup:**
1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram
2. Send a message to your bot, get `chat_id` via `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Add `bot_token` and `chat_id` to `config.json` under `telegram`

---

## Dashboard

Dark-themed Streamlit dashboard (`python main.py dashboard`):
- **Upload Goal Phase Banner** — Current phase (Cruise/Assault/Beast) with active tactics
- **Live Alert Panel** — Dictatorship, malware, H&R pending, dominated swarms, revenge targets
- **5 Live Metrics** — Upload/download speed, global ratio, seeding count, ISP mode
- **Swarm Dominance Panel** — Dominated swarms with live stats
- **Revenge Targets Panel** — Ratio recovery targets
- **Per-Tracker Breakdown** — Upload totals by tracker
- **Dual Historical Charts** — Total upload + upload speed over time
- **All Torrents Table** — Full list with state badges

---

## qBittorrent Client (30+ API Methods)

The `QBitClient` wrapper supports:
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
├── main.py              # CLI entry point (Click) — 12 commands including beast & diagnose
├── automation.py        # 15 automation rules + adaptive engine
├── qbit_client.py       # qBittorrent WebAPI wrapper (30+ methods)
├── freeleech_hunter.py  # Generic tracker freeleech scraper
├── torr9_hunter.py      # Torr9.net smart hunter (freeleech + smart + popular)
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
            "isp_evasion":       { "enabled": false },
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
            "swarm_dominator":   { "enabled": true, "max_seeders": 3, "min_leechers": 1 },
            "tracker_booster":   { "enabled": true },
            "revenge_rule":      { "enabled": true, "revenge_below_ratio": 0.5, "min_downloaded_mb": 50 }
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
        "notify_only": true,
        "smart_hunt": true,
        "hunt_popular": false,
        "max_size_gb": 8.0,
        "max_per_run": 2,
        "jwt_token": "YOUR_JWT_TOKEN_HERE",
        "interval_sec": 600
    }
}
```

---

## Requirements

- Python 3.10+
- qBittorrent with WebUI enabled (Options > Web UI)
- **Port forwarded** (UPnP or manual — run `diagnose` to check)
- Dependencies: `requests`, `click`, `streamlit`, `plotly`, `beautifulsoup4`
