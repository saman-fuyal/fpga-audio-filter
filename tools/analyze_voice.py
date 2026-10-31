#!/usr/bin/env python3
"""How each filter bank shaped a recorded voice.

    py tools\\analyze_voice.py      (after tools\\record_voice.bat)
    -> results/hw_voice.txt and results/hw_voice.png/.pdf

For every recording it prints the level, the peak (clipping check) and how much of the voice energy
falls in each frequency band, relative to the same band in the bank-0 recording. A filter shows up as
a strong drop in the bands it should remove: bank 1 above 1 kHz, bank 2 below 2 kHz, bank 3 below
400 Hz and above 3.4 kHz, the ASIC core above 3.4 kHz.
"""
import os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RES = os.path.join(ROOT, "results")
RUNS = [("voice_b0", "bank 0 bypass"), ("voice_b1", "bank 1 low-pass 1 kHz"),
        ("voice_b2", "bank 2 high-pass 2 kHz"), ("voice_b3", "bank 3 band-pass 0.4-3.4 kHz"),
        ("voice_asic", "31-tap ASIC core (3.4 kHz low-pass)")]
BANDS = [(80, 300), (500, 900), (1200, 1800), (2300, 3200), (4500, 7000), (8000, 16000)]   # gaps skip the transition bands


def main():
    from scipy.io import wavfile
    from scipy import signal
    spec, rows = {}, []
    for tag, name in RUNS:
        path = os.path.join(RES, tag + ".wav")
        if not os.path.exists(path):
            sys.exit(f"missing {path}: run tools\\record_voice.bat first")
        fs, y = wavfile.read(path)
        y = y.astype(float)
        f, p = signal.welch(y - y.mean(), fs, nperseg=2048)
        spec[tag] = (f, p)
        band = [p[(f >= a) & (f < b)].sum() for a, b in BANDS]
        rms = 20 * np.log10(np.sqrt(np.mean(y ** 2)) / 32768 + 1e-12)
        peak = 20 * np.log10(np.max(np.abs(y)) / 32768 + 1e-12)
        rows.append((tag, name, rms, peak, band))
    ref = rows[0][4]
    head = "recording".ljust(36) + "peak".rjust(7) + "".join(f"{a}-{b} Hz".rjust(15) for a, b in BANDS)
    lines = ["Voice through each bank: energy per band relative to bank 0 (dB); peak in dBFS", head]
    for tag, name, rms, peak, band in rows:
        rel = [10 * np.log10(b / r) if b > 0 and r > 0 else float("nan") for b, r in zip(band, ref)]
        clip = "  CLIPPED" if peak > -1.0 else ""
        lines.append(f"{name[:36]:36s}{peak:7.1f}" + "".join(f"{v:15.1f}" for v in rel) + clip)
    if any(r[3] > -1.0 for r in rows):
        lines.append("Clipped recordings add distortion products in every band: redo them at a lower gain.")
    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(RES, "hw_voice.txt"), "w").write(txt + "\n")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sys.path.insert(0, os.path.join(ROOT, "model"))
    from design_filters import bw_style, C_BLUE, C_VERM, C_GREEN, C_ORANGE, C_PURPLE
    plt = bw_style()

    def smooth(f, p, frac=6):
        """1/frac-octave smoothing, so the spectra read as curves instead of a noisy band."""
        out = np.empty_like(p)
        for i, fc in enumerate(f):
            k = (f >= fc * 2 ** (-0.5 / frac)) & (f <= fc * 2 ** (0.5 / frac))
            out[i] = p[k].mean() if k.any() else p[i]
        return out

    f0, p0 = spec["voice_b0"]
    ref_db = 10 * np.log10(smooth(f0, p0) / p0.max() + 1e-16)
    cols = [C_BLUE, C_VERM, C_GREEN, C_PURPLE]
    edges = {"voice_b1": [1000], "voice_b2": [2000], "voice_b3": [400, 3400], "voice_asic": [3400]}
    fig, axs = plt.subplots(2, 2, figsize=(3.5, 3.2), sharex=True, sharey=True)
    for ax, (tag, name, *_), col in zip(axs.flat, rows[1:], cols):
        f, p = spec[tag]
        ax.semilogx(np.maximum(f0, 1), ref_db, "-", color="#9a9a9a", lw=0.8, label="bank 0")
        ax.semilogx(np.maximum(f, 1), 10 * np.log10(smooth(f, p) / p0.max() + 1e-16), "-", color=col, lw=0.9,
                    label=name.split(" (")[0].replace("31-tap ASIC core", "ASIC core"))
        for e in edges[tag]:
            ax.axvline(e, color="black", lw=0.4, ls=":")
        ax.set_title(name.split(" (")[0].replace("31-tap ASIC core", "ASIC core (3.4 kHz LP)"), fontsize=6.5, pad=2)
        ax.set_xlim(80, 20000); ax.set_ylim(-110, 5); ax.grid(alpha=0.3)
    for ax in axs[1]:
        ax.set_xlabel("Frequency (Hz)")
    for ax in axs[:, 0]:
        ax.set_ylabel("Power (dB)")
    fig.legend(handles=[plt.Line2D([], [], color="#9a9a9a", lw=0.8)], labels=["bank 0 (no filter), same speaker"],
               loc="upper center", fontsize=6, frameon=False, ncol=1, bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout(rect=(0, 0, 1, 0.95), h_pad=0.6, w_pad=0.4)
    fig.savefig(os.path.join(RES, "hw_voice.png"), dpi=600)
    fig.savefig(os.path.join(RES, "hw_voice.pdf"))
    plt.close(fig)
    print("-> results/hw_voice.txt, hw_voice.png/.pdf")


if __name__ == "__main__":
    main()
