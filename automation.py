"""Rules-based seedbox automation engine.

Manages torrents automatically based on configurable rules:
- Auto-pause low-ratio stalled seeds
- Auto-remove old completed torrents
- Auto-categorize by tracker
- Enforce global ratio/speed limits
"""

import time
import threading
from datetime import datetime, timezone
from qbit_client import QBitClient
from database import record_global_snapshot, record_torrent_snapshots
from notifier import TelegramNotifier


class Rule:
    """Base class for automation rules."""
    name = "base_rule"
    enabled = True

    def evaluate(self, client, torrents):
        raise NotImplementedError


class StaleSeederRule(Rule):
    """Pause torrents that have been seeding with 0 upload for too long."""
    name = "stale_seeder"

    def __init__(self, max_idle_hours=48):
        self.max_idle_hours = max_idle_hours

    def evaluate(self, client, torrents):
        actions = []
        now = time.time()
        for t in torrents:
            if t["state"] in ("uploading", "stalledUP", "forcedUP"):
                last_activity = t.get("last_activity", 0)
                idle_hours = (now - last_activity) / 3600 if last_activity > 0 else 0
                if idle_hours > self.max_idle_hours and t.get("ratio", 0) >= 1.0:
                    client.pause(t["hash"])
                    actions.append(f"Paused stale seeder: {t['name'][:40]} (idle {idle_hours:.0f}h, ratio {t['ratio']:.2f})")
        return actions


class CleanupRule(Rule):
    """Remove completed torrents older than a threshold to prevent Hit & Run."""
    name = "cleanup"

    def __init__(self, min_ratio=2.0, min_active_seed_hours=72):
        self.min_ratio = min_ratio
        self.min_seed_seconds = min_active_seed_hours * 3600

    def evaluate(self, client, torrents):
        actions = []
        for t in torrents:
            if t["state"] in ("uploading", "stalledUP", "pausedUP"):
                seeding_time = t.get("seeding_time", 0)

                ratio_safe = t.get("ratio", 0) >= self.min_ratio
                time_safe = seeding_time >= self.min_seed_seconds

                if ratio_safe and time_safe:
                    client.delete(t["hash"], delete_files=False)
                    actions.append(f"H&R Safe Removal: {t['name'][:40]} (ratio: {t['ratio']:.2f}, active seed: {seeding_time/3600:.1f}h)")
                elif ratio_safe and not time_safe:
                    if "H&R-Pending" not in t.get("tags", ""):
                        client.add_tags(t["hash"], "H&R-Pending")
                        actions.append(f"Waiting for H&R clearance: {t['name'][:40]} ({seeding_time/3600:.1f}h / {self.min_seed_seconds/3600}h)")

        return actions


class AutoCategoryRule(Rule):
    """Auto-categorize torrents based on tracker hostname."""
    name = "auto_category"

    def __init__(self, tracker_map=None):
        self.tracker_map = tracker_map or {}

    def evaluate(self, client, torrents):
        actions = []
        for t in torrents:
            if t.get("category"):
                continue
            tracker_url = t.get("tracker", "")
            for keyword, category in self.tracker_map.items():
                if keyword.lower() in tracker_url.lower():
                    client.set_category(t["hash"], category)
                    actions.append(f"Categorized: {t['name'][:40]} -> {category}")
                    break
        return actions


class RatioGuardRule(Rule):
    """Tag torrents below a minimum ratio threshold as low-priority."""
    name = "ratio_guard"

    def __init__(self, warn_ratio=0.5):
        self.warn_ratio = warn_ratio

    def evaluate(self, client, torrents):
        actions = []
        for t in torrents:
            if t["state"] in ("uploading", "stalledUP") and t.get("ratio", 0) < self.warn_ratio:
                if "low-ratio" not in t.get("tags", ""):
                    client.add_tags(t["hash"], "low-ratio")
                    actions.append(f"Tagged low-ratio: {t['name'][:40]} (ratio {t['ratio']:.2f})")
        return actions


