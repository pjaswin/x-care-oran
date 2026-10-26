#!/usr/bin/env python3
"""Generate the result figures of the paper from data/processed/ into figures/.

  fig_legend.pdf              shared legend placed above each pair of half-column panels (one column wide)
  fig_rq1_reversals.pdf       cross-xApp reversals per run (box + ten seeds; number = median)        half column
  fig_rq1_handovers.pdf       executed handovers per run                                             half column
  fig_rq2_outage.pdf          CQM objective: share of time with serving SINR below 0 dB (mean)       half column
  fig_rq2_overload.pdf        MLB objective: share of time a cell is above 60 % PRB utilisation      half column
  fig_rq3_latency_ccdf.pdf    exceedance probability of per-UE 100-ms PDCP latency (ten seeds pooled), one column

Each figure is drawn at its final size (fonts 7-9 pt); include half-column panels with width=0.5\\columnwidth.
Usage:  python3 analysis/make_figures.py
"""
import csv, gzip, os, statistics as st
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb
from matplotlib.patches import Patch
import common as cm

OUT = os.path.join(cm.ROOT, "figures")
HUE = {"baseline": "#4a4a4a", "x-care": "#2a78d6", "priority-cqm": "#eb6834", "priority-mlb": "#1baf7a"}
INK, WHISK, GRID, REF = "#111111", "#333333", "#dedede", "#d62728"
HALF_W, HALF_H = 1.75, 1.64                                  # inches
M_LEFT, M_RIGHT, M_BOTTOM, M_TOP = 0.43, 0.04, 0.12, 0.06


def mix(c, w): return tuple(w * np.array(to_rgb(c)) + (1 - w))
def shade(c, k): return tuple(np.array(to_rgb(c)) * k)


FILL = {k: mix(v, 0.45) for k, v in HUE.items()}
EDGE = {k: shade(v, 0.72) for k, v in HUE.items()}
DOT = {k: shade(v, 0.62) for k, v in HUE.items()}

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Liberation Serif", "Nimbus Roman", "TeX Gyre Termes", "Times New Roman", "DejaVu Serif"],
    "pdf.fonttype": 42, "ps.fonttype": 42,
    "text.color": INK, "axes.labelcolor": INK, "axes.edgecolor": INK, "xtick.color": INK, "ytick.color": INK,
    "axes.linewidth": 0.7, "axes.labelsize": 8, "axes.labelweight": "bold", "axes.labelpad": 2,
    "xtick.labelsize": 8, "ytick.labelsize": 7.5, "xtick.major.size": 2.5, "ytick.major.size": 2.5, "ytick.minor.size": 1.5,
    "xtick.major.width": 0.7, "ytick.major.width": 0.7,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white"})


def half_up(x): return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def check_and_save(fig, name):
    """Every text at least 0.03 in inside the canvas and no two texts overlapping, then save PDF + PNG."""
    fig.canvas.draw(); r = fig.canvas.get_renderer(); W, H = fig.bbox.width, fig.bbox.height; m = 0.03 * fig.dpi
    boxes = [(t.get_text(), t.get_window_extent(r)) for t in fig.findobj(plt.Text) if t.get_visible() and t.get_text().strip()]
    clipped = [s for s, b in boxes if b.x0 < m or b.y0 < m or b.x1 > W - m or b.y1 > H - m]
    overlap = [(a, b) for i, (a, ba) in enumerate(boxes) for (b, bb) in boxes[i + 1:] if ba.overlaps(bb)]
    assert not clipped and not overlap, (name, clipped, overlap)
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, f"{name}.pdf"), metadata={"CreationDate": None}); fig.savefig(os.path.join(OUT, f"{name}.png"), dpi=600)
    plt.close(fig); print(f"figures/{name}.pdf")


def half_axes():
    fig, ax = plt.subplots(figsize=(HALF_W, HALF_H))
    fig.subplots_adjust(left=M_LEFT / HALF_W, right=1 - M_RIGHT / HALF_W, bottom=M_BOTTOM / HALF_H, top=1 - M_TOP / HALF_H)
    ax.set_xticks([]); ax.set_xlim(-0.48, 3.48)
    ax.yaxis.grid(True, color=GRID, lw=0.4); ax.set_axisbelow(True); ax.spines[["top", "right"]].set_visible(False)
    return fig, ax


def legend():
    os.makedirs(OUT, exist_ok=True)
    fig = plt.figure(figsize=(3.5, 0.2))
    fig.legend(handles=[Patch(facecolor=FILL[c], edgecolor=EDGE[c], lw=0.8, label=cm.LABELS[c]) for c in cm.CONFIGS],
               loc="center", ncol=4, frameon=False, fontsize=8, handlelength=1.2, handleheight=0.9, handletextpad=0.4,
               columnspacing=1.1, borderaxespad=0, borderpad=0)
    fig.savefig(os.path.join(OUT, "fig_legend.pdf"), metadata={"CreationDate": None}); fig.savefig(os.path.join(OUT, "fig_legend.png"), dpi=600)
    plt.close(fig); print("figures/fig_legend.pdf")


