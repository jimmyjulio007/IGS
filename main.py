"""IGS - Intelligent Seeding Suite: CLI entry point."""

import json
import os
import click
from qbit_client import QBitClient
from automation import (
    AutomationEngine, StaleSeederRule, CleanupRule, AutoCategoryRule,
    RatioGuardRule, RaceRule, ISPEvasionRule, SniperRule, DictatorshipRule,
    HealingRule, AntiSpywareRule, UploadGoalRule, NightRaidRule,
    SwarmDominatorRule, TrackerBoosterRule, RevengeRule,
)
from notifier import load_notifier
from tracker_stats import print_summary, format_bytes
from database import init_db

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_CONFIG = {
    "qbittorrent": {
        "host": "http://localhost",
        "port": 8080,
        "username": "admin",
        "password": "adminadmin"
    },
    "automation": {
        "enabled": True,
        "interval_sec": 300,
        "rules": {
            "race_rule": {"enabled": True, "max_age_hours": 2, "min_leechers": 1},
            "isp_evasion": {"enabled": True, "peak_start_hour": 18, "peak_end_hour": 23},
            "sniper_rule": {"enabled": True, "min_speed_kbps": 50, "demand_leechers": 3},
            "dictatorship_rule": {"enabled": True, "trigger_leechers": 2},
            "healing_rule": {"enabled": True},
            "anti_spyware": {"enabled": True},
            "stale_seeder": {"enabled": True, "max_idle_hours": 48},
            "cleanup": {"enabled": True, "min_ratio": 2.0, "min_active_seed_hours": 72},
            "ratio_guard": {"enabled": True, "warn_ratio": 0.5},
            "auto_category": {"enabled": False, "tracker_map": {}},
            "upload_goal": {"enabled": True, "target_tb": 1.0},
            "night_raid": {"enabled": True, "raid_start_hour": 0, "raid_end_hour": 7},
            "swarm_dominator": {"enabled": True, "max_seeders": 3, "min_leechers": 3},
            "tracker_booster": {"enabled": True},
            "revenge_rule": {"enabled": True, "revenge_below_ratio": 0.5, "min_downloaded_mb": 100}
        }
    },
    "telegram": {
        "bot_token": "",
        "chat_id": ""
    },
    "freeleech_hunter": {
        "enabled": False,
        "interval_sec": 600,
        "max_per_run": 5,
        "trackers": {}
    }
}


def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        click.secho(f"[*] Created default config: {CONFIG_FILE}. Edit it with your qBittorrent settings.", fg="yellow")
        return DEFAULT_CONFIG
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def make_client(config):
    qb = config["qbittorrent"]
    return QBitClient(
        host=qb["host"],
        port=qb["port"],
        username=qb["username"],
        password=qb["password"],
    )