class RaceRule(Rule):
    """Reannounce new torrents to grab early leechers and enable super seeding.

    Only reannounces once per torrent to avoid tracker rate-limiting.
    """
    name = "race_rule"

    def __init__(self, max_age_hours=2, min_leechers=1):
        self.max_age_hours = max_age_hours
        self.min_leechers = min_leechers
        self._announced = set()

    def evaluate(self, client, torrents):
        actions = []
        now = time.time()
        for t in torrents:
            h = t["hash"]
            added_on = t.get("added_on", 0)
            age_hours = (now - added_on) / 3600

            if age_hours > self.max_age_hours:
                self._announced.discard(h)
                continue

            if 0 < age_hours <= self.max_age_hours and t.get("num_leechs", 0) >= self.min_leechers:
                if t.get("super_seeding", False) is False:
                    client.set_super_seeding(h, True)
                    actions.append(f"Enabled Super-Seeding: {t['name'][:40]}")

                if h not in self._announced:
                    client.reannounce(h)
                    self._announced.add(h)
                    actions.append(f"Racing Reannounce: {t['name'][:40]} (Leechers: {t.get('num_leechs', 0)})")
        return actions


class ISPEvasionRule(Rule):
    """Toggle alternative speed limits during ISP peak hours to avoid shaping."""
    name = "isp_evasion"

    def __init__(self, peak_start_hour=18, peak_end_hour=23):
        self.peak_start_hour = peak_start_hour
        self.peak_end_hour = peak_end_hour

    def evaluate(self, client, torrents):
        actions = []
        current_hour = datetime.now().hour
        alt_mode_active = client.get_speed_limits_mode() == 1

        is_peak = False
        if self.peak_start_hour < self.peak_end_hour:
            is_peak = self.peak_start_hour <= current_hour < self.peak_end_hour
        else:
            is_peak = current_hour >= self.peak_start_hour or current_hour < self.peak_end_hour

        if is_peak and not alt_mode_active:
            client.toggle_speed_limits_mode()
            actions.append("ISP Evasion: Enabled Alternative Speed Limits (Peak Hours).")
        elif not is_peak and alt_mode_active:
            client.toggle_speed_limits_mode()
            actions.append("ISP Evasion: Restored Global Download/Upload Speeds (Off-Peak).")

        return actions


class SniperRule(Rule):
    """Bandwidth focusing: prioritize torrents with high demand by boosting their upload limit
    and throttling low-demand torrents when bandwidth is contested."""
    name = "sniper_rule"

    def __init__(self, min_speed_kbps=50, demand_leechers=3):
        self.min_speed_bytes = min_speed_kbps * 1024
        self.demand_leechers = demand_leechers

    def evaluate(self, client, torrents):
        actions = []
        uploading = [t for t in torrents if t["state"] == "uploading"]
        if len(uploading) < 2:
            return actions

        high_demand = [t for t in uploading if t.get("num_leechs", 0) >= self.demand_leechers]
        low_demand = [t for t in uploading if t.get("num_leechs", 0) < self.demand_leechers]

        if not high_demand:
            # No high-demand torrents — release any existing throttles
            for t in low_demand:
                if t.get("up_limit", 0) > 0:
                    client.set_upload_limit(t["hash"], 0)
                    actions.append(f"Sniper: Released throttle on {t['name'][:30]}")
            return actions

        # Throttle low-demand torrents to free bandwidth for high-demand ones
        for t in low_demand:
            if t.get("up_limit", 0) == 0:
                client.set_upload_limit(t["hash"], self.min_speed_bytes)
                actions.append(f"Sniper: Throttled low-demand {t['name'][:30]} to {self.min_speed_bytes//1024}KB/s")

        # Ensure high-demand torrents are unlimited
        for t in high_demand:
            if t.get("up_limit", 0) > 0:
                client.set_upload_limit(t["hash"], 0)
                actions.append(f"Sniper: Unleashed high-demand {t['name'][:30]}")

        return actions


class DictatorshipRule(Rule):
    """Golden Torrent: Pause all other torrents if you are the ONLY seeder on a highly demanded torrent."""
    name = "dictatorship_rule"

    def __init__(self, trigger_leechers=2, notifier: TelegramNotifier = None):
        self.trigger_leechers = trigger_leechers
        self.notifier = notifier
        self._paused_by_us = set()

    def evaluate(self, client, torrents):
        actions = []
        golden_torrent = None

        for t in torrents:
            if t.get("num_seeds", 0) == 0 and t.get("num_leechs", 0) >= self.trigger_leechers:
                golden_torrent = t
                break

        if golden_torrent:
            hashes_to_pause = [
                t["hash"] for t in torrents
                if t["hash"] != golden_torrent["hash"]
                and t["state"] in ("uploading", "stalledUP")
                and t["hash"] not in self._paused_by_us
            ]
            if hashes_to_pause:
                client.pause("|".join(hashes_to_pause))
                self._paused_by_us.update(hashes_to_pause)
                actions.append(f"DICTATORSHIP ENGAGED! Focus 100% on: {golden_torrent['name'][:40]} ({len(hashes_to_pause)} paused)")
                if self.notifier:
                    from tracker_stats import format_speed
                    self.notifier.alert_dictatorship(
                        golden_torrent['name'],
                        golden_torrent.get('num_leechs', 0),
                        format_speed(golden_torrent.get('up_speed', 0))
                    )

        elif self._paused_by_us:
            # Resume only torrents WE paused
            still_paused = [t["hash"] for t in torrents if t["hash"] in self._paused_by_us and t["state"] == "pausedUP"]
            if still_paused:
                client.resume("|".join(still_paused))
                actions.append(f"Dictatorship Ended. Resumed {len(still_paused)} torrent(s).")
                if self.notifier:
                    self.notifier.alert_dictatorship_ended(len(still_paused))
            self._paused_by_us.clear()

        return actions


