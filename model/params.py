"""Single source of truth for every number shared by the Python model and the RTL.

If you change anything here, re-run `make model` so the .hex coefficient files and
the generated Verilog header (rtl/af_params.vh) and ROM modules are rebuilt.
"""

# ---------------------------------------------------------------- clocks / rates
F_SYS = 100_000_000          # Nexys A7 oscillator, pin E3
MCLK_DIV = 40                # M_CLK = F_SYS / MCLK_DIV = 2.5 MHz (ADMP421 range: 1.0-3.3 MHz)
F_PDM = F_SYS // MCLK_DIV    # 2.5 MHz PDM bit rate

CIC_N = 4                    # number of integrator/comb stages
CIC_R = 25                   # CIC decimation factor  -> 100 kHz
CIC_W = 21                   # register width: 2 + ceil(N*log2(R)) = 2 + 19 = 21 bits
F_CIC = F_PDM // CIC_R       # 100 kHz

COMP_TAPS = 63               # CIC-compensation / anti-alias FIR, decimate by 2
COMP_DECIM = 2
COMP_AW = 6                  # 2**6 = 64 >= 63 taps
FS = F_CIC // COMP_DECIM     # 50 kHz audio sample rate

MAIN_TAPS = 511              # selectable main FIR (4 banks)
MAIN_AW = 9                  # 2**9 = 512 >= 511
MAIN_BANKS = 4

# ---------------------------------------------------------------- fixed point
DW = 24                      # datapath width (signed), fits DSP48E1 25-bit A port
CW = 18                      # coefficient width (signed), fits DSP48E1 18-bit B port
CFRAC = 16                   # coefficient fractional bits: Q2.16, range [-2, 2)
ACC_W = 48                   # accumulator width (DSP48E1 P register)
CIC_SHIFT = 3                # CIC output (<= 390625) << 3 -> 0.3725 of 24-bit full scale
DC_K = 10                    # DC blocker: pole at 1 - 2^-10, corner ~ FS/(2*pi*1024) = 7.8 Hz
OUT_W = 16                   # audio output word (top 16 of 24 bits)
GAIN_MAX = 15                # digital gain = 2^g, g = 0..15 (0..90 dB)

# ---------------------------------------------------------------- outputs
PWM_BITS = 10                # 100 MHz / 1024 = 97.66 kHz carrier (RM: >= 50 kHz)

# ---------------------------------------------------------------- PDM sampling phase
# M_CLK is high while cnt >= MCLK_DIV/2. ADMP421 with L/R=0 drives DATA in one half of the
# clock period and is high-Z in the other half. We sample near the END of the half in
# which the microphone drives (max data-valid margin). SW[6] swaps the half, which is a
# built-in debug check of the microphone timing (see paper Sec. IV-B).
SAMPLE_CNT_HI = 38           # end of the high phase (default, SW[6]=0)
SAMPLE_CNT_LO = 18           # end of the low phase  (SW[6]=1)

# ---------------------------------------------------------------- UART test interface
BAUD = 1_000_000             # FT2232HQ supports exactly 1 Mbaud (3 MHz / 3)
CAP_AW = 14                  # capture buffer 2^14 = 16384 samples (0.33 s at 50 kHz)
VERSION = (1, 1)            # 1.1: Verilog-2001 rewrite + ASIC core as bank 4

BANK_NAMES = ["Bypass (delay only)", "Low-pass 1 kHz", "High-pass 2 kHz",
              "Telephone band-pass 0.4-3.4 kHz"]
PAR_BANK = 4                 # bank 4 = the 31-tap parallel FIR shared with the ASIC (SW8)
