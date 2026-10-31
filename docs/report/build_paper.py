#!/usr/bin/env python3
"""Build the IEEE-format Word paper from the project's results.

    py docs\\report\\build_paper.py         -> docs/report/paper.docx and paper.pdf

* Uses the IEEE conference template (docs/report/template/conference-template-a4.docx) and its
  styles; headings, figures, tables and references are numbered by the template.
* Every number comes from the files in results/ and asic/results/ through make_macros.collect().
  A value whose file is missing appears as a red [TBD] marker.
* docs/report/figs/user/asic_layout.png (drawn by asic/plot_layout.py) is Fig. 9; without it a
  dashed placeholder is shown. The measured bank-3 response comes from results/hw_freqresp_b3.json.
* On Windows the PDF is exported by Microsoft Word as PDF/A, so every font is embedded.
"""
import os, re, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import docx_lib as D
import make_macros

TEMPLATE = os.path.join(HERE, "template", "conference-template-a4.docx")
FIGS = os.path.join(HERE, "figs")
USER = os.path.join(FIGS, "user")
TITLE = "Design and Bit-Exact Verification of a Real-Time Digital Microphone Filter on FPGA and SKY130"
# First-page footer of the IEEE template ("XXX-X-XXXX-XXXX-X/XX/$XX.00 (c)20XX IEEE"). The conference
# supplies this copyright line (ISBN, price, year) only for the final camera-ready version. Leave it
# empty for submission; paste the line the conference gives you here when it asks for it.
COPYRIGHT_LINE = ""
COL_W = 243.0          # one column, pt
FULL_W = 504.6         # both columns, pt

# ------------------------------------------------------------------ result values
_M = make_macros.collect()


def V(key):
    v = _M[key]
    m = re.fullmatch(r"\\tbd\{(.*)\}", v)
    if m:
        return "[[TBD:" + ("TBD" if m.group(1) in ("TBD", "--") else m.group(1)) + "]]"
    return v.replace("{,}", ",")


def AREA_PCT():
    """Cell-area increase of PIPE=1 over PIPE=0 from the Yosys SKY130 estimate."""
    import json
    try:
        r = json.load(open(os.path.join(ROOT, "asic", "results", "yosys_sky130.json")))["runs"]
        a = {x["pipe"]: x["cell_area_um2"] for x in r}
        return str(round(100 * (a[1] / a[0] - 1)))
    except (OSError, KeyError, ValueError):
        return "[[TBD:TBD]]"


def SIM_COUNT(tb):
    """Samples checked by a testbench, from results/sim_summary.json (or the ASIC log)."""
    import json
    try:
        if tb == "tb_fir_par":
            txt = open(os.path.join(ROOT, "asic", "results", "tb_fir_par.log")).read()
            m = re.search(r"PASS tb_fir_par: (\d+) samples", txt)
            return (f"{2 * int(m.group(1)):,}".replace(",", " "), "PASS") if m else ("\u2013", "[[TBD:FAIL]]")
        d = json.load(open(os.path.join(ROOT, "results", "sim_summary.json")))[tb]
        return f"{d['checked_samples']:,}".replace(",", " "), ("PASS" if d["pass"] else "[[TBD:FAIL]]")
    except (OSError, KeyError, ValueError, AttributeError):
        return "\u2013", "[[TBD:not run]]"


def NEG(v):
    """Typographic minus sign for a negative value from V()."""
    return v.replace("-", "\u2212")


def HWTOTAL():
    """Samples compared bit for bit on the board by the self-test (results/hw_selftest.json)."""
    import json
    try:
        d = json.load(open(os.path.join(ROOT, "results", "hw_selftest.json")))
        n = sum(x["samples"] for x in d["fir"]) + sum(x["samples"] for x in d["chain"])
        return f"{n:,}".replace(",", "\u00a0")
    except (OSError, KeyError, ValueError):
        return "[[TBD:TBD]]"


def SIMHOST():
    """Samples compared by the host tool against the software copy of the board."""
    import json
    try:
        d = json.load(open(os.path.join(ROOT, "results", "simhost_selftest.json")))
        n = sum(x["samples"] for x in d["fir"]) + sum(x["samples"] for x in d["chain"])
        return f"{n:,}".replace(",", " ")
    except (OSError, KeyError, ValueError):
        return "[[TBD:TBD]]"


