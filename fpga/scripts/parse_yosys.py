#!/usr/bin/env python3
"""Parse results/yosys_xilinx_stat.txt (Yosys synth_xilinx) -> results/yosys_xilinx.json"""
import json, os, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
txt = open(os.path.join(ROOT, "results", "yosys_xilinx_stat.txt")).read()


def count(pattern):
    tot = 0
    for m in re.finditer(r"^\s+(\d+)\s+(?:[\d.E+-]+\s+)?(\S+)\s*$", txt, re.M):
        if re.fullmatch(pattern, m.group(2)):
            tot += int(m.group(1))
    return tot


res = {
    "lut": count(r"LUT[1-6]"),
    "lutram": count(r"RAM\d+[XM].*|RAM\d+S|RAM\d+D.*"),
    "ff": count(r"FD[RSCPE]E?"),
    "carry4": count(r"CARRY4"),
    "dsp48e1": count(r"DSP48E1"),
    "bram18": count(r"RAMB18E1"),
    "bram36": count(r"RAMB36E1"),
    "srl": count(r"SRL.*"),
    "muxf": count(r"MUXF[78]"),
}
res["bram_tiles"] = res["bram36"] + 0.5 * res["bram18"]
json.dump(res, open(os.path.join(ROOT, "results", "yosys_xilinx.json"), "w"), indent=2)
print(json.dumps(res, indent=2))
