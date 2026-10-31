#!/usr/bin/env python3
"""Host tool for the Nexys A7 audio filter (UART test port, 1 Mbaud 8N1).

    pip install pyserial numpy scipy matplotlib

    python3 host/af_host.py --port COM5 ping            # Windows
    python3 host/af_host.py --port /dev/ttyUSB1 ping     # Linux (the 2nd FTDI interface)
    python3 host/af_host.py --port ... selftest          # bit-exact HW vs Python, all banks
    python3 host/af_host.py --port ... freqresp --bank 3 # measured response of a bank
    python3 host/af_host.py --port ... capture --wav mic.wav   # 0.33 s of live audio
    python3 host/af_host.py --sim selftest               # same tool against a software FPGA

Every hardware result is written to results/hw_*.json / .pdf for the report.
"""
import argparse, json, os, struct, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "model"))
from params import *  # noqa: F401,F403
import golden as g

RES = os.path.join(ROOT, "results")
PREFIX = "hw_"   # becomes "simhost_" with --sim so model runs never masquerade as board data


# ============================================================================ transports
class FpgaLink:
    def __init__(self, port, baud=BAUD, timeout=2.0):
        import serial  # pyserial
        self.s = serial.Serial(port, baud, timeout=timeout)
        if hasattr(self.s, "set_buffer_size"):          # Windows: default RX buffer is only 4 kB
            self.s.set_buffer_size(rx_size=1 << 20, tx_size=1 << 16)
        time.sleep(0.05)
        self.s.reset_input_buffer()

    def write(self, b):
        self.s.write(bytes(b))

    def read_available(self):
        """Whatever has arrived so far (used after a deliberately aborted command)."""
        time.sleep(0.05)
        return self.s.read(self.s.in_waiting or 0)

    def read(self, n):
        out = bytearray()
        t0 = time.time()
        while len(out) < n:
            chunk = self.s.read(n - len(out))
            if not chunk and time.time() - t0 > max(2.0, n * 12 / BAUD * 3):
                break
            out += chunk
        return bytes(out)


class SimLink:
    """Software stand-in for the FPGA that speaks the same protocol using the golden
    model. Lets you exercise this tool (and the analysis) without a board."""

    def __init__(self):
        self.coefs = g.load_coefs()
        self.shifts = g.main_shifts()
        self.rx = bytearray()
        self.buf = bytearray()
        self.cap_t = 0.0

    def write(self, b):
        self.buf += bytes(b)
        self._run()

    def read(self, n):
        out, self.rx = bytes(self.rx[:n]), self.rx[n:]
        return out

    def _need(self, n):
        return len(self.buf) >= n

    def _run(self):
        while self.buf:
            c = chr(self.buf[0])
            if c == "P":
                self.buf = self.buf[1:]; self.rx += bytes([0x41, 0x46, VERSION[0], VERSION[1]])
            elif c == "S":
                self.buf = self.buf[1:]; self.rx += bytes([0x80, 0x0D, 0x00])
            elif c == "T":
                if not self._need(4): return
                bank, n = self.buf[1], struct.unpack("<H", self.buf[2:4])[0]
                if not self._need(4 + 3 * n): return
                raw = self.buf[4:4 + 3 * n]; self.buf = self.buf[4 + 3 * n:]
                x = [g.wrap(int.from_bytes(raw[3 * i:3 * i + 3], "little"), 24) for i in range(n)]
                comp, main = self.coefs
                if bank == PAR_BANK:
                    y = [v << 8 for v in g.fir_par([v >> 8 for v in x], g.load_par())]
                else:
                    y = g.fir(x, main[bank & 3], CFRAC + self.shifts[0][bank & 3])
                for v in y: self.rx += (v & 0xFFFFFF).to_bytes(3, "little")
            elif c == "D":
                if not self._need(5): return
                bank, gain, n = self.buf[1], self.buf[2], struct.unpack("<H", self.buf[3:5])[0]
                if not self._need(5 + n): return
                raw = self.buf[5:5 + n]; self.buf = self.buf[5 + n:]
                bits = [(b >> j) & 1 for b in raw for j in range(8)]
                o = g.chain(bits, bank if bank == PAR_BANK else bank & 3, gain & 15, self.coefs, self.shifts)
                for v in o: self.rx += struct.pack("<h", v)
            elif c == "C":
                self.buf = self.buf[1:]
                n = 1 << CAP_AW
                t = (np.arange(n * 50) / F_PDM) + self.cap_t
                bits = g.pdm_modulate(0.3 * np.sin(2 * np.pi * 1000 * t) + 0.01 * np.random.randn(len(t)))
                o = g.chain(bits, 0, 0, self.coefs, self.shifts)
                o = (o + [0] * n)[:n]
                for v in o: self.rx += struct.pack("<h", v)
            else:
                self.buf = self.buf[1:]