def make_rules(config, notifier=None):
    rules_cfg = config.get("automation", {}).get("rules", {})
    rules = []

    rr = rules_cfg.get("race_rule", {})
    if rr.get("enabled", True):
        rules.append(RaceRule(max_age_hours=rr.get("max_age_hours", 2), min_leechers=rr.get("min_leechers", 1)))

    isp = rules_cfg.get("isp_evasion", {})
    if isp.get("enabled", True):
        rules.append(ISPEvasionRule(peak_start_hour=isp.get("peak_start_hour", 18), peak_end_hour=isp.get("peak_end_hour", 23)))

    sr = rules_cfg.get("sniper_rule", {})
    if sr.get("enabled", True):
        rules.append(SniperRule(min_speed_kbps=sr.get("min_speed_kbps", 50), demand_leechers=sr.get("demand_leechers", 3)))

    dr = rules_cfg.get("dictatorship_rule", {})
    if dr.get("enabled", True):
        rules.append(DictatorshipRule(trigger_leechers=dr.get("trigger_leechers", 2), notifier=notifier))

    hr = rules_cfg.get("healing_rule", {})
    if hr.get("enabled", True):
        rules.append(HealingRule())

    asr = rules_cfg.get("anti_spyware", {})
    if asr.get("enabled", True):
        rules.append(AntiSpywareRule(notifier=notifier))

    sc = rules_cfg.get("stale_seeder", {})
    if sc.get("enabled", True):
        rules.append(StaleSeederRule(max_idle_hours=sc.get("max_idle_hours", 48)))

    cc = rules_cfg.get("cleanup", {})
    if cc.get("enabled", True):
        rules.append(CleanupRule(
            min_ratio=cc.get("min_ratio", 2.0), 
            min_active_seed_hours=cc.get("min_active_seed_hours", 72)
        ))

    rg = rules_cfg.get("ratio_guard", {})
    if rg.get("enabled", True):
        rules.append(RatioGuardRule(warn_ratio=rg.get("warn_ratio", 0.5)))

    ac = rules_cfg.get("auto_category", {})
    if ac.get("enabled", False):
        rules.append(AutoCategoryRule(tracker_map=ac.get("tracker_map", {})))

    ug = rules_cfg.get("upload_goal", {})
    if ug.get("enabled", True):
        target_bytes = int(ug.get("target_tb", 1.0) * 1024**4)
        rules.append(UploadGoalRule(target_bytes=target_bytes, notifier=notifier))

    nr = rules_cfg.get("night_raid", {})
    if nr.get("enabled", True):
        rules.append(NightRaidRule(
            raid_start_hour=nr.get("raid_start_hour", 0),
            raid_end_hour=nr.get("raid_end_hour", 7),
            notifier=notifier,
        ))

    sd = rules_cfg.get("swarm_dominator", {})
    if sd.get("enabled", True):
        rules.append(SwarmDominatorRule(
            max_seeders=sd.get("max_seeders", 3),
            min_leechers=sd.get("min_leechers", 3),
            notifier=notifier,
        ))

    tb = rules_cfg.get("tracker_booster", {})
    if tb.get("enabled", True):
        rules.append(TrackerBoosterRule())

    rv = rules_cfg.get("revenge_rule", {})
    if rv.get("enabled", True):
        rules.append(RevengeRule(
            revenge_below_ratio=rv.get("revenge_below_ratio", 0.5),
            min_downloaded_mb=rv.get("min_downloaded_mb", 100),
            notifier=notifier,
        ))

    return rules


@click.group()
def cli():
    """IGS - Intelligent Seeding Suite

    Manage your seedbox, automate torrent tasks, and track your ratio.
    """
    init_db()


@cli.command()
def status():
    """Show live seeding stats from qBittorrent."""
    config = load_config()
    client = make_client(config)
    print_summary(client)


@cli.command()
def start():
    """Start the automation engine (runs in foreground)."""
    config = load_config()
    client = make_client(config)
    notifier = load_notifier(config)
    rules = make_rules(config, notifier=notifier)
    interval = config.get("automation", {}).get("interval_sec", 300)

    click.secho("=" * 50, fg="cyan")
    click.secho("  IGS - Intelligent Seeding Suite", fg="cyan", bold=True)
    click.secho("=" * 50, fg="cyan")
    click.echo(f"  qBittorrent: {config['qbittorrent']['host']}:{config['qbittorrent']['port']}")
    click.echo(f"  Version: {client.get_app_version()}")
    click.echo(f"  Rules: {len(rules)} active | Interval: {interval}s")
    if notifier.enabled:
        click.secho("  📱 Telegram: ACTIVE", fg="green")
    else:
        click.secho("  📱 Telegram: Not configured (add bot_token + chat_id to config.json)", dim=True)
    click.echo("=" * 50)

    engine = AutomationEngine(client, rules=rules, interval_sec=interval, notifier=notifier)
    engine.start()

    # Start Freeleech Hunter if configured
    fh_cfg = config.get("freeleech_hunter", {})
    fh_instance = None
    if fh_cfg.get("enabled", False):
        from freeleech_hunter import FreeleechHunter, build_profiles
        profiles = build_profiles(config)
        if profiles:
            fh_instance = FreeleechHunter(
                client=client,
                profiles=profiles,
                interval_sec=fh_cfg.get("interval_sec", 600),
                notifier=notifier,
                max_per_run=fh_cfg.get("max_per_run", 5),
            )
            fh_instance.start()

    click.echo("[*] Automation running. Press Ctrl+C to stop.")

    # Start Torr9 Freeleech Hunter if configured
    from torr9_hunter import build_torr9_hunter
    torr9_instance = None
    torr9_instance = build_torr9_hunter(config, client, notifier=notifier)
    if torr9_instance:
        mode = "🔔 Alert Only" if torr9_instance.notify_only else "⬇️ Auto-Download"
        torr9_instance.start()
        click.secho(f"  🔍 Torr9 Hunter: ACTIVE ({mode})", fg="green")
    else:
        click.secho("  🔍 Torr9 Hunter: Not configured (add torr9.jwt_token to config.json)", dim=True)

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop()
        if fh_instance:
            fh_instance.stop()
        if torr9_instance:
            torr9_instance.stop()
        click.echo("[*] Stopped.")