def boxes(per_seed, ylabel, ylim, yticks, name):
    fig, ax = half_axes()
    data = [per_seed[c] for c in cm.CONFIGS]
    bp = ax.boxplot(data, positions=range(4), widths=0.6, patch_artist=True, whis=(0, 100), showfliers=False, zorder=2,
                    medianprops=dict(color=INK, lw=1.3, solid_capstyle="butt"), whiskerprops=dict(color=WHISK, lw=0.7),
                    capprops=dict(color=WHISK, lw=0.7))
    for patch, c in zip(bp["boxes"], cm.CONFIGS):
        patch.set_facecolor(FILL[c]); patch.set_edgecolor(EDGE[c]); patch.set_linewidth(0.8)
    rng = np.random.default_rng(7)                                    # fixed jitter of the seed points
    for j, c in enumerate(cm.CONFIGS):
        ax.scatter(j + rng.uniform(-0.14, 0.14, size=len(per_seed[c])), per_seed[c], s=6, color=DOT[c], edgecolor="white", linewidth=0.3, zorder=4)
        ax.annotate(f"{half_up(st.median(per_seed[c]))}", (j, max(per_seed[c])), textcoords="offset points", xytext=(0, 2),
                    ha="center", va="bottom", fontsize=7.5, fontweight="bold", color=INK, zorder=5)
    ax.set_ylabel(ylabel, labelpad=2); ax.set_ylim(*ylim); ax.set_yticks(yticks)
    ax.set_xticks([]); ax.set_xlim(-0.48, 3.48)                       # the legend image names the configurations
    check_and_save(fig, name)


def bars(per_seed, ylabel, ylim, yticks, fmt, name):
    fig, ax = half_axes()
    vals = [st.mean(per_seed[c]) for c in cm.CONFIGS]
    for j, (c, v) in enumerate(zip(cm.CONFIGS, vals)):
        ax.bar(j, v, width=0.62, color=FILL[c], edgecolor=EDGE[c], lw=0.8, zorder=2)
        ax.annotate(fmt.format(v), (j, v), textcoords="offset points", xytext=(0, 2), ha="center", va="bottom", fontsize=7,
                    fontweight="bold", color=INK, zorder=5, bbox=dict(boxstyle="square,pad=0.1", facecolor="white", edgecolor="none"))
    ax.axhline(vals[0], color=REF, lw=0.9, ls=(0, (4, 2.5)), zorder=3)
    ax.set_ylabel(ylabel, labelpad=2); ax.set_ylim(*ylim); ax.set_yticks(yticks)
    ax.set_xticks([]); ax.set_xlim(-0.48, 3.48)                       # the legend image names the configurations
    check_and_save(fig, name)


def latency_ccdf():
    lat = defaultdict(list)
    with gzip.open(os.path.join(cm.PROCESSED, "latency_intervals.csv.gz"), "rt") as f:
        for r in csv.DictReader(f):
            lat[r["config"]].append(float(r["latency_ms"]))
    style = {"baseline": dict(lw=1.3, ls="-"), "x-care": dict(lw=1.8, ls="-"),
             "priority-cqm": dict(lw=1.4, ls=(0, (4, 1.6))), "priority-mlb": dict(lw=1.4, ls=(0, (5, 1.5, 1.2, 1.5)))}
    plt.rcParams.update({"axes.labelsize": 9, "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.labelpad": 3, "xtick.major.pad": 4})
    fig, ax = plt.subplots(figsize=(3.5, 2.2))
    fig.subplots_adjust(left=0.15, right=0.95, bottom=0.18, top=0.97)
    for c in cm.CONFIGS:
        x = np.sort(np.array(lat[c])); ccdf = 1.0 - np.arange(1, len(x) + 1) / len(x); keep = ccdf > 0
        ax.plot(x[keep], ccdf[keep], color=HUE[c], label=cm.LABELS[c], zorder=3, **style[c])
    ax.axhline(0.05, color="#555555", lw=0.7, ls=(0, (1, 1.5)), zorder=2)
    ax.text(392, 0.056, "P95", ha="right", va="bottom", fontsize=7.5, color="#333333")
    ax.set_yscale("log"); ax.set_ylim(1e-3, 1); ax.set_xlim(0, 400)
    ax.set_yticks([1e-3, 1e-2, 1e-1, 1]); ax.set_yticklabels(["0.001", "0.01", "0.1", "1"]); ax.set_xticks(range(0, 401, 100))
    ax.set_xlabel("Latency (ms)"); ax.set_ylabel("P(latency > x)")
    ax.grid(True, which="major", color=GRID, lw=0.4); ax.set_axisbelow(True); ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="lower left", frameon=False, fontsize=8, handlelength=2.6, borderaxespad=0.2)
    check_and_save(fig, "fig_rq3_latency_ccdf")


def main():
    rows = list(csv.DictReader(open(os.path.join(cm.PROCESSED, "metrics_by_seed.csv"))))
    seeds = lambda col: {c: [float(r[col]) for r in rows if r["config"] == c] for c in cm.CONFIGS}
    legend()
    boxes(seeds("reversals"), "Cross-xApp reversals", (0, 445), range(0, 401, 100), "fig_rq1_reversals")
    boxes(seeds("executed_handovers"), "Executed handovers", (0, 1040), range(0, 801, 200), "fig_rq1_handovers")
    bars(seeds("outage_time_pct"), "Outage time (%)", (0, 2.75), [0, 0.5, 1.0, 1.5, 2.0, 2.5], "{:.2f}", "fig_rq2_outage")
    bars(seeds("overload_time_pct"), "Overload time (%)", (0, 44), range(0, 41, 10), "{:.1f}", "fig_rq2_overload")
    latency_ccdf()


if __name__ == "__main__":
    main()
