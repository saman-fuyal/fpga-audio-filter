#!/usr/bin/env python3
"""Paper figure from the board measurements: measured vs designed response of bank 3.

    py model\\plot_hw.py      -> docs/report/figs/hw_freqresp_b3.pdf/.png (if results/hw_freqresp_b3.json exists)
"""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import golden as g                     # noqa: E402
import params as P                     # noqa: E402
from design_filters import bw_style, savefig, C_BLUE, C_VERM   # noqa: E402


def main(bank=3):
    src = os.path.join(ROOT, "results", f"hw_freqresp_b{bank}.json")
    if not os.path.exists(src):
        print("no", src, "- run  py host\\af_host.py --port COMx all  first")
        return
    from scipy import signal
    d = json.load(open(src))
    f = np.array(d["freqs"]); m = np.array(d["measured_db"])
    _, main_c = g.load_coefs()
    msh, _ = g.main_shifts()
    h = np.array(main_c[bank]) / (1 << (P.CFRAC + msh[bank]))
    w, H = signal.freqz(h, worN=16384, fs=P.FS)
    _, Hm = signal.freqz(h, worN=f, fs=P.FS)
    dev = np.abs(m - 20 * np.log10(np.maximum(np.abs(Hm), 1e-12)))
    plt = bw_style()
    fig, ax = plt.subplots(figsize=(3.5, 2.3))
    ax.semilogx(np.maximum(w, 1), 20 * np.log10(np.maximum(np.abs(H), 1e-9)), "-", color=C_BLUE, lw=0.5,
                label="Design (quantized)", zorder=1)
    ax.semilogx(f, m, "o", ms=2.8, mfc=C_VERM, mec="black", mew=0.4, label="Measured on FPGA",
                zorder=3)
    ax.set_xlim(40, 25000); ax.set_ylim(-120, 6); ax.set_yticks(range(-120, 1, 20))
    ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("Magnitude (dB)")
    ax.legend(fontsize=6.5, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False,
              borderaxespad=0.2, handlelength=1.8, columnspacing=1.5)
    fig.tight_layout(); savefig(fig, f"hw_freqresp_b{bank}"); plt.close(fig)
    k = m > -60
    print(f"hw_freqresp_b{bank}: {len(f)} points, max deviation above -60 dB {dev[k].max():.4f} dB")


if __name__ == "__main__":
    main()
