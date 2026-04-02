"""IGS - Streamlit Web Dashboard v2.0 with live alert panels and dark theme."""

import streamlit as st
import plotly.graph_objects as go
import json
import os
import time

from qbit_client import QBitClient
from tracker_stats import get_live_summary, get_tracker_breakdown, format_bytes, format_speed
from database import init_db, get_global_history

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

# ── Styles ────────────────────────────────────────────────────────────────────
CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
    
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .stApp { background-color: #0a0c10; }

    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #141922, #1c2333);
        border-radius: 12px;
        padding: 14px 18px;
        border: 1px solid #252d40;
    }

    [data-testid="stMetricLabel"] { color: #8b9ab5 !important; font-size: 0.75rem !important; }
    [data-testid="stMetricValue"] { color: #e4eaf4 !important; font-size: 1.4rem !important; font-weight: 700 !important; }

    .alert-box {
        border-radius: 10px;
        padding: 14px 18px;
        margin: 6px 0;
        display: flex;
        align-items: center;
        gap: 12px;
        font-size: 0.9rem;
        font-weight: 500;
    }
    .alert-danger {
        background: rgba(220, 38, 38, 0.1);
        border: 1px solid rgba(220, 38, 38, 0.4);
        color: #f87171;
    }
    .alert-gold {
        background: rgba(245, 158, 11, 0.1);
        border: 1px solid rgba(245, 158, 11, 0.4);
        color: #fbbf24;
    }
    .alert-blue {
        background: rgba(59, 130, 246, 0.1);
        border: 1px solid rgba(59, 130, 246, 0.4);
        color: #60a5fa;
    }
    .alert-green {
        background: rgba(16, 185, 129, 0.1);
        border: 1px solid rgba(16, 185, 129, 0.4);
        color: #34d399;
    }

    .dictatorship-banner {
        background: linear-gradient(90deg, rgba(245,158,11,0.15), rgba(239,68,68,0.15));
        border: 1px solid rgba(245,158,11,0.6);
        border-radius: 12px;
        padding: 16px 22px;
        margin: 12px 0;
        text-align: center;
        animation: pulse-border 2s infinite;
    }
    @keyframes pulse-border {
        0%, 100% { border-color: rgba(245,158,11,0.6); }
        50% { border-color: rgba(239,68,68,0.9); }
    }
    .dictatorship-title {
        font-size: 1.2rem;
        font-weight: 700;
        color: #fbbf24;
        letter-spacing: 0.05em;
    }

    div[data-testid="stDataFrame"] {
        background: #141922 !important;
        border-radius: 10px;
        border: 1px solid #252d40;
    }

    h2, h3 { color: #c8d6ef !important; font-weight: 600 !important; }
    hr { border-color: #1e2737 !important; }
</style>
"""


@st.cache_resource
def get_client():
    with open(CONFIG_FILE) as f:
        config = json.load(f)
    qb = config["qbittorrent"]
    return QBitClient(host=qb["host"], port=qb["port"], username=qb["username"], password=qb["password"])


def get_state_badge(state: str) -> str:
    badges = {
        "uploading":   "🟢 Uploading",
        "stalledUP":   "🟡 Stalled",
        "pausedUP":    "⏸️ Paused",
        "queuedUP":    "⏳ Queued",
        "forcedUP":    "🔥 Forced",
        "downloading": "🔵 DL",
        "stalledDL":   "🔵 Stalled DL",
        "forcedDL":    "🔵 Forced DL",
        "pausedDL":    "⏸️ Paused DL",
        "error":       "🔴 Error",
    }
    return badges.get(state, f"⚪ {state}")


def render_alerts(torrents):
    """Render danger alerts for torrents tagged MALWARE-WARNING or Dictatorship mode."""
    malware_torrents = [t for t in torrents if "MALWARE-WARNING" in t.get("tags", "")]
    golden_torrents  = [t for t in torrents if t.get("num_seeds", 0) == 0 and t.get("num_leechs", 0) >= 2 and t["state"] == "uploading"]
    hr_pending       = [t for t in torrents if "H&R-Pending" in t.get("tags", "")]

    if not (malware_torrents or golden_torrents or hr_pending):
        st.markdown('<div class="alert-box alert-green">✅ No active alerts. All systems nominal.</div>', unsafe_allow_html=True)
        return

    if golden_torrents:
        gt = golden_torrents[0]
        st.markdown(f"""
        <div class="dictatorship-banner">
            <div class="dictatorship-title">👑 DICTATORSHIP MODE ACTIVE</div>
            <div style="color:#e4eaf4;margin-top:6px;font-size:0.9rem;">
                Seizing 100% bandwidth → <strong>{gt['name'][:60]}</strong>
                &nbsp;|&nbsp; Leechers: <strong>{gt.get('num_leechs',0)}</strong>
                &nbsp;|&nbsp; Upload: <strong>{format_speed(gt.get('up_speed',0))}</strong>
            </div>
        </div>
        """, unsafe_allow_html=True)

    for t in malware_torrents:
        st.markdown(f'<div class="alert-box alert-danger">🚨 MALWARE DETECTED &amp; PAUSED → <strong>{t["name"][:60]}</strong></div>', unsafe_allow_html=True)

    for t in hr_pending:
        seeding_time = t.get("seeding_time", 0)
        st.markdown(f'<div class="alert-box alert-gold">⏳ H&amp;R Clearance Pending → <strong>{t["name"][:50]}</strong> ({seeding_time/3600:.1f}h seeded)</div>', unsafe_allow_html=True)

    # Dominated swarms
    dominated = [t for t in torrents if "DOMINATED" in t.get("tags", "")]
    for t in dominated:
        st.markdown(
            f'<div class="alert-box alert-blue">👊 SWARM DOMINATED → <strong>{t["name"][:50]}</strong> '
            f'(Seeds: {t.get("num_seeds",0)} | Leechs: {t.get("num_leechs",0)} | '
            f'⬆️ {format_speed(t.get("up_speed",0))})</div>',
            unsafe_allow_html=True
        )

    # Revenge targets
    revenge = [t for t in torrents if "REVENGE" in t.get("tags", "")]
    for t in revenge:
        st.markdown(
            f'<div class="alert-box alert-danger">⚔️ REVENGE TARGET → <strong>{t["name"][:50]}</strong> '
            f'(Ratio: {t.get("ratio",0):.2f} | DL: {format_bytes(t.get("downloaded",0))})</div>',
            unsafe_allow_html=True
        )


def main():
    st.set_page_config(page_title="IGS Dashboard", page_icon="🌐", layout="wide", initial_sidebar_state="collapsed")
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    init_db()

    # ── Header ────────────────────────────────────────────────────
    st.markdown("### 🌐 IGS · Intelligent Seeding Suite")
    st.caption("Live seedbox command center")

    try:
        client = get_client()
    except Exception as e:
        st.error(f"Cannot connect to qBittorrent: {e}")
        st.info("Make sure qBittorrent is running with WebUI enabled and config.json is correct.")
        return

    torrents = client.get_torrents(sort="uploaded")
    summary  = get_live_summary(client)

    # ── ISP Mode indicator ────────────────────────────────────────
    alt_mode_active = False
    try:
        alt_mode_active = client.get_speed_limits_mode() == 1
    except Exception:
        pass

    # ── Alert Panel ───────────────────────────────────────────────
    st.markdown("#### 🔔 Live Alerts")
    render_alerts(torrents)
    st.divider()

    # ── Stats Row ─────────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("⬆️ Upload Speed",   format_speed(summary["upload_speed"]) + (" 🛡️" if alt_mode_active else ""))
    col2.metric("⬇️ Download Speed", format_speed(summary["download_speed"]))
    col3.metric("📊 Global Ratio",   f"{summary['global_ratio']:.3f}")
    col4.metric("🌱 Seeding",        f"{summary['seeding_count']} / {summary['total_count']}")
    col5.metric("☁️ ISP Mode",       "🛡️ Alt Limits" if alt_mode_active else "🔓 Full Speed")

    st.divider()

    # ── Upload Goal Progress ───────────────────────────────────────
    with open(CONFIG_FILE) as f:
        _cfg = json.load(f)
    target_tb  = _cfg.get("automation", {}).get("rules", {}).get("upload_goal", {}).get("target_tb", 1.0)
    target_bytes = int(target_tb * 1024**4)
    total_uploaded = summary["total_uploaded"]
    goal_pct = min(total_uploaded / target_bytes, 1.0)

    # Determine active phase
    if goal_pct >= 0.80:
        phase_name, phase_icon, phase_color = "BEAST", "🔥", "red"
    elif goal_pct >= 0.50:
        phase_name, phase_icon, phase_color = "ASSAULT", "⚔️", "orange"
    else:
        phase_name, phase_icon, phase_color = "CRUISE", "🚢", "blue"

    st.subheader(f"🎯 Upload Goal — {target_tb:.0f} TB")

    # Phase banner
    phase_styles = {
        "BEAST": ("rgba(239,68,68,0.15)", "rgba(239,68,68,0.6)", "#f87171"),
        "ASSAULT": ("rgba(245,158,11,0.15)", "rgba(245,158,11,0.5)", "#fbbf24"),
        "CRUISE": ("rgba(59,130,246,0.12)", "rgba(59,130,246,0.4)", "#60a5fa"),
    }
    bg, border, color = phase_styles[phase_name]
    st.markdown(f"""
    <div style="background:{bg};border:1px solid {border};border-radius:10px;padding:10px 18px;margin-bottom:12px;display:flex;align-items:center;gap:12px;">
        <span style="font-size:1.5rem;">{phase_icon}</span>
        <span style="color:{color};font-weight:700;font-size:1rem;letter-spacing:0.04em;">PHASE: {phase_name}</span>
        <span style="color:#8b9ab5;font-size:0.82rem;margin-left:auto;">
            {"Uncap + Super-Seed + Reannounce" if phase_name == "CRUISE" else ""}
            {"+ Force-Start + Priority Boost + DL Throttle" if phase_name == "ASSAULT" else ""}
            {"+ Resume All + Kill Downloads + Max Peers" if phase_name == "BEAST" else ""}
        </span>
    </div>
    """, unsafe_allow_html=True)

    col_g1, col_g2, col_g3 = st.columns(3)
    col_g1.metric("Uploaded",  format_bytes(total_uploaded))
    col_g2.metric("Remaining", format_bytes(max(target_bytes - total_uploaded, 0)))
    col_g3.metric("Progress",  f"{goal_pct*100:.2f}%")
    st.progress(goal_pct)

    if goal_pct >= 1.0:
        st.success("🏆 GOAL REACHED! You've uploaded 1 TB!")
    elif summary["upload_speed"] > 0:
        eta_sec = max(target_bytes - total_uploaded, 0) / summary["upload_speed"]
        eta_str = f"{eta_sec/86400:.1f} days" if eta_sec >= 86400 else f"{eta_sec/3600:.1f} hours"
        st.caption(f"⏱️ ETA at current speed: ~{eta_str}")

    st.divider()

    # ── Transfer Totals + Tracker Breakdown ───────────────────────
    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("Transfer Totals")
        st.metric("Total Uploaded",   format_bytes(summary["total_uploaded"]))
        st.metric("Total Downloaded", format_bytes(summary["total_downloaded"]))

    with col_right:
        st.subheader("Per-Tracker Breakdown")
        breakdown = get_tracker_breakdown(client)
        if breakdown:
            tracker_data = [
                {
                    "Tracker":  host,
                    "Torrents": s["count"],
                    "Seeding":  s["seeding"],
                    "Uploaded": format_bytes(s["uploaded"]),
                    "Ratio":    round(s["ratio"], 2),
                }
                for host, s in sorted(breakdown.items(), key=lambda x: x[1]["uploaded"], reverse=True)
            ]
            st.dataframe(tracker_data, width="stretch", hide_index=True)
        else:
            st.info("No tracker data available.")

    st.divider()

    # ── Top Seeders ───────────────────────────────────────────────
    st.subheader("🏆 Top Seeders")
    if summary["top_seeders"]:
        top_data = [
            {
                "Name":     t["name"][:55],
                "Uploaded": format_bytes(t.get("uploaded", 0)),
                "Ratio":    round(t.get("ratio", 0), 2),
                "State":    get_state_badge(t.get("state", "?")),
                "Seeds":    t.get("num_seeds", 0),
                "Leeches":  t.get("num_leechs", 0),
                "Tags":     t.get("tags", ""),
            }
            for t in summary["top_seeders"]
        ]
        st.dataframe(top_data, width="stretch", hide_index=True)
    else:
        st.info("No seeding torrents found.")

    # ── Swarm Dominance Panel ─────────────────────────────────────
    dominated_torrents = [t for t in torrents if "DOMINATED" in t.get("tags", "")]
    revenge_torrents = [t for t in torrents if "REVENGE" in t.get("tags", "")]

    if dominated_torrents or revenge_torrents:
        st.divider()
        col_dom, col_rev = st.columns(2)

        with col_dom:
            st.subheader("👊 Dominated Swarms")
            if dominated_torrents:
                dom_data = [
                    {
                        "Name": t["name"][:45],
                        "Seeds": t.get("num_seeds", 0),
                        "Leechs": t.get("num_leechs", 0),
                        "Upload": format_bytes(t.get("uploaded", 0)),
                        "Speed": format_speed(t.get("up_speed", 0)),
                        "Ratio": round(t.get("ratio", 0), 2),
                    }
                    for t in sorted(dominated_torrents, key=lambda x: x.get("num_leechs", 0), reverse=True)
                ]
                st.dataframe(dom_data, width="stretch", hide_index=True)
            else:
                st.caption("No dominated swarms currently.")

        with col_rev:
            st.subheader("⚔️ Revenge Targets")
            if revenge_torrents:
                rev_data = [
                    {
                        "Name": t["name"][:45],
                        "Downloaded": format_bytes(t.get("downloaded", 0)),
                        "Uploaded": format_bytes(t.get("uploaded", 0)),
                        "Ratio": round(t.get("ratio", 0), 2),
                        "State": get_state_badge(t.get("state", "?")),
                    }
                    for t in sorted(revenge_torrents, key=lambda x: x.get("ratio", 0))
                ]
                st.dataframe(rev_data, width="stretch", hide_index=True)
            else:
                st.caption("No revenge targets currently.")

    # ── Historical Charts ─────────────────────────────────────────
    st.divider()
    st.subheader("📈 Upload History")
    hours   = st.slider("Hours to display", 1, 720, 168, step=24)
    history = get_global_history(hours=hours)

    if history:
        timestamps = [h["timestamp"] for h in history]
        uploaded   = [h["total_uploaded"] / (1024**3) for h in history]
        up_speeds  = [h["upload_speed"] / (1024**2) for h in history]

        col_chart1, col_chart2 = st.columns(2)

        with col_chart1:
            st.caption("Total Uploaded (GB)")
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=timestamps, y=uploaded,
                mode="lines",
                fill="tozeroy",
                name="Total Uploaded (GB)",
                line=dict(color="#34d399", width=2),
                fillcolor="rgba(52,211,153,0.1)"
            ))
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="#0a0c10",
                plot_bgcolor="#0a0c10",
                height=280,
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(family="Inter"),
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_chart2:
            st.caption("Upload Speed (MB/s)")
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=timestamps, y=up_speeds,
                mode="lines",
                fill="tozeroy",
                name="Upload Speed (MB/s)",
                line=dict(color="#60a5fa", width=2),
                fillcolor="rgba(96,165,250,0.1)"
            ))
            fig2.update_layout(
                template="plotly_dark",
                paper_bgcolor="#0a0c10",
                plot_bgcolor="#0a0c10",
                height=280,
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(family="Inter"),
            )
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No historical data yet. Run `python main.py start` or `python main.py beast` to begin recording.")

    # ── All Torrents Expander ─────────────────────────────────────
    with st.expander("📋 All Torrents", expanded=False):
        if torrents:
            all_data = [
                {
                    "Name":       t["name"][:55],
                    "Size":       format_bytes(t.get("size", 0)),
                    "Uploaded":   format_bytes(t.get("uploaded", 0)),
                    "Downloaded": format_bytes(t.get("downloaded", 0)),
                    "Ratio":      round(t.get("ratio", 0), 2),
                    "State":      get_state_badge(t.get("state", "?")),
                    "Tags":       t.get("tags", ""),
                }
                for t in torrents
            ]
            st.dataframe(all_data, width="stretch", hide_index=True)

    # ── Auto Refresh ──────────────────────────────────────────────
    st.divider()
    col_r1, col_r2 = st.columns([1, 3])
    with col_r1:
        if st.button("🔄 Refresh Now"):
            st.rerun()
    with col_r2:
        if st.checkbox("⏱️ Auto-refresh every 30s"):
            time.sleep(30)
            st.rerun()


if __name__ == "__main__":
    main()