@cli.command()
@click.option("--target-tb", default=None, type=float, help="Override target in TB (default: from config)")
def goal(target_tb):
    """Show upload goal progress and estimated time to reach 1 TB."""
    config = load_config()
    client = make_client(config)

    ug_cfg = config.get("automation", {}).get("rules", {}).get("upload_goal", {})
    target_tb = target_tb or ug_cfg.get("target_tb", 1.0)
    target_bytes = int(target_tb * 1024**4)

    torrents = client.get_torrents()
    transfer = client.get_global_transfer_info()

    total_uploaded = sum(t.get("uploaded", 0) for t in torrents)
    up_speed = transfer.get("up_info_speed", 0)  # bytes/sec

    pct = min((total_uploaded / target_bytes) * 100, 100.0)
    remaining = max(target_bytes - total_uploaded, 0)

    bar_filled = int(pct / 5)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    # Determine phase
    if pct >= 80:
        phase, phase_icon, phase_color = "BEAST", "🔥", "red"
    elif pct >= 50:
        phase, phase_icon, phase_color = "ASSAULT", "⚔️", "yellow"
    else:
        phase, phase_icon, phase_color = "CRUISE", "🚢", "cyan"

    click.secho("\n  🎯 IGS — Upload Goal Tracker", fg="cyan", bold=True)
    click.secho("  " + "─" * 42, fg="cyan")
    click.secho(f"  Phase   : {phase_icon} {phase}", fg=phase_color, bold=True)
    click.echo(f"  Target  : {target_tb:.1f} TB  ({format_bytes(target_bytes)})")
    click.echo(f"  Uploaded: {format_bytes(total_uploaded)}")
    click.echo(f"  Speed   : {format_bytes(up_speed)}/s")
    click.secho(f"\n  [{bar}] {pct:.1f}%\n", fg="green" if pct >= 100 else "yellow")

    if pct >= 100:
        click.secho("  🏆 GOAL REACHED! Congratulations!", fg="green", bold=True)
    elif up_speed > 0:
        eta_seconds = remaining / up_speed
        if eta_seconds < 3600:
            eta_str = f"{eta_seconds/60:.0f} minutes"
        elif eta_seconds < 86400:
            eta_str = f"{eta_seconds/3600:.1f} hours"
        else:
            eta_str = f"{eta_seconds/86400:.1f} days"
        click.secho(f"  ETA     : ~{eta_str} at current speed", fg="cyan")
    else:
        click.secho("  ETA     : No active upload speed detected (nothing seeding?)", fg="red")
    click.echo()


@cli.command("list")
def list_torrents():
    """List all torrents with their stats."""
    config = load_config()
    client = make_client(config)
    torrents = client.get_torrents(sort="uploaded")

    if not torrents:
        click.echo("No torrents found.")
        return

    click.echo(f"{'Name':<40} {'Size':>10} {'Uploaded':>12} {'Ratio':>8} {'State':<12}")
    click.echo("-" * 86)
    for t in torrents:
        click.echo(
            f"{t['name'][:39]:<40} "
            f"{format_bytes(t.get('size', 0)):>10} "
            f"{format_bytes(t.get('uploaded', 0)):>12} "
            f"{t.get('ratio', 0):>8.2f} "
            f"{t.get('state', '?'):<12}"
        )


@cli.command()
@click.argument("target")
def add(target):
    """Add a torrent by magnet link, URL, or .torrent file path."""
    config = load_config()
    client = make_client(config)

    if os.path.isfile(target):
        success = client.add_torrent(torrent_file=target)
    else:
        success = client.add_torrent(urls=target)

    if success:
        click.secho("[+] Added successfully.", fg="green")
    else:
        click.secho("[!] Failed to add torrent.", fg="red")


