#!/usr/bin/env python3
"""Interactive versions of the project's multi-curve plots: docs/plots/interactive_plots.html.

    py tools\\make_interactive_plots.py

Open the HTML file in a browser. Click a legend entry to hide or show that curve; double-click an
entry to show it alone (double-click again to bring all back). Drag to zoom, double-click the plot
to reset. The page loads Plotly from a CDN, so the browser needs internet access the first time.

Plots (each one is skipped if its data file is missing):
  1. decimator: CIC, compensation FIR and their cascade           (mem/coef_comp.hex)
  2. the five filter banks: design and measured on the FPGA        (mem/*.hex, results/hw_freqresp_b*.json)
  3. bit-exact check: RTL simulation vs the Python model            (results/sim_chain_out.txt)
  4. recorded voice through each bank                                     (results/voice_*.wav)
  5. SKY130 runs: typical-corner slack and cell area                (asic/results/sweep.json)
The static figures in the paper are unchanged; this page is for exploring the data on screen.
"""
import json, os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "model"))
import params as P                                   # noqa: E402
import golden as g                                   # noqa: E402

OUT = os.path.join(ROOT, "docs", "plots", "interactive_plots.html")
PLOTLY = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"
COL = ["#7f7f7f", "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]
NAMES = ["0: bypass", "1: low-pass 1 kHz", "2: high-pass 2 kHz", "3: band-pass 0.4-3.4 kHz",
         "4: 31-tap ASIC core"]


def r(a, nd=3):
    return [round(float(v), nd) for v in a]


def db(h):
    return 20 * np.log10(np.maximum(np.abs(h), 1e-9))


def fig_decimator():
    from scipy import signal
    from design_filters import cic_mag
    sc = json.load(open(os.path.join(ROOT, "results", "filters.json")))["comp"]["coef_shift"]
    comp, _ = g.load_coefs()
    h = np.array(comp, dtype=float) / (1 << (P.CFRAC + sc))
    f = np.linspace(1, P.F_CIC / 2, 2000)
    _, H = signal.freqz(h, worN=f, fs=P.F_CIC)
    c = cic_mag(f)
    tr = [dict(x=r(f / 1e3), y=r(db(c), 2), name="CIC (N=4, R=25)", line=dict(color=COL[1], dash="dot")),
          dict(x=r(f / 1e3), y=r(db(H), 2), name="Compensation FIR (63 taps)", line=dict(color=COL[2], dash="dash")),
          dict(x=r(f / 1e3), y=r(db(H * c), 2), name="Cascade", line=dict(color="black"))]
    lay = dict(xaxis=dict(title="Frequency (kHz)", range=[0, 50]), yaxis=dict(title="Magnitude (dB)", range=[-120, 10]),
               shapes=[dict(type="rect", x0=25, x1=50, y0=-120, y1=10, fillcolor="rgba(230,159,0,0.12)",
                            line=dict(width=0), layer="below")])
    return "Decimator: CIC, compensation FIR and cascade (aliasing band shaded)", tr, lay


def fig_banks():
    from scipy import signal
    _, main_c = g.load_coefs()
    msh, _ = g.main_shifts()
    f = np.unique(np.round(np.logspace(np.log10(20), np.log10(25000), 1500)))
    tr = []
    for b in range(5):
        if b < 4:
            h = np.array(main_c[b], dtype=float) / (1 << (P.CFRAC + msh[b]))
        else:
            h = np.array(g.load_par(), dtype=float) / 32768.0
        _, H = signal.freqz(h, worN=f, fs=P.FS)
        tr.append(dict(x=r(f, 1), y=r(db(H), 2), name=NAMES[b] + " (design)", legendgroup=f"b{b}",
                       line=dict(color=COL[b])))
        mp = os.path.join(ROOT, "results", f"hw_freqresp_b{b}.json")
        if os.path.exists(mp):
            d = json.load(open(mp))
            tr.append(dict(x=r(d["freqs"], 1), y=r(d["measured_db"], 2), name=NAMES[b] + " (measured on FPGA)",
                           legendgroup=f"b{b}", mode="markers",
                           marker=dict(color=COL[b], size=6, symbol="circle-open")))
    lay = dict(xaxis=dict(title="Frequency (Hz)", type="log"), yaxis=dict(title="Magnitude (dB)", range=[-130, 8]))
    return "Filter banks: design response and points measured on the board", tr, lay


def fig_bitexact():
    p = os.path.join(ROOT, "results", "sim_chain_out.txt")
    if not os.path.exists(p):
        return None
    sim = {}
    for line in open(p):
        s, n, v = (int(t) for t in line.split())
        sim.setdefault(s, []).append(v)
    tr = []
    for s in sorted(sim):
        e = os.path.join(ROOT, "sim", "vectors", f"chain_exp_{s}.hex")
        if not os.path.exists(e):
            continue
        ref = np.array([g.wrap(int(l, 16), P.OUT_W) for l in open(e) if l.strip()], dtype=float)
        rtl = np.array(sim[s], dtype=float)[:len(ref)]
        t = np.arange(len(ref)) / P.FS * 1e3
        tr.append(dict(x=r(t, 3), y=r(ref, 0), name=f"setting {s}: Python model", legendgroup=f"s{s}",
                       visible=True if s == 3 else "legendonly", line=dict(color=COL[6], width=4)))
        tr.append(dict(x=r(t, 3), y=r(rtl, 0), name=f"setting {s}: RTL simulation", legendgroup=f"s{s}",
                       visible=True if s == 3 else "legendonly", line=dict(color=COL[2], width=1.2)))
        tr.append(dict(x=r(t, 3), y=r(rtl - ref, 0), name=f"setting {s}: difference (LSB)", legendgroup=f"s{s}",
                       visible=True if s == 3 else "legendonly", line=dict(color=COL[3], width=1)))
    lay = dict(xaxis=dict(title="Time (ms)"), yaxis=dict(title="Output sample"))
    return "Bit-exact check: RTL simulation against the Python model (settings 0-4; 3 shown first)", tr, lay


def fig_voice():
    from scipy.io import wavfile
    from scipy import signal
    tags = [("voice_b0", NAMES[0]), ("voice_b1", NAMES[1]), ("voice_b2", NAMES[2]), ("voice_b3", NAMES[3]),
            ("voice_asic", NAMES[4])]
    if not all(os.path.exists(os.path.join(ROOT, "results", t + ".wav")) for t, _ in tags):
        return None
    tr, ref = [], None
    for i, (t, name) in enumerate(tags):
        fs, y = wavfile.read(os.path.join(ROOT, "results", t + ".wav"))
        f, p = signal.welch(y.astype(float) - y.mean(), fs, nperseg=2048)
        sm = np.array([p[(f >= fc * 2 ** (-1 / 12)) & (f <= fc * 2 ** (1 / 12))].mean() for fc in f])
        ref = sm.max() if ref is None else ref
        k = f >= 60
        tr.append(dict(x=r(f[k], 1), y=r(10 * np.log10(sm[k] / ref + 1e-16), 2), name=name, line=dict(color=COL[i])))
    lay = dict(xaxis=dict(title="Frequency (Hz)", type="log"), yaxis=dict(title="Power (dB, rel. bank 0 peak)",
                                                                           range=[-110, 5]))
    return "Recorded voice through each bank (1/6-octave smoothed)", tr, lay


def fig_asic():
    p = os.path.join(ROOT, "asic", "results", "sweep.json")
    if not os.path.exists(p):
        return None
    rows = json.load(open(p))
    tr = []
    for pipe, sym in ((0, "circle"), (1, "square")):
        rr = sorted([x for x in rows if x["pipe"] == pipe and x.get("ws_tt") is not None], key=lambda x: x["period_ns"])
        if not rr:
            continue
        per = [x["period_ns"] for x in rr]
        tr.append(dict(x=per, y=r([x["ws_tt"] for x in rr], 3), name=f"PIPE={pipe}: setup slack (typical corner)",
                       mode="lines+markers", marker=dict(symbol=sym, size=8), line=dict(color=COL[1 + pipe])))
        tr.append(dict(x=per, y=r([x["design__instance__area__stdcell"] / 1e3 for x in rr], 1), xaxis="x2",
                       yaxis="y2", name=f"PIPE={pipe}: cell area", mode="lines+markers",
                       marker=dict(symbol=sym + "-open", size=8), line=dict(color=COL[1 + pipe], dash="dash")))
    # two stacked panels sharing the period axis, instead of two y-axes on one panel
    lay = dict(height=640,
               xaxis=dict(anchor="y", domain=[0, 1], matches="x2", showticklabels=False),
               yaxis=dict(title="Setup slack, typical corner (ns)", domain=[0.56, 1], zeroline=True),
               xaxis2=dict(title="Clock period (ns)", anchor="y2", domain=[0, 1]),
               yaxis2=dict(title="Cell area without fill (10\u00b3 \u00b5m\u00b2)", domain=[0, 0.44]))
    return "SKY130 runs: slack (top) and cell area (bottom) against the clock period", tr, lay


def main():
    figs = []
    for fn in (fig_decimator, fig_banks, fig_bitexact, fig_voice, fig_asic):
        try:
            res = fn()
        except (OSError, KeyError, ValueError) as e:
            print(f"skipped {fn.__name__}: {e}")
            continue
        if res is None:
            print(f"skipped {fn.__name__}: data file not found")
            continue
        figs.append(res)
    divs, js = [], []
    for i, (title, tr, lay) in enumerate(figs):
        for t in tr:
            t.setdefault("type", "scatter")
            t.setdefault("mode", "lines")
        lay.setdefault("height", 460)
        lay.update(margin=dict(l=60, r=30, t=10, b=50),
                   legend=dict(orientation="h", y=-0.18), hovermode="closest", template="plotly_white")
        divs.append(f'<section><h2>{title}</h2><div id="p{i}" class="plot"></div></section>')
        js.append(f"Plotly.newPlot('p{i}', {json.dumps(tr)}, {json.dumps(lay)}, {{responsive: true, displaylogo: false}});")
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Interactive plots</title>
<script src="{PLOTLY}"></script>
<style>
 body {{ font-family: Georgia, 'Times New Roman', serif; margin: 0 auto; max-width: 980px; padding: 16px; color: #222; background: #fff; }}
 h1 {{ font-size: 1.5rem; margin: 0.4em 0 0.2em; }}
 h2 {{ font-size: 1.05rem; margin: 1.6em 0 0.3em; }}
 p.hint {{ color: #555; margin: 0 0 0.6em; }}
 .plot {{ width: 100%; }}
</style></head><body>
<h1>Real-time digital microphone filter: interactive plots</h1>
<p class="hint">Click a legend entry to hide or show that curve. Double-click an entry to show it alone, and
double-click it again to bring every curve back. Drag on a plot to zoom; double-click the plot to reset.</p>
{''.join(divs)}
<script>
{chr(10).join(js)}
</script>
</body></html>
"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"{len(figs)} plots -> {OUT} ({os.path.getsize(OUT) / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