class HealingRule(Rule):
    """Self-Repair: Detect tracker errors and reannounce to fix unregistered/error states."""
    name = "healing_rule"

    def evaluate(self, client, torrents):
        actions = []
        for t in torrents:
            if t.get("state") == "error":
                try:
                    trackers = client.get_trackers(t["hash"])
                    for tr in trackers:
                        if tr.get("status") == 4 or "unregistered" in tr.get("msg", "").lower():
                            client.reannounce(t["hash"])
                            actions.append(f"Auto-Heal: Forced reannounce for tracker error on {t['name'][:30]}")
                            break
                except Exception:
                    pass
        return actions


class AntiSpywareRule(Rule):
    """Anti-Malware: Scan torrent contents. If dangerous extensions (.exe, .vbs) are found in non-software torrents, pause and flag them."""
    name = "anti_spyware_rule"

    def __init__(self, bad_extensions=None, notifier: TelegramNotifier = None):
        self.bad_extensions = bad_extensions or [".exe", ".bat", ".vbs", ".cmd", ".scr"]
        self.notifier = notifier
        self._checked_hashes = set()

    def evaluate(self, client, torrents):
        actions = []
        for t in torrents:
            h = t["hash"]
            # Only check once per torrent to avoid spamming the API
            if h in self._checked_hashes:
                continue
                
            try:
                files = client.get_torrent_files(h)
                self._checked_hashes.add(h) # Mark as checked
                
                for f in files:
                    filename = f.get("name", "").lower()
                    if any(filename.endswith(ext) for ext in self.bad_extensions):
                        client.pause(h)
                        if "MALWARE-WARNING" not in t.get("tags", ""):
                            client.add_tags(h, "MALWARE-WARNING")
                        actions.append(f"🚨 ANTI-SPYWARE: Paused {t['name'][:30]} - Suspicious file found: {filename}")
                        if self.notifier:
                            self.notifier.alert_malware(t['name'], filename)
                        break
            except Exception:
                pass # If we fail to get files, try again next cycle by not adding to _checked_hashes
                
        return actions


class AutomationEngine:
    """Runs rules on a schedule and records stats."""

    def __init__(self, client: QBitClient, rules=None, interval_sec=300):
        self.client = client
        self.rules = rules or [
            StaleSeederRule(),
            CleanupRule(),
            RatioGuardRule(),
            RaceRule(),
            ISPEvasionRule(),
            SniperRule(),
            DictatorshipRule(),
            HealingRule(),
            AntiSpywareRule(),
        ]
        self.interval = interval_sec
        self._stop = threading.Event()
        self._thread = None
        self.last_actions = []

    def run_once(self):
        """Execute all rules once and record stats."""
        torrents = self.client.get_torrents()
        transfer = self.client.get_global_transfer_info()

        record_global_snapshot(transfer, torrents)
        record_torrent_snapshots(torrents)

        actions = []
        for rule in self.rules:
            if rule.enabled:
                try:
                    result = rule.evaluate(self.client, torrents)
                    actions.extend(result)
                except Exception as e:
                    actions.append(f"[ERROR] Rule '{rule.name}': {e}")

        self.last_actions = actions
        return actions

    def _loop(self):
        while not self._stop.is_set():
            try:
                actions = self.run_once()
                if actions:
                    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
                    print(f"[{timestamp}] Automation ran {len(actions)} action(s):")
                    for a in actions:
                        print(f"  - {a}")
            except Exception as e:
                print(f"[Automation Error] {e}")
            self._stop.wait(self.interval)

    def start(self):
        """Start the automation loop in a background thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[Automation] Started (interval: {self.interval}s, rules: {len(self.rules)})")

    def stop(self):
        """Stop the automation loop."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        print("[Automation] Stopped.")