# ============================================================================ commands
def ping(link):
    link.write(b"P")
    r = link.read(4)
    ok = len(r) == 4 and r[:2] == b"AF"
    print(f"ping: {r.hex(' ')} -> {'OK, firmware v%d.%d' % (r[2], r[3]) if ok else 'NO RESPONSE'}")
    return ok


def status(link):
    link.write(b"S")
    r = link.read(3)
    if len(r) != 3:
        print("status: no response"); return None
    sw = (r[0] << 8) | r[1]
    f = r[2]
    print(f"switches 0x{sw:04X}: bank {sw & 3}, gain {(sw >> 2) & 15}, phase {'L' if sw >> 6 & 1 else 'H'},"
          f" out {'delta-sigma' if sw >> 7 & 1 else 'PWM'}, ASIC core {'ON' if sw >> 8 & 1 else 'off'},"
          f" amp {'ON' if sw >> 15 else 'off'}")
    print(f"flags 0x{f:02X}: test={f & 1} uart_frame_err_now={f >> 1 & 1} "
          f"error_sticky={f >> 2 & 1} (red LED16: overrun, UART framing or protocol error) capture={f >> 3 & 1}")
    return dict(sw=sw, flags=f)


T_CHUNK = 1024          # samples per 'T' command (3 kB each way; safe for any OS buffer)
D_CHUNK = 64000         # PDM bits per 'D' command (8 kB in, 2.5 kB out)


def fir_hw(link, bank, x):
    """Run x (int, 24-bit) through the main FIR bank on the FPGA ('T').

    x must have at most T_CHUNK samples: every command clears the delay line, so a longer
    signal would not be one continuous filtering operation."""
    assert len(x) <= T_CHUNK, "split the signal; each 'T' command restarts the filter"
    y = []
    for i in range(0, len(x), T_CHUNK):
        blk = x[i:i + T_CHUNK]
        hdr = bytes([ord("T"), bank]) + struct.pack("<H", len(blk))
        body = b"".join((int(v) & 0xFFFFFF).to_bytes(3, "little") for v in blk)
        link.write(hdr + body)
        r = link.read(3 * len(blk))
        if len(r) != 3 * len(blk):
            raise RuntimeError(f"'T' returned {len(r)} of {3 * len(blk)} bytes")
        y += [g.wrap(int.from_bytes(r[3 * k:3 * k + 3], "little"), 24) for k in range(len(blk))]
    return y


def chain_hw(link, bank, gain, bits):
    """Send PDM bits through the whole chain on the FPGA ('D'). Each call restarts the chain."""
    nbytes = len(bits) // 8
    raw = bytes(int(sum(int(bits[8 * i + j]) << j for j in range(8))) for i in range(nbytes))
    link.write(bytes([ord("D"), bank, gain]) + struct.pack("<H", nbytes) + raw)
    nout = (nbytes * 8) // (CIC_R * COMP_DECIM)
    r = link.read(2 * nout)
    if len(r) != 2 * nout:
        raise RuntimeError(f"'D' returned {len(r)} of {2 * nout} bytes")
    return list(struct.unpack(f"<{nout}h", r))


def capture(link):
    n = 1 << CAP_AW
    link.write(b"C")
    r = link.read(2 * n)
    if len(r) != 2 * n:
        hint = (" - about half the bytes: the board runs an old bitstream without the FIFO almost-full "
                "fix; rebuild and reprogram") if 0.45 < len(r) / (2 * n) < 0.55 else ""
        raise RuntimeError(f"capture returned {len(r)} of {2 * n} bytes{hint}")
    return np.array(struct.unpack(f"<{n}h", r), dtype=float)


