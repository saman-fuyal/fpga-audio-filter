#!/usr/bin/env python3
"""Black-and-white timing-diagram figure from a real simulation dump (sim/wave.vcd).

    cd sim && iverilog -g2005 -DDUMP -I ../rtl -s tb_vivado -o tb_wave.vvp tb_vivado.v ../rtl/*.v
    vvp -n tb_wave.vvp && cd .. && python3 model/plot_waveforms.py

Panel (a): microphone interface - M_CLK, M_DATA (the line is released, 'z', in the other
           half period), the sampling strobe and the captured bit.
Panel (b): one output of the 511-tap FIR - input strobe, FSM state, tap counter, result.
"""
import os, re, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIGS = os.path.join(ROOT, "docs", "report", "figs")
sys.path.insert(0, os.path.dirname(__file__))


def parse_vcd(path):
    ids, sig = {}, {}
    scope = []
    t = 0
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("$scope"):
                scope.append(line.split()[2])
            elif line.startswith("$upscope"):
                scope.pop()
            elif line.startswith("$var"):
                p = line.split()
                name = ".".join(scope[1:] + [p[4]])
                ids.setdefault(p[3], []).append(name)
                sig[name] = []
            elif line.startswith("#"):
                t = int(line[1:])
            elif line and line[0] in "01xzXZ" and len(line) > 1 and not line.startswith("$"):
                for n in ids.get(line[1:], []):
                    sig[n].append((t, line[0].lower()))
            elif line.startswith("b"):
                v, i = line[1:].split()
                for n in ids.get(i, []):
                    sig[n].append((t, v))
    return sig


def steps(ev, t0, t1):
    """Event list -> (times, values) step arrays clipped to [t0, t1] (ps)."""
    ts, vs = [], []
    cur = None
    for t, v in ev:
        if t <= t0:
            cur = v
            continue
        if t > t1:
            break
        if cur is not None:
            ts.append(t0 if not ts else ts[-1]); vs.append(cur)
        ts.append(t); vs.append(v); cur = v
    return cur, [(t, v) for t, v in ev if t0 < t <= t1]


def level_trace(ev, t0, t1):
    cur = None
    for t, v in ev:
        if t <= t0:
            cur = v
    xs, ys = [t0], [cur]
    for t, v in ev:
        if t0 < t <= t1:
            xs += [t, t]; ys += [ys[-1], v]
    xs.append(t1); ys.append(ys[-1])
    return np.array(xs, dtype=float), ys