@cli.command()
@click.argument("hashes")
@click.option("--files", is_flag=True, help="Also delete downloaded files")
def remove(hashes, files):
    """Remove torrent(s) by hash. Use 'all' for everything."""
    config = load_config()
    client = make_client(config)
    client.delete(hashes, delete_files=files)
    click.secho(f"[+] Removed: {hashes}", fg="green")


@cli.command()
def trackers():
    """Show per-tracker stats breakdown."""
    from tracker_stats import get_tracker_breakdown
    config = load_config()
    client = make_client(config)
    breakdown = get_tracker_breakdown(client)

    click.echo(f"{'Tracker':<30} {'Torrents':>8} {'Seeding':>8} {'Uploaded':>12} {'Ratio':>8}")
    click.echo("-" * 70)
    for host, s in sorted(breakdown.items(), key=lambda x: x[1]["uploaded"], reverse=True):
        click.echo(
            f"{host[:29]:<30} "
            f"{s['count']:>8} "
            f"{s['seeding']:>8} "
            f"{format_bytes(s['uploaded']):>12} "
            f"{s['ratio']:>8.2f}"
        )


@cli.command()
def dashboard():
    """Launch the Streamlit web dashboard."""
    import subprocess
    import sys
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.py")
    click.echo("[*] Launching dashboard at http://localhost:8501 ...")
    subprocess.run([sys.executable, "-m", "streamlit", "run", dashboard_path])

@cli.command()
def secure_boost():
    """Apply extreme connection limits and activate anti-spy IP blocklist."""
    click.secho(f"🚀 Activating Swarm Brute-Forcing & Security Shield...", fg="cyan", bold=True)
    config = load_config()
    client = make_client(config)
    
    # High-performance blocklist from github (auto-updated daily by maintainers)
    blocklist_url = "https://github.com/Naunter/BT_BlockLists/raw/master/bt_blocklists.gz"
    
    prefs = {
        # 1. Swarm Penetration (Extreme limits)
        "max_conns": 2000,
        "max_conns_per_torrent": 500,
        "max_uploads": 250,
        "max_uploads_per_torrent": 50,
        "max_half_open_connections": 100,
        
        # 2. Tit-for-Tat aggression (1 = Rate-based algorithm)
        "choking_algorithm": 1,
        
        # 3. Security Shield (IP blocklist)
        "ip_filter_enabled": True,
        "ip_filter_path": blocklist_url,
        "ip_filter_trackers": True # Also block malicious trackers
    }
    
    try:
        client.set_preferences(prefs)
        click.secho("✅ Limits pushed: Max Connections (2000), Half-Open (100).", fg="green")
        click.secho("✅ Algorithm overridden: Rate-based Choking (Fastest Download).", fg="green")
        click.secho(f"🛡️  Security Shield Active: IP Blocklist injected.", fg="green")
        click.secho(f"   (URL: {blocklist_url})", dim=True)
        click.secho("\nYour qBittorrent is now configured to vacuum swarms safely.", fg="green", bold=True)
    except Exception as e:
        click.secho(f"❌ Failed to push optimize payload to qBittorrent: {e}", fg="red")

