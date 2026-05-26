"""Generate styled timeline charts. 2 PNGs per run (insert/update), both master+slave."""

from pathlib import Path
import re
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, Rectangle

BASE = Path(__file__).parent
WORKERS = 10  # configured slave applier workers
RUNS = [
    "1.dev_baseline",
    "2.dev_tuned",
    "3.poc_buf5g_dwb1",
    "4.poc_bufdef_dwb0",
    "5.poc_bufdef_dwb1",
    "6.poc_buf5g_dwb0",
    "7.poc_baseline",
]

ROW_RE = re.compile(r"^\|\s*(tbl\d+)\s*\|\s*([\d:.]+)\s*\|\s*([\d:.]+)\s*\|\s*([\d.]+)\s*\|")

# Modern color palette
COLOR_BG = "#F7F9FC"
COLOR_GRID = "#D9DEE6"
COLOR_MASTER = "#1F77B4"
COLOR_MASTER_LIGHT = "#A6CEE3"
COLOR_SLAVE = "#E07A1F"
COLOR_SLAVE_LIGHT = "#FFD8A8"
COLOR_LAG = "#E94B6A"
COLOR_TEXT = "#1F2A37"
COLOR_TEXT_MUTED = "#5A6473"
COLOR_BAND = "#EEF2F7"


def parse_time(s):
    return datetime.strptime(s.strip(), "%H:%M:%S.%f")


def parse_file(path):
    text = path.read_text()
    sections = {"Insert": {"master": [], "slave": []}, "Update": {"master": [], "slave": []}}
    current_op = None
    current_role = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## Insert"):
            current_op, current_role = "Insert", None
        elif s.startswith("## Update"):
            current_op, current_role = "Update", None
        elif s.startswith("### master"):
            current_role = "master"
        elif s.startswith("### slave"):
            current_role = "slave"
        elif current_op and current_role:
            m = ROW_RE.match(s)
            if m:
                tbl, start, end, _dur = m.groups()
                sections[current_op][current_role].append(
                    (tbl, parse_time(start), parse_time(end))
                )
    return sections


def metrics(master_rows, slave_rows):
    m_start = min(r[1] for r in master_rows)
    m_end = max(r[2] for r in master_rows)
    s_start = min(r[1] for r in slave_rows)
    s_end = max(r[2] for r in slave_rows)
    m_elapsed = (m_end - m_start).total_seconds()
    s_elapsed = (s_end - s_start).total_seconds()
    slave_sum = sum((r[2] - r[1]).total_seconds() for r in slave_rows)
    eff_par = slave_sum / s_elapsed if s_elapsed > 0 else 0
    # Per-table lag: slave end - master end for the same table
    master_end_by_tbl = {}
    for r in master_rows:
        master_end_by_tbl[r[0]] = max(master_end_by_tbl.get(r[0], r[2]), r[2])
    slave_end_by_tbl = {}
    for r in slave_rows:
        slave_end_by_tbl[r[0]] = max(slave_end_by_tbl.get(r[0], r[2]), r[2])
    per_tbl_lag = {
        t: (slave_end_by_tbl[t] - master_end_by_tbl[t]).total_seconds()
        for t in master_end_by_tbl if t in slave_end_by_tbl
    }
    return {
        "m_start": m_start, "m_end": m_end, "s_start": s_start, "s_end": s_end,
        "m_elapsed": m_elapsed, "s_elapsed": s_elapsed,
        "slave_sum": slave_sum, "eff_par": eff_par,
        "per_tbl_lag": per_tbl_lag,
        "lag_max": max(per_tbl_lag.values()) if per_tbl_lag else 0,
        "lag_avg": (sum(per_tbl_lag.values()) / len(per_tbl_lag)) if per_tbl_lag else 0,
        "master_end_by_tbl": master_end_by_tbl,
        "slave_end_by_tbl": slave_end_by_tbl,
        # eff.par ≤ 1 means sum ≤ elapsed → no concurrent work → sequential.
        # Small tolerance for handoff noise.
        "mode": "parallel" if eff_par > 1.05 else "sequential",
    }


def draw_card(ax, x, y, w, h, title, value, sub, color, value_color=None):
    """Draw a stat card at axes-fraction coords."""
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.005,rounding_size=0.012",
        linewidth=0, facecolor=color, alpha=0.12,
        transform=ax.transAxes, clip_on=False, zorder=5,
    )
    ax.add_patch(box)
    # left accent
    ax.add_patch(Rectangle((x, y), 0.006, h, facecolor=color, transform=ax.transAxes,
                           clip_on=False, zorder=6))
    ax.text(x + 0.018, y + h - 0.022, title, transform=ax.transAxes,
            fontsize=8.5, color=COLOR_TEXT_MUTED, fontweight="600",
            ha="left", va="top", zorder=7)
    ax.text(x + 0.018, y + h / 2 - 0.005, value, transform=ax.transAxes,
            fontsize=16, color=value_color or color, fontweight="bold",
            ha="left", va="center", zorder=7)
    ax.text(x + 0.018, y + 0.02, sub, transform=ax.transAxes,
            fontsize=8, color=COLOR_TEXT_MUTED,
            ha="left", va="bottom", zorder=7)


