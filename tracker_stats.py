"""Ratio tracking and analytics across torrents/trackers."""

from qbit_client import QBitClient
from database import get_global_history, get_torrent_history, get_top_seeders


def format_bytes(b):
    """Human-readable byte formatting."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(b) < 1024:
            return f"{b:.2f} {unit}"
        b /= 1024
    return f"{b:.2f} PB"


def format_speed(bps):
    """Human-readable speed formatting (bytes/sec input)."""
    return f"{format_bytes(bps)}/s"


def get_live_summary(client: QBitClient):
    """Get a real-time summary of seeding activity."""
    transfer = client.get_global_transfer_info()
    torrents = client.get_torrents()

    seeding = [t for t in torrents if t.get("state", "").startswith("upload") or t["state"] == "stalledUP"]
    downloading = [t for t in torrents if t.get("state", "").startswith("download") or t["state"] == "stalledDL"]

    total_up = sum(t.get("uploaded", 0) for t in torrents)
    total_dl = sum(t.get("downloaded", 0) for t in torrents)
    global_ratio = total_up / max(total_dl, 1)

    return {
        "upload_speed": transfer.get("up_info_speed", 0),
        "download_speed": transfer.get("dl_info_speed", 0),
        "total_uploaded": total_up,
        "total_downloaded": total_dl,
        "global_ratio": global_ratio,
        "seeding_count": len(seeding),
        "downloading_count": len(downloading),
        "total_count": len(torrents),
        "top_seeders": sorted(seeding, key=lambda t: t.get("uploaded", 0), reverse=True)[:5],
    }


def get_tracker_breakdown(client: QBitClient):
    """Group torrents by tracker and show per-tracker stats."""
    torrents = client.get_torrents()
    trackers = {}

    for t in torrents:
        tracker_url = t.get("tracker", "unknown")
        # Extract hostname
        host = tracker_url
        if "://" in tracker_url:
            host = tracker_url.split("://")[1].split("/")[0].split(":")[0]
        if not host:
            host = "no-tracker"

        if host not in trackers:
            trackers[host] = {"uploaded": 0, "downloaded": 0, "count": 0, "seeding": 0}

        trackers[host]["uploaded"] += t.get("uploaded", 0)
        trackers[host]["downloaded"] += t.get("downloaded", 0)
        trackers[host]["count"] += 1
        if t.get("state", "").startswith("upload") or t["state"] == "stalledUP":
            trackers[host]["seeding"] += 1

    for host, stats in trackers.items():
        stats["ratio"] = stats["uploaded"] / max(stats["downloaded"], 1)

    return trackers


def print_summary(client: QBitClient):
    """Print a formatted summary to console."""
    summary = get_live_summary(client)
    print("=" * 50)
    print("  IGS - Intelligent Seeding Suite - Live Stats")
    print("=" * 50)
    print(f"  Upload Speed:   {format_speed(summary['upload_speed'])}")
    print(f"  Download Speed: {format_speed(summary['download_speed'])}")
    print(f"  Total Uploaded: {format_bytes(summary['total_uploaded'])}")
    print(f"  Total Downloaded: {format_bytes(summary['total_downloaded'])}")
    print(f"  Global Ratio:   {summary['global_ratio']:.3f}")
    print(f"  Seeding: {summary['seeding_count']} | Downloading: {summary['downloading_count']} | Total: {summary['total_count']}")
    print("-" * 50)

    if summary["top_seeders"]:
        print("  Top Seeders:")
        for t in summary["top_seeders"]:
            print(f"    {t['name'][:35]:35s}  {format_bytes(t['uploaded']):>12s}  ratio {t.get('ratio', 0):.2f}")
    print("=" * 50)