# ------------------------------------------------------------------ references (numbered by first citation)
REFS = {
    "schreier": "R. Schreier and G. C. Temes, *Understanding Delta-Sigma Data Converters*. Piscataway, NJ, USA: Wiley-IEEE Press, 2005.",
    "hogenauer": "E. B. Hogenauer, \u201cAn economical class of digital filters for decimation and interpolation,\u201d *IEEE Trans. Acoust., Speech, Signal Process.*, vol. 29, no. 2, pp. 155\u2013162, Apr. 1981.",
    "lyons": "R. G. Lyons, *Understanding Digital Signal Processing*, 3rd ed. Upper Saddle River, NJ, USA: Prentice Hall, 2010.",
    "meyerbaese": "U. Meyer-Baese, *Digital Signal Processing with Field Programmable Gate Arrays*, 4th ed. Berlin, Germany: Springer, 2014.",
    "nexys": "Digilent Inc., \u201cNexys A7 reference manual.\u201d [Online]. Available: https://digilent.com/reference/programmable-logic/nexys-a7/reference-manual",
    "todorovic": "D. Todorovi\u0107, I. Salom, V. \u010celebi\u0107, and J. Prezelj, \u201cImplementation and application of FPGA platform with digital MEMS microphone array,\u201d in *Proc. 4th Int. Conf. Electrical, Electronics and Computing Engineering (IcETRAN)*, Kladovo, Serbia, Jun. 2017.",
    "ilies": "E. Ilies, M. Marinca, and A. Gontean, \u201cPost-implementation evaluation of CIC filters for digital audio applications on FPGA,\u201d *J. Low Power Electron. Appl.*, vol. 16, no. 1, Art. no. 5, 2026, doi: 10.3390/jlpea16010005.",
    "dasilva": "B. da Silva, A. Braeken, and A. Touhafi, \u201cFPGA-based architectures for acoustic beamforming with microphone arrays: Trends, challenges and research opportunities,\u201d *Computers*, vol. 7, no. 3, Art. no. 41, 2018, doi: 10.3390/computers7030041.",
    "kwentus": "A. Y. Kwentus, Z. Jiang, and A. N. Willson, \u201cApplication of filter sharpening to cascaded integrator-comb decimation filters,\u201d *IEEE Trans. Signal Process.*, vol. 45, no. 2, pp. 457\u2013467, Feb. 1997.",
    "openlane": "M. Shalan and T. Edwards, \u201cBuilding OpenLANE: A 130nm OpenROAD-based tapeout-proven flow,\u201d in *Proc. IEEE/ACM Int. Conf. Computer-Aided Design (ICCAD)*, 2020, pp. 1\u20136.",
    "librelane": "The LibreLane Contributors, \u201cLibreLane: An open-source ASIC implementation flow.\u201d [Online]. Available: https://github.com/librelane/librelane",
    "sky130": "SkyWater Technology and Google, \u201cSKY130 open-source process design kit,\u201d 2020. [Online]. Available: https://github.com/google/skywater-pdk",
    "tinytapeout": "M. Venn, \u201cTiny Tapeout: A shared silicon tapeout platform accessible to everyone,\u201d *IEEE Solid-State Circuits Mag.*, 2024. [Online]. Available: https://ieeexplore.ieee.org/document/10584359",
    "admp421": "Analog Devices, \u201cADMP421: Low-profile, low-power, bottom-port digital output MEMS microphone,\u201d data sheet.",
    "mcclellan": "J. H. McClellan, T. W. Parks, and L. R. Rabiner, \u201cA computer program for designing optimum FIR linear phase digital filters,\u201d *IEEE Trans. Audio Electroacoust.*, vol. 21, no. 6, pp. 506\u2013526, Dec. 1973.",
    "itu": "ITU-T, \u201cTransmission performance characteristics of pulse code modulation channels,\u201d Recommendation G.712, 2001.",
    "ug479": "AMD Xilinx, \u201c7 Series DSP48E1 slice user guide (UG479).\u201d",
    "hartley": "R. I. Hartley, \u201cSubexpression sharing in filters using canonic signed digit multipliers,\u201d *IEEE Trans. Circuits Syst. II*, vol. 43, no. 10, pp. 677\u2013688, Oct. 1996.",
    "parhi": "K. K. Parhi, *VLSI Digital Signal Processing Systems: Design and Implementation*. New York, NY, USA: Wiley, 1999.",
    "icarus": "S. Williams, \u201cIcarus Verilog.\u201d [Online]. Available: https://github.com/steveicarus/iverilog",
    "verilator": "W. Snyder, \u201cVerilator.\u201d [Online]. Available: https://www.veripool.org/verilator/",
    "yosys": "C. Wolf, \u201cYosys Open SYnthesis Suite.\u201d [Online]. Available: https://github.com/YosysHQ/yosys",
}
_order = []


def cite(text):
    """Replace {key1,key2} citation tokens with IEEE numbers in order of first use."""
    def rep(m):
        nums = []
        for k in m.group(1).split(","):
            k = k.strip()
            if k not in REFS:
                raise KeyError(k)
            if k not in _order:
                _order.append(k)
            nums.append(_order.index(k) + 1)
        nums.sort()
        return ", ".join(f"[[REF:{n}]]" for n in nums)        # each [n] links to reference n
    return re.sub(r"(?<![\^_])\{([a-z0-9_]+(?:,\s*[a-z0-9_]+)*)\}", rep, text)


# ------------------------------------------------------------------ figure helpers
FIGNUM = [0]
TABNUM = [0]
LABELS = {}


def fig_label(key):
    FIGNUM[0] += 1
    LABELS[key] = FIGNUM[0]
    return FIGNUM[0]


def placeholder(path, lines, aspect=0.6):
    """Dashed black-on-white placeholder image the user replaces later."""
    from PIL import Image, ImageDraw, ImageFont
    W = 2400
    H = int(W * aspect)
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    for x in range(10, W - 10, 40):
        d.line([(x, 10), (min(x + 22, W - 10), 10)], fill="black", width=6)
        d.line([(x, H - 10), (min(x + 22, W - 10), H - 10)], fill="black", width=6)
    for y in range(10, H - 10, 40):
        d.line([(10, y), (10, min(y + 22, H - 10))], fill="black", width=6)
        d.line([(W - 10, y), (W - 10, min(y + 22, H - 10))], fill="black", width=6)
    try:
        f1 = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf", 90)
        f2 = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf", 64)
    except OSError:
        f1 = f2 = ImageFont.load_default()
    y = H // 2 - 60 * len(lines)
    for k, ln in enumerate(lines):
        f = f1 if k == 0 else f2
        w = d.textlength(ln, font=f)
        d.text(((W - w) / 2, y), ln, fill="black", font=f)
        y += 130 if k == 0 else 95
    im.save(path)
    return path


def fig_file(name, fallback_lines, aspect=0.6, search=()):
    for p in [os.path.join(USER, name)] + list(search):
        if os.path.exists(p):
            return p, True
    ph = os.path.join(FIGS, "ph_" + name)
    return placeholder(ph, fallback_lines, aspect), False


