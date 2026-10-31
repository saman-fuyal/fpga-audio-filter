#!/usr/bin/env python3
"""Pure sine test tones for the microphone tests: play them from the laptop speaker.

    py tools\\make_test_tones.py      -> tools/test_tones/sine_<f>Hz.wav (48 kHz, 16 bit, 60 s, -6 dBFS)

Each file is an exact sine (harmonics below -100 dB), with 20 ms fade-in and fade-out so the
speaker does not click. Copy the folder to the phone and play the files in any music player.
"""
import os
import numpy as np
from scipy.io import wavfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "test_tones")
FS, SECONDS, LEVEL_DBFS = 48000, 60, -6.0
FREQS = [200, 500, 1000, 3000, 8000]


def main():
    os.makedirs(OUT, exist_ok=True)
    t = np.arange(FS * SECONDS) / FS
    fade = np.minimum(1.0, np.minimum(t, t[-1] - t) / 0.02)
    amp = 10 ** (LEVEL_DBFS / 20) * 32767
    for f in FREQS:
        y = np.round(amp * fade * np.sin(2 * np.pi * f * t)).astype(np.int16)
        p = os.path.join(OUT, f"sine_{f}Hz.wav")
        wavfile.write(p, FS, y)
        print("written", p)


if __name__ == "__main__":
    main()