def draw_chart(run_name, op, master_rows, slave_rows, out_path):
    slave_start = {r[0]: r[1] for r in slave_rows}
    all_tbls = {r[0] for r in master_rows + slave_rows}
    table_order = sorted(all_tbls, key=lambda t: (slave_start.get(t), int(t[3:])))
    n = len(table_order)
    M = metrics(master_rows, slave_rows)

    fig = plt.figure(figsize=(14.5, max(7.5, 0.62 * n + 4.0)), facecolor=COLOR_BG)
    # Reserve top space for header card
    ax = fig.add_axes([0.07, 0.06, 0.88, 0.76])
    ax.set_facecolor(COLOR_BG)

    t0 = M["m_start"]
    t_end = M["s_end"]

    def to_sec(t):
        return (t - t0).total_seconds()

    # Alternating row bands
    for idx, tbl in enumerate(table_order):
        y = n - idx
        if idx % 2 == 0:
            ax.axhspan(y - 0.5, y + 0.5, facecolor=COLOR_BAND, alpha=0.55, zorder=0)

    bar_h = 0.32

    # Per-table lag arrows: master end → slave end for the same table
    for idx, tbl in enumerate(table_order):
        if tbl not in M["per_tbl_lag"]:
            continue
        y = n - idx
        x0 = to_sec(M["master_end_by_tbl"][tbl])
        x1 = to_sec(M["slave_end_by_tbl"][tbl])
        if x1 - x0 < 0.2:
            continue
        ax.annotate(
            "",
            xy=(x1, y), xytext=(x0, y),
            arrowprops=dict(arrowstyle="->,head_length=0.4,head_width=0.25",
                            color=COLOR_LAG, lw=1.1, alpha=0.85,
                            shrinkA=0, shrinkB=0),
            zorder=2,
        )
        lag_v = M["per_tbl_lag"][tbl]
        ax.text((x0 + x1) / 2, y + 0.02, f"{lag_v:.1f}s",
                ha="center", va="bottom",
                fontsize=7.2, color=COLOR_LAG, fontweight="700",
                zorder=4)

    # Draw bars
    for idx, tbl in enumerate(table_order):
        y = n - idx
        for r in master_rows:
            if r[0] == tbl:
                s = to_sec(r[1]); d = to_sec(r[2]) - s
                ax.barh(y + 0.18, d, left=s, height=bar_h,
                        color=COLOR_MASTER, edgecolor="white", linewidth=0.8,
                        zorder=3)
                ax.text(s + d / 2, y + 0.18, f"{d:.1f}s",
                        ha="center", va="center", fontsize=7.5,
                        color="white", fontweight="600", zorder=4)
        for r in slave_rows:
            if r[0] == tbl:
                s = to_sec(r[1]); d = to_sec(r[2]) - s
                ax.barh(y - 0.18, d, left=s, height=bar_h,
                        color=COLOR_SLAVE, edgecolor="white", linewidth=0.8,
                        zorder=3)
                ax.text(s + d / 2, y - 0.18, f"{d:.1f}s",
                        ha="center", va="center", fontsize=7.5,
                        color="white", fontweight="600", zorder=4)

    # No global end-line annotations; per-row lag arrows speak for themselves

    # Summary lane at bottom (y = 0): range brackets, not bars.
    m_x0, m_x1 = to_sec(M["m_start"]), to_sec(M["m_end"])
    s_x0, s_x1 = to_sec(M["s_start"]), to_sec(M["s_end"])

    def bracket(ax, x0, x1, y, color, label):
        # Horizontal line
        ax.plot([x0, x1], [y, y], color=color, linewidth=2.2,
                solid_capstyle="butt", zorder=3)
        # End caps (vertical ticks)
        cap = 0.13
        ax.plot([x0, x0], [y - cap, y + cap], color=color, linewidth=2.2, zorder=3)
        ax.plot([x1, x1], [y - cap, y + cap], color=color, linewidth=2.2, zorder=3)
        # Center label inside a white pill so the line shows through left/right
        mid = (x0 + x1) / 2
        ax.text(mid, y, label,
                ha="center", va="center",
                fontsize=11, color=color, fontweight="800",
                zorder=5,
                bbox=dict(boxstyle="round,pad=0.35",
                          facecolor=COLOR_BG, edgecolor="none"))

    bracket(ax, m_x0, m_x1, 0 + 0.22, COLOR_MASTER,
            f"MASTER · {M['m_elapsed']:.1f}s")
    bracket(ax, s_x0, s_x1, 0 - 0.22, COLOR_SLAVE,
            f"SLAVE · {M['s_elapsed']:.1f}s")
    # Divider between table rows and summary lane
    ax.axhline(0.58, color=COLOR_TEXT_MUTED, linewidth=1.0, alpha=0.6,
               linestyle="-", zorder=1)

    # Y axis (include summary lane at 0)
    yticks = [0] + list(range(1, n + 1))
    yticklabels = ["TOTAL"] + list(reversed(table_order))
    ax.set_yticks(yticks)
    ax.set_yticklabels(yticklabels,
                       fontsize=10, color=COLOR_TEXT, fontweight="600")
    ax.tick_params(axis="y", length=0)
    # Make TOTAL tick label visually distinct
    total_lbl = ax.get_yticklabels()[0]
    total_lbl.set_fontsize(11)
    total_lbl.set_fontweight("900")
    total_lbl.set_color("#11324D")

    # X axis (no bottom label per user preference)
    ax.tick_params(axis="x", colors=COLOR_TEXT_MUTED, labelsize=9)
    ax.grid(axis="x", linestyle=":", color=COLOR_GRID, linewidth=0.8, alpha=0.9, zorder=0)
    ax.set_axisbelow(True)

    # Strip spines
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(COLOR_GRID)

    # Fixed x-axis (300s) so all charts share the same scale, making
    # the speed-up from parallelization visually obvious.
    ax.set_xlim(-3, 300)
    ax.set_ylim(-0.55, n + 1.0)

    # ---- Header: title + worker-config note + (parallel only) info card ----
    op_icon = "▶" if op == "Insert" else "✎"
    fig.text(0.07, 0.92, f"{op_icon}  {op.upper()} TIMELINE",
             fontsize=20, fontweight="bold", color=COLOR_TEXT, ha="left")

    # Info card: run name + mode line (parallel = full stats, sequential = mode only)
    if M["mode"] == "parallel":
        accent_color = "#2BAE66"
        util_pct = (M["eff_par"] / WORKERS) * 100
        mode_line = (f"● PARALLEL  ·  {WORKERS} workers"
                     f"  ·  eff.par {M['eff_par']:.2f} / {WORKERS} expected"
                     f"  ·  {util_pct:.0f}% util")
        card_w = 0.50
    else:
        accent_color = "#9A6FB0"
        mode_line = "● SEQUENTIAL"
        card_w = 0.22
    card_x, card_y, card_h = 0.07, 0.842, 0.060
    bg = FancyBboxPatch(
        (card_x, card_y), card_w, card_h,
        boxstyle="round,pad=0.003,rounding_size=0.012",
        linewidth=0, facecolor=accent_color, alpha=0.10,
        transform=fig.transFigure, clip_on=False,
    )
    fig.patches.append(bg)
    accent = Rectangle((card_x, card_y), 0.005, card_h,
                       facecolor=accent_color,
                       transform=fig.transFigure, clip_on=False)
    fig.patches.append(accent)
    fig.text(card_x + 0.014, card_y + card_h - 0.013, run_name,
             fontsize=11, color=COLOR_TEXT, fontweight="800",
             ha="left", va="top")
    fig.text(card_x + 0.014, card_y + 0.012, mode_line,
             fontsize=9.5, color=accent_color, fontweight="700",
             ha="left", va="bottom")

    # Elapsed totals are shown in the bottom TOTAL lane instead of top cards.

    # Legend at top-left of plot area
    handles = [
        mpatches.Patch(color=COLOR_MASTER, label="master"),
        mpatches.Patch(color=COLOR_SLAVE, label="slave"),
        mpatches.Patch(color=COLOR_LAG, label="table lag (M→S)"),
    ]
    ax.legend(handles=handles,
              loc="lower right", bbox_to_anchor=(1.0, 1.005),
              ncol=3, frameon=False, fontsize=9.5,
              labelcolor=COLOR_TEXT, handlelength=1.6,
              columnspacing=1.8, handletextpad=0.6)

    fig.savefig(out_path, dpi=140, facecolor=COLOR_BG)
    plt.close(fig)


for run in RUNS:
    md_path = BASE / run / f"{run}.md"
    if not md_path.exists():
        print(f"missing {md_path}")
        continue
    data = parse_file(md_path)
    for op in ("Insert", "Update"):
        master = data[op]["master"]; slave = data[op]["slave"]
        if not master or not slave:
            continue
        out = BASE / run / f"{run}_{op.lower()}.png"
        draw_chart(run, op, master, slave, out)
        print(f"wrote {out.relative_to(BASE)}")
