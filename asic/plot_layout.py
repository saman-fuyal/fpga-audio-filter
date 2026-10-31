#!/usr/bin/env python3
"""Fig. 9 of the paper: the routed layout of the 31-tap core, drawn from the final DEF in grey tones.

LibreLane's own render (final/render/*.png) shows every layer in full colour, and the n-well and fill
layers cover the whole core in magenta, so nothing of the routing is visible in print. This script
draws only the metal wiring, one grey tone per layer, plus the power straps and the die outline, on a
white background, at a size that stays sharp in one column.

    (Ubuntu)  cp ~/fpga-audio-filter/asic/runs/p1_t7p0_u45/final/def/fir_par.def \\
                 /mnt/c/Users/ACER/Desktop/fpga-audio-filter/fpga-audio-filter/asic/results/
    (Windows) py asic\\plot_layout.py asic\\results\\fir_par.def
              -> docs/report/figs/user/asic_layout.png (+ .pdf)

Needs only numpy and matplotlib (no KLayout).
"""
import argparse, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "docs", "report", "figs", "user", "asic_layout.png")

# grey tone and line width (points) per routing layer, light for low layers, dark for high ones
STYLE = {"li1": ("#d9d9d9", 0.10), "met1": ("#bdbdbd", 0.12), "met2": ("#8c8c8c", 0.14),
         "met3": ("#5a5a5a", 0.18), "met4": ("#303030", 0.22), "met5": ("#000000", 0.30)}


def tokens(text):
    """DEF text split into tokens, with parentheses and semicolons as separate tokens."""
    return re.findall(r"\(|\)|;|[^\s();]+", text)


def section(text, name):
    m = re.search(rf"^\s*{name}\b.*?^\s*END\s+{name}\b", text, re.S | re.M)
    return m.group(0) if m else ""


def parse_routes(sec, special):
    """Return {layer: [((x1, y1), (x2, y2), width_or_None), ...]} from a NETS/SPECIALNETS section."""
    segs = {}
    t = tokens(sec)
    i, n = 0, len(t)
    layer, width, prev = None, None, None
    while i < n:
        tok = t[i]
        if tok in ("ROUTED", "FIXED", "COVER", "NEW"):
            if i + 1 < n:
                layer = t[i + 1]
                i += 2
                width, prev = None, None
                if special and i < n and re.fullmatch(r"-?\d+(\.\d+)?", t[i]):
                    width = float(t[i]); i += 1
                continue
        if tok == ";":
            layer, prev = None, None
            i += 1; continue
        if tok == "(" and layer is not None:
            j = t.index(")", i)
            vals = t[i + 1:j]
            i = j + 1
            if len(vals) < 2:
                continue
            x = prev[0] if vals[0] == "*" and prev else (float(vals[0]) if vals[0] != "*" else None)
            y = prev[1] if vals[1] == "*" and prev else (float(vals[1]) if vals[1] != "*" else None)
            if x is None or y is None:
                continue
            pt = (x, y)
            if prev is not None and pt != prev:
                segs.setdefault(layer, []).append((prev, pt, width))
            prev = pt
            continue
        if tok in ("RECT", "VIRTUAL", "MASK", "SHAPE", "STYLE"):
            # RECT ( dx1 dy1 dx2 dy2 ) and VIRTUAL ( x y ) are not wires: skip their parentheses
            if tok in ("RECT", "VIRTUAL") and i + 1 < n and t[i + 1] == "(":
                i = t.index(")", i + 1) + 1
                if tok == "VIRTUAL":
                    prev = None
                continue
            i += 2; continue
        i += 1
    return segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("def_file")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    text = open(a.def_file, errors="replace").read()
    unit = float(re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", text).group(1))
    die = [float(v) / unit for v in re.search(r"DIEAREA\s*\(\s*(\S+)\s+(\S+)\s*\)\s*\(\s*(\S+)\s+(\S+)\s*\)",
                                              text).groups()]
    nets = parse_routes(section(text, "NETS"), special=False)
    pwr = parse_routes(section(text, "SPECIALNETS"), special=True)
    if not nets:
        sys.exit("no routed nets found: is this the final (routed) DEF?")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    plt.rcParams.update({"font.size": 7, "font.family": "serif"})
    w_um, h_um = die[2] - die[0], die[3] - die[1]
    fig_w = 3.4
    fig, ax = plt.subplots(figsize=(fig_w, fig_w * h_um / w_um + 0.35))
    order = ["li1", "met1", "met2", "met3", "met4", "met5"]
    counts = {}
    for lay in order:
        s = nets.get(lay, [])
        if s:
            col, lw = STYLE[lay]
            ax.add_collection(LineCollection([[(p[0] / unit, p[1] / unit), (q[0] / unit, q[1] / unit)]
                                              for p, q, _ in s], colors=col, linewidths=lw))
            counts[lay] = len(s)
    for lay in ("met4", "met5"):                # power straps on top, at their real width (the met1
                                                # rails along every cell row would only grey the picture)
        s = pwr.get(lay, [])
        if not s:
            continue
        col = STYLE.get(lay, ("#000000", 0.3))[0]
        pt_per_um = fig_w * 72.0 / w_um
        ax.add_collection(LineCollection([[(p[0] / unit, p[1] / unit), (q[0] / unit, q[1] / unit)]
                                          for p, q, _ in s], colors=col,
                                         linewidths=[max((wd or 0) / unit * pt_per_um, 0.3) for _, _, wd in s],
                                         alpha=0.55))
    ax.add_patch(plt.Rectangle((die[0], die[1]), w_um, h_um, fill=False, lw=0.6, ec="black"))
    ax.set_xlim(die[0], die[2]); ax.set_ylim(die[1], die[3]); ax.set_aspect("equal")
    ax.set_xlabel(r"x ($\mu$m)"); ax.set_ylabel(r"y ($\mu$m)")
    ax.tick_params(length=2)
    fig.tight_layout(pad=0.3)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    fig.savefig(a.out, dpi=600)
    fig.savefig(os.path.splitext(a.out)[0] + ".pdf")
    plt.close(fig)
    print(f"die {w_um:.0f} x {h_um:.0f} um; wire segments per layer: "
          + ", ".join(f"{k} {v}" for k, v in counts.items())
          + f"; power layers: {', '.join(sorted(pwr)) or 'none'}")
    print("written", a.out)


if __name__ == "__main__":
    main()
