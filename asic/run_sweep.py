#!/usr/bin/env python3
"""Project 3 design-space sweep with LibreLane (SKY130, sky130_fd_sc_hd).

Runs the full RTL -> GDS flow for every combination of
    micro-architecture  PIPE in {0, 1}
    clock period        CLOCK_PERIOD (ns)
    core utilization    FP_CORE_UTIL (%)
and collects area, timing slack, power and sign-off results into
asic/results/sweep.csv and plots (asic/results/*.pdf) for the report.

Usage (inside a LibreLane environment: nix-shell, or pip + --dockerized):
    python3 asic/run_sweep.py                      # default: PIPE 0 at 25 ns, PIPE 1 at 12 ns (2 runs)
    python3 asic/run_sweep.py --runs 0:21,1:9      # confirmation runs at the periods it suggests
    python3 asic/run_sweep.py --grid               # full grid (--periods x --utils), very slow on a laptop
    python3 asic/run_sweep.py --quick              # 4 runs, to check the setup
    python3 asic/run_sweep.py --dockerized         # use `python3 -m librelane --dockerized`
    python3 asic/run_sweep.py --collect-only       # just re-parse existing runs

Method: each version is first routed at a clock it meets with margin; its shortest period is then
the clock period minus the worst setup slack at the typical corner (nom_tt_025C_1v80, the corner of
the pre-layout estimate), and a second run at that period confirms it. A run takes 20-40 min on a
WSL2 laptop, and much longer when the clock is far too short (the timing repair then iterates for a
long time), which is why the full grid is not the default. A run that stops early (for example on a setup
violation at a short period) is still listed, with the metrics of its last finished step.
"""
import argparse, csv, itertools, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "runs")
RES = os.path.join(HERE, "results")

METRICS = [
    "design__instance__count", "design__instance__area", "design__instance__area__stdcell",
    "design__instance__area__class:fill_cell", "design__instance__utilization",
    "design__core__area", "design__die__area", "timing__setup__ws", "timing__hold__ws",
    "timing__setup_vio__count", "power__total", "route__wirelength", "clock__skew__worst_setup",
    "magic__drc_error__count", "design__lvs_error__count", "antenna__violating__nets",
]


def tag(pipe, period, util):
    return f"p{pipe}_t{str(period).replace('.', 'p')}_u{util}"


def run_one(pipe, period, util, docker, pdk):
    t = tag(pipe, period, util)
    cmd = ([sys.executable, "-m", "librelane", "--dockerized"] if docker else ["librelane"])
    cmd += ["--pdk", pdk, "--run-tag", t, "--overwrite",
            "-c", f"SYNTH_PARAMETERS=PIPE={pipe}",          # list variable: plain value, no JSON
            "-c", f"CLOCK_PERIOD={period}",
            "-c", f"FP_CORE_UTIL={util}",
            os.path.join(HERE, "config.json")]
    print(">>", " ".join(cmd), flush=True)
    t0 = time.time()
    rc = subprocess.call(cmd, cwd=HERE)
    print(f"<< {t}: exit {rc}, {time.time() - t0:.0f} s", flush=True)
    return rc


def last_step_metrics(rdir):
    """Metrics of the last step that finished, for a run that stopped before final/."""
    steps = sorted(d for d in os.listdir(rdir) if os.path.isdir(os.path.join(rdir, d)) and d[:1].isdigit())
    for d in reversed(steps):
        so = os.path.join(rdir, d, "state_out.json")
        if os.path.exists(so):
            try:
                return json.load(open(so)).get("metrics", {}), d
            except ValueError:
                continue
    return {}, ""


def collect():
    rows = []
    if not os.path.isdir(RUNS):
        return rows
    for t in sorted(os.listdir(RUNS)):
        rdir = os.path.join(RUNS, t)
        if not t.startswith("p") or not os.path.isdir(rdir) or t.count("_") != 2:
            continue
        mj = os.path.join(rdir, "final", "metrics.json")
        if os.path.exists(mj):
            m, status = json.load(open(mj)), "complete"
        else:
            m, last = last_step_metrics(rdir)
            status = f"stopped after {last}" if last else "no step finished"
        p, per, u = t.split("_")
        row = dict(tag=t, pipe=int(p[1:]), period_ns=float(per[1:].replace("p", ".")), util=int(u[1:]),
                   status=status)
        for k in METRICS:
            row[k] = m.get(k)
        ws = row["timing__setup__ws"]
        if ws is not None:
            row["fmax_mhz"] = 1000.0 / (row["period_ns"] - ws)
        row["ws_tt"] = m.get("timing__setup__ws__corner:nom_tt_025C_1v80")
        row["ws_ss"] = m.get("timing__setup__ws__corner:nom_ss_100C_1v60")
        row["min_period_tt_ns"] = (row["period_ns"] - row["ws_tt"]) if row["ws_tt"] is not None else None
        gds = [f for f in os.listdir(os.path.join(RUNS, t, "final", "gds"))] if os.path.isdir(os.path.join(RUNS, t, "final", "gds")) else []
        row["gds"] = gds[0] if gds else ""
        rows.append(row)
    return rows