# ------------------------------------------------------------------ document body
def build():
    img = D.Images()
    B = []                                    # body XML fragments
    P = lambda text, style="BodyText": B.append(D.para(style, D.rich(cite(text))))
    H1 = lambda text: B.append(D.para("Heading1", D.rich(text)))
    H2 = lambda text: B.append(D.para("Heading2", D.rich(text)))

    def FIG(key, path, caption, width=COL_W):
        n = fig_label(key)
        B.append(D.image_para(img, path, width))
        B.append(D.para("figurecaption", D.rich(cite(caption))))
        return n

    def FULLFIG(key, path, caption):
        B.append(D.section_break(cols=2))
        n = FIG(key, path, caption, FULL_W)
        B.append(D.section_break(cols=1))
        return n

    def TABLE(key, title, rows, widths, align=None, note=None):
        TABNUM[0] += 1
        LABELS[key] = TABNUM[0]
        B.append(D.para("tablehead", D.rich(title), keep_next=True))
        B.append(D.table(rows, widths, align=align))
        if note:
            B.append(D.para("tablefootnote", D.rich(cite(note))))
        else:
            B.append(D.para("BodyText", "", extra_ppr='<w:spacing w:after="0pt"/>'))

    roman = lambda n: ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"][n - 1]

    # pre-assign figure / table numbers used in the text (order of appearance below)
    F = {k: i + 1 for i, k in enumerate(
        ["system", "wave", "decim", "banks", "mac", "fsm", "bitexact", "hwfreq", "layout"])}
    T = {k: roman(i + 1) for i, k in enumerate(["related", "banks", "verif", "fpga", "asic"])}

    # ================================================================ title block (1 column)
    B.append(D.para("papertitle", D.rich(TITLE)))
    B.append(D.para("Author", D.run("Saman Fuyal") + D.brk()
                    + D.run("Department of Electrical and Electronics Engineering", i=True) + D.brk()
                    + D.run("Kathmandu University", i=True) + D.brk() + D.run("Dhulikhel, Nepal")
                    + D.brk() + D.run("smnfyl@gmail.com"),
                    extra_ppr='<w:spacing w:before="6pt" w:after="12pt"/>'))
    B.append(D.section_break(cols=1, first=True, top="54pt"))

    # ================================================================ abstract
    B.append(D.para("Abstract", D.run("Abstract", i=True, b=True) + D.run("—", b=True) + D.rich(
        "Digital MEMS microphones deliver audio as a one-bit pulse-density-modulated (PDM) stream, so every "
        "system that uses them needs a decimation and filtering chain. This paper presents such a chain on a "
        "Nexys A7-50T board and the method used to verify it. A fourth-order cascaded integrator-comb (CIC) "
        "decimator and a 63-tap droop-compensating FIR filter turn the 2.5 MHz PDM stream into 24-bit samples "
        "at 50 kHz. A DC blocker follows, then one of five filters chosen at run time: four 511-tap "
        "linear-phase filters that share one DSP48E1 multiplier, and a 31-tap parallel filter. Storing each "
        "coefficient bank with its own power-of-two scale recovers up to 14.2 dB of the stopband attenuation "
        "that 18-bit quantization would cost. A Python model reproduces every rounding and saturation step, "
        "and the RTL matched it sample for sample in block, chain and pin-level simulation; the pin-level test "
        "also exposed a byte-loss defect that the block tests missed. A UART port repeats the comparison on "
        f"the board. On the XC7A50T the design meets 100 MHz with {V('VWns')} ns of setup slack. The 31-tap "
        "filter enters the open-source LibreLane flow for the SkyWater 130 nm process unchanged, where "
        f"pipelining raises the routed clock from {V('LFmaxZ')} MHz to {V('LFmaxO')} MHz for {V('LAreaPct')}% "
        "more cell area.", base_b=True)))
    B.append(D.para("Keywords", D.run("Keywords—", b=True, i=True) + D.rich(
        "FPGA, PDM microphone, CIC decimator, FIR filter, fixed-point arithmetic, bit-exact verification, "
        "hardware-in-the-loop, SKY130, LibreLane", base_b=True)))

    # ================================================================ I. introduction
    H1("Introduction")
    P("Digital MEMS microphones are found in phones, laptops, hearing aids and voice assistants. Each one "
      "contains a delta-sigma modulator and outputs a one-bit stream at a few megahertz {schreier}. Turning "
      "that stream into audio takes low-pass filtering and decimation, usually a CIC stage followed by one or "
      "more FIR stages {hogenauer, lyons}. Software-defined radios use the same structure in their receive "
      "path {meyerbaese}.")
    P("On FPGA teaching boards the microphone is often read with a counter that adds up the ones in a fixed "
      "window; the Nexys A7 reference manual suggests 128 bits per output sample {nexys}. Such a counter is a "
      "single moving-average stage. It lowers the rate, but its sinc response folds much of the modulator "
      "noise back into the audio band and bends the passband. Published FPGA microphone systems build the "
      "chain from vendor IP or generated HDL and report resources and clock speed {todorovic, ilies}. They "
      "say less about whether the hardware output matches the design model exactly, or how a filter designed "
      "for an FPGA can be carried towards an integrated circuit.")
    P("This work addresses those points with free tools on a low-cost board. Its contributions are:")
    for item in [
        "a complete PDM-to-audio chain on the Nexys A7-50T in one 100 MHz clock domain, with five filters "
        "selectable at run time, four of which share one multiplier;",
        "per-bank power-of-two coefficient scaling, which raises the stopband attenuation of the narrow "
        "filters by 6.6 to 14.2 dB for the cost of a four-way shift selection;",
        "a verification flow in which a Python model, the RTL at three levels of integration and the board "
        "itself are compared bit for bit, the last through a UART hardware-in-the-loop port;",
        "a 31-tap filter core written once and used both on the FPGA and in the open-source SKY130 ASIC flow, "
        "in pipelined and unpipelined forms."]:
        B.append(D.para("bulletlist", D.rich(cite(item))))
    P("Section II reviews related work, Sections III and IV describe the architecture and design, Section V "
      "the verification, Section VI the results, and Section VII concludes.")

    # ================================================================ II. related work
    H1("Related Work and Research Gap")
    P("Hogenauer introduced the CIC filter as a multiplier-free decimator {hogenauer}. Its passband droop is "
      "usually corrected by a short FIR filter, and Kwentus et al. showed that sharpening improves both the "
      "droop and the alias rejection {kwentus}. Textbooks treat this cascade as standard practice for "
      "oversampled converters {lyons, meyerbaese}.")
    P("Todorović et al. built an FPGA platform for a MEMS microphone array on a Spartan-6 device "
      "{todorovic}. A fifth-order CIC, two half-band stages and a low-pass FIR filter, all Xilinx IP cores "
      "generated in System Generator, decimate a 3.072 MHz PDM stream by 64 to 48 kHz. The chain was not "
      "tested on its own; the authors compare measurements of the whole beamforming system with Matlab "
      "simulations. Da Silva et al. reviewed FPGA beamformers that use digital MEMS arrays and describe PDM "
      "demodulation and filtering as their common front end {dasilva}. Ilies et al. compared three CIC "
      "implementations for a 3.072 MHz MEMS microphone on an Artix-7 device, generated by HDL Coder, by the "
      "AMD CIC Compiler and from open-source RTL {ilies}. They report LUT, register and clock-speed "
      "differences, and the three outputs agree to within about 1.6 units on a signal of roughly 4700 units "
      "peak to peak, which the authors call functionally equivalent rather than bit-exact.")
    P("On the silicon side, OpenLANE and its successor LibreLane combine open-source tools into a complete "
      "RTL-to-GDSII flow {openlane, librelane}, the SkyWater SKY130 process design kit is freely available "
      "{sky130}, and shared shuttles such as Tiny Tapeout let students fabricate small designs {tinytapeout}.")
    P(f"Table {T['related']} compares these works. The FPGA designs treat the decimator either as a resource "
      "and speed problem or as the front end of a larger system. None of them ties the word lengths to the "
      "stopband the filters achieve, compares the hardware output with a reference model on the board itself, "
      "or carries a filter core unchanged from the FPGA into an ASIC flow. The present work does all three.")
    TABLE("related", "Comparison with Related FPGA Microphone Front Ends", [
        ["Work", "Device", "Decimation chain", "Filters", "Verification", "ASIC"],
        [cite("{nexys}"), "Artix-7", "count ones, 128 bits", "1 fixed", "not reported", "no"],
        [cite("{todorovic}"), "Spartan-6", "CIC5, 2 half-band, FIR (IP)", "1 fixed", "system vs. Matlab", "no"],
        [cite("{ilies}"), "Artix-7", "CIC only, 3 versions", "–", "within 1.6 units", "no"],
        ["This work", "Artix-7", "CIC4, 63-tap comp., DC block", "5 (switch)", "bit-exact: model, RTL, board", "same RTL"],
    ], [27, 31, 66, 32, 57, 30], align="lllcll")

    # ================================================================ III. architecture
    H1("System Architecture")
    P(f"Fig. {F['system']} shows the signal path. The board provides a 100 MHz oscillator, an Analog Devices "
      "ADMP421 PDM microphone {admp421} and a mono audio output whose open-drain input feeds a fourth-order "
      "Sallen-Key Butterworth low-pass filter {nexys}. All logic runs on the 100 MHz clock. The microphone "
      "clock is a registered data output, so the design has no derived clock, and its only clock-domain "
      "crossings are two-flop synchronizers on the asynchronous inputs (switches, button, UART receive and "
      "microphone data). The CIC registers are 21 bits wide. The filters carry 24-bit data with 18-bit "
      "coefficients and a 48-bit accumulator, and the output is 16 bits at 50 kHz.")
    FIG("system", os.path.join(FIGS, "fig_system.png"),
        "Signal chain of the audio filter. Solid lines carry live audio. Dashed lines are the test paths of "
        "the UART controller: D injects PDM bits, T injects filter input samples and C captures the output.",
        width=COL_W * 0.92)

    # ================================================================ IV. design
    H1("Design Methodology")
    H2("Design Flow and Coding Rules")
    P("Every constant (rates, widths, filter edges, shifts) is defined once in a Python file. Scripts design "
      "and quantize the filters, write the coefficient ROMs as Verilog case statements and generate the test "
      "vectors, so the RTL, the model and the tests share one source. The RTL is plain Verilog-2001 written "
      "to four rules: logic modules contain no initial blocks, delays or unbounded loops; every combinational "
      "block assigns a default to each output, so no latch can be inferred; combinational logic (blocking "
      "assignments) and registers (non-blocking assignments) sit in separate blocks; and each file is "
      "divided into ports, declarations, combinational logic and sequential logic. Verilator lint with all "
      "warnings enabled {verilator} runs clean, and Yosys {yosys} reports no inferred latch.")

    H2("PDM Interface and Sampling Phase")
    P("The microphone clock M_CLK is the 100 MHz clock divided by 40, or 2.5 MHz, inside the ADMP421 range of "
      "1 MHz to 3.3 MHz {nexys}. With its left/right select pin low, the microphone drives DATA during one "
      "half of the clock period and releases the line during the other half {nexys, admp421}, so the sample "
      "must fall inside the driven half. DATA passes through a two-flop synchronizer and is taken at count 38 "
      "of 40, about 50 ns before the falling edge at which the microphone releases the line (Fig. "
      f"{F['wave']}a). Switch SW6 moves the sampling point to the other half period. Sampling the released "
      "line returns noise, so the switch also checks the timing on the board. The top-level testbench models "
      "the released half as high impedance, and a wrong phase would then fail the bit-exact comparison.")
    FIG("wave", os.path.join(FIGS, "waveforms.png"),
        "Simulated waveforms (Icarus Verilog). (a) Microphone interface: the line is released (dotted) in "
        "the half period the microphone does not drive. (b) One output of the 511-tap filter.")

    H2("CIC Decimator")
    P("A CIC filter with N = 4 stages, decimation R = 25 and differential delay M = 1 reduces the rate to "
      "100 kHz without multipliers {hogenauer}. Its transfer function and DC gain are")
    B.append(D.equation_img(img, D.render_equation(r"H(z)=\left[\frac{1-z^{-R}}{1-z^{-1}}\right]^{N},\quad H(1)=R^{N}=390\,625", os.path.join(FIGS, "eq1.png")), 1))
    P("The PDM bit is mapped to ±1, so the registers need 2 + ⌈N log_{2}(RM)⌉ = 21 bits. The "
      "integrators may overflow: two's-complement arithmetic is modular, and the comb outputs stay exact as "
      "long as the registers have that width. The CIC output is shifted left by three bits, which places its "
      "full scale at 0.37 of the 24-bit range and leaves headroom for the passband boost of the next filter.")

    H2("Droop Compensation and Second Decimation")
    P(f"The CIC response falls by {V('CicDroop')} dB at 16 kHz. A 63-tap linear-phase FIR filter at 100 kHz, "
      "which also decimates by two, corrects the droop and removes the band that would alias into the audio "
      "band {kwentus}. Its coefficients come from a weighted least-squares fit to 1/|H(f)| from 0 to 16 kHz, "
      "with a stopband from 25 kHz. After quantization the cascade is flat to within "
      f"{V('CompRipple')} dB up to 16 kHz and attenuates the 25 kHz to 50 kHz band by {V('CompStop')} dB "
      f"(Fig. {F['decim']}).")
    FIG("decim", os.path.join(FIGS, "decimator_response.png"),
        f"CIC, compensation filter and their cascade at the 100 kHz rate. The hatched band aliases after "
        f"decimation by two and is attenuated by {V('CompStop')} dB.")

    H2("DC Blocker")
    P("MEMS microphones and the CIC produce a DC offset that the gain stage would otherwise amplify into "
      "saturation. A first-order high-pass without a multiplier removes it:")
    B.append(D.equation_img(img, D.render_equation(r"y[n]=x[n]-\left\lfloor a[n]/2^{K}\right\rfloor,\quad a[n+1]=a[n]+y[n]", os.path.join(FIGS, "eq3.png")), 2))
    P("With K = 10 the pole lies at 1 − 2^{−10} and the corner frequency near 7.8 Hz.")

    H2("Selectable Filter Banks and Coefficient Scaling")
    P("Four 511-tap linear-phase filters were designed with the Parks-McClellan algorithm {mcclellan}: a pure "
      "delay used as bypass, a 1 kHz low-pass, a 2 kHz high-pass and a 0.4 kHz to 3.4 kHz band-pass based on "
      "the telephone voice band {itu}. All four have a group delay of 255 samples (5.1 ms), so switching banks "
      "does not shift the signal in time. Coefficients use 18 bits to match the DSP48E1 multiplier {ug479}.")
    P("Narrow-band filters have small coefficients; the largest low-pass tap is 0.047. In a fixed Q2.16 format "
      "the top five bits of every coefficient are then unused, and the quantization floor limits the stopband "
      "to about 70 dB. Each bank b is therefore stored multiplied by 2^{s}, where s = s_{b} is the largest "
      "exponent for which the coefficients still fit in 18 bits, and the accumulator is shifted right by "
      "S = 16 + s_{b}:")
    B.append(D.equation_img(img, D.render_equation(r"y[n]=\mathrm{sat}\left(\left(\sum_{k=0}^{510}h_b[k]\,x[n-k]+2^{S-1}\right)\gg S\right)", os.path.join(FIGS, "eq4.png")), 3))
    P(f"Table {T['banks']} shows the effect: the stopband of the low-pass filter rises from {V('StopUB')} dB to "
      f"{V('StopB')} dB, within 1 dB of the unquantized design. Fig. {F['banks']} shows the quantized "
      "responses together with the 31-tap filter of Section IV-H.")
    TABLE("banks", "Filter Banks of the 511-Tap FIR (f_{s} = 50 kHz)", [
        ["Bank", "Edges (kHz)", "s_{b}", "Float (dB)", "Q2.16 (dB)", "Scaled (dB)", "Ripple (dB)"],
        ["0 bypass", "–", V("ShiftA"), "–", "–", "–", "0"],
        ["1 low-pass", "1.0 / 1.4", V("ShiftB"), V("StopFB"), V("StopUB"), V("StopB"), V("RippleB")],
        ["2 high-pass", "1.6 / 2.0", V("ShiftC"), V("StopFC"), V("StopUC"), V("StopC"), V("RippleC")],
        ["3 band-pass", "0.4 to 3.4", V("ShiftD"), V("StopFD"), V("StopUD"), V("StopD"), V("RippleD")],
    ], [44, 44, 20, 33, 34, 34, 34], align="lcccccc",
        note="Float, Q2.16 and scaled give the stopband attenuation of the unquantized design, of 18-bit "
             "coefficients without scaling, and of the scaled coefficients used in hardware.")
    FIG("banks", os.path.join(FIGS, "main_banks.png"),
        "Magnitude responses of the quantized filter banks 1 to 3 and of the 31-tap parallel filter (bank 4).")

    H2("Time-Multiplexed FIR Architecture")
    P(f"At 100 MHz and 50 kHz there are 2000 clock cycles per output sample, so the 511-tap filter computes "
      f"one product per cycle (Fig. {F['mac']}). Samples are kept in a 512-word circular buffer in "
      "simple-dual-port block RAM, and coefficients in a 4 × 512 ROM addressed by bank and tap. The "
      "pipeline of RAM and ROM read, operand registers, multiply, accumulate, rounding, and shift with "
      "saturation maps onto the A, B, M and P registers of a DSP48E1. One output takes 511 + 6 = 517 "
      f"cycles, about 26% of the budget (Fig. {F['wave']}b). The same module, with decimation by two and a "
      "single bank, implements the compensation filter. An input that arrives while the filter is busy "
      "raises an overrun flag that lights a red LED, so a lost sample is always visible. After reset the "
      "delay line is cleared, which gives hardware and model the same starting state.")
    FIG("mac", os.path.join(FIGS, "fig_mac.png"),
        "Serial multiply-accumulate datapath of the 511-tap filter. The tap index k runs from 0 to 510 for "
        "each output; flags that travel with the data mark the first and last products.")

    H2("Parallel FIR Core Shared with the ASIC")
    P("Bank 4 is a 31-tap linear-phase low-pass filter with 16-bit data and coefficients and a "
      f"{V('AsicStop')} dB stopband. It computes all taps in parallel, which is the form an ASIC without RAM "
      "macros needs. Symmetry halves the multipliers to 16 through pre-adders, and because the coefficients "
      "are constants, ASIC synthesis reduces each multiplier to shifts and additions "
      f"({V('AsicCsd')} non-zero canonical-signed-digit terms in total) {{hartley}}. A parameter selects one of "
      "two micro-architectures {parhi}: PIPE = 0 registers only the input shift register and the output, while "
      "PIPE = 1 adds a register after the pre-adders, the multipliers and every adder-tree level. The FPGA uses "
      "PIPE = 1, and switch SW8 routes the audio through this core instead of the 511-tap filter. The same "
      "Verilog file is the input of the ASIC flow in Section VI-D.")

    H2("Gain and Output Stage")
    P("A switch-selected gain of 2^{g} (g = 0 to 15, 0 dB to 90 dB) with saturation makes up for the low "
      "microphone level; speech at 60 dB SPL is roughly −60 dBFS at the ADMP421 output {admp421}. The top "
      "16 bits drive either a 10-bit PWM modulator with a 97.7 kHz carrier, above the 50 kHz minimum that "
      "Digilent recommends for the board filter {nexys}, or a first-order delta-sigma modulator running at "
      "100 MHz {schreier}. The output pin is open drain, as the board requires, and the modulator input is "
      "held at mid-scale in test mode and while the amplifier is off.")

    H2("Control and Hardware Test Port")
    P(f"A command controller (Fig. {F['fsm']}) receives commands over the board's USB-UART at 1 Mbaud. 'P' and "
      "'S' return an identifier and the switch and error state. 'T' sends 24-bit samples through one filter "
      "bank and returns the results. 'D' sends PDM bytes through the whole chain and returns 16-bit audio "
      "samples. 'C' records 16 384 live output samples (0.33 s) and sends them to the host. 'T' and 'D' "
      "first clear the chain and mute the output, so the board reproduces the Python model exactly, and "
      "restore live operation when they finish. A watchdog returns the controller to IDLE when the host "
      "stops sending for 0.17 s.")
    FIG("fsm", os.path.join(FIGS, "fig_fsm.png"),
        "State diagram of the UART command controller. CLRW clears the filter delay lines before a test "
        "command; a byte that arrives during the clear is held and processed afterwards. Header and run "
        "states return to IDLE if the host stops sending for 0.17 s.")

    H2("Hardware Implementation")
    P("The pin constraints come from Digilent's master constraint file. Asynchronous inputs are declared "
      "as false paths because each passes through a synchronizer, and the microphone data timing is set by "
      "the sampling phase of Section IV-B. Switches select the bank, gain, sampling half and modulator; the "
      "LEDs and the seven-segment display show the signal level, the settings and a sticky error flag. The "
      "RTL hierarchy that Vivado 2018.2 elaborates matches Fig. 1 block for block, and the DC blocker "
      "elaborates to a shift, a subtractor, an adder and two comparators, with no multiplier.")

    # ================================================================ V. verification
    H1("Verification Methodology")
    H2("Golden Model and Testbenches")
    P("The Python model reproduces every register-level detail of the RTL: CIC wrap-around and decimation "
      "phase, FIR rounding by adding 2^{S−1} before an arithmetic shift, saturation, DC-blocker truncation "
      "and the gain stage. Because the model also writes the coefficient ROMs and the test vectors, RTL and "
      f"model share one source of coefficients. Table {T['verif']} lists the self-checking testbenches, which "
      "run in Icarus Verilog {icarus}. Their stimuli include impulses, full-scale random data, sign patterns "
      "that drive the accumulator into saturation, and PDM streams from a second-order delta-sigma modulator "
      "model. The chain testbench supplies PDM bits 2.5 times faster than the microphone to stress the "
      "pipeline; no overrun occurred. A separate plain-Verilog testbench targets the Vivado 2018.2 simulator.")
    TABLE("verif", "Verification Summary (Simulation)", [
        ["Testbench", "Scope", "Samples", "Result"],
        ["tb_cic", "CIC: random, tones, DC", *SIM_COUNT("tb_cic")],
        ["tb_fir", "4 banks, saturation, overrun; comp. FIR", *SIM_COUNT("tb_fir")],
        ["tb_chain", "PDM to audio, 5 settings; DC blocker", *SIM_COUNT("tb_chain")],
        ["tb_top", "pins: microphone model, UART P/S/T/D/C (full FIFO), watchdog, open drain", *SIM_COUNT("tb_top")],
        ["tb_fir_par", "31-tap core, PIPE = 0 and 1", *SIM_COUNT("tb_fir_par")],
    ], [42, 125, 38, 38], align="llrc")
    H2("Defects Found at the Top Level and on the Board")
    P("Every block passed its own test, yet the first pin-level run of the 'T' command returned 39 of 40 "
      "samples, all wrong. At the start of a command the controller clears the filter delay line and then "
      "waits; that wait (11 µs) was longer than one UART byte (10 µs), so the first data byte was "
      "dropped and every later sample was misaligned by one byte. The fix shortens the wait to 6 µs, still "
      "longer than the 512-cycle clear, and adds a one-byte holding register so that no byte can be lost. The "
      "defect lay in the interaction between the protocol timing and the clear sequence, which no block-level "
      "test exercises.")
    P("A second defect appeared only on the board: the capture command returned 16 641 of 32 768 bytes. The "
      "controller registers its write to the UART transmit FIFO, so a byte enters the FIFO one clock after "
      "the controller has checked the full flag. The capture dump writes the two bytes of a sample on "
      "consecutive clocks. With one slot free, both writes passed the check and the FIFO dropped the "
      "second. Once the 512-byte FIFO had filled, every second byte was lost, which predicts 16 640 bytes. "
      "The 'T' and 'D' replies never fill the FIFO because their output is paced by their input, and the "
      "top-level test captured only 128 bytes. An almost-full flag now stops the writer one slot early, and "
      "the top-level test captures 2048 bytes and compares each one with the samples that were recorded.")
    H2("Board-Level Comparison")
    P("On the board the host repeats the comparison through the UART port. It sends an impulse and random "
      "full-scale blocks through each bank, and PDM streams through the whole chain, and compares every "
      "returned sample with the model. The host tool also runs against a software copy of the board; in that "
      f"mode it compared {SIMHOST()} samples with no mismatch before the hardware was available.")

    # ================================================================ VI. results
    H1("Results and Discussion")
    H2("Simulation Results")
    P(f"Fig. {F['bitexact']} overlays the RTL output and the model for the band-pass setting; the difference is "
      "zero for every sample, and the same holds for all testbenches in Table "
      f"{T['verif']}. The 511-tap filter delivers a result 517 cycles after its input, and the whole chain has "
      f"a group delay of {V('EndDelay')} ms.")
    FIG("bitexact", os.path.join(FIGS, "bitexact.png"),
        "Full-chain output for bank 3: RTL simulation against the Python model. The difference is zero over "
        "all 1500 samples.")
    H2("FPGA Implementation")
    P(f"Table {T['fpga']} compares the Yosys synth_xilinx estimate {{yosys}} with Vivado 2018.2 after placement "
      f"and routing on the XC7A50T. The design meets the 100 MHz constraint with a worst setup slack of "
      f"{V('VWns')} ns, which corresponds to about {V('VFmax')} MHz, and a hold slack of {V('VWhs')} ns. Each "
      "serial filter uses one DSP slice, the 16 constant multipliers of the parallel core use most of the "
      "others, and eight of the block-RAM tiles hold the capture buffer.")
    TABLE("fpga", "FPGA Implementation on the XC7A50T", [
        ["Resource", "Yosys estimate", "Vivado", "Available"],
        ["LUT", V("YLut"), V("VLut"), "32 600"],
        ["Flip-flop", V("YFf"), V("VFf"), "65 200"],
        ["DSP48E1", V("YDsp"), V("VDsp"), "120"],
        ["Block RAM (36 Kb tiles)", V("YBram"), V("VBram"), "75"],
        ["WNS / WHS at 100 MHz (ns)", "–", V("VWns") + " / " + V("VWhs"), "–"],
        ["On-chip power (mW)", "–", V("VPower"), "–"],
    ], [83, 55, 55, 50], align="lrrr")
    H2("On-Board Measurements")
    # paper-style plot of the board measurement (model/plot_hw.py), made from results/hw_freqresp_b3.json
    if os.path.exists(os.path.join(ROOT, "results", "hw_freqresp_b3.json")):
        sys.path.insert(0, os.path.join(ROOT, "model"))
        import plot_hw
        plot_hw.main(3)
    hwf, have_hw = fig_file("hw_freqresp_b3.png", ["Measured response of bank 3 on the FPGA",
                                                   "python host/af_host.py --port COMx all"], aspect=0.62,
                            search=[os.path.join(FIGS, "hw_freqresp_b3.png"),
                                    os.path.join(ROOT, "results", "hw_freqresp_b3.png")])
    P(f"The hardware-in-the-loop self-test sent {V('HwFirSamples')} samples through the five filters and "
      f"{V('HwChainSamples')} samples through the whole chain. Every output matched the golden model bit for bit "
      f"({V('HwFirErr')} mismatches in either test), both over JTAG and after the board had booted from "
      f"flash. Fig. {F['hwfreq']} shows bank 3 measured with 60 stepped sines through the 'T' path; above "
      "\u221260 dB the four MAC banks agree with the quantized design to 0.001 dB, and the 31-tap core to "
      "0.03 dB, the difference coming from its 16-bit data path.")
    P(f"For the live path, a pure 1 kHz sine from a laptop speaker 10 cm from the microphone gave an SNR of "
      f"{V('HwSnr')} dB with the harmonics excluded, a THD of {NEG(V('HwThd'))} dB and a SINAD of {V('HwSinad')} dB "
      f"at \u221232 dBFS. These values include the speaker and the room. A phone speaker at the same level gave "
      f"a THD of {NEG(V('HwPhoneThd'))} dB that improved by 16 dB when its volume was lowered, so that distortion was "
      f"acoustic. In the same setup the low-pass bank removed a 3 kHz tone by {V('HwLpRej')} dB and the SKY130 "
      f"core removed an 8 kHz tone by {V('HwAsicRej')} dB, against 89.4 and 57.2 dB by design; the first figure "
      "is limited by the noise floor of a 16\u00a0384-sample capture. Both PDM sampling phases (SW6) gave the same "
      "result within 1 dB.")
    FIG("hwfreq", hwf, "Bank 3 (telephone band-pass): designed response and the response measured on the "
        "FPGA with 60 stepped sines through the UART test path.")
    H2("ASIC Implementation")
    lay, _ = fig_file("asic_layout.png", ["Routed fir_par layout (KLayout)", "librelane --last-run --flow OpenInKLayout",
                                          "save as docs/report/figs/user/asic_layout.png"], aspect=0.8)
    P(f"Table {T['asic']} gives a pre-layout estimate from Yosys with ABC mapping to the sky130_fd_sc_hd "
      "library at the typical corner (25 °C, 1.8 V). The delay counts gate delays only, without wires, "
      "clock-to-output and setup time. Pipelining cuts the critical gate delay from "
      f"{V('EDelayZ')} ns to {V('EDelayO')} ns for about {AREA_PCT()}% more cell area, mostly from the extra "
      f"{V('EFlopsO')} versus {V('EFlopsZ')} flip-flops. The LibreLane runs add placement, clock-tree "
      "synthesis, routing, static timing with extracted parasitics, and DRC and LVS checks. Each version is "
      "routed at a clock it meets, its shortest period is taken as that clock minus the worst setup slack at "
      f"the typical corner, and a second run at that period confirms it. The slow corner (100 °C, 1.6 V) is "
      "not closed at these periods; a product would need a longer clock or more pipelining there. "
      f"Fig. {F['layout']} shows the routed layout of the pipelined core.")
    TABLE("asic", "SKY130 Results for the 31-Tap Core", [
        ["Metric", "PIPE = 0", "PIPE = 1"],
        ["Cells (pre-layout)", V("ECellsZ"), V("ECellsO")],
        ["Flip-flops", V("EFlopsZ"), V("EFlopsO")],
        ["Cell area (µm^{2})", V("EAreaZ"), V("EAreaO")],
        ["Critical gate delay (ns)", V("EDelayZ"), V("EDelayO")],
        ["Min. period after routing (ns)", V("LPeriodZ"), V("LPeriodO")],
        ["Area after routing (µm^{2})", V("LAreaZ"), V("LAreaO")],
        ["Power (mW)", V("LPowerZ"), V("LPowerO")],
        ["DRC / LVS errors", V("LDrcZ") + " / " + V("LLvsZ"), V("LDrcO") + " / " + V("LLvsO")],
    ], [113, 65, 65], align="lrr")
    FIG("layout", lay, "Routed layout of the pipelined 31-tap core on SKY130.", width=COL_W * 0.8)
    H2("Discussion and Limitations")
    P("The design trades latency for hardware. The 511-tap filters add 5.1 ms of delay and the whole chain "
      f"{V('EndDelay')} ms, which suits monitoring and demonstration but would call for shorter or "
      "minimum-phase filters in a hearing aid. On this board the microphone data line keeps its last value "
      "while released, so both PDM sampling phases read valid bits and SW6 cannot catch a wrong phase; a "
      "board without that behavior would need the phase checked again. The live-path numbers are bounded by "
      "the acoustic source and the room rather than by the filter, and the board's output filter and PWM "
      "carrier limit the analog quality at the jack, so quality is measured digitally through the capture "
      "command.")

    # ================================================================ VII. conclusion
    H1("Conclusion and Future Work")
    P("A digital microphone filter was designed for the Nexys A7-50T with five run-time selectable filters, "
      "four of them on one DSP slice, and per-bank coefficient scaling that recovers up to 14.2 dB of stopband "
      "attenuation. A bit-exact verification flow covers every block, the full chain and the pin-level top "
      "level, and extends to the board through a UART test port. The 31-tap core runs on the FPGA and enters "
      "the open-source SKY130 flow from the same source file. Future work includes a minimum-phase mode with "
      "lower latency, an adaptive noise-cancellation stage, and fabrication of the core on a shared shuttle.")

    # ================================================================ acknowledgment + references
    B.append(D.para("Heading5", D.rich("Acknowledgment")))
    P("The author thanks the Department of Electrical and Electronics Engineering, Kathmandu University, for "
      "access to the Nexys A7 board.")
    B.append(D.para("Heading5", D.rich("References")))
    for n, k in enumerate(_order, 1):
        B.append(D.para("references", D.bookmark(f"_RefCite{n}", 900 + n, D.rich(REFS[k]))))
    unused = [k for k in REFS if k not in _order]
    if unused:
        print("note: uncited references omitted:", unused)
    assert FIGNUM[0] == len(F), (FIGNUM[0], len(F))
    assert all(LABELS[k] == F[k] for k in F), "figure numbering out of order"
    return B, img


