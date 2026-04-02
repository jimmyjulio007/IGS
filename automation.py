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


class UploadGoalRule(Rule):
    """Upload Goal Tracker v2 — Adaptive 3-Phase Swarm Domination Engine.

    Phases scale aggression based on distance to goal:
      PHASE 1 — CRUISE  (> 50% remaining): Uncap uploads, Super-Seed, periodic reannounce.
      PHASE 2 — ASSAULT (20-50% remaining): + Force-start queued torrents, throttle downloads,
                                               boost connections, prioritize high-leecher torrents.
      PHASE 3 — BEAST   (< 20% remaining):  + Resume ALL paused seeders, kill all downloads,
                                               force reannounce every cycle, max peer discovery.

    Every phase is cumulative — Beast includes everything from Cruise and Assault.
    """
    name = "upload_goal_rule"

    PHASE_CRUISE  = "CRUISE"
    PHASE_ASSAULT = "ASSAULT"
    PHASE_BEAST   = "BEAST"

    def __init__(self, target_bytes: int = 1_099_511_627_776, notifier=None):  # Default: 1 TB
        self.target_bytes = target_bytes
        self.notifier = notifier
        self._milestone_pct = 0
        self._reannounce_cycle = 0  # Reannounce every N cycles (not every cycle in Cruise)
        self._phase = self.PHASE_CRUISE
        self._beast_paused_dl = set()  # Track downloads we paused in Beast mode

    def _get_phase(self, pct):
        """Determine aggression phase based on progress."""
        if pct >= 80:
            return self.PHASE_BEAST
        elif pct >= 50:
            return self.PHASE_ASSAULT
        return self.PHASE_CRUISE

    def evaluate(self, client, torrents):
        actions = []
        self._reannounce_cycle += 1

        # ── 0. Calculate progress ────────────────────────────────
        total_uploaded = sum(t.get("uploaded", 0) for t in torrents)
        pct = min((total_uploaded / self.target_bytes) * 100, 100.0) if self.target_bytes > 0 else 0
        self._phase = self._get_phase(pct)

        seeding = [t for t in torrents if t.get("state") in ("uploading", "stalledUP", "forcedUP")]
        queued  = [t for t in torrents if t.get("state") == "queuedUP"]
        paused  = [t for t in torrents if t.get("state") == "pausedUP"]
        downloading = [t for t in torrents if t.get("state") in ("downloading", "stalledDL", "forcedDL")]

        # ── PHASE 1: CRUISE (always active) ──────────────────────

        # 1a. Remove per-torrent upload caps on ALL seeding torrents
        capped = [t["hash"] for t in seeding + queued if t.get("up_limit", -1) > 0]
        if capped:
            client.set_upload_limit("|".join(capped), 0)
            actions.append(f"[{self._phase}] Uncapped upload on {len(capped)} torrent(s)")

        # 1b. Enable Super-Seeding on torrents with leechers
        for t in seeding:
            if t.get("num_leechs", 0) >= 1 and not t.get("super_seeding", False):
                try:
                    client.set_super_seeding(t["hash"], True)
                except Exception:
                    pass

        # 1c. Periodic reannounce (every 3 cycles in Cruise, every cycle in higher phases)
        reannounce_interval = 1 if self._phase != self.PHASE_CRUISE else 3
        if self._reannounce_cycle % reannounce_interval == 0:
            reannounce_targets = [t for t in seeding if t.get("num_leechs", 0) >= 1]
            if reannounce_targets:
                client.reannounce("|".join(t["hash"] for t in reannounce_targets))
                actions.append(f"[{self._phase}] Reannounced {len(reannounce_targets)} active seeder(s)")

        # 1d. Remove global upload speed limit if set
        try:
            prefs = client.get_preferences()
            if prefs.get("up_limit", 0) > 0:
                client.set_preferences({"up_limit": 0})
                actions.append(f"[{self._phase}] Removed global upload speed cap")
        except Exception:
            pass

        # ── PHASE 2: ASSAULT (50%+ progress) ─────────────────────
        if self._phase in (self.PHASE_ASSAULT, self.PHASE_BEAST):

            # 2a. Force-start ALL queued seeding torrents (bypass queue limit)
            if queued:
                for t in queued:
                    client.set_force_start(t["hash"], True)
                actions.append(f"[{self._phase}] Force-started {len(queued)} queued torrent(s)")

            # 2b. Prioritize torrents by leecher demand (best ratio opportunities first)
            high_demand = sorted(seeding, key=lambda t: t.get("num_leechs", 0), reverse=True)
            if high_demand and high_demand[0].get("num_leechs", 0) >= 3:
                top_hashes = [t["hash"] for t in high_demand[:5]]
                for h in top_hashes:
                    try:
                        client.set_torrent_priority(h, "topPrio")
                    except Exception:
                        pass
                actions.append(f"[{self._phase}] Boosted priority on top {len(top_hashes)} high-demand torrent(s)")

            # 2c. Throttle download speed to give upload maximum bandwidth
            try:
                prefs = client.get_preferences()
                current_dl_limit = prefs.get("dl_limit", 0)
                # In Assault: throttle to 512 KB/s — in Beast: kill downloads entirely (see below)
                target_dl = 0 if self._phase == self.PHASE_BEAST else 512 * 1024
                if current_dl_limit != target_dl:
                    client.set_preferences({"dl_limit": target_dl})
                    if target_dl > 0:
                        actions.append(f"[{self._phase}] Throttled global download to {target_dl // 1024} KB/s")
                    else:
                        actions.append(f"[{self._phase}] Killed global download limit (Beast override)")
            except Exception:
                pass

            # 2d. Boost connection settings for maximum swarm penetration
            try:
                prefs = client.get_preferences()
                boosts = {}
                if prefs.get("max_connec", 0) < 3000:
                    boosts["max_connec"] = 3000
                if prefs.get("max_connec_per_torrent", 0) < 750:
                    boosts["max_connec_per_torrent"] = 750
                if prefs.get("max_uploads", 0) < 500:
                    boosts["max_uploads"] = 500
                if prefs.get("max_uploads_per_torrent", 0) < 100:
                    boosts["max_uploads_per_torrent"] = 100
                # Enable DHT, PeX, LSD for maximum peer discovery
                if not prefs.get("dht", True):
                    boosts["dht"] = True
                if not prefs.get("pex", True):
                    boosts["pex"] = True
                if not prefs.get("lsd", True):
                    boosts["lsd"] = True
                if boosts:
                    client.set_preferences(boosts)
                    actions.append(f"[{self._phase}] Boosted connection limits & peer discovery ({len(boosts)} setting(s))")
            except Exception:
                pass

        # ── PHASE 3: BEAST MODE (80%+ progress) ─────────────────
        if self._phase == self.PHASE_BEAST:

            # 3a. Resume ALL paused seeders — every torrent must contribute
            if paused:
                resume_hashes = [t["hash"] for t in paused]
                client.resume("|".join(resume_hashes))
                for h in resume_hashes:
                    client.set_force_start(h, True)
                actions.append(f"[BEAST] Force-resumed {len(resume_hashes)} paused seeder(s)")

            # 3b. Pause active downloads to free 100% bandwidth for upload
            if downloading:
                dl_hashes = [t["hash"] for t in downloading]
                client.pause("|".join(dl_hashes))
                self._beast_paused_dl.update(dl_hashes)
                actions.append(f"[BEAST] Paused {len(dl_hashes)} download(s) — 100% upload focus")

            # 3c. Force reannounce on ALL seeders (not just active ones)
            all_seed_hashes = [t["hash"] for t in seeding + queued]
            if all_seed_hashes:
                client.reannounce("|".join(all_seed_hashes))

            # 3d. Remove any per-torrent download limits that waste bandwidth
            dl_limited = [t["hash"] for t in seeding if t.get("dl_limit", 0) > 0]
            if dl_limited:
                client.set_download_limit("|".join(dl_limited), 0)

        # ── Restore downloads if we drop back from Beast ─────────
        if self._phase != self.PHASE_BEAST and self._beast_paused_dl:
            still_paused = [t["hash"] for t in torrents if t["hash"] in self._beast_paused_dl and t.get("state") == "pausedDL"]
            if still_paused:
                client.resume("|".join(still_paused))
                actions.append(f"[{self._phase}] Restored {len(still_paused)} download(s) (exited Beast Mode)")
            self._beast_paused_dl.clear()
            # Restore download limit
            try:
                client.set_preferences({"dl_limit": 0})
            except Exception:
                pass

        # ── Progress bar & milestones ────────────────────────────
        target_gb = self.target_bytes / (1024**3)
        uploaded_gb = total_uploaded / (1024**3)
        bar_filled = int(pct / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        phase_icon = {"CRUISE": "🚢", "ASSAULT": "⚔️", "BEAST": "🔥"}[self._phase]
        actions.append(
            f"{phase_icon} Upload Goal [{self._phase}]: [{bar}] {uploaded_gb:.1f} GB / {target_gb:.0f} GB ({pct:.1f}%)"
        )

        # Notify at milestones (25%, 50%, 75%, 100%)
        for milestone in [25, 50, 75, 100]:
            if pct >= milestone and self._milestone_pct < milestone:
                self._milestone_pct = milestone
                if self.notifier:
                    emoji = "🏆" if milestone == 100 else "🎯"
                    phase_msg = f"\n⚡ Phase: <b>{self._phase}</b>" if milestone < 100 else ""
                    self.notifier.send(
                        f"{emoji} <b>Upload Milestone: {milestone}%!</b>\n\n"
                        f"📈 {uploaded_gb:.1f} GB / {target_gb:.0f} GB uploaded{phase_msg}\n"
                        f"Keep seeding!"
                    )
                break

        return actions


class NightRaidRule(Rule):
    """Full throttle during off-peak hours. Removes ALL speed limits at night,
    force-starts every torrent, and reannounces everything to maximize overnight upload.

    Night = free bandwidth. Day = ISP evasion. This rule is the inverse of ISPEvasionRule.
    """
    name = "night_raid"

    def __init__(self, raid_start_hour=0, raid_end_hour=7, notifier=None):
        self.raid_start_hour = raid_start_hour
        self.raid_end_hour = raid_end_hour
        self.notifier = notifier
        self._raiding = False
        self._raid_cycle = 0

    def _is_raid_time(self):
        hour = datetime.now().hour
        if self.raid_start_hour < self.raid_end_hour:
            return self.raid_start_hour <= hour < self.raid_end_hour
        return hour >= self.raid_start_hour or hour < self.raid_end_hour

    def evaluate(self, client, torrents):
        actions = []

        if self._is_raid_time():
            if not self._raiding:
                self._raiding = True
                self._raid_cycle = 0
                if self.notifier:
                    self.notifier.send(
                        "🌙 <b>NIGHT RAID ENGAGED</b>\n\n"
                        "All limits removed. Every torrent force-started.\n"
                        "Maximum upload until dawn."
                    )

            self._raid_cycle += 1

            # Remove ALL global speed limits
            try:
                client.set_preferences({"up_limit": 0, "dl_limit": 0})
            except Exception:
                pass

            # Disable alternative speed mode if active
            try:
                if client.get_speed_limits_mode() == 1:
                    client.toggle_speed_limits_mode()
                    actions.append("[NIGHT RAID] Disabled alt speed limits — full power")
            except Exception:
                pass

            # Force-start all paused/queued seeding torrents
            resumable = [t for t in torrents if t.get("state") in ("pausedUP", "queuedUP")]
            if resumable:
                for t in resumable:
                    client.set_force_start(t["hash"], True)
                actions.append(f"[NIGHT RAID] Force-started {len(resumable)} torrent(s)")

            # Uncap everything
            capped = [t["hash"] for t in torrents if t.get("up_limit", 0) > 0]
            if capped:
                client.set_upload_limit("|".join(capped), 0)
                actions.append(f"[NIGHT RAID] Uncapped {len(capped)} torrent(s)")

            # Reannounce every 2 cycles to find new peers
            if self._raid_cycle % 2 == 0:
                seeding = [t for t in torrents if t.get("state") in ("uploading", "stalledUP", "forcedUP")]
                if seeding:
                    client.reannounce("|".join(t["hash"] for t in seeding))
                    actions.append(f"[NIGHT RAID] Reannounced {len(seeding)} seeder(s)")

            if self._raid_cycle == 1:
                actions.append("[NIGHT RAID] Engaged — all limits removed, maximum upload")

        elif self._raiding:
            self._raiding = False
            self._raid_cycle = 0
            actions.append("[NIGHT RAID] Ended — daytime mode restored")
            if self.notifier:
                self.notifier.send(
                    "🌅 <b>Night Raid Ended</b>\n\n"
                    "Daytime speed management restored.",
                    silent=True,
                )

        return actions


class SwarmDominatorRule(Rule):
    """Detect swarms where you are one of very few seeders (1-3) with many leechers.
    Aggressively optimize these torrents: Super-Seed, max connections, force reannounce,
    and set unlimited share ratio to farm maximum upload from your dominant position."""
    name = "swarm_dominator"

    def __init__(self, max_seeders=3, min_leechers=3, notifier=None):
        self.max_seeders = max_seeders
        self.min_leechers = min_leechers
        self.notifier = notifier
        self._dominated = set()

    def evaluate(self, client, torrents):
        actions = []

        dominant = []
        for t in torrents:
            if t.get("state") not in ("uploading", "stalledUP", "forcedUP"):
                continue
            seeds = t.get("num_seeds", 0)
            leechs = t.get("num_leechs", 0)
            if seeds <= self.max_seeders and leechs >= self.min_leechers:
                dominant.append(t)

        for t in dominant:
            h = t["hash"]

            # Enable super seeding for piece-optimal distribution
            if not t.get("super_seeding", False):
                try:
                    client.set_super_seeding(h, True)
                except Exception:
                    pass

            # Force-start to bypass queue
            client.set_force_start(h, True)

            # Uncap upload
            if t.get("up_limit", 0) > 0:
                client.set_upload_limit(h, 0)

            # Set unlimited share ratio (keep seeding forever)
            try:
                client.set_share_limits(h, ratio_limit=-1, seeding_time_limit=-1)
            except Exception:
                pass

            # Force reannounce to attract more peers
            client.reannounce(h)

            # Tag for dashboard visibility
            if "DOMINATED" not in t.get("tags", ""):
                client.add_tags(h, "DOMINATED")

            if h not in self._dominated:
                self._dominated.add(h)
                ratio = f"{t.get('ratio', 0):.2f}"
                actions.append(
                    f"[DOMINATOR] Seized swarm: {t['name'][:35]} "
                    f"(Seeds: {t.get('num_seeds', 0)}, Leechs: {t.get('num_leechs', 0)}, Ratio: {ratio})"
                )
                if self.notifier:
                    self.notifier.send(
                        f"👊 <b>Swarm Dominated</b>\n\n"
                        f"📦 <code>{t['name'][:50]}</code>\n"
                        f"🌱 Seeders: <b>{t.get('num_seeds', 0)}</b> | "
                        f"👥 Leechers: <b>{t.get('num_leechs', 0)}</b>\n"
                        f"Super-Seed + Force-Start + Unlimited ratio active."
                    )

        # Clean up tags for torrents no longer dominated
        current_dominant_hashes = {t["hash"] for t in dominant}
        lost = self._dominated - current_dominant_hashes
        for h in lost:
            self._dominated.discard(h)
            try:
                client.remove_tags(h, "DOMINATED")
            except Exception:
                pass

        return actions


class TrackerBoosterRule(Rule):
    """Inject well-known public UDP trackers into all torrents to maximize peer discovery.
    Only adds to torrents that don't already have these trackers.
    Runs once per torrent (tracked by hash)."""
    name = "tracker_booster"

    PUBLIC_TRACKERS = [
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://open.demonii.com:1337/announce",
        "udp://tracker.openbittorrent.com:6969/announce",
        "udp://exodus.desync.com:6969/announce",
        "udp://tracker.torrent.eu.org:451/announce",
        "udp://open.stealth.si:80/announce",
    ]

    def __init__(self):
        self._boosted_hashes = set()

    def evaluate(self, client, torrents):
        actions = []
        for t in torrents:
            h = t["hash"]
            if h in self._boosted_hashes:
                continue

            try:
                existing = client.get_trackers(h)
                existing_urls = {tr.get("url", "") for tr in existing}

                new_trackers = [u for u in self.PUBLIC_TRACKERS if u not in existing_urls]
                if new_trackers:
                    client.add_trackers(h, new_trackers)
                    actions.append(f"[BOOSTER] Injected {len(new_trackers)} tracker(s) into {t['name'][:35]}")
            except Exception:
                pass

            self._boosted_hashes.add(h)

        return actions


class RevengeRule(Rule):
    """Identify torrents where you downloaded a lot but uploaded very little (ratio < threshold).
    Force-seed these aggressively: uncap, super-seed, force-start, reannounce.
    Goal: Pay back what you took and build ratio on torrents that hurt you."""
    name = "revenge_rule"

    def __init__(self, revenge_below_ratio=0.5, min_downloaded_mb=100, notifier=None):
        self.revenge_ratio = revenge_below_ratio
        self.min_downloaded = min_downloaded_mb * 1024 * 1024
        self.notifier = notifier
        self._revenging = set()

    def evaluate(self, client, torrents):
        actions = []

        for t in torrents:
            h = t["hash"]
            if t.get("state") not in ("uploading", "stalledUP", "forcedUP", "pausedUP", "queuedUP"):
                continue

            downloaded = t.get("downloaded", 0)
            ratio = t.get("ratio", 0)

            if downloaded >= self.min_downloaded and ratio < self.revenge_ratio:
                # This torrent is hurting our ratio — attack it
                if t.get("state") in ("pausedUP", "queuedUP"):
                    client.resume(h)
                    client.set_force_start(h, True)

                if t.get("up_limit", 0) > 0:
                    client.set_upload_limit(h, 0)

                if not t.get("super_seeding", False) and t.get("num_leechs", 0) >= 1:
                    try:
                        client.set_super_seeding(h, True)
                    except Exception:
                        pass

                # Set unlimited share ratio
                try:
                    client.set_share_limits(h, ratio_limit=-1, seeding_time_limit=-1)
                except Exception:
                    pass

                # Tag it
                if "REVENGE" not in t.get("tags", ""):
                    client.add_tags(h, "REVENGE")

                if h not in self._revenging:
                    self._revenging.add(h)
                    actions.append(
                        f"[REVENGE] Targeting {t['name'][:35]} "
                        f"(DL: {downloaded / (1024**3):.1f} GB, Ratio: {ratio:.2f})"
                    )

            elif h in self._revenging and ratio >= self.revenge_ratio:
                # Ratio recovered — mission accomplished
                self._revenging.discard(h)
                try:
                    client.remove_tags(h, "REVENGE")
                except Exception:
                    pass
                actions.append(f"[REVENGE] Mission complete: {t['name'][:35]} (Ratio: {ratio:.2f})")
                if self.notifier:
                    self.notifier.send(
                        f"✅ <b>Revenge Complete</b>\n\n"
                        f"📦 <code>{t['name'][:50]}</code>\n"
                        f"📊 Ratio recovered to <b>{ratio:.2f}</b>",
                        silent=True,
                    )

        return actions


class AutomationEngine:
    """Beast-mode automation engine with adaptive intervals and daily digest."""

    def __init__(self, client: QBitClient, rules=None, interval_sec=300, notifier=None):
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
        self.base_interval = interval_sec
        self.interval = interval_sec
        self.notifier = notifier
        self._stop = threading.Event()
        self._thread = None
        self.last_actions = []
        self.cycle_count = 0
        self.total_actions = 0
        self._last_digest_hour = -1
        self._session_start = time.time()

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
        self.cycle_count += 1
        self.total_actions += len(actions)

        # Adaptive interval: if many actions fired, check more frequently
        action_count = len([a for a in actions if not a.startswith("[ERROR]")])
        if action_count >= 10:
            self.interval = max(self.base_interval // 3, 60)
        elif action_count >= 5:
            self.interval = max(self.base_interval // 2, 90)
        else:
            self.interval = self.base_interval

        return actions

    def _send_daily_digest(self, transfer, torrents):
        """Send a daily Telegram digest at a configured hour."""
        current_hour = datetime.now().hour
        if current_hour != 8 or self._last_digest_hour == current_hour:
            return
        if not self.notifier or not self.notifier.enabled:
            return

        self._last_digest_hour = current_hour
        total_up = sum(t.get("uploaded", 0) for t in torrents)
        total_dl = sum(t.get("downloaded", 0) for t in torrents)
        ratio = total_up / max(total_dl, 1)
        seeding = sum(1 for t in torrents if t.get("state", "").startswith("upload") or t.get("state") == "stalledUP")
        up_speed = transfer.get("up_info_speed", 0)
        uptime = (time.time() - self._session_start) / 3600

        from tracker_stats import format_bytes, format_speed
        self.notifier.send(
            f"📊 <b>IGS Daily Digest</b>\n\n"
            f"⬆️ Total Uploaded: <b>{format_bytes(total_up)}</b>\n"
            f"📈 Global Ratio: <b>{ratio:.3f}</b>\n"
            f"🌱 Seeding: <b>{seeding}</b> / {len(torrents)} torrents\n"
            f"⚡ Current Speed: <b>{format_speed(up_speed)}</b>\n"
            f"🔄 Engine Cycles: <b>{self.cycle_count}</b> ({self.total_actions} actions)\n"
            f"⏱️ Uptime: <b>{uptime:.1f}h</b>"
        )

    def _loop(self):
        while not self._stop.is_set():
            try:
                actions = self.run_once()

                # Try daily digest
                try:
                    transfer = self.client.get_global_transfer_info()
                    torrents = self.client.get_torrents()
                    self._send_daily_digest(transfer, torrents)
                except Exception:
                    pass

                if actions:
                    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
                    print(f"[{timestamp}] Cycle #{self.cycle_count} — {len(actions)} action(s) (next in {self.interval}s):")
                    for a in actions:
                        print(f"  - {a}")
            except Exception as e:
                print(f"[Automation Error] {e}")
            self._stop.wait(self.interval)

    def start(self):
        """Start the automation loop in a background thread."""
        self._stop.clear()
        self._session_start = time.time()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[Automation] Started (interval: {self.interval}s, rules: {len(self.rules)})")

    def stop(self):
        """Stop the automation loop."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        print(f"[Automation] Stopped after {self.cycle_count} cycles, {self.total_actions} total actions.")