def watchdog(link):
    """Watchdog test: send two commands that stop half-way; the controller must abort each after 0.17 s
    (2^24 clocks), return to live operation and answer the next command, with no error flag."""
    ok = True
    # 1) a 'T' header that announces 100 samples, followed by only 10 of them
    link.write(bytes([ord("T"), 1]) + struct.pack("<H", 100) + b"\x00\x00\x00" * 10)
    time.sleep(0.6)
    late = link.read_available() if hasattr(link, "read_available") else b""
    ok_a = ping(link)
    print(f"watchdog 1 (data stops after 10 of 100 samples): {len(late)} bytes returned, "
          f"next ping {'OK' if ok_a else 'FAILED'}")
    # 2) a 'D' header cut off after two of its five bytes
    link.write(bytes([ord("D"), 0]))
    time.sleep(0.6)
    if hasattr(link, "read_available"):
        link.read_available()
    ok_b = ping(link)
    print(f"watchdog 2 (header stops after 2 of 5 bytes): next ping {'OK' if ok_b else 'FAILED'}")
    st = status(link)
    ok_c = st is not None and (st["flags"] & 0x05) == 0           # not in test mode, no sticky error
    print(f"WATCHDOG {'PASS' if (ok_a and ok_b and ok_c) else 'FAIL'}"
          f" (test flag and error flag after recovery: {'clear' if ok_c else 'SET'})")
    return ok_a and ok_b and ok_c


