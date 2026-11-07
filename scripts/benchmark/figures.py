"""Draw the two figures in docs/benchmark.md from the stored scoring output of each set's run.

    uv run --with matplotlib python scripts/benchmark/figures.py

matplotlib is not a project dependency, so the command above brings it in for this run only. Every number is read
from notes/<set>/report.json; nothing is typed in here except Elicit's published BioASQ figures, which have no run
of ours behind them.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # file output only, no window
import matplotlib.pyplot as plt  # noqa: E402 (after the backend is set)

ROOT = Path(__file__).resolve().parents[2]
KS = [10, 20, 50, 100, 200]
SETS = [("bioasq", "BioASQ (100 questions)"), ("litsearch", "LitSearch (200 questions)")]
ELICIT = {10: 0.390, 20: 0.483, 50: 0.603, 100: 0.670}  # published, BioASQ only, no figure at 200

GREY, BLUE, NAVY, ORANGE, TEAL = "#9a9a9a", "#4a8fe0", "#1b3a6b", "#e0802f", "#2a9d8f"
ARMS = (("openalex", GREY, "o", "A: plain OpenAlex query"),
        ("deixis_fused", BLUE, "s", "B: DEIXIS, reranker off"),
        ("deixis_rerank", NAVY, "D", "C: DEIXIS, reranker on"))
# The three contrasts of the gains figure, in the order they are drawn.
CONTRASTS = (("deixis_rerank_minus_deixis_fused", "C − B", NAVY),
             ("deixis_fused_minus_openalex", "B − A", BLUE),
             ("deixis_rerank_minus_openalex", "C − A", TEAL))

plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.color": "#dddddd",
                     "grid.linewidth": 0.8, "axes.edgecolor": "#444444"})


def report(name):
    """The scoring output of one set's 18 Oct run."""
    return json.loads((ROOT / "notes" / name / "report.json").read_text())


def recall_figure(out):
    """recall@k for every arm, one panel per set."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, (name, title) in zip(axes, SETS):
        scores = report(name)
        for arm, color, marker, label in ARMS:
            ys = [scores[arm][f"@{k}"] for k in KS]
            ax.plot(range(len(KS)), ys, color=color, marker=marker, markersize=6, linewidth=2, label=label)
        if name == "bioasq":  # the only set Elicit publishes
            ks = [k for k in KS if k in ELICIT]
            ax.plot([KS.index(k) for k in ks], [ELICIT[k] for k in ks], color=ORANGE, marker="^",
                    markersize=6, linewidth=2, linestyle="--", label="Elicit, published")
        ax.set_title(title)
        ax.set_xticks(range(len(KS)), [str(k) for k in KS])
        ax.set_xlabel("first k results")
        ax.set_ylim(0, 0.85)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("recall@k")
    handles, labels = [], []
    for ax in axes:  # one shared legend; Elicit's entry comes from the first panel only
        for handle, label in zip(*ax.get_legend_handles_labels()):
            if label not in labels:
                handles.append(handle)
                labels.append(label)
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(out, dpi=180)


def gains_figure(out):
    """Paired difference in recall@50 with its 95% interval, one row per set and contrast."""
    rows = []
    for name, title in SETS:
        scores = report(name)
        for key, mark, color in CONTRASTS:
            value = scores[key]["@50"]
            rows.append((f"{title.split(' (')[0]}   {mark}", value["mean"], value["low"], value["high"], color))
    fig, ax = plt.subplots(figsize=(9, 4.0))
    for y, (_, mean, low, high, color) in enumerate(rows):
        ax.plot([low, high], [y, y], color=color, linewidth=2.5, solid_capstyle="round")
        ax.plot([mean], [y], marker="o", markersize=7, color=color)
    ax.axvline(0, color="#333333", linewidth=1.2)
    ax.axvline(0.10, color="#999999", linewidth=1.2, linestyle="--")  # the project's bar against a plain query
    ax.text(0.10, -0.62, "+0.10 bar", color="#777777", ha="center", va="bottom", fontsize=10)
    ax.axhline(len(CONTRASTS) - 0.5, color="#dddddd", linewidth=1)  # between the two sets
    ax.set_yticks(range(len(rows)), [row[0] for row in rows])
    ax.set_ylim(len(rows) - 0.4, -0.9)  # first row at the top, room above it for the bar label
    ax.set_xlabel("difference in recall@50 (mean and paired 95% interval)")
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(out, dpi=180)


def main():
    recall_figure(ROOT / "assets/benchmark-recall.png")
    gains_figure(ROOT / "assets/benchmark-gains.png")
    print("assets/benchmark-recall.png, assets/benchmark-gains.png")


if __name__ == "__main__":
    main()
