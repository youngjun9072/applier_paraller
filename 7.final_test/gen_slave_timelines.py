"""Generate slave-only timeline charts (no master bars).

Origin (t=0) is the first slave apply, so charts focus on slave behavior alone.
Outputs `{run}_slave_insert.png` / `{run}_slave_update.png` in each run dir.
"""

from pathlib import Path
import re
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, Rectangle

BASE = Path(__file__).parent
WORKERS = 10
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

COLOR_BG = "#F7F9FC"
COLOR_GRID = "#D9DEE6"
COLOR_SLAVE = "#E07A1F"
COLOR_TEXT = "#1F2A37"
COLOR_TEXT_MUTED = "#5A6473"
COLOR_BAND = "#EEF2F7"


def parse_time(s):
    return datetime.strptime(s.strip(), "%H:%M:%S.%f")


def parse_file(path):
    text = path.read_text()
    sections = {"Insert": {"master": [], "slave": []},
                "Update": {"master": [], "slave": []}}
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
                tbl, start, end, _ = m.groups()
                sections[current_op][current_role].append(
                    (tbl, parse_time(start), parse_time(end))
                )
    return sections


def metrics(slave_rows):
    s_start = min(r[1] for r in slave_rows)
    s_end = max(r[2] for r in slave_rows)
    s_elapsed = (s_end - s_start).total_seconds()
    slave_sum = sum((r[2] - r[1]).total_seconds() for r in slave_rows)
    eff_par = slave_sum / s_elapsed if s_elapsed > 0 else 0
    return {
        "s_start": s_start, "s_end": s_end, "s_elapsed": s_elapsed,
        "slave_sum": slave_sum, "eff_par": eff_par,
        "mode": "parallel" if eff_par > 1.05 else "sequential",
    }


def draw_chart(run_name, op, slave_rows, out_path):
    slave_start = {r[0]: r[1] for r in slave_rows}
    table_order = sorted({r[0] for r in slave_rows},
                         key=lambda t: (slave_start.get(t), int(t[3:])))
    n = len(table_order)
    M = metrics(slave_rows)

    fig = plt.figure(figsize=(14.5, max(7.5, 0.62 * n + 4.0)), facecolor=COLOR_BG)
    ax = fig.add_axes([0.07, 0.06, 0.88, 0.76])
    ax.set_facecolor(COLOR_BG)

    t0 = M["s_start"]

    def to_sec(t):
        return (t - t0).total_seconds()

    for idx in range(n):
        y = n - idx
        if idx % 2 == 0:
            ax.axhspan(y - 0.5, y + 0.5, facecolor=COLOR_BAND, alpha=0.55, zorder=0)

    bar_h = 0.55

    for idx, tbl in enumerate(table_order):
        y = n - idx
        for r in slave_rows:
            if r[0] == tbl:
                s = to_sec(r[1]); d = to_sec(r[2]) - s
                ax.barh(y, d, left=s, height=bar_h,
                        color=COLOR_SLAVE, edgecolor="white", linewidth=0.8,
                        zorder=3)
                ax.text(s + d / 2, y, f"{d:.1f}s",
                        ha="center", va="center", fontsize=9,
                        color="white", fontweight="700", zorder=4)

    s_x0 = to_sec(M["s_start"])
    s_x1 = to_sec(M["s_end"])

    def bracket(ax, x0, x1, y, color, label):
        ax.plot([x0, x1], [y, y], color=color, linewidth=2.2, zorder=3)
        cap = 0.13
        ax.plot([x0, x0], [y - cap, y + cap], color=color, linewidth=2.2, zorder=3)
        ax.plot([x1, x1], [y - cap, y + cap], color=color, linewidth=2.2, zorder=3)
        mid = (x0 + x1) / 2
        ax.text(mid, y, label, ha="center", va="center",
                fontsize=11, color=color, fontweight="800", zorder=5,
                bbox=dict(boxstyle="round,pad=0.35",
                          facecolor=COLOR_BG, edgecolor="none"))

    bracket(ax, s_x0, s_x1, 0, COLOR_SLAVE,
            f"SLAVE ELAPSED · {M['s_elapsed']:.1f}s")
    ax.axhline(0.58, color=COLOR_TEXT_MUTED, linewidth=1.0, alpha=0.6, zorder=1)

    yticks = [0] + list(range(1, n + 1))
    yticklabels = ["TOTAL"] + list(reversed(table_order))
    ax.set_yticks(yticks)
    ax.set_yticklabels(yticklabels, fontsize=10, color=COLOR_TEXT, fontweight="600")
    ax.tick_params(axis="y", length=0)
    total_lbl = ax.get_yticklabels()[0]
    total_lbl.set_fontsize(11)
    total_lbl.set_fontweight("900")
    total_lbl.set_color("#8B3300")

    ax.tick_params(axis="x", colors=COLOR_TEXT_MUTED, labelsize=9)
    ax.grid(axis="x", linestyle=":", color=COLOR_GRID, linewidth=0.8, alpha=0.9, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(COLOR_GRID)

    # Fixed x-axis (120s) — covers max slave elapsed (dev_tuned Update ~112s)
    ax.set_xlim(-2, 120)
    ax.set_ylim(-0.55, n + 1.0)

    op_icon = "▶" if op == "Insert" else "✎"
    fig.text(0.07, 0.92, f"{op_icon}  {op.upper()} TIMELINE  (slave only)",
             fontsize=20, fontweight="bold", color=COLOR_TEXT, ha="left")

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

    handles = [mpatches.Patch(color=COLOR_SLAVE, label="slave")]
    ax.legend(handles=handles,
              loc="lower right", bbox_to_anchor=(1.0, 1.005),
              ncol=1, frameon=False, fontsize=9.5,
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
        slave = data[op]["slave"]
        if not slave:
            continue
        out = BASE / run / f"{run}_slave_{op.lower()}.png"
        draw_chart(run, op, slave, out)
        print(f"wrote {out.relative_to(BASE)}")
