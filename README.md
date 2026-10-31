# Design and Bit-Exact Verification of a Real-Time Digital Microphone Filter on FPGA and SKY130

[!\[Regression](https://github.com/saman-fuyal/fpga-audio-filter/actions/workflows/regression.yml/badge.svg)](https://github.com/YOUR-USERNAME/fpga-audio-filter/actions/workflows/regression.yml)

Saman Fuyal, Department of Electrical and Electronics Engineering, Kathmandu University

This project filters the sound from the MEMS microphone on a Digilent Nexys A7-50T in real time
and plays the result on the board's audio jack. The microphone delivers a 1-bit PDM stream at
2.5 MHz. The FPGA turns it into 24-bit audio at 50 kHz and passes it through one of five filters
chosen with the switches. Every stage gives exactly the same numbers as a Python model of the
design, and that was checked in simulation and again on the board. One of the five filters,
`rtl/fir\_par.v`, also went through the open-source LibreLane flow for the SkyWater 130 nm process.

!\[Board and laptop during the on-board self-test](docs/photos/setup\_labelled.jpg)

```
mic -> PDM i/f -> CIC N=4 R=25 -> comp FIR 63t /2 -> DC block -> FIR 511t, banks 0-3 (1 DSP) -> gain -> PWM/DS -> jack
       2.5 MHz      100 kHz         50 kHz                      or FIR 31t parallel (bank 4, ASIC core)   open drain
                    UART 1 Mbaud: inject PDM bits or filter samples, read results, capture live audio
```

Hardware and tools: Nexys A7-50T (xc7a50ticsg324-1L), Vivado 2018.2, Icarus Verilog 12, Python 3,
Microsoft Word for the paper, and WSL2 Ubuntu with Nix and LibreLane for the chip flow.
`COMMANDS.md` lists every command, in order.

## Results

Simulation. The four testbenches (CIC, FIR, whole chain, and the top level driven through the
real pins with a microphone model and a UART host model) and the ASIC-core testbench all match
the Python model sample for sample. GitHub runs all of them, and the coding-rule check, on every
push (`.github/workflows/regression.yml`); the badge at the top shows the latest result.

FPGA (Vivado 2018.2, post-route): 1948 LUTs, 2191 flip-flops, 18 DSP48E1 slices and 10.5
block-RAM tiles. The design meets 100 MHz with 1.462 ns of setup slack (about 117 MHz maximum)
and uses 95 mW.

On the board:

|Test|Result|
|-|-|
|Bit-exact self-test over UART|67 920 samples, 0 mismatches, both over JTAG and after booting from flash|
|Measured frequency response, 60 tones per bank|within 0.001 dB of the design for banks 0 to 3 and 0.03 dB for the 31-tap core|
|1 kHz tone from a laptop speaker|SNR 42.2 dB, THD -37.6 dB, SINAD 36.3 dB|
|Live tone through the filters|low-pass removes 3 kHz by 85.5 dB, high-pass removes 500 Hz by 89.3 dB, ASIC core removes 8 kHz by 56.7 dB|
|Voice through each bank|each filter removes its stopband from speech (`results/hw\_voice.png`)|
|Gain, switches, reset, error flags|6 dB per gain step, every switch decoded, no error flag after all tests|

SKY130 with LibreLane, typical corner (25 °C, 1.8 V), DRC and LVS clean:

||Unpipelined|Pipelined|
|-|-|-|
|Shortest clock period|15.6 ns (64 MHz)|6.0 ns (166 MHz)|
|Standard-cell area|145 592 µm²|190 643 µm²|
|Power at that clock|10.8 mW|27.5 mW|

The slow corner (100 °C, 1.6 V) does not close at these periods.

`results/hw\_results\_summary.txt` collects every board result in one place.

### Listen to it

These are 0.33 s recordings of my voice, captured from the board's output over USB with the
microphone 20 cm away and the gain at 4. Each is a separate take, one per filter. Open a file
and click the download button to play it.

|Recording|Filter|What you should hear|
|-|-|-|
|[voice\_b0.wav](results/voice_b0.wav)|bank 0, no filtering|the plain voice|
|[voice\_b1.wav](results/voice_b1.wav)|bank 1, low-pass 1 kHz|muffled; 2.3 to 3.2 kHz is 52 dB down|
|[voice\_b2.wav](results/voice_b2.wav)|bank 2, high-pass 2 kHz|thin and hissy; below 300 Hz is 87 dB down|
|[voice\_b3.wav](results/voice_b3.wav)|bank 3, band-pass 0.4 to 3.4 kHz|telephone-like; 4.5 to 7 kHz is 43 dB down|
|[voice\_asic.wav](results/voice_asic.wav)|31-tap ASIC core, low-pass|slightly dull; 8 to 16 kHz is 20 dB down|

The levels come from `tools/analyze\_voice.py`, which compares each recording with bank 0 band by
band (`results/hw\_voice.txt`).

!\[Spectrum of the voice recordings through each filter](results/hw\_voice.png)

### Two defects found on the way

The pin-level testbench showed that the first data byte of a UART test command was lost: the
controller cleared the filters for 11 µs, longer than one UART byte. The wait is now 6 µs, and a
byte that arrives during it is held in a register.

The board showed that a live capture returned only 16 641 of 32 768 bytes. The UART transmit
FIFO's push is registered, and the controller sends the low and high byte of a sample on
consecutive clocks, so with one free slot the second byte was dropped. The controller now stops
on an "almost full" flag, and the top-level testbench captures enough samples to fill the FIFO.

### What was not tested

The listening tests through the audio jack were not done. The only earphones available had a
4-pole plug, which is silent in the board's mono 3-pole jack. The testbench checks the audio pin
(open drain, PWM toggling, enable, mute during tests), but the delta-sigma output mode (SW7) was
never exercised.

## Board controls

|Control|Function|
|-|-|
|SW1, SW0|filter bank: 0 bypass, 1 low-pass 1 kHz, 2 high-pass 2 kHz, 3 band-pass 0.4 to 3.4 kHz|
|SW8|31-tap parallel filter (the ASIC core); overrides SW1 and SW0|
|SW5 to SW2|digital gain 2^g, g = 0 to 15 (0 to 90 dB)|
|SW6|PDM sampling half: down = end of the high phase, up = low phase|
|SW7|output: down = PWM at 97.7 kHz, up = first-order delta-sigma|
|SW15|audio amplifier on; leave it off until the gain is set|
|BTNC|clears the red error LED|
|CPU\_RESET|restarts the design|
|LD15 to LD0|level meter, 6 dB per LED; LD15 means clipping|
|LED16|green blink when running, red after a lost sample or a UART error|
|LED17|blue during a UART test or capture|
|7-segment|`b<bank> G<gain> <H/L><P/d>`, and `tESt-` during a UART test|

## UART protocol (1 Mbaud, 8N1, little-endian)

|Host sends|FPGA returns|
|-|-|
|`P`|`A F <major> <minor>` (firmware 1.1)|
|`S`|`SW\[15:8] SW\[7:0] FLAGS` (bit 0 test, 1 framing error now, 2 sticky error, 3 capture)|
|`T bank nlo nhi` + n 3-byte samples|n 3-byte outputs of the selected filter (bank 0 to 4); the delay line is cleared first|
|`D bank gain nlo nhi` + n PDM bytes (LSB first)|floor(8n/50) 2-byte outputs of the whole chain|
|`C`|16 384 live 2-byte output samples (0.33 s)|

`host/af\_host.py` speaks this protocol. With `--sim` it talks to a software copy of the board
instead, which is how the host side was tested before the board arrived.

## Design numbers

|||
|-|-|
|Audio rate, end-to-end delay|50 kHz, 5.43 ms|
|CIC droop at 16 kHz|1.47 dB, flattened to 0.006 dB ripple by the compensation filter; 95.1 dB alias rejection|
|Stopband of the 511-tap banks (18-bit coefficients, scaled per bank)|low-pass 84.3 dB, high-pass 77.2 dB, band-pass 79.3 dB|
|Multiply-accumulate budget|517 of 2000 clocks per sample on one DSP48E1|

## Coding rules

Every RTL file follows four rules: synthesizable code only, no latches (a default for every
combinational signal and every `case`), combinational and sequential logic kept apart (`=` and
`<=`), and the same four sections in every module (ports, localparams and wires, combinational,
sequential). `tools/check\_rules.py` checks them, Yosys proves there is no latch, and Verilator
`-Wall` reports nothing.

## Folders

```
model/      params.py (all constants), design\_filters.py, golden.py (the bit-exact model), gen\_vectors.py, plots
rtl/        Verilog-2001: top\_nexys\_a7, pdm\_rx, cic\_decim, fir\_mac, dc\_block, fir\_par, audio\_chain,
            audio\_dac, uart, cmd\_ctrl, ui, sync2, generated coef\_rom\_\*.v, af\_params.vh, fir\_par\_coefs.vh
sim/        tb\_cic, tb\_fir, tb\_chain, tb\_top (Icarus), tb\_vivado.v (Vivado simulator), vectors/
fpga/       constraints/nexys\_a7.xdc, scripts/ for build, programming and the GUI project
build/      the bitstream (top\_nexys\_a7.bit), the flash image (.mcs) and the Vivado reports
host/       af\_host.py, the PC side of the UART port
asic/       LibreLane config, run\_sweep.py, plot\_layout.py, the ASIC-core testbench and results/
tools/      rule checker, test tones, voice recording and analysis, interactive plots
docs/       report/ (paper and its build script), photos/, plots/interactive\_plots.html
results/    every measurement, log and plot, simulation and board
```