def selftest(link, seed=1):
    rng = np.random.default_rng(seed)
    comp, main = g.load_coefs()
    msh, csh = g.main_shifts()
    report = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "fir": [], "chain": []}
    lo, hi = -(1 << 23), (1 << 23) - 1
    ok_all = True
    for b in list(range(MAIN_BANKS)) + [PAR_BANK]:
        # impulse (returns the coefficients), then random full-scale blocks; each block is one
        # 'T' command and therefore starts from a cleared delay line, like the model
        blocks = [[hi] + [0] * MAIN_TAPS] + [list(rng.integers(lo, hi + 1, T_CHUNK)) for _ in range(3)]
        t0 = time.time()
        y, e, x = [], [], []
        for blk in blocks:
            y += fir_hw(link, b, blk)
            if b == PAR_BANK:
                e += [v << 8 for v in g.fir_par([v >> 8 for v in blk], g.load_par())]
            else:
                e += g.fir(blk, main[b], CFRAC + msh[b])
            x += blk
        dt = time.time() - t0
        nbad = int(sum(1 for a, c in zip(y, e) if a != c))
        ok_all &= nbad == 0
        report["fir"].append(dict(bank=b, samples=len(x), mismatches=nbad, seconds=dt))
        print(f"FIR bank {b}: {len(x)} samples, {nbad} mismatches  ({'PASS' if nbad == 0 else 'FAIL'})")
    for b, gn in [(0, 4), (1, 6), (2, 6), (3, 8), (PAR_BANK, 4)]:
        t = np.arange(int(0.2 * F_PDM)) / F_PDM
        x = 0.4 * np.sin(2 * np.pi * 440 * t) + 0.2 * np.sin(2 * np.pi * 5000 * t) + 0.01 * rng.standard_normal(len(t))
        bits = g.pdm_modulate(x)
        bits = bits[: (len(bits) // 400) * 400]
        y = []
        e = []
        for i in range(0, len(bits), D_CHUNK):             # each command restarts the chain
            blk = bits[i:i + D_CHUNK]
            y += chain_hw(link, b, gn, blk)
            e += g.chain(blk, b, gn, (comp, main), (msh, csh))
        nbad = int(sum(1 for a, c in zip(y, e) if a != c))
        ok_all &= nbad == 0 and len(y) == len(e)
        report["chain"].append(dict(bank=b, gain=gn, samples=len(y), mismatches=nbad))
        print(f"chain bank {b} gain {gn}: {len(y)} samples, {nbad} mismatches  ({'PASS' if nbad == 0 else 'FAIL'})")
    report["pass"] = bool(ok_all)
    os.makedirs(RES, exist_ok=True)
    with open(os.path.join(RES, PREFIX + "selftest.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    print("SELFTEST", "PASS" if ok_all else "FAIL", f"-> results/{PREFIX}selftest.json")
    return ok_all


def freqresp(link, bank, npts=60, plot=True):
    """Measure the hardware FIR magnitude response with stepped sines ('T' mode)."""
    comp, main = g.load_coefs()
    msh, _ = g.main_shifts()
    freqs = np.unique(np.round(np.geomspace(50, 24000, npts)))
    amp = 0.5 * (1 << 23)
    n = T_CHUNK
    meas = []
    for f in freqs:
        k = np.arange(n)
        x = np.round(amp * np.sin(2 * np.pi * f * k / FS)).astype(int).tolist()
        y = np.array(fir_hw(link, bank, x), dtype=float)[MAIN_TAPS:]   # skip the start-up transient
        kk = np.arange(MAIN_TAPS, n)
        # least-squares fit of a sine + cosine at f: exact amplitude even for a
        # non-integer number of periods in the window
        B = np.column_stack([np.sin(2 * np.pi * f * kk / FS), np.cos(2 * np.pi * f * kk / FS), np.ones_like(kk)])
        c, *_ = np.linalg.lstsq(B, y, rcond=None)
        a = np.hypot(c[0], c[1])
        meas.append(20 * np.log10(max(a / amp, 1e-9)))
    from scipy import signal
    href = (np.array(g.load_par()) / (1 << 15)) if bank == PAR_BANK else \
        (np.array(main[bank]) / (1 << (CFRAC + msh[bank])))
    w, H = signal.freqz(href, worN=8192, fs=FS)
    out = dict(bank=bank, freqs=freqs.tolist(), measured_db=meas)
    with open(os.path.join(RES, f"{PREFIX}freqresp_b{bank}.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    if plot:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams.update({"font.size": 8, "font.family": "STIXGeneral", "mathtext.fontset": "stix"})
        fig, ax = plt.subplots(figsize=(3.5, 2.2))
        # screen plots are in colour (the paper redraws Fig. 8 in greyscale with model/plot_hw.py)
        ax.semilogx(np.maximum(w, 1), 20 * np.log10(np.maximum(np.abs(H), 1e-9)), "-", color="#1f77b4",
                    lw=0.8, label="Design (quantized)", zorder=1)
        ax.semilogx(freqs, meas, "o", ms=3, mfc="#ff7f0e", mec="#a0410a", mew=0.5,
                    label="Measured on FPGA", zorder=3)
        ax.set_xlim(40, 25000); ax.set_ylim(-120, 6); ax.grid(alpha=0.3)
        ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("Magnitude (dB)"); ax.legend(fontsize=6.5)
        fig.tight_layout(); fig.savefig(os.path.join(RES, f"{PREFIX}freqresp_b{bank}.pdf"))
        fig.savefig(os.path.join(RES, f"{PREFIX}freqresp_b{bank}.png"), dpi=600); plt.close(fig)
    print(f"freqresp bank {bank}: {len(freqs)} points -> results/{PREFIX}freqresp_b{bank}.json/.pdf")
    return out


def analyze_capture(y, wav=None, tag="capture", freq=None):
    from scipy import signal
    n = len(y)
    if wav:
        from scipy.io import wavfile
        wavfile.write(wav, FS, y.astype(np.int16))
    win = signal.windows.blackmanharris(n)
    Y = np.fft.rfft((y - y.mean()) * win)
    P = np.abs(Y) ** 2
    f = np.fft.rfftfreq(n, 1 / FS)
    df = f[1]
    band_e = lambda k: P[max(k - 6, 0):k + 7].sum()          # main lobe of the Blackman-Harris window
    if freq:                                                  # filter tests: measure at the played tone even
        kf = int(round(freq / df))                            # when the filter has removed it
        k0 = max(kf - 6, 0) + int(np.argmax(P[max(kf - 6, 0):kf + 7]))
    else:
        k0 = int(np.argmax(P[5:])) + 5
    sig = band_e(k0)
    inband = (f > 20) & (f < 20000)
    total = P[inband].sum()
    # harmonics 2f0, 3f0, ... below 20 kHz (searched +-6 bins around the expected bin)
    harm, hlist = 0.0, []
    for m in range(2, 40):
        k = int(round(m * f[k0] / df))
        if f[min(k, len(f) - 1)] >= 20000:
            break
        kk = max(k - 6, 0) + int(np.argmax(P[max(k - 6, 0):k + 7]))
        e = band_e(kk); harm += e; hlist.append(round(float(10 * np.log10(e / sig)), 1))
    noise = max(total - sig - harm, 1e-30)
    res = dict(rms_dbfs=float(20 * np.log10(np.sqrt(np.mean(y ** 2)) / 32768 + 1e-12)),
               peak_dbfs=float(20 * np.log10(np.max(np.abs(y)) / 32768 + 1e-12)),
               tone_hz=float(f[k0]),
               snr_db=float(10 * np.log10(sig / noise)),                   # noise only, harmonics excluded
               thd_db=float(10 * np.log10(max(harm, 1e-30) / sig)),         # harmonics 2..k, 20 Hz-20 kHz
               sinad_db=float(10 * np.log10(sig / max(total - sig, 1e-30))),  # everything that is not the tone
               harmonics_dbc=hlist[:9])
    # RMS level of the tone alone in dBFS, same scale as rms_dbfs (Parseval with the window energy)
    res["tone_dbfs"] = float(10 * np.log10(sig / (np.sum(win ** 2) * n / 2 * 32768 ** 2) + 1e-30))
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "font.family": "STIXGeneral", "mathtext.fontset": "stix"})
    fig, ax = plt.subplots(2, 1, figsize=(3.5, 3.4))
    t = np.arange(n) / FS * 1e3
    ax[0].plot(t, y, "-", color="#1f77b4", lw=0.5); ax[0].set_xlabel("Time (ms)"); ax[0].set_ylabel("Sample")
    ax[1].semilogx(np.maximum(f, 1), 10 * np.log10(P / P.max() + 1e-16), "-", color="#d62728", lw=0.5)
    ax[1].set_xlim(20, 25000); ax[1].set_xlabel("Frequency (Hz)"); ax[1].set_ylabel("dB (rel. peak)")
    for a in ax: a.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(RES, f"{PREFIX}{tag}.pdf"))
    fig.savefig(os.path.join(RES, f"{PREFIX}{tag}.png"), dpi=600); plt.close(fig)
    return res


# ============================================================================ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port of the Nexys A7 (USB-UART)")
    ap.add_argument("--sim", action="store_true", help="talk to the software model instead of a board")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping"); sub.add_parser("status"); sub.add_parser("selftest")
    sub.add_parser("watchdog", help="two deliberately incomplete commands, then check recovery")
    p = sub.add_parser("freqresp"); p.add_argument("--bank", type=int, default=1); p.add_argument("--points", type=int, default=60)
    p = sub.add_parser("capture"); p.add_argument("--wav", default=None); p.add_argument("--tag", default="capture")
    p.add_argument("--freq", type=float, default=None, help="measure at this tone frequency (Hz) instead of the largest peak")
    p = sub.add_parser("all", help="ping, status, selftest, freqresp for every bank")
    a = ap.parse_args()
    os.makedirs(RES, exist_ok=True)

    global PREFIX
    if a.sim:
        link = SimLink()
        PREFIX = "simhost_"
    elif a.port:
        link = FpgaLink(a.port)
    else:
        ap.error("give --port <serial port> or --sim")

    if a.cmd == "ping":
        sys.exit(0 if ping(link) else 1)
    if a.cmd == "status":
        status(link)
    if a.cmd == "selftest":
        sys.exit(0 if selftest(link) else 1)
    if a.cmd == "watchdog":
        if a.sim:
            sys.exit("watchdog needs the real board (--port)")
        sys.exit(0 if watchdog(link) else 1)
    if a.cmd == "freqresp":
        freqresp(link, a.bank, a.points)
    if a.cmd == "capture":
        if a.freq is not None and not (0 < a.freq < FS / 2):
            ap.error(f"--freq must be between 0 and {FS // 2} Hz (got {a.freq:g}); for 8 kHz type --freq 8000")
        y = capture(link)
        r = analyze_capture(y, a.wav, a.tag, a.freq)
        with open(os.path.join(RES, f"{PREFIX}{a.tag}.json"), "w") as fh:
            json.dump(r, fh, indent=2)
        print(json.dumps(r, indent=2))
        # every file is overwritten on each run; print where they went so there is no doubt
        import time
        out = [os.path.join(RES, f"{PREFIX}{a.tag}.{e}") for e in ("json", "pdf", "png")]
        if a.wav:
            out.append(a.wav)
        print("saved (" + time.strftime("%H:%M:%S") + "):")
        for pth in out:
            print("  ", os.path.abspath(pth))
    if a.cmd == "all":
        assert ping(link)
        status(link)
        ok = selftest(link)
        for b in list(range(MAIN_BANKS)) + [PAR_BANK]:
            freqresp(link, b)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