def write_docx(body, img, out_path):
    with zipfile.ZipFile(TEMPLATE) as z:
        files = {n: z.read(n) for n in z.namelist()}
    doc = files["word/document.xml"].decode("utf-8")
    head = doc[:doc.index("<w:body>") + len("<w:body>")]
    if 'xmlns:a="' not in head[:head.index(">", head.index("<w:document"))]:
        head = head.replace("<w:document ", '<w:document xmlns:a="http://purl.oclc.org/ooxml/drawingml/main" ', 1)
    final_sect = D.sect(cols=2)
    new_doc = head + "".join(body) + final_sect + "</w:body></w:document>"
    files["word/document.xml"] = new_doc.encode("utf-8")
    # relationships + media
    rels = files["word/_rels/document.xml.rels"].decode("utf-8")
    rels = re.sub(r'<Relationship Id="rId(9|10)"[^>]*/>', "", rels)   # template hyperlinks no longer used
    add = "".join(f'<Relationship Id="{rid}" Type="{D.REL_IMAGE}" Target="{tgt}"/>' for rid, tgt, _ in img.items)
    files["word/_rels/document.xml.rels"] = rels.replace("</Relationships>", add + "</Relationships>").encode()
    for rid, tgt, path in img.items:
        files["word/" + tgt] = open(path, "rb").read()
    ct = files["[Content_Types].xml"].decode()
    if 'Extension="png"' not in ct:
        ct = ct.replace("<Default Extension=\"xml\"", '<Default Extension="png" ContentType="image/png"/><Default Extension="xml"')
    files["[Content_Types].xml"] = ct.encode()
    # footers: page numbers on every page; the first page also keeps the copyright line if one is set
    from xml.sax.saxutils import escape
    ftr = files["word/footer1.xml"].decode("utf-8")
    root = ftr[:ftr.index("<w:p ")]
    line = ""
    if COPYRIGHT_LINE:
        line = ('<w:p><w:pPr><w:pStyle w:val="Footer"/><w:jc w:val="start"/></w:pPr><w:r><w:rPr><w:sz w:val="16"/>'
                f'<w:szCs w:val="16"/></w:rPr><w:t>{escape(COPYRIGHT_LINE)}</w:t></w:r></w:p>')
    files["word/footer1.xml"] = (root + line + D.page_number_paragraph() + "</w:ftr>").encode("utf-8")
    files["word/footer2.xml"] = (root + D.page_number_paragraph() + "</w:ftr>").encode("utf-8")
    rels = files["word/_rels/document.xml.rels"].decode("utf-8")
    ftype = re.search(r'Type="([^"]+/footer)"', rels).group(1)
    rels = rels.replace("</Relationships>", f'<Relationship Id="rIdPgNum" Type="{ftype}" Target="footer2.xml"/>'
                        "</Relationships>")
    files["word/_rels/document.xml.rels"] = rels.encode("utf-8")
    ct = files["[Content_Types].xml"].decode()
    if "/word/footer2.xml" not in ct:
        ct = ct.replace("</Types>", '<Override PartName="/word/footer2.xml" ContentType="application/'
                        'vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>')
    files["[Content_Types].xml"] = ct.encode()
    # document properties
    core = files["docProps/core.xml"].decode()
    core = re.sub(r"<dc:title>.*?</dc:title>", "<dc:title>" + TITLE + "</dc:title>", core)
    files["docProps/core.xml"] = core.encode()
    # keep the 600-dpi figures: stop Word from recompressing pictures to 220 ppi when it saves or exports
    st = files.get("word/settings.xml")
    if st is not None:
        st = st.decode("utf-8")
        if "doNotAutoCompressPictures" not in st:
            # schema order: after clrSchemeMapping/doNotIncludeSubdocsInStats, before forceUpgrade ... listSeparator
            # and the w14/w15 extension elements, so Word does not report unreadable content
            m = re.search(r"<w:(forceUpgrade|captions|readModeInkLockDown|smartTagType|schemaLibrary|shapeDefaults|"
                          r"doNotEmbedSmartTags|decimalSymbol|listSeparator)\b|<w1[45]:|</w:settings>", st)
            m = m or re.search(r"</w:settings>", st)
            st = st[:m.start()] + "<w:doNotAutoCompressPictures/>" + st[m.start():]
        files["word/settings.xml"] = st.encode("utf-8")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in ["[Content_Types].xml"] + [n for n in files if n != "[Content_Types].xml"]:
            z.writestr(n, files[n])