@cli.command()
def diagnose():
    """Diagnose why upload isn't increasing — checks every possible bottleneck."""
    config = load_config()
    client = make_client(config)

    click.secho("\n  🔍 IGS — Upload Diagnostic Report", fg="cyan", bold=True)
    click.secho("  " + "═" * 50, fg="cyan")

    issues = []
    warnings = []
    good = []

    # 1. Connection check
    try:
        version = client.get_app_version()
        good.append(f"qBittorrent connected (v{version})")
    except Exception as e:
        issues.append(f"Cannot connect to qBittorrent: {e}")
        click.secho("\n  CRITICAL: Cannot reach qBittorrent. Fix connection first.", fg="red", bold=True)
        return

    # 2. Get all data
    torrents = client.get_torrents()
    transfer = client.get_global_transfer_info()
    prefs = client.get_preferences()

    # 3. Check if any torrents exist
    if not torrents:
        issues.append("No torrents loaded! Add torrents to start uploading.")
        click.secho("\n  CRITICAL: No torrents in qBittorrent. Add content first.", fg="red", bold=True)
        return

    # 4. Torrent state analysis
    seeding = [t for t in torrents if t.get("state") in ("uploading", "stalledUP", "forcedUP")]
    paused = [t for t in torrents if t.get("state") in ("pausedUP", "pausedDL")]
    queued = [t for t in torrents if t.get("state") in ("queuedUP", "queuedDL")]
    errored = [t for t in torrents if t.get("state") == "error"]
    downloading = [t for t in torrents if t.get("state") in ("downloading", "stalledDL", "forcedDL")]
    active_uploading = [t for t in torrents if t.get("state") == "uploading"]
    stalled = [t for t in torrents if t.get("state") == "stalledUP"]

    click.echo(f"\n  Torrents: {len(torrents)} total")
    click.echo(f"    Active uploading : {len(active_uploading)}")
    click.echo(f"    Stalled (UP)     : {len(stalled)}")
    click.echo(f"    Paused           : {len(paused)}")
    click.echo(f"    Queued           : {len(queued)}")
    click.echo(f"    Downloading      : {len(downloading)}")
    click.echo(f"    Errored          : {len(errored)}")

    if not seeding:
        issues.append("NO torrents are seeding! Everything is paused/queued/downloading.")
    elif not active_uploading:
        warnings.append(f"{len(stalled)} torrents seeding but ALL stalled (no peers downloading from you).")

    if paused:
        warnings.append(f"{len(paused)} torrent(s) are paused — they contribute nothing.")

    if queued:
        issues.append(f"{len(queued)} torrent(s) are QUEUED (waiting). Disable queue limits or force-start them.")

    if errored:
        issues.append(f"{len(errored)} torrent(s) in ERROR state:")
        for t in errored[:3]:
            issues.append(f"  - {t['name'][:50]}")

    # 5. Leecher analysis — THE #1 REASON for no upload
    total_leechers = sum(t.get("num_leechs", 0) for t in seeding)
    torrents_with_leechers = [t for t in seeding if t.get("num_leechs", 0) > 0]

    click.echo(f"\n  Leecher Analysis:")
    click.echo(f"    Total leechers across seeding torrents: {total_leechers}")
    click.echo(f"    Torrents with 1+ leechers: {len(torrents_with_leechers)} / {len(seeding)}")

    if total_leechers == 0:
        issues.append(
            "ZERO LEECHERS on all your torrents! Nobody is downloading from you.\n"
            "      → This is the #1 reason for no upload.\n"
            "      → You need to seed POPULAR content with active leechers.\n"
            "      → Add new/trending torrents, or Freeleech content."
        )
    elif len(torrents_with_leechers) < 3:
        warnings.append(f"Only {len(torrents_with_leechers)} torrent(s) have leechers. Add more popular content.")

    # Top torrents by leechers
    if torrents_with_leechers:
        click.echo(f"\n  Top torrents by demand:")
        for t in sorted(torrents_with_leechers, key=lambda x: x.get("num_leechs", 0), reverse=True)[:5]:
            speed = format_bytes(t.get("up_speed", 0))
            click.echo(
                f"    {t['name'][:40]:<40} "
                f"Leechs: {t.get('num_leechs', 0):>3} | "
                f"Seeds: {t.get('num_seeds', 0):>3} | "
                f"Speed: {speed}/s"
            )

    # 6. Port / Firewall check (connection_status in transfer info)
    click.echo(f"\n  Network:")
    conn_status = transfer.get("connection_status", "unknown")
    listen_port = prefs.get("listen_port", "?")
    click.echo(f"    Connection Status : {conn_status}")
    click.echo(f"    Listen Port       : {listen_port}")

    if conn_status == "firewalled":
        issues.append(
            "CONNECTION STATUS = FIREWALLED!\n"
            f"      → Port {listen_port} is NOT accessible from outside.\n"
            "      → Peers CANNOT connect to you. You can only connect outward.\n"
            "      → This MASSIVELY reduces upload. Fix:\n"
            "        1. Forward port {listen_port} TCP+UDP in your router\n"
            "        2. Or enable UPnP in qBittorrent (Options > Connection)\n"
            "        3. Check Windows Firewall allows qBittorrent"
        )
    elif conn_status == "connected":
        good.append(f"Port {listen_port} is OPEN — peers can connect to you")
    elif conn_status == "disconnected":
        issues.append("qBittorrent says DISCONNECTED — no internet or DHT/tracker issues")

    upnp = prefs.get("upnp", False)
    if not upnp:
        warnings.append("UPnP is DISABLED. Enable it if you can't forward ports manually.")

    # 7. Speed limits check
    click.echo(f"\n  Speed Limits:")
    up_limit = prefs.get("up_limit", 0)
    dl_limit = prefs.get("dl_limit", 0)
    alt_enabled = transfer.get("use_alt_speed_limits", 0)
    alt_up = prefs.get("alt_up_limit", 0)

    if alt_enabled:
        click.secho(f"    Alternative Speed Mode: ACTIVE (upload cap: {alt_up // 1024} KB/s)", fg="yellow")
        warnings.append(f"Alternative speed limits ACTIVE — upload capped to {alt_up // 1024} KB/s!")
    else:
        click.echo(f"    Alternative Speed Mode: OFF")

    if up_limit > 0:
        issues.append(f"Global upload limit is SET to {up_limit // 1024} KB/s! Remove it.")
        click.secho(f"    Global Upload Limit: {up_limit // 1024} KB/s ← BOTTLENECK!", fg="red")
    else:
        click.echo(f"    Global Upload Limit: Unlimited")
        good.append("No global upload speed cap")

    if dl_limit > 0:
        click.echo(f"    Global Download Limit: {dl_limit // 1024} KB/s")
    else:
        click.echo(f"    Global Download Limit: Unlimited")

    # Per-torrent caps
    capped_torrents = [t for t in seeding if t.get("up_limit", 0) > 0]
    if capped_torrents:
        warnings.append(f"{len(capped_torrents)} seeding torrent(s) have individual upload speed caps!")

    # 8. Connection settings
    click.echo(f"\n  Connection Settings:")
    max_conn = prefs.get("max_connec", 0)
    max_conn_torrent = prefs.get("max_connec_per_torrent", 0)
    max_uploads = prefs.get("max_uploads", 0)
    queue_enabled = prefs.get("queueing_enabled", True)
    max_active_up = prefs.get("max_active_uploads", 0)

    click.echo(f"    Max Connections      : {max_conn}")
    click.echo(f"    Max Conn/Torrent     : {max_conn_torrent}")
    click.echo(f"    Max Upload Slots     : {max_uploads}")
    click.echo(f"    Queueing             : {'ON' if queue_enabled else 'OFF'}")
    click.echo(f"    Max Active Uploads   : {max_active_up}")

    if max_conn > 0 and max_conn < 500:
        warnings.append(f"Max connections is only {max_conn} — increase to 2000+")
    if queue_enabled and max_active_up > 0 and max_active_up < len(seeding):
        issues.append(
            f"Queue limits active: max {max_active_up} active uploads but you have {len(seeding)} seeding torrents.\n"
            "      → Some torrents are waiting in queue doing nothing.\n"
            "      → Disable queueing or raise max_active_uploads."
        )

    # 9. DHT / PeX / LSD
    dht = prefs.get("dht", False)
    pex = prefs.get("pex", False)
    lsd = prefs.get("lsd", False)
    click.echo(f"\n  Peer Discovery:")
    click.echo(f"    DHT: {'ON' if dht else 'OFF'}  |  PeX: {'ON' if pex else 'OFF'}  |  LSD: {'ON' if lsd else 'OFF'}")
    if not dht:
        warnings.append("DHT is DISABLED — you're missing peer discovery. Enable it.")
    if not pex:
        warnings.append("PeX is DISABLED — you're missing peer exchange. Enable it.")

    # 10. Tracker errors
    tracker_errors = 0
    for t in seeding[:20]:
        try:
            trackers = client.get_trackers(t["hash"])
            for tr in trackers:
                if tr.get("status") == 4:
                    tracker_errors += 1
        except Exception:
            pass
    if tracker_errors:
        warnings.append(f"{tracker_errors} tracker error(s) detected. Run `python main.py start` for auto-healing.")

    # 11. Current speed
    up_speed = transfer.get("up_info_speed", 0)
    dl_speed = transfer.get("dl_info_speed", 0)
    click.echo(f"\n  Current Speed:")
    click.echo(f"    Upload   : {format_bytes(up_speed)}/s")
    click.echo(f"    Download : {format_bytes(dl_speed)}/s")

    if up_speed == 0 and total_leechers > 0:
        warnings.append("Leechers exist but upload is 0 — possible firewall/NAT issue.")

    # ── REPORT ──────────────────────────────────────────────────
    click.echo()
    click.secho("  " + "═" * 50, fg="cyan")

    if issues:
        click.secho(f"\n  ❌ ISSUES FOUND ({len(issues)}):", fg="red", bold=True)
        for i, issue in enumerate(issues, 1):
            click.secho(f"    {i}. {issue}", fg="red")

    if warnings:
        click.secho(f"\n  ⚠️  WARNINGS ({len(warnings)}):", fg="yellow")
        for i, w in enumerate(warnings, 1):
            click.secho(f"    {i}. {w}", fg="yellow")

    if good:
        click.secho(f"\n  ✅ OK:", fg="green")
        for g in good:
            click.secho(f"    - {g}", fg="green")

    # ── RECOMMENDATIONS ─────────────────────────────────────────
    click.echo()
    if any("FIREWALLED" in i for i in issues):
        click.secho("  🔧 TOP PRIORITY: Forward your port. This alone can 10x your upload.", fg="red", bold=True)
    elif total_leechers == 0:
        click.secho("  🔧 TOP PRIORITY: Add popular/Freeleech content. No leechers = no upload.", fg="red", bold=True)
    elif any("QUEUED" in i for i in issues):
        click.secho("  🔧 TOP PRIORITY: Run `python main.py beast` to disable queue limits.", fg="yellow", bold=True)
    elif up_speed == 0:
        click.secho("  🔧 TRY: Run `python main.py beast` to force-start everything and remove limits.", fg="yellow", bold=True)
    else:
        click.secho("  System looks healthy. Upload should be working.", fg="green", bold=True)

    click.echo()


