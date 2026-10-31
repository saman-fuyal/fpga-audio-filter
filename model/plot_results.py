#!/usr/bin/env python3
"""Figures for the report from simulation results.

  figs/bitexact.pdf      RTL simulation output vs Python model (and their difference)
  figs/chain_spectra.pdf spectrum of the 3-tone test signal after each filter bank
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from params import *  # noqa
import golden as g

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIGS = os.path.join(ROOT, "docs", "report", "figs")


def read_hex(path, w):
    return [g.wrap(int(l, 16), w) for l in open(path) if l.strip()]


def main():
    from design_filters import bw_style, savefig, C_SKY, C_VERM, C_GREEN, C_BLUE, C_PURPLE
    plt = bw_style()

    # ---------------- bit-exact overlay (setting 3: band-pass, gain 6)
    sim = {}
    for line in open(os.path.join(ROOT, "results", "sim_chain_out.txt")):
        s, n, v = (int(t) for t in line.split())
        sim.setdefault(s, []).append(v)
    exp = read_hex(os.path.join(ROOT, "sim", "vectors", "chain_exp_3.hex"), OUT_W)
    rtl = np.array(sim[3], dtype=float)
    ref = np.array(exp, dtype=float)
    t = np.arange(len(ref)) / FS * 1e3
    fig, ax = plt.subplots(2, 1, figsize=(3.5, 2.5), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    ax[0].plot(t, ref, color=C_SKY, lw=2.4, label="Python golden model")
    ax[0].plot(t, rtl, "-", color=C_VERM, lw=0.6, label="RTL simulation")
    # legend above the plot area, so it never covers the signal
    ax[0].set_ylabel("Output sample")
    ax[0].legend(fontsize=6.5, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False,
                 borderaxespad=0.2, handlelength=1.8, columnspacing=1.5)
    ax[1].plot(t, rtl - ref, color=C_GREEN, lw=0.9)
    ax[1].set_ylim(-1, 1); ax[1].set_ylabel("Difference (LSB)"); ax[1].set_xlabel("Time (ms)")
    fig.tight_layout(); savefig(fig, "bitexact"); plt.close(fig)
    print("bitexact: max |diff| =", np.max(np.abs(rtl - ref)), "over", len(ref), "samples")

    # ---------------- spectra of the 3-tone signal through each bank
    n = int(0.25 * F_PDM)
    tt = np.arange(n) / F_PDM
    x = (np.sin(2 * np.pi * 440 * tt) + np.sin(2 * np.pi * 2500 * tt + 1) + np.sin(2 * np.pi * 9000 * tt + 2)) * 0.2
    bits = g.pdm_modulate(x)
    comp, main = g.load_coefs()
    shifts = g.main_shifts()
    fig, ax = plt.subplots(figsize=(3.5, 2.4))
    sty = ["-", "--", "-.", ":", "-"]
    gry = ["#999999", C_BLUE, C_VERM, C_GREEN, C_PURPLE]
    for b in range(MAIN_BANKS + 1):
        y = np.array(g.chain(bits, b, 0, (comp, main), shifts)[600:], dtype=float)
        w = np.blackman(len(y))
        Y = np.abs(np.fft.rfft(y * w)) / (np.sum(w) / 2) / 32768
        f = np.fft.rfftfreq(len(y), 1 / FS)
        ax.semilogx(np.maximum(f, 1), 20 * np.log10(Y + 1e-12), sty[b], color=gry[b], lw=0.6, label=f"bank {b}")
    ax.set_xlim(100, 25000); ax.set_ylim(-150, 0)
    ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("Level (dBFS)")
    ax.legend(fontsize=6, ncol=2, loc="lower left")
    fig.tight_layout(); savefig(fig, "chain_spectra"); plt.close(fig)
    print("figures written")


if __name__ == "__main__":
    main()
