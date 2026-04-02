"""SQLite storage for historical ratio and transfer stats."""

import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "igs_stats.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            total_uploaded INTEGER NOT NULL,
            total_downloaded INTEGER NOT NULL,
            upload_speed INTEGER NOT NULL,
            download_speed INTEGER NOT NULL,
            active_torrents INTEGER NOT NULL,
            seeding_torrents INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS torrent_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            hash TEXT NOT NULL,
            name TEXT NOT NULL,
            uploaded INTEGER NOT NULL,
            downloaded INTEGER NOT NULL,
            ratio REAL NOT NULL,
            state TEXT NOT NULL,
            num_seeds INTEGER NOT NULL,
            num_leeches INTEGER NOT NULL,
            category TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(timestamp);
        CREATE INDEX IF NOT EXISTS idx_torrent_snapshots_ts ON torrent_snapshots(timestamp);
        CREATE INDEX IF NOT EXISTS idx_torrent_snapshots_hash ON torrent_snapshots(hash);
    """)
    conn.close()


def record_global_snapshot(transfer_info, torrent_list):
    """Save a point-in-time global stats snapshot."""
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    seeding = sum(1 for t in torrent_list if t.get("state", "").startswith("upload"))
    conn.execute(
        "INSERT INTO snapshots (timestamp, total_uploaded, total_downloaded, "
        "upload_speed, download_speed, active_torrents, seeding_torrents) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            now,
            transfer_info.get("up_info_data", 0),
            transfer_info.get("dl_info_data", 0),
            transfer_info.get("up_info_speed", 0),
            transfer_info.get("dl_info_speed", 0),
            len(torrent_list),
            seeding,
        ),
    )
    conn.commit()
    conn.close()


def record_torrent_snapshots(torrent_list):
    """Save per-torrent stats."""
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            now,
            t["hash"],
            t.get("name", "unknown"),
            t.get("uploaded", 0),
            t.get("downloaded", 0),
            t.get("ratio", 0),
            t.get("state", "unknown"),
            t.get("num_seeds", 0),
            t.get("num_leechs", 0),
            t.get("category", ""),
        )
        for t in torrent_list
    ]
    conn.executemany(
        "INSERT INTO torrent_snapshots "
        "(timestamp, hash, name, uploaded, downloaded, ratio, state, num_seeds, num_leeches, category) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def get_global_history(hours=24):
    """Return global snapshots from the last N hours."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM snapshots WHERE timestamp >= datetime('now', ?) ORDER BY timestamp",
        (f"-{hours} hours",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_torrent_history(torrent_hash, hours=24):
    """Return snapshots for a specific torrent."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM torrent_snapshots WHERE hash = ? AND timestamp >= datetime('now', ?) "
        "ORDER BY timestamp",
        (torrent_hash, f"-{hours} hours"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_top_seeders(limit=10):
    """Return torrents with highest upload contribution (latest snapshot)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT hash, name, uploaded, ratio, state FROM torrent_snapshots "
        "WHERE timestamp = (SELECT MAX(timestamp) FROM torrent_snapshots) "
        "ORDER BY uploaded DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
