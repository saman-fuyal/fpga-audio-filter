#!/usr/bin/env python3
"""Collect PASS/FAIL and checked-sample counts from results/tb_*.log -> results/sim_summary.json"""
import glob, json, os, re
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
out = {}
for f in sorted(glob.glob(os.path.join(ROOT, "results", "tb_*.log"))):
    txt = open(f).read()
    name = os.path.basename(f)[:-4]
    nums = [int(n) for n in re.findall(r"(\d+) (?:outputs|samples)", txt)]
    out[name] = {"pass": ("PASS " + name) in txt and "FAIL" not in txt,
                 "checked_samples": sum(nums), "lines": [l.strip() for l in txt.splitlines() if l.startswith("  ") or "PASS" in l or "FAIL" in l]}
json.dump(out, open(os.path.join(ROOT, "results", "sim_summary.json"), "w"), indent=2)
for k, v in out.items():
    print(f"{k:12s} {'PASS' if v['pass'] else 'FAIL'}  ({v['checked_samples']} samples checked)")