def plots(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "font.family": "serif"})
    fig, ax = plt.subplots(1, 2, figsize=(7.0, 2.4))
    for pipe, mk, col in ((0, "o-", "#0072B2"), (1, "s--", "#D55E00")):     # Okabe-Ito blue / vermillion
        # typical-corner slack (as in the paper) and cell area without filler cells
        r = sorted([x for x in rows if x["pipe"] == pipe and x["util"] == min(y["util"] for y in rows)
                    and x.get("ws_tt") is not None and x.get("design__instance__area__stdcell") is not None],
                   key=lambda x: x["period_ns"])
        if not r:
            continue
        per = [x["period_ns"] for x in r]
        ax[0].plot(per, [x["ws_tt"] for x in r], mk, color=col, ms=3.5, lw=1, label=f"PIPE={pipe}")
        ax[1].plot(per, [x["design__instance__area__stdcell"] / 1e3 for x in r], mk, color=col, ms=3.5, lw=1,
                   label=f"PIPE={pipe}")
    ax[0].axhline(0, color="k", lw=0.6)
    ax[0].set_xlabel("Clock period (ns)"); ax[0].set_ylabel("Setup slack, typical corner (ns)")
    ax[1].set_xlabel("Clock period (ns)"); ax[1].set_ylabel(r"Cell area, no fill ($10^3\,\mu$m$^2$)")
    for a in ax: a.grid(alpha=0.3); a.legend(fontsize=7)
    fig.tight_layout(); fig.savefig(os.path.join(RES, "asic_sweep.pdf"))
    fig.savefig(os.path.join(RES, "asic_sweep.png"), dpi=600); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="0:25,1:12", help="pipe:period_ns list, at --util")
    ap.add_argument("--util", type=int, default=45)
    ap.add_argument("--grid", action="store_true", help="run the full --periods x --utils grid instead")
    ap.add_argument("--periods", default="6,8,10,15,20,25")
    ap.add_argument("--utils", default="35,55")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--dockerized", action="store_true")
    ap.add_argument("--pdk", default="sky130A")
    ap.add_argument("--collect-only", action="store_true")
    ap.add_argument("--plot-only", action="store_true", help="only redraw the plot from results/sweep.json")
    a = ap.parse_args()
    os.makedirs(RES, exist_ok=True)
    periods = [float(p) for p in a.periods.split(",")]
    utils = [int(u) for u in a.utils.split(",")]
    if a.grid:
        todo = list(itertools.product((0, 1), periods, utils))
    elif a.quick:
        todo = list(itertools.product((0, 1), [5.0, 15.0], [45]))
    else:
        todo = []
        for item in a.runs.split(","):
            pp, per = item.split(":")
            todo.append((int(pp), float(per), a.util))
    if not a.collect_only and not a.plot_only:
        if not a.dockerized and shutil.which("librelane") is None:
            sys.exit("librelane not found: run inside `nix-shell` or use --dockerized")
        for pipe, per, u in todo:
            run_one(pipe, per, u, a.dockerized, a.pdk)
    if a.plot_only:                              # on Windows, from the copied asic/results/sweep.json
        plots(json.load(open(os.path.join(RES, "sweep.json"))))
        print("-> asic/results/asic_sweep.pdf/png")
        return
    rows = collect()
    if not rows:
        sys.exit("no finished runs found in asic/runs/")
    keys = list(rows[0].keys())
    with open(os.path.join(RES, "sweep.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(rows)
    with open(os.path.join(RES, "sweep.json"), "w") as fh:
        json.dump(rows, fh, indent=2)
    for r in rows:
        print(f"{r['tag']:16s} cell_area={r['design__instance__area__stdcell']} ws_all={r['timing__setup__ws']} "
              f"P={r['power__total']} DRC={r['magic__drc_error__count']} LVS={r['design__lvs_error__count']} "
              f"tt_slack={r['ws_tt']} min_period_tt={r['min_period_tt_ns']} [{r['status']}]")
    print("-> asic/results/sweep.csv, sweep.json")
    # suggested confirmation run: the shortest typical-corner period, rounded up to 0.5 ns
    import math
    sug = []
    for pipe in (0, 1):
        c = [r for r in rows if r["pipe"] == pipe and r["status"] == "complete" and r["min_period_tt_ns"]]
        if not c:
            continue
        mp = min(r["min_period_tt_ns"] for r in c)
        closed = [r["period_ns"] for r in c if r["ws_tt"] is not None and r["ws_tt"] >= 0]
        # confirmed once a run within 1 ns of the estimate met timing at the typical corner
        if closed and min(closed) - mp <= 1.0:
            print(f"PIPE={pipe}: confirmed, met timing at {min(closed):g} ns (typical corner); "
                  f"shortest period {mp:.2f} ns")
        else:
            sug.append(f"{pipe}:{math.ceil(mp * 2) / 2:g}")
    if sug:
        print("confirmation run:  python3 asic/run_sweep.py --runs " + ",".join(sug))
    try:
        plots(rows)
        print("-> asic/results/asic_sweep.pdf/png")
    except ImportError:
        # the LibreLane nix-shell has no matplotlib; draw it on Windows with --plot-only
        print("(plot skipped: no matplotlib here; on Windows run  py asic\\run_sweep.py --plot-only)")


if __name__ == "__main__":
    main()
