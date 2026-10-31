#!/usr/bin/env python3
"""Generate stimulus + expected-response files for the self-checking testbenches.

All files are plain hex, one value per line, read with $readmemh. Two's-complement values
are written at their RTL width. Directory: sim/vectors/
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from params import *  # noqa: F401,F403
import golden as g

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VD = os.path.join(ROOT, "sim", "vectors")
rng = np.random.default_rng(2026)


def wr(name, vals, width):
    digits = (width + 3) // 4
    mask = (1 << width) - 1
    with open(os.path.join(VD, name), "w") as fh:
        for v in vals:
            fh.write(format(int(v) & mask, "0{}X".format(digits)) + "\n")


def tone_bits(seconds, freqs, amp=0.5, noise=0.0):
    n = int(seconds * F_PDM)
    t = np.arange(n) / F_PDM
    x = sum(np.sin(2 * np.pi * f * t + i) for i, f in enumerate(freqs)) * (amp / len(freqs))
    if noise:
        x = x + noise * rng.standard_normal(n)
    return g.pdm_modulate(np.clip(x, -0.95, 0.95))


def main():
    os.makedirs(VD, exist_ok=True)
    comp, main = g.load_coefs()
    msh, csh = g.main_shifts()

    # ------------------------------------------------ CIC: random bits + tone bits
    bits = np.concatenate([rng.integers(0, 2, 5000), tone_bits(0.004, [1000, 7000]),
                           np.ones(300, dtype=int), np.zeros(300, dtype=int)])
    wr("cic_in.hex", bits, 1)
    c = g.cic_decim(bits)
    wr("cic_exp.hex", c, CIC_W)
    print(f"cic: {len(bits)} bits -> {len(c)} outputs")

    # ------------------------------------------------ FIR banks: impulse, full-scale extremes, random
    lo, hi = -(1 << (DW - 1)), (1 << (DW - 1)) - 1
    x = [hi] + [0] * (MAIN_TAPS + 5)                       # impulse -> coefficients
    x += list(rng.integers(lo, hi + 1, 600))                 # random full-scale
    # worst case for saturation: sign pattern of the coefficients at full scale
    x += [hi if h >= 0 else lo for h in main[2][::-1]] * 1
    x += [lo if h >= 0 else hi for h in main[2][::-1]] * 1
    x += list((0.3 * hi * np.sin(2 * np.pi * 1500 * np.arange(800) / FS)).astype(int))
    wr("fir_in.hex", x, DW)
    for b in range(MAIN_BANKS):
        y = g.fir(x, main[b], CFRAC + msh[b])
        wr(f"fir_exp_b{b}.hex", y, DW)
    print(f"fir: {len(x)} inputs per bank")

    # comp FIR, decimate by 2
    xc = [v << CIC_SHIFT for v in c] + list(rng.integers(lo, hi + 1, 400))
    wr("comp_in.hex", xc, DW)
    wr("comp_exp.hex", g.fir(xc, comp, CFRAC + csh, decim=COMP_DECIM), DW)

    # DC blocker
    xd = list(rng.integers(lo // 4, hi // 4, 3000) + (hi // 3)) + [hi] * 500 + [lo] * 500
    wr("dc_in.hex", xd, DW)
    wr("dc_exp.hex", g.dc_block(xd), DW)

    # ------------------------------------------------ full chain (PDM -> out16), several settings
    cb = tone_bits(0.03, [440, 2500, 9000], amp=0.6, noise=0.01)
    wr("chain_in.hex", cb, 1)
    settings = [(0, 1), (1, 4), (2, 0), (3, 1), (4, 2)]   # setting 1 saturates; 4 = ASIC core
    with open(os.path.join(VD, "chain_settings.txt"), "w") as fh:
        for b, gn in settings:
            fh.write(f"{b} {gn}\n")
    for i, (b, gn) in enumerate(settings):
        o = g.chain(cb, b, gn, (comp, main), (msh, csh))
        wr(f"chain_exp_{i}.hex", o, OUT_W)
    print(f"chain: {len(cb)} bits -> {len(o)} outputs x {len(settings)} settings")

    # ------------------------------------------------ top-level (mic pins + UART), shorter
    tb = tone_bits(0.012, [700, 4000], amp=0.6)
    wr("top_mic.hex", tb, 1)
    # live path with switches: bank 1, gain 3
    wr("top_live_exp.hex", g.chain(tb, 1, 3, (comp, main), (msh, csh)), OUT_W)

    # UART 'T' (FIR test) : bank 3, 40 samples of 24-bit
    tx = list(rng.integers(lo, hi + 1, 40))
    wr("uart_t_in.hex", tx, DW)
    wr("uart_t_exp.hex", g.fir(tx, main[3], CFRAC + msh[3]), DW)
    # UART 'T' with bank 4 (31-tap parallel FIR): input 24-bit, core sees the top 16 bits
    tx4 = list(rng.integers(lo, hi + 1, 30))
    wr("uart_t4_in.hex", tx4, DW)
    wr("uart_t4_exp.hex", [v << (DW - 16) for v in g.fir_par([v >> (DW - 16) for v in tx4], g.load_par())], DW)
    # UART 'D' (chain test) : bank 2, gain 5, 200 bytes of PDM (1600 bits -> 32 outputs)
    db = tone_bits(1600 / F_PDM, [3000], amp=0.5)
    pdm_bytes = [int(sum(int(db[8 * i + j]) << j for j in range(8))) for i in range(200)]
    wr("uart_d_in.hex", pdm_bytes, 8)
    wr("uart_d_exp.hex", g.chain(db[:1600], 2, 5, (comp, main), (msh, csh)), OUT_W)
    print("top/uart vectors written")


if __name__ == "__main__":
    main()
