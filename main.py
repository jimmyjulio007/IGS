"""IGS - Intelligent Seeding Suite: CLI entry point."""

import json
import os
import click
from qbit_client import QBitClient
from automation import AutomationEngine, StaleSeederRule, CleanupRule, AutoCategoryRule, RatioGuardRule, RaceRule, ISPEvasionRule, SniperRule, DictatorshipRule, HealingRule, AntiSpywareRule
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
            "auto_category": {"enabled": False, "tracker_map": {}}
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

    engine = AutomationEngine(client, rules=rules, interval_sec=interval)
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

cli.add_command(list_torrents, name="ls")
cli.add_command(remove, name="rm")

if __name__ == "__main__":
    cli()