def main():
    body, img = build()
    out = os.path.join(HERE, "paper.docx")
    write_docx(body, img, out)
    print("written", out, f"({len(img.items)} figures)")
    pdf = os.path.join(HERE, "paper.pdf")
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", HERE, out],
                       capture_output=True, timeout=300)
    elif os.name == "nt":
        # Windows without LibreOffice: let Microsoft Word export the PDF (needs Word installed)
        ps = ("$w = New-Object -ComObject Word.Application; $w.Visible = $false; $w.DisplayAlerts = 0; "
              # open read-only, so a copy of paper.docx left open in Word does not block the export
              f"$d = $w.Documents.Open('{out}', $false, $true); "
              # PDF/A export embeds every font (IEEE PDF eXpress needs that); plain SaveAs as a fallback
              f"try {{ $d.ExportAsFixedFormat('{pdf}', 17, $false, 0, 0, 1, 1, 0, $true, $true, 0, $true, $true, $true); "
              "Write-Output 'EXPORT=PDFA' } "
              f"catch {{ Write-Output ('EXPORT=FALLBACK ' + $_.Exception.Message); $d.SaveAs([ref] '{pdf}', [ref] 17) }}; "
              "$d.Close([ref] 0); $w.Quit()")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                               timeout=300)
            msg = (r.stdout or "") + (r.stderr or "")
            if "EXPORT=PDFA" in msg:
                print("PDF exported by Word as PDF/A: every font embedded")
            else:
                print("WARNING: Word could not export PDF/A, so fonts may not be embedded. "
                      "Close every Word window and run this again. Word said:\n" + msg.strip()[:600])
        except (OSError, subprocess.SubprocessError) as e:
            print("WARNING: Word export failed:", e)
    if os.path.exists(pdf) and os.path.getmtime(pdf) >= os.path.getmtime(out):
        print("written", pdf)
    else:
        print("note: paper.pdf was not updated (no LibreOffice or Word found). "
              "Open paper.docx in Word and use File > Save As > PDF.")

if __name__ == "__main__":
    main()