def main():
    from design_filters import bw_style, savefig
    plt = bw_style()
    sig = parse_vcd(os.path.join(ROOT, "sim", "wave.vcd"))
    g = lambda k: next(v for n, v in sig.items() if n.endswith(k))
    start = min(t for ev in sig.values() for t, _ in ev if t > 0)

    fig, axes = plt.subplots(2, 1, figsize=(3.5, 3.6), gridspec_kw={"height_ratios": [1, 0.95]})
    # ---------------- (a) PDM interface, 1.6 us
    ax = axes[0]
    t0 = start + 100_000; t1 = t0 + 1_600_000
    # the captured bit is only meaningful at the strobe: hold it from strobe to strobe
    bv = g("u_pdm.bit_valid"); bo = g("u_pdm.bit_out")
    def value_at(ev, t):
        cur = "x"
        for tt, v in ev:
            if tt > t:
                break
            cur = v
        return cur
    held = []
    for t, v in bv:
        if v == "1":
            held.append((t + 10_000, value_at(bo, t + 10_000)))   # register output after the edge
    rows = [("M_CLK", g("M_CLK")), ("M_DATA", g("M_DATA")), ("sample strobe", bv),
            ("bit to CIC", held)]
    lvl = lambda v: 0.4 if v in ("z", "x", None) else (0.8 if v == "1" else 0.0)
    for r, (name, ev) in enumerate(rows):
        y0 = (len(rows) - 1 - r) * 1.5
        xs, ys = level_trace(ev, t0, t1)
        xs = (xs - t0) / 1e3
        for k in range(len(xs) - 1):
            v = ys[k]
            ax.plot([xs[k], xs[k + 1]], [y0 + lvl(v)] * 2, ":" if v in ("z", "x", None) else "-",
                    color="#D55E00" if v in ("z", "x", None) else "#0072B2", lw=0.9)
            if k + 1 < len(ys) and ys[k + 1] != v:
                ax.plot([xs[k + 1]] * 2, [y0 + lvl(v), y0 + lvl(ys[k + 1])], "-", color="#0072B2", lw=0.6)
        ax.text(-25, y0 + 0.4, name, ha="right", va="center", fontsize=7)
    ax.set_xlim(0, (t1 - t0) / 1e3); ax.set_ylim(-0.4, len(rows) * 1.5 - 0.4)
    ax.set_yticks([]); ax.grid(False)
    ax.set_xlabel("Time (ns); dotted = line released (high-Z)")
    ax.set_title("(a) PDM interface", fontsize=8, loc="left")

    # ---------------- (b) one FIR output computation
    ax = axes[1]
    dcv = g("dc_v")
    tdc = [t for t, v in dcv if v == "1"]
    t0 = (tdc[0] if tdc else start) - 200_000; t1 = t0 + 6_000_000
    st_ev = g("u_main.state_q"); k_ev = g("u_main.k_q"); ov = g("u_main.out_valid")
    names = {0: "CLEAR", 1: "IDLE", 2: "MAC", 3: "DRAIN"}
    rows = [("FIR input strobe", dcv), ("FIR result strobe", ov)]
    for r, (name, ev) in enumerate(rows):
        y0 = 3.0 - r * 1.5
        xs, ys = level_trace(ev, t0, t1)
        xs = (xs - t0) / 1e6
        ax.plot(xs, [y0 + (0.8 if v == "1" else 0.0) for v in ys], "-", color="#0072B2", lw=0.9)
        ax.text(-0.05, y0 + 0.4, name, ha="right", va="center", fontsize=7)
    # state as labelled bus
    xs, ys = level_trace(st_ev, t0, t1)
    xs = (xs - t0) / 1e6
    y0 = 0.0
    seg = []
    for i in range(0, len(xs) - 1):
        if xs[i + 1] > xs[i]:
            seg.append((xs[i], xs[i + 1], int(ys[i], 2)))
    for a, b, v in seg:
        ax.plot([a, b], [y0, y0], "k-", lw=0.8); ax.plot([a, b], [y0 + 0.8, y0 + 0.8], "k-", lw=0.8)
        ax.plot([a, a], [y0, y0 + 0.8], "k-", lw=0.8)
        if b - a > 0.25:
            ax.text((a + b) / 2, y0 + 0.4, names.get(v, str(v)), ha="center", va="center", fontsize=6.5)
    ax.text(-0.05, y0 + 0.4, "FIR state", ha="right", va="center", fontsize=7)
    mac = [(a, b) for a, b, v in seg if v == 2]
    if mac:
        a, b = mac[0]
        ax.annotate("", xy=(a, -0.35), xytext=(b, -0.35), arrowprops=dict(arrowstyle="<->", lw=0.6))
        ax.text((a + b) / 2, -0.8, f"511 MACs = {(b - a) * 1e3:.0f} ns", ha="center", fontsize=6.5)
    ax.set_xlim(0, (t1 - t0) / 1e6); ax.set_ylim(-1.1, 4.2)
    ax.set_yticks([]); ax.grid(False); ax.set_xlabel("Time (µs)")
    ax.set_title("(b) One output of the 511-tap FIR", fontsize=8, loc="left")
    fig.subplots_adjust(left=0.27, right=0.97, top=0.95, bottom=0.115, hspace=0.47)
    savefig(fig, "waveforms"); plt.close(fig)
    print("waveforms figure written")


if __name__ == "__main__":
    main()
