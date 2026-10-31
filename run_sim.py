#!/usr/bin/env python3
"""Cross-platform (Windows / Linux / macOS) runner for the simulation flow.

    python run_sim.py              # all bit-exact testbenches (needs Icarus Verilog)
    python run_sim.py --quick      # shorter top-level run (60 instead of 600 live samples)
    python run_sim.py --model      # regenerate filters, ROMs and vectors first
    python run_sim.py --only tb_fir
    python run_sim.py --asic       # Project 3 core testbench as well

Windows: install Icarus Verilog from https://bleyer.org/icarus/ (tick "add to PATH"),
and Python 3 with:  pip install numpy scipy matplotlib pyserial
"""
import argparse, glob, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.join(ROOT, "sim")
RTL = sorted(glob.glob(os.path.join(ROOT, "rtl", "*.v")))
TBS = ["tb_cic", "tb_fir", "tb_chain", "tb_top"]


def run(cmd, cwd, log=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    out = p.stdout + p.stderr
    if log:
        with open(log, "w") as fh:
            fh.write(out)
    return p.returncode, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--model", action="store_true")
    ap.add_argument("--asic", action="store_true")
    ap.add_argument("--only", default=None)
    a = ap.parse_args()

    for tool in ("iverilog", "vvp"):
        if shutil.which(tool) is None:
            sys.exit(f"'{tool}' not found on PATH - install Icarus Verilog (https://bleyer.org/icarus/)")
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)

    if a.model:
        for script in ("model/design_filters.py", "asic/design_asic_fir.py", "model/gen_vectors.py"):
            print(">>", script)
            rc, out = run([sys.executable, script], ROOT)
            if rc:
                sys.exit(out)

    tbs = [a.only] if a.only else TBS
    ok = True
    for tb in tbs:
        t0 = time.time()
        rc, out = run(["iverilog", "-g2012", "-I", os.path.join("..", "rtl"), "-s", tb, "-o", tb + ".vvp",
                       tb + ".sv"] + [os.path.relpath(f, SIM) for f in RTL], SIM)
        if rc:
            print(f"{tb}: COMPILE ERROR\n{out}")
            ok = False
            continue
        args = ["vvp", "-n", tb + ".vvp"] + (["+quick"] if (a.quick and tb == "tb_top") else [])
        rc, out = run(args, SIM, os.path.join(ROOT, "results", tb + ".log"))
        passed = ("PASS " + tb) in out and "FAIL" not in out
        ok &= passed
        print(f"{tb:9s} {'PASS' if passed else 'FAIL'}  ({time.time() - t0:5.0f} s)   log: results/{tb}.log")
        if not passed:
            print("\n".join(l for l in out.splitlines() if "MISMATCH" in l or "ERROR" in l or "FAIL" in l)[:3000])

    if a.asic:
        d = os.path.join(ROOT, "asic", "sim")
        rc, out = run(["iverilog", "-g2012", "-I", os.path.join("..", "..", "rtl"), "-o", "tb_fir_par.vvp",
                       "tb_fir_par.sv", os.path.join("..", "..", "rtl", "fir_par.v")], d)
        rc, out = run(["vvp", "-n", "tb_fir_par.vvp"], d, os.path.join(ROOT, "asic", "results", "tb_fir_par.log"))
        passed = "PASS tb_fir_par" in out
        ok &= passed
        print(f"tb_fir_par {'PASS' if passed else 'FAIL'}")

    run([sys.executable, os.path.join("model", "summarize_sim.py")], ROOT)
    print("ALL PASS" if ok else "SOME TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
