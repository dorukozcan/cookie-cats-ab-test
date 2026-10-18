#!/usr/bin/env python3
"""Cookie Cats A/B test: does moving the first gate from level 30 to level 40 change retention?

Run:    python3 analysis.py
Needs:  data/cookie_cats.csv (download link in README.md), pandas, numpy, scipy, matplotlib
Writes: results.json and figures/*.png

Groups: gate_30 is the control (the original design), gate_40 is the test.
Every effect below is reported as gate_40 minus gate_30, so a negative number means
moving the gate to level 40 made the metric worse.
"""
from __future__ import annotations

import json
from math import sqrt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MPath
from scipy import stats

plt.rcParams["font.family"] = ["Arial", "DejaVu Sans"]

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "cookie_cats.csv"
FIGS = ROOT / "figures"

SEED = 2026
N_BOOT = 20_000
ALPHA = 0.05
POWER = 0.80
GATE_REACH_ROUNDS = 30  # a player needs at least ~30 rounds to reach level 30 (rounds count failed attempts too)

CONTROL, TEST = "gate_30", "gate_40"
GROUPS = (CONTROL, TEST)
LABEL = {CONTROL: "Gate at level 30 (control)", TEST: "Gate at level 40 (test)"}
METRICS = {"retention_1": "Day-1 retention", "retention_7": "Day-7 retention"}

# Chart tokens: categorical slots 1-2 of the reference palette, validated for a light surface.
COLOR = {CONTROL: "#2a78d6", TEST: "#eb6834"}
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"


# ----------------------------------------------------------------------------- data

def load() -> pd.DataFrame:
    df = pd.read_csv(DATA)
    expected = ["userid", "version", "sum_gamerounds", "retention_1", "retention_7"]
    assert list(df.columns) == expected, f"unexpected columns: {list(df.columns)}"
    assert df["userid"].is_unique, "duplicate players"
    assert not df.isna().any().any(), "missing values"
    assert set(df["version"]) == set(GROUPS), f"unexpected groups: {set(df['version'])}"
    for col in METRICS:
        df[col] = df[col].astype(bool)
    return df


# ----------------------------------------------------------------------------- statistics

Z_CRIT = stats.norm.ppf(1 - ALPHA / 2)
Z_POWER = stats.norm.ppf(POWER)


def compare_rates(sub: pd.DataFrame, metric: str, rng: np.random.Generator) -> dict:
    """Two-proportion z-test, 95% CI and a bootstrap for the effect gate_40 - gate_30."""
    n = sub.groupby("version")[metric].size().reindex(GROUPS)
    x = sub.groupby("version")[metric].sum().reindex(GROUPS)
    p_c, p_t = x[CONTROL] / n[CONTROL], x[TEST] / n[TEST]
    effect = p_t - p_c

    pooled = (x[CONTROL] + x[TEST]) / (n[CONTROL] + n[TEST])
    z = effect / sqrt(pooled * (1 - pooled) * (1 / n[CONTROL] + 1 / n[TEST]))
    p_value = 2 * stats.norm.sf(abs(z))
    se = sqrt(p_c * (1 - p_c) / n[CONTROL] + p_t * (1 - p_t) / n[TEST])

    # Bootstrap: resampling players with replacement. For a yes/no metric the number of
    # retained players in a resample is exactly a binomial draw, so we draw that directly.
    boot = rng.binomial(n[TEST], p_t, N_BOOT) / n[TEST] - rng.binomial(n[CONTROL], p_c, N_BOOT) / n[CONTROL]

    return {
        "n": {g: int(n[g]) for g in GROUPS},
        "rate": {CONTROL: float(p_c), TEST: float(p_t)},
        "ci95_rate": {
            g: [float(r - Z_CRIT * sqrt(r * (1 - r) / n[g])), float(r + Z_CRIT * sqrt(r * (1 - r) / n[g]))]
            for g, r in ((CONTROL, p_c), (TEST, p_t))
        },
        "effect_pp": float(effect * 100),
        "relative_change_pct": float(effect / p_c * 100),
        "ci95_effect_pp": [float((effect - Z_CRIT * se) * 100), float((effect + Z_CRIT * se) * 100)],
        "z": float(z),
        "p_value": float(p_value),
        "bootstrap_ci95_effect_pp": [float(np.percentile(boot, 2.5) * 100), float(np.percentile(boot, 97.5) * 100)],
        "prob_gate40_worse": float((boot < 0).mean()),
        "_boot_pp": boot * 100,
    }


def mde_pp(p: float, n_c: int, n_t: int) -> float:
    """Smallest true effect (in percentage points) this sample detects 80% of the time at alpha 0.05."""
    return (Z_CRIT + Z_POWER) * sqrt(p * (1 - p) * (1 / n_c + 1 / n_t)) * 100


# ----------------------------------------------------------------------------- charts

