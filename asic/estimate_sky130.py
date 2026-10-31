#!/usr/bin/env python3
"""Pre-layout SKY130 estimate for the Project 3 FIR core using only Yosys + ABC.

For PIPE = 0 and 1: synthesize, map to sky130_fd_sc_hd (typical corner, 25 C, 1.8 V),
report standard-cell area, cell/flop counts and ABC's critical-path delay (gate delays only,
no wires, no clock-to-Q/setup). This is a quick sanity check before the full LibreLane
run, which adds placement, routing parasitics and real static timing.

Needs the Liberty file sky130_fd_sc_hd__tt_025C_1v80.lib. Looked up in:
  $SKY130_LIB, $PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/lib/, asic/lib/
"""
import glob, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIBNAME = "sky130_fd_sc_hd__tt_025C_1v80.lib"


def find_lib():
    cands = [os.environ.get("SKY130_LIB", "")]
    if os.environ.get("PDK_ROOT"):
        cands += glob.glob(os.path.join(os.environ["PDK_ROOT"], "**", LIBNAME), recursive=True)
    cands += [os.path.join(HERE, "lib", LIBNAME), "/tmp/orfs/flow/platforms/sky130hd/lib/" + LIBNAME]
    for c in cands:
        if c and os.path.exists(c):
            return c
    sys.exit(f"cannot find {LIBNAME}; set SKY130_LIB=/path/to/{LIBNAME}")


def run(pipe, lib):
    abc_script = os.path.join(HERE, "results", "abc_delay.script")
    with open(abc_script, "w") as fh:
        fh.write("strash; ifraig; scorr; dc2; strash; &get -n; &dch -f; &nf; &put; "
                 "buffer; upsize; dnsize; stime -p\n")
    ys = f"""
read_verilog -I{HERE}/../rtl {HERE}/../rtl/fir_par.v
chparam -set PIPE {pipe} fir_par
synth -top fir_par -flatten
dfflibmap -liberty {lib}
abc -liberty {lib} -script {abc_script}
opt_clean -purge
stat -liberty {lib}
"""
    p = subprocess.run(["yosys", "-p", ys], capture_output=True, text=True)
    log = p.stdout
    with open(os.path.join(HERE, "results", f"yosys_sky130_p{pipe}.log"), "w") as fh:
        fh.write(log)
    if p.returncode:
        print(p.stderr[-2000:]); sys.exit(f"yosys failed for PIPE={pipe}")
    area = float(re.findall(r"Chip area for (?:top )?module '\\?fir_par':\s*([\d.]+)", log)[-1])
    cells = int(re.findall(r"^\s+(\d+)\s+[\d.E+-]*\s*cells$", log, re.M)[-1]) if re.findall(r"^\s+(\d+)\s+[\d.E+-]*\s*cells$", log, re.M) else \
        int(re.findall(r"Number of cells:\s+(\d+)", log)[-1])
    flops = sum(int(n) for n in re.findall(r"^\s+(\d+)\s+[\d.E+-]*\s+sky130_fd_sc_hd__df\w+", log, re.M)) or \
        sum(int(n) for n in re.findall(r"sky130_fd_sc_hd__df\w+\s+(\d+)", log))
    delays = [float(d) for d in re.findall(r"Delay\s*=\s*([\d.]+)\s*ps", log)]
    return dict(pipe=pipe, cell_area_um2=area, cells=cells, flops=flops,
                comb_delay_ps=max(delays) if delays else None)


def main():
    lib = find_lib()
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    res = [run(p, lib) for p in (0, 1)]
    for r in res:
        if r["comb_delay_ps"]:
            r["fmax_est_mhz_gate_only"] = 1e6 / r["comb_delay_ps"]
    with open(os.path.join(HERE, "results", "yosys_sky130.json"), "w") as fh:
        json.dump(dict(liberty=os.path.basename(lib), runs=res), fh, indent=2)
    for r in res:
        print(r)


if __name__ == "__main__":
    main()
