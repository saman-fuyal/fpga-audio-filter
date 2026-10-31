#!/usr/bin/env python3
"""Bit-exact golden model of the audio chain.

Every function mirrors the register-level behaviour of the matching RTL module, so the
simulation (and later the FPGA via the UART test port) must reproduce these numbers
*exactly*, sample for sample. Any single-LSB difference is a bug.
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from params import *  # noqa: F401,F403

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ------------------------------------------------------------------ helpers
def wrap(v, w):
    """Two's-complement wrap to w bits (what a w-bit register does)."""
    m = 1 << w
    v &= m - 1
    return v - m if v >= (m >> 1) else v


def sat(v, w):
    lo, hi = -(1 << (w - 1)), (1 << (w - 1)) - 1
    return lo if v < lo else hi if v > hi else v


def load_hex(path, width):
    out = []
    for line in open(path):
        line = line.strip()
        if line:
            out.append(wrap(int(line, 16), width))
    return out


def load_coefs():
    comp = load_hex(os.path.join(ROOT, "mem", "coef_comp.hex"), CW)[:COMP_TAPS]
    allm = load_hex(os.path.join(ROOT, "mem", "coef_main.hex"), CW)
    depth = 1 << MAIN_AW
    main = [allm[b * depth: b * depth + MAIN_TAPS] for b in range(MAIN_BANKS)]
    return comp, main


def load_par():
    """31-tap parallel FIR coefficients (Q1.15), shared with the ASIC (bank 4)."""
    return load_hex(os.path.join(ROOT, "mem", "coef_par.hex"), 16)


def fir_par(x16, q):
    """rtl/fir_par.v: y = sat16((sum q[k] x[n-k] + 2^14) >> 15), history starts at zero."""
    q = np.asarray(q, dtype=np.int64)
    hist = np.zeros(len(q), dtype=np.int64)
    out = []
    for v in x16:
        hist[1:] = hist[:-1]
        hist[0] = v
        out.append(sat((int(np.dot(hist, q)) + (1 << 14)) >> 15, 16))
    return out


def main_shifts():
    import json
    r = json.load(open(os.path.join(ROOT, "results", "filters.json")))
    return r["main_shifts"], r["comp"]["coef_shift"]


# ------------------------------------------------------------------ stimulus
def pdm_modulate(x):
    """2nd-order delta-sigma modulator (CIFB). x in [-1, 1) float -> list of 0/1 bits.

    This stands in for the ADMP421's internal modulator when we generate test stimulus.
    """
    i1 = i2 = 0.0
    y = 1.0
    bits = np.empty(len(x), dtype=np.uint8)
    for n, s in enumerate(x):
        i1 += s - y
        i2 += i1 - y
        y = 1.0 if i2 >= 0 else -1.0
        bits[n] = 1 if y > 0 else 0
    return bits


# ------------------------------------------------------------------ blocks
def cic_decim(bits, n=CIC_N, r=CIC_R, w=CIC_W):
    """N-stage CIC. Integrators are a register chain (stage k adds the OLD value of k-1),
    decimation fires on every r-th input, combs run at the low rate."""
    integ = [0] * n
    dly = [0] * n
    cnt = 0
    out = []
    for b in bits:
        x = 1 if b else -1
        new = [wrap(integ[0] + x, w)] + [wrap(integ[k] + integ[k - 1], w) for k in range(1, n)]
        integ = new
        if cnt == r - 1:
            cnt = 0
            v = integ[n - 1]
            for k in range(n):
                v, dly[k] = wrap(v - dly[k], w), v
            out.append(v)
        else:
            cnt += 1
    return out


def fir(x, h, shift, decim=1, dw=DW):
    """Serial-MAC FIR as built in rtl/fir_mac.v.

    y[m] = sat_dw( (sum_k h[k] * x[n-k] + 2^(shift-1)) >> shift ),  n = m*decim + decim-1
    History starts at zero (the RTL clears its delay line on reset / clear).
    """
    h = np.asarray(h, dtype=np.int64)
    ntaps = len(h)
    hist = np.zeros(ntaps, dtype=np.int64)  # hist[0] = newest
    out = []
    rnd = 1 << (shift - 1)
    for n, v in enumerate(x):
        hist[1:] = hist[:-1]
        hist[0] = v
        if n % decim == decim - 1:
            acc = int(np.dot(hist, h))
            out.append(sat((acc + rnd) >> shift, dw))
    return out


def dc_block(x, k=DC_K, dw=DW):
    """y = sat(x - (acc >> k)); acc += x - (acc >> k). Pole at z = 1 - 2^-k."""
    acc = 0
    out = []
    for v in x:
        est = acc >> k
        out.append(sat(v - est, dw))
        acc = acc + v - est
    return out


def gain_out(x, g, dw=DW, ow=OUT_W):
    """Digital gain 2^g with saturation, then keep the top OUT_W bits (floor)."""
    y24 = [sat(v << g, dw) for v in x]
    return y24, [v >> (dw - ow) for v in y24]


def chain(bits, bank, gain, coefs=None, shifts=None, taps=False):
    """Full live path: PDM bits -> out16 samples (and optionally every intermediate)."""
    comp, main = coefs if coefs else load_coefs()
    msh, csh = shifts if shifts else main_shifts()
    c = cic_decim(bits)
    c3 = [v << CIC_SHIFT for v in c]
    d = fir(c3, comp, CFRAC + csh, decim=COMP_DECIM)
    e = dc_block(d)
    if bank == PAR_BANK:      # 31-tap parallel FIR on the top 16 bits, result back to 24 bits
        f = [v << (DW - 16) for v in fir_par([v >> (DW - 16) for v in e], load_par())]
    else:
        f = fir(e, main[bank], CFRAC + msh[bank])
    y24, o = gain_out(f, gain)
    if taps:
        return dict(cic=c, comp=d, dc=e, fir=f, y24=y24, out=o)
    return o


# ------------------------------------------------------------------ output stage
def pwm_duty(s16, bits=PWM_BITS):
    """Offset-binary duty from a signed 16-bit sample (top PWM_BITS bits)."""
    return (s16 >> (OUT_W - bits)) + (1 << (bits - 1))


if __name__ == "__main__":
    # quick self-test: 1 kHz tone through every bank, print the measured level
    fs_pdm = F_PDM
    t = np.arange(int(0.05 * fs_pdm)) / fs_pdm
    for f0 in (500, 1000, 3000, 8000):
        bits = pdm_modulate(0.5 * np.sin(2 * np.pi * f0 * t))
        levels = []
        for b in range(MAIN_BANKS):
            o = np.array(chain(bits, b, 0)[400:], dtype=float)
            levels.append(20 * np.log10(np.sqrt(np.mean(o ** 2)) / 32768 + 1e-12))
        print(f"{f0:5d} Hz  " + "  ".join(f"bank{b}: {l:7.1f} dBFS" for b, l in enumerate(levels)))