def style_axes(ax, *, grid_axis: str = "y") -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelcolor=INK2, length=0, labelsize=10)
    ax.grid(axis=grid_axis, color=GRID, linewidth=1)
    ax.set_axisbelow(True)


def new_figure(width: float = 8.0, height: float = 4.6):
    fig, ax = plt.subplots(figsize=(width, height), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    style_axes(ax)
    return fig, ax


def rounded_column(ax, x_center: float, width: float, height: float, color: str, radius_px: float = 4) -> None:
    """Column with a 4px rounded top and a square base (drawn in data units after limits are set)."""
    fig = ax.figure
    fig.canvas.draw()
    bbox = ax.get_window_extent()
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    rx = radius_px * (x1 - x0) / bbox.width
    ry = min(radius_px * (y1 - y0) / bbox.height, height / 2)
    left, right = x_center - width / 2, x_center + width / 2
    verts = [
        (left, 0), (left, height - ry), (left, height), (left + rx, height),
        (right - rx, height), (right, height), (right, height - ry), (right, 0), (left, 0),
    ]
    codes = [MPath.MOVETO, MPath.LINETO, MPath.CURVE3, MPath.CURVE3,
             MPath.LINETO, MPath.CURVE3, MPath.CURVE3, MPath.LINETO, MPath.CLOSEPOLY]
    ax.add_patch(PathPatch(MPath(verts, codes), facecolor=color, edgecolor="none", zorder=2))


def legend(ax, loc: str = "upper right") -> None:
    handles = [plt.Line2D([], [], marker="s", linestyle="", markersize=9, color=COLOR[g], label=LABEL[g]) for g in GROUPS]
    leg = ax.legend(handles=handles, loc=loc, frameon=False, fontsize=10)
    for text in leg.get_texts():
        text.set_color(INK2)


def title(fig, main: str, sub: str) -> None:
    fig.text(0.06, 0.95, main, fontsize=13, fontweight="bold", color=INK, ha="left", va="top")
    fig.text(0.06, 0.885, sub, fontsize=10, color=INK2, ha="left", va="top")


def column_chart(path: Path, groups_of_bars: list[tuple[str, dict]], main: str, sub: str, ymax: float) -> None:
    """groups_of_bars: [(x label, comparison dict)], one column per experiment group, with 95% CI whiskers."""
    fig, ax = new_figure()
    fig.subplots_adjust(top=0.78, bottom=0.12, left=0.08, right=0.97)
    width = 0.13
    ax.set_xlim(-0.6, len(groups_of_bars) - 0.4)
    ax.set_ylim(0, ymax)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(decimals=0))
    ax.set_xticks(range(len(groups_of_bars)), [lab for lab, _ in groups_of_bars], fontsize=11)
    for i, (_, res) in enumerate(groups_of_bars):
        for j, g in enumerate(GROUPS):
            xc = i + (j - 0.5) * (width + 0.03)  # surface gap between neighbouring columns
            rate = res["rate"][g] * 100
            lo, hi = (v * 100 for v in res["ci95_rate"][g])
            rounded_column(ax, xc, width, rate, COLOR[g])
            ax.plot([xc, xc], [lo, hi], color=INK2, linewidth=1.2, zorder=3, solid_capstyle="round")
            ax.text(xc, hi + ymax * 0.015, f"{rate:.1f}%", ha="center", va="bottom", fontsize=10, color=INK)
    legend(ax)
    title(fig, main, sub)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def bootstrap_chart(path: Path, results: dict) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.8), dpi=160, sharey=False)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(top=0.66, bottom=0.14, left=0.04, right=0.98, wspace=0.12)
    for ax, metric in zip(axes, METRICS):
        style_axes(ax, grid_axis="x")
        res = results[metric]
        boot = res["_boot_pp"]
        kde = stats.gaussian_kde(boot)
        xs = np.linspace(min(boot.min(), -0.1), max(boot.max(), 0.1), 400)
        ys = kde(xs)
        ax.fill_between(xs, ys, color=INK2, alpha=0.10, linewidth=0)
        ax.plot(xs, ys, color=INK2, linewidth=2, solid_capstyle="round")
        lo, hi = res["bootstrap_ci95_effect_pp"]
        ax.plot([lo, hi], [0, 0], color=INK, linewidth=3, solid_capstyle="round", zorder=3)
        ax.axvline(0, color=AXIS, linewidth=1)
        ax.set_yticks([])
        ax.set_ylim(0, ys.max() * 1.25)
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.1f} pp" if v else "0"))
        ax.text(0.0, 1.17, METRICS[metric], transform=ax.transAxes, ha="left", va="bottom", fontsize=11,
                fontweight="bold", color=INK)
        ax.text(0.0, 1.03, f"P(gate 40 is worse) = {res['prob_gate40_worse']:.1%}  ·  95% interval {lo:+.2f} to {hi:+.2f} pp",
                transform=ax.transAxes, ha="left", va="bottom", fontsize=9.5, color=INK2)
    title(fig, "Moving the gate to level 40 lowers day-7 retention",
          f"Bootstrap distribution of the effect (gate 40 minus gate 30), {N_BOOT:,} resamples; "
          "the dark bar is the 95% interval")
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def rounds_chart(path: Path, df: pd.DataFrame) -> None:
    fig, ax = new_figure(height=4.4)
    fig.subplots_adjust(top=0.78, bottom=0.14, left=0.08, right=0.97)
    max_rounds = 100
    for g in GROUPS:
        counts = df.loc[df["version"] == g, "sum_gamerounds"].value_counts().reindex(range(max_rounds + 1), fill_value=0)
        ax.plot(counts.index, counts.values, color=COLOR[g], linewidth=2, solid_joinstyle="round")
    ax.set_xlim(0, max_rounds)
    ax.set_ylim(0, None)
    for gate in (30, 40):
        ax.axvline(gate, color=AXIS, linewidth=1, zorder=1)
        ax.text(gate + 0.8, ax.get_ylim()[1] * 0.96, f"gate {gate}", fontsize=9, color=INK2, va="top")
    ax.set_xlabel("Game rounds played after install", fontsize=10, color=INK2)
    ax.yaxis.set_major_locator(matplotlib.ticker.MultipleLocator(500))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / 1000:g}K" if v >= 1000 else f"{v:.0f}"))
    legend(ax)
    title(fig, "Most players stop long before either gate",
          "Number of players by game rounds played (0-100 shown); the two groups overlap almost exactly")
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def split_chart(path: Path, split: dict) -> None:
    """Where do the extra test-group players sit? One neutral series: test minus control headcount."""
    fig, ax = plt.subplots(figsize=(8.0, 3.2), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    style_axes(ax, grid_axis="x")
    fig.subplots_adjust(top=0.70, bottom=0.12, left=0.30, right=0.93)
    names = [("under_30_rounds", "Under 30 rounds\n(never reached a gate)"), ("30_plus_rounds", "30+ rounds\n(could reach a gate)")]
    extra = [split[k]["extra_test_players"] for k, _ in names]
    ys = [1, 0]
    span = max(abs(v) for v in extra) * 1.25
    ax.set_xlim(-span * 0.25, span * 1.9)
    ax.set_ylim(-0.6, 1.6)
    for y, v in zip(ys, extra):
        ax.barh(y, v, height=0.34, color=INK2, zorder=2)
        p_srm = split[names[ys.index(y)][0]]["srm_p_value"]
        p_txt = "p < 0.001" if p_srm < 0.001 else f"p = {p_srm:.2f}"
        ax.text(v + span * 0.015 if v >= 0 else span * 0.015, y, f"{v:+,} players  (split check {p_txt})",
                va="center", ha="left", fontsize=10, color=INK)
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.set_yticks(ys, [lab for _, lab in names], fontsize=10)
    ax.set_xticks([])
    title(fig, "Data check: the test group's extra players never reached a gate",
          "Test-group headcount minus control-group headcount, by how far players got")
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


# ----------------------------------------------------------------------------- main

def main() -> None:
    FIGS.mkdir(exist_ok=True)
    rng = np.random.default_rng(SEED)
    df = load()
    out: dict = {"players": int(len(df))}

    # 1. Was the split healthy? (sample ratio mismatch check against the intended 50/50)
    counts = df["version"].value_counts().reindex(GROUPS)
    chi2, p_srm = stats.chisquare(counts.values)
    out["split"] = {"counts": {g: int(counts[g]) for g in GROUPS},
                    "share_test": float(counts[TEST] / counts.sum()),
                    "srm_chi2": float(chi2), "srm_p_value": float(p_srm)}

    # 2. Engagement (game rounds) - heavy-tailed, so medians and a rank test, not just means
    r = {g: df.loc[df["version"] == g, "sum_gamerounds"] for g in GROUPS}
    top = df.loc[df["sum_gamerounds"].idxmax()]
    mwu = stats.mannwhitneyu(r[CONTROL], r[TEST], alternative="two-sided")
    out["rounds"] = {
        g: {"mean": float(r[g].mean()), "median": float(r[g].median()), "p75": float(r[g].quantile(0.75)),
            "max": int(r[g].max()), "share_zero": float((r[g] == 0).mean()),
            "share_reached_30_rounds": float((r[g] >= GATE_REACH_ROUNDS).mean()),
            "mean_without_top_player": float(r[g][r[g] < top["sum_gamerounds"]].mean())}
        for g in GROUPS
    }
    out["rounds"]["top_player"] = {"version": str(top["version"]), "rounds": int(top["sum_gamerounds"])}
    out["rounds"]["mann_whitney_p_value"] = float(mwu.pvalue)

    # 3. Retention: the decision metrics
    results = {m: compare_rates(df, m, rng) for m in METRICS}
    for m, res in results.items():
        res["mde_pp"] = mde_pp(res["rate"][CONTROL], res["n"][CONTROL], res["n"][TEST])
        # players per group a follow-up test needs to detect a 0.5 pp change 80% of the time
        p0 = res["rate"][CONTROL]
        res["n_per_group_for_0_5pp"] = int(np.ceil(2 * (Z_CRIT + Z_POWER) ** 2 * p0 * (1 - p0) / 0.005 ** 2))

    # 4. Who could the gate even affect? Players under 30 rounds never reached either gate, so the
    #    groups should match there (a built-in sanity check); the effect should sit in the 30+ group.
    reached = df["sum_gamerounds"] >= GATE_REACH_ROUNDS
    share_tab = pd.crosstab(df["version"], reached)
    seg_chi2_p = float(stats.chi2_contingency(share_tab)[1])
    segments = {
        "under_30_rounds": {m: compare_rates(df[~reached], m, rng) for m in METRICS},
        "30_plus_rounds": {m: compare_rates(df[reached], m, rng) for m in METRICS},
    }

    def clean(res: dict) -> dict:
        return {k: v for k, v in res.items() if not k.startswith("_")}

    out["retention"] = {m: clean(res) for m, res in results.items()}
    out["segments"] = {s: {m: clean(res) for m, res in seg.items()} for s, seg in segments.items()}
    out["segments"]["reached_30_share_p_value"] = seg_chi2_p
    out["segments"]["split"] = {}
    for name, mask in (("under_30_rounds", ~reached), ("30_plus_rounds", reached)):
        c = df.loc[mask, "version"].value_counts().reindex(GROUPS)
        out["segments"]["split"][name] = {"counts": {g: int(c[g]) for g in GROUPS},
                                          "extra_test_players": int(c[TEST] - c[CONTROL]),
                                          "srm_p_value": float(stats.chisquare(c.values)[1])}
    (ROOT / "results.json").write_text(json.dumps(out, indent=2))

    # Charts
    column_chart(FIGS / "retention_by_group.png", [(METRICS[m], results[m]) for m in METRICS],
                 "Day-7 retention drops when the first gate moves to level 40",
                 "Share of players who came back 1 and 7 days after installing; whiskers = 95% CI", ymax=52)
    bootstrap_chart(FIGS / "effect_bootstrap.png", results)
    rounds_chart(FIGS / "rounds_distribution.png", df)
    seg = segments
    column_chart(FIGS / "day7_by_segment.png",
                 [("Under 30 rounds\n(never reached a gate)", seg["under_30_rounds"]["retention_7"]),
                  ("30+ rounds\n(could reach a gate)", seg["30_plus_rounds"]["retention_7"])],
                 "Players who could reach a gate show the same ~0.9 pp drop",
                 "Day-7 retention by how far players got; the 30+ group is smaller, so its CI is wider", ymax=60)
    split_chart(FIGS / "split_check.png", out["segments"]["split"])

    # Console summary
    s = out["split"]
    print(f"Players: {out['players']:,}  |  control {s['counts'][CONTROL]:,}  test {s['counts'][TEST]:,}  "
          f"(test share {s['share_test']:.2%}, SRM p = {s['srm_p_value']:.4f})")
    for m, res in out["retention"].items():
        print(f"{METRICS[m]:16s} control {res['rate'][CONTROL]:.2%}  test {res['rate'][TEST]:.2%}  "
              f"effect {res['effect_pp']:+.2f} pp [{res['ci95_effect_pp'][0]:+.2f}, {res['ci95_effect_pp'][1]:+.2f}]  "
              f"p = {res['p_value']:.4f}  P(test worse) = {res['prob_gate40_worse']:.1%}  MDE {res['mde_pp']:.2f} pp")
    for name, seg_res in segments.items():
        res = seg_res["retention_7"]
        print(f"Day-7, {name:16s} n = {sum(res['n'].values()):,}  effect {res['effect_pp']:+.2f} pp  p = {res['p_value']:.4f}")
    for name, sp in out["segments"]["split"].items():
        print(f"Split, {name:16s} control {sp['counts'][CONTROL]:,}  test {sp['counts'][TEST]:,}  "
              f"extra test players {sp['extra_test_players']:+,}  SRM p = {sp['srm_p_value']:.4f}")
    rd = out["rounds"]
    print(f"Rounds median control {rd[CONTROL]['median']:.0f} / test {rd[TEST]['median']:.0f}  "
          f"(Mann-Whitney p = {rd['mann_whitney_p_value']:.3f}); top player {rd['top_player']}")


if __name__ == "__main__":
    main()