@cli.command()
def beast():
    """Activate Beast Mode: max performance, all rules ON, 60s interval, full throttle."""
    config = load_config()
    client = make_client(config)
    notifier = load_notifier(config)

    click.secho("", fg="red")
    click.secho("  ╔══════════════════════════════════════════════╗", fg="red", bold=True)
    click.secho("  ║         🔥 IGS BEAST MODE ACTIVATED 🔥       ║", fg="red", bold=True)
    click.secho("  ╚══════════════════════════════════════════════╝", fg="red", bold=True)
    click.secho("", fg="red")

    # 1. Inject maximum performance settings
    click.secho("  [1/4] Injecting extreme performance settings...", fg="yellow")
    blocklist_url = "https://github.com/Naunter/BT_BlockLists/raw/master/bt_blocklists.gz"
    beast_prefs = {
        "max_connec": 4000,
        "max_connec_per_torrent": 1000,
        "max_uploads": 750,
        "max_uploads_per_torrent": 150,
        "max_half_open_connections": 200,
        "choking_algorithm": 1,
        "up_limit": 0,
        "dl_limit": 0,
        "dht": True,
        "pex": True,
        "lsd": True,
        "ip_filter_enabled": True,
        "ip_filter_path": blocklist_url,
        "ip_filter_trackers": True,
        "queueing_enabled": False,
        "max_active_uploads": -1,
        "max_active_torrents": -1,
    }
    try:
        client.set_preferences(beast_prefs)
        click.secho("    Max Connections: 4000 | Per-Torrent: 1000", fg="green")
        click.secho("    Max Uploads: 750 | Half-Open: 200", fg="green")
        click.secho("    Queueing: DISABLED (all torrents active)", fg="green")
        click.secho("    DHT + PeX + LSD: ENABLED", fg="green")
        click.secho("    IP Blocklist: ACTIVE", fg="green")
    except Exception as e:
        click.secho(f"    Failed: {e}", fg="red")

    # 2. Force-start ALL seeding torrents
    click.secho("  [2/4] Force-starting all seeders...", fg="yellow")
    torrents = client.get_torrents()
    seeders = [t for t in torrents if t.get("state") in ("uploading", "stalledUP", "pausedUP", "queuedUP")]
    for t in seeders:
        client.set_force_start(t["hash"], True)
        if t.get("up_limit", 0) > 0:
            client.set_upload_limit(t["hash"], 0)
    click.secho(f"    Force-started {len(seeders)} torrent(s), all caps removed", fg="green")

    # 3. Resume all paused seeders
    paused = [t for t in torrents if t.get("state") == "pausedUP"]
    if paused:
        client.resume("|".join(t["hash"] for t in paused))
        click.secho(f"    Resumed {len(paused)} paused seeder(s)", fg="green")

    # 4. Start engine with ALL 15 rules at 60s interval
    click.secho("  [3/4] Starting automation engine (60s interval, 15 rules)...", fg="yellow")

    # Force all rules ON
    rules_cfg = config.get("automation", {}).get("rules", {})
    rules = []
    rules.append(RaceRule(max_age_hours=rules_cfg.get("race_rule", {}).get("max_age_hours", 2)))
    rules.append(ISPEvasionRule())
    rules.append(SniperRule())
    rules.append(DictatorshipRule(notifier=notifier))
    rules.append(HealingRule())
    rules.append(AntiSpywareRule(notifier=notifier))
    rules.append(StaleSeederRule())
    rules.append(CleanupRule())
    rules.append(RatioGuardRule())
    target_bytes = int(rules_cfg.get("upload_goal", {}).get("target_tb", 1.0) * 1024**4)
    rules.append(UploadGoalRule(target_bytes=target_bytes, notifier=notifier))
    rules.append(NightRaidRule(notifier=notifier))
    rules.append(SwarmDominatorRule(notifier=notifier))
    rules.append(TrackerBoosterRule())
    rules.append(RevengeRule(notifier=notifier))
    ac_cfg = rules_cfg.get("auto_category", {})
    if ac_cfg.get("tracker_map"):
        rules.append(AutoCategoryRule(tracker_map=ac_cfg.get("tracker_map", {})))

    engine = AutomationEngine(client, rules=rules, interval_sec=60, notifier=notifier)
    engine.start()
    click.secho(f"    {len(rules)} rules active | 60s cycle | Adaptive interval ON", fg="green")

    # 5. Start hunters
    click.secho("  [4/4] Starting freeleech hunters...", fg="yellow")
    fh_instance = None
    fh_cfg = config.get("freeleech_hunter", {})
    if fh_cfg.get("enabled", False):
        from freeleech_hunter import FreeleechHunter, build_profiles
        profiles = build_profiles(config)
        if profiles:
            fh_instance = FreeleechHunter(
                client=client, profiles=profiles,
                interval_sec=fh_cfg.get("interval_sec", 600),
                notifier=notifier, max_per_run=fh_cfg.get("max_per_run", 5),
            )
            fh_instance.start()
            click.secho(f"    Freeleech Hunter: ACTIVE ({len(profiles)} tracker(s))", fg="green")

    from torr9_hunter import build_torr9_hunter
    torr9_instance = build_torr9_hunter(config, client, notifier=notifier)
    if torr9_instance:
        torr9_instance.start()
        mode = "Alert Only" if torr9_instance.notify_only else "Auto-Download"
        click.secho(f"    Torr9 Hunter: ACTIVE ({mode})", fg="green")

    click.secho("")
    click.secho("  ══════════════════════════════════════════════", fg="red")
    click.secho(f"  🔥 BEAST MODE RUNNING — {len(seeders)} seeders | {len(rules)} rules | 60s cycles", fg="red", bold=True)
    click.secho("  ══════════════════════════════════════════════", fg="red")
    click.secho("  Press Ctrl+C to stop.\n", dim=True)

    if notifier and notifier.enabled:
        notifier.send(
            "🔥 <b>BEAST MODE ACTIVATED</b>\n\n"
            f"🚀 {len(seeders)} seeders force-started\n"
            f"⚙️ {len(rules)} rules active | 60s cycles\n"
            f"📡 Connections: 4000 | Uploads: 750\n"
            "All limits removed. Maximum upload."
        )

    try:
        import time as _time
        while True:
            _time.sleep(1)
    except KeyboardInterrupt:
        engine.stop()
        if fh_instance:
            fh_instance.stop()
        if torr9_instance:
            torr9_instance.stop()
        click.echo("[*] Beast Mode stopped.")


cli.add_command(list_torrents, name="ls")
cli.add_command(remove, name="rm")

if __name__ == "__main__":
    cli()
