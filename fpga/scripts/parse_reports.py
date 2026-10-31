#!/usr/bin/env python3
"""Extract the numbers the paper needs from Vivado reports.

    python3 fpga/scripts/parse_reports.py      (after build.tcl)

Writes results/fpga_results.json and regenerates docs/report/results_macros.tex, so the
LaTeX tables update automatically.
"""
import json, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RPT = os.path.join(ROOT, "build", "reports")


def grab(path, pattern, cast=float, default=None):
    try:
        txt = open(path).read()
    except FileNotFoundError:
        return default
    m = re.search(pattern, txt, re.M)
    return cast(m.group(1)) if m else default


def util_row(path, name):
    """'| Slice LUTs | 1234 | 0 | 0 | 63400 | 1.95 |' -> (used, available, percent)."""
    try:
        txt = open(path).read()
    except FileNotFoundError:
        return None
    m = re.search(r"^\|\s*" + re.escape(name) + r"\*?\s*\|\s*([\d.]+)\s*\|.*?\|\s*([\d.]+)\s*\|\s*([<\d.]+)\s*\|\s*$", txt, re.M)
    if not m:
        return None
    return dict(used=float(m.group(1)), available=float(m.group(2)), percent=m.group(3))


def main():
    u = os.path.join(RPT, "utilization.rpt")
    t = os.path.join(RPT, "timing_summary.rpt")
    p = os.path.join(RPT, "power.rpt")
    s = os.path.join(RPT, "slack.txt")
    res = {
        "lut": util_row(u, "Slice LUTs"),
        "lutram": util_row(u, "LUT as Memory"),
        "ff": util_row(u, "Slice Registers"),
        "bram": util_row(u, "Block RAM Tile"),
        "dsp": util_row(u, "DSPs"),
        "wns_ns": grab(s, r"^WNS\s+(-?[\d.]+)"),
        "whs_ns": grab(s, r"^WHS\s+(-?[\d.]+)"),
        # Design Timing Summary row: WNS  TNS  TNS-failing  TNS-total  WHS ...; TNS is the 2nd number
        "tns_ns": grab(t, r"^\s*-?[\d.]+\s+(-?[\d.]+)\s+\d+\s+\d+\s+-?[\d.]+"),
        "total_power_w": grab(p, r"Total On-Chip Power \(W\)\s*\|\s*([\d.]+)"),
        "dynamic_power_w": grab(p, r"Dynamic \(W\)\s*\|\s*([\d.]+)"),
        "static_power_w": grab(p, r"Device Static \(W\)\s*\|\s*([\d.]+)"),
    }
    if res["wns_ns"] is not None:
        res["fmax_mhz"] = 1000.0 / (10.0 - res["wns_ns"])
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "fpga_results.json"), "w") as fh:
        json.dump(res, fh, indent=2)
    print(json.dumps(res, indent=2))
    # regenerate the LaTeX macros (also pulls in hardware-test and ASIC results)
    sys.path.insert(0, os.path.join(ROOT, "docs", "report"))
    import make_macros
    make_macros.main()


if __name__ == "__main__":
    main()
