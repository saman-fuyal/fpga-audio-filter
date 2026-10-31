#!/usr/bin/env python3
"""Turn every result file into LaTeX macros (docs/report/results_macros.tex).

Numbers that do not exist yet (board measurements, Vivado, LibreLane) become a red
\\tbd{...} marker, so the paper always compiles and shows exactly what is still missing.
Re-run after each new result:  python3 docs/report/make_macros.py
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
R = os.path.join(ROOT, "results")


def load(path):
    try:
        return json.load(open(path))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def fmt(v, nd=1):
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, float):
        if nd == 0:                             # whole numbers: thousands separator from five digits on
            n = int(round(v))
            return f"{n:,}".replace(",", "{,}") if abs(n) >= 10000 else str(n)
        return f"{v:.{nd}f}"
    return f"{v:,}".replace(",", "{,}")


def collect():
    """All result values as strings; missing ones are '\\tbd{...}'."""
    out = {}

    def put(name, val, nd=1, tbd="TBD"):
        s = fmt(val, nd) if val is not None else None
        out[name] = s if s is not None else f"\\tbd{{{tbd}}}"

    # ---------------- filter design
    f = load(os.path.join(R, "filters.json"))
    c = f["comp"]
    put("CicDroop", -c["cic_droop_at_16k_db"], 2)
    put("CompRipple", c["cic_plus_comp_ripple_0_16k_db"], 3)
    put("CompStop", c["stopband_25k_50k_atten_db"], 1)
    put("CompShift", c["coef_shift"])
    put("AccBits", f["accumulator_bits_needed"])
    put("EndDelay", f["end_to_end_group_delay_ms"], 2)
    letters = "ABCD"
    for m in f["main"]:
        L = letters[m["bank"]]
        put(f"Shift{L}", m["coef_shift"])
        put(f"Ripple{L}", m["quantized"].get("passband_ripple_db"), 3)
        put(f"Stop{L}", m["quantized"].get("stopband_atten_db"), 1, "--")
        put(f"StopU{L}", m["quantized_unscaled"].get("stopband_atten_db"), 1, "--")
        put(f"StopF{L}", m["float"].get("stopband_atten_db"), 1, "--")

    # ---------------- simulation
    s = load(os.path.join(R, "sim_summary.json")) or {}
    for tb, name in (("tb_cic", "SimCic"), ("tb_fir", "SimFir"), ("tb_chain", "SimChain"), ("tb_top", "SimTop")):
        put(name, "PASS" if s.get(tb, {}).get("pass") else None)

    # ---------------- Yosys resource estimate (always available)
    y = load(os.path.join(R, "yosys_xilinx.json")) or {}
    for k, n in (("lut", "YLut"), ("ff", "YFf"), ("dsp48e1", "YDsp"), ("bram_tiles", "YBram"), ("lutram", "YLutram")):
        put(n, y.get(k), 1)

    # ---------------- Vivado (after build on the lab PC)
    v = load(os.path.join(R, "fpga_results.json")) or {}
    def used(k):
        return (v.get(k) or {}).get("used")
    put("VLut", int(used("lut")) if used("lut") is not None else None)
    put("VFf", int(used("ff")) if used("ff") is not None else None)
    put("VDsp", int(used("dsp")) if used("dsp") is not None else None)
    put("VBram", used("bram"), 1)
    put("VWns", v.get("wns_ns"), 3)
    put("VWhs", v.get("whs_ns"), 3)
    put("VFmax", v.get("fmax_mhz"), 1)
    put("VPower", (v.get("total_power_w") or 0) * 1e3 if v.get("total_power_w") else None, 0)
    put("VDynPower", (v.get("dynamic_power_w") or 0) * 1e3 if v.get("dynamic_power_w") else None, 0)

    # ---------------- on-board measurements
    hw = load(os.path.join(R, "hw_selftest.json"))
    if hw:
        put("HwFirSamples", sum(t["samples"] for t in hw["fir"]))
        put("HwFirErr", sum(t["mismatches"] for t in hw["fir"]))
        put("HwChainSamples", sum(t["samples"] for t in hw["chain"]))
        put("HwChainErr", sum(t["mismatches"] for t in hw["chain"]))
    else:
        for n in ("HwFirSamples", "HwFirErr", "HwChainSamples", "HwChainErr"):
            put(n, None)
    # paper value: 1 kHz from the laptop speaker; the phone speaker distorted (results/hw_d4b_summary.txt)
    cap = load(os.path.join(R, "hw_d4b_laptop.json")) or load(os.path.join(R, "hw_capture.json")) or {}
    put("HwSnr", cap.get("snr_db"), 1)
    put("HwThd", cap.get("thd_db"), 1)
    put("HwSinad", cap.get("sinad_db"), 1)
    put("HwTone", cap.get("tone_hz"), 0)
    # live-chain filter checks: tone level after the filter minus the level in bank 0, same setup
    def rej(on, off):
        x, y = load(os.path.join(R, on)), load(os.path.join(R, off))
        return (y["tone_dbfs"] - x["tone_dbfs"]) if x and y and "tone_dbfs" in x and "tone_dbfs" in y else None
    put("HwLpRej", rej("hw_d6_b1_3k.json", "hw_d6_b0_3k.json"), 1)
    put("HwAsicRej", rej("hw_d8_on_8k.json", "hw_d8_off_8k.json"), 1)
    ph = load(os.path.join(R, "hw_d4b_v0.json")) or {}
    put("HwPhoneThd", ph.get("thd_db"), 1)
    out["HaveHwFreq"] = "1" if os.path.exists(os.path.join(R, "hw_freqresp_b3.pdf")) else "0"
    out["HaveHwCapture"] = "1" if (os.path.exists(os.path.join(R, "hw_d4b_laptop.pdf"))
                                  or os.path.exists(os.path.join(R, "hw_capture.pdf"))) else "0"

    # ---------------- ASIC
    a = load(os.path.join(ROOT, "asic", "results", "asic_fir.json")) or {}
    put("AsicStop", a.get("stopband_atten_db"), 1)
    put("AsicCsd", a.get("csd_nonzero_digits_total"))
    e = load(os.path.join(ROOT, "asic", "results", "yosys_sky130.json"))
    if e:
        for r in e["runs"]:
            P = "Z" if r["pipe"] == 0 else "O"
            put(f"EArea{P}", r["cell_area_um2"], 0)
            put(f"ECells{P}", r["cells"])
            put(f"EFlops{P}", r["flops"])
            put(f"EDelay{P}", r["comb_delay_ps"] / 1000.0 if r["comb_delay_ps"] else None, 2)
            put(f"EFmax{P}", r.get("fmax_est_mhz_gate_only"), 0)
    else:
        for P in "ZO":
            for n in ("EArea", "ECells", "EFlops", "EDelay", "EFmax"):
                put(n + P, None)
    sw = load(os.path.join(ROOT, "asic", "results", "sweep.json"))
    out["HaveSweep"] = "1" if sw else "0"
    best = {}
    if sw:
        for r in sw:
            # only runs that reached sign-off count; timing at the typical corner, like the pre-layout estimate
            ws = r.get("ws_tt", r.get("timing__setup__ws"))
            if r.get("status", "complete") != "complete" or ws is None or ws < 0:
                continue
            k = r["pipe"]
            if k not in best or r["period_ns"] < best[k]["period_ns"]:
                best[k] = dict(r, min_period=r["period_ns"] - ws)
    for k, P in ((0, "Z"), (1, "O")):
        b = best.get(k, {})
        put(f"LPeriod{P}", b.get("min_period"), 1)
        # standard-cell area without filler cells (design__instance__area counts the fill too)
        put(f"LArea{P}", b.get("design__instance__area__stdcell", b.get("design__instance__area")), 0)
        put(f"LPower{P}", b.get("power__total") * 1e3 if b.get("power__total") is not None else None, 2)
        put(f"LFmax{P}", 1000.0 / b["min_period"] if b.get("min_period") else None, 0)
        put(f"LDrc{P}", b.get("magic__drc_error__count"))
        put(f"LLvs{P}", b.get("design__lvs_error__count"))

    az = best.get(0, {}).get("design__instance__area__stdcell")
    ao = best.get(1, {}).get("design__instance__area__stdcell")
    put("LAreaPct", 100.0 * (ao / az - 1) if az and ao else None, 0)
    return out


def main():
    out = collect()
    with open(os.path.join(HERE, "results_macros.tex"), "w") as fh:
        fh.write("% GENERATED by docs/report/make_macros.py -- do not edit\n")
        for k, val in out.items():
            fh.write(f"\\newcommand{{\\{k}}}{{{val}}}\n")
    print(f"{len(out)} macros -> docs/report/results_macros.tex "
          f"({sum('tbd' in v for v in out.values())} still TBD)")


if __name__ == "__main__":
    main()
