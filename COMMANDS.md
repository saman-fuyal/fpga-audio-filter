# Commands

Every command used in this project, in the order you would run them. Windows commands go in
Command Prompt, opened in the project folder:

```bat
cd /d C:\Users\ACER\Desktop\fpga-audio-filter\fpga-audio-filter
```

The board is on COM6 here. Check Device Manager, under Ports, if yours differs.

## 1. One-time setup on Windows

```bat
py -m pip install numpy scipy matplotlib pyserial pillow pypdfium2
```
Python packages for the model, the host tool and the plots.

Icarus Verilog 12 comes from bleyer.org/icarus (tick "add to PATH"). Vivado 2018.2 is expected in
`C:\Xilinx\Vivado\2018.2`. Microsoft Word is needed to export the paper as PDF.

```bat
iverilog -V
```
Confirms Icarus is on the PATH.

## 2. Model and simulation

```bat
py run_sim.py --model --asic
```
Redesigns the filters, regenerates the ROMs and test vectors, and runs every testbench. Ends with
ALL PASS after about 25 minutes.

```bat
py run_sim.py
```
Runs the testbenches without regenerating anything.

```bat
py run_sim.py --quick
```
Same, with a shorter top-level run.

```bat
py run_sim.py --only tb_fir
```
Runs one testbench.

```bat
py tools\check_rules.py
```
Checks the four RTL coding rules (needs Yosys; on Windows run it from WSL if Yosys is missing).

## 3. FPGA build and programming

```bat
build.bat
```
Builds the bitstream and the flash image into `build\` and writes `results\fpga_results.json`
(about 15 minutes, board not needed).

```bat
program.bat
```
Loads the bitstream into the FPGA over USB. It is lost at power-off.

```bat
program.bat flash
```
Writes the design into the QSPI flash, so the board starts it by itself at power-on (jumper JP1
on QSPI).

```bat
project.bat
```
Creates and opens a Vivado GUI project, for schematics and the Vivado simulator.

```bat
py fpga\scripts\parse_reports.py
```
Reads the Vivado reports again into `results\fpga_results.json`.

## 4. Board tests

```bat
py host\af_host.py --port COM6 ping
```
Checks that the board answers (prints firmware v1.1).

```bat
py host\af_host.py --port COM6 status
```
Shows the switch settings and the error flags.

```bat
py host\af_host.py --port COM6 selftest
```
Bit-exact self-test of all filters and the whole chain on the board.

```bat
py host\af_host.py --port COM6 all
```
Self-test, then the measured frequency response of every bank.

```bat
py host\af_host.py --port COM6 freqresp --bank 3 --points 60
```
Measured response of one bank.

```bat
py host\af_host.py --port COM6 watchdog
```
Sends two unfinished commands and checks that the board recovers.

```bat
py host\af_host.py --sim selftest
```
The same self-test against a software copy of the board, no board needed.

```bat
py tools\make_test_tones.py
```
Writes pure sine WAV files (200 Hz to 8 kHz) to `tools\test_tones\`.

```bat
py host\af_host.py --port COM6 capture --tag d4b_laptop
```
Records 0.33 s of live output and reports level, SNR, THD and SINAD. Play
`sine_1000Hz.wav` from the laptop speaker 10 cm from the microphone, bank 0, gain 0.

```bat
py host\af_host.py --port COM6 capture --tag d6_b1_3k --freq 3000
```
Measures the level of a played tone after a filter. Take one capture in bank 0 and one in the
filtering bank, then compare `tone_dbfs`.

```bat
py host\af_host.py --port COM6 capture --wav results\voice_b0.wav --tag voice_b0
```
Records live output as a WAV file.

```bat
tools\record_voice.bat
```
Records your voice through each bank in turn and plays it back (gain 4, SW15 down).

```bat
py tools\analyze_voice.py
```
Measures what each filter did to the voice recordings: `results\hw_voice.txt` and `.png`.

## 5. Paper and plots

```bat
py docs\report\build_paper.py
```
Builds `docs\report\paper.docx` and exports `paper.pdf` through Word. Close Word first. It should
print "PDF exported by Word as PDF/A: every font embedded".

```bat
py tools\make_interactive_plots.py
start docs\plots\interactive_plots.html
```
Builds and opens the interactive plots (needs internet the first time).

```bat
py docs\report\prep_schematic.py C:/Users/ACER/Desktop/rtl_top.pdf
```
Turns a Vivado schematic PDF into a black-on-white PNG in `docs\report\figs\user\`.

## 6. SKY130 chip flow (Ubuntu in WSL)

One-time setup, in PowerShell as administrator:

```powershell
wsl --install -d Ubuntu
wsl -d Ubuntu -u root passwd saman
wsl --list --verbose
```
Installs Ubuntu, sets the Linux password, and checks that Ubuntu runs under WSL 2.

In Ubuntu:

```bash
sudo apt-get install -y curl
curl --proto '=https' --tlsv1.2 -fsSL https://artifacts.nixos.org/nix-installer | sh -s -- install --no-confirm --extra-conf "
    extra-substituters = https://nix-cache.fossi-foundation.org
    extra-trusted-public-keys = nix-cache.fossi-foundation.org:3+K59iFwXqKsL7BNu6Guy0v+uTlwsxYQxjspXzqLYQs=
    extra-experimental-features = nix-command flakes
"
```
Installs Nix with LibreLane's download cache. Close and reopen Ubuntu afterwards.

```bash
nix config show | grep -E "substituters|experimental"
```
Checks that the cache and flakes are on.

```bash
git clone https://github.com/librelane/librelane ~/librelane
cd ~/librelane
nix-shell
librelane --smoke-test
```
Gets LibreLane, enters its environment (10 to 30 minutes the first time) and tests it.

Every later session starts with:

```bash
cd ~/librelane && nix-shell
```

Inside the nix-shell:

```bash
cp -r /mnt/c/Users/ACER/Desktop/fpga-audio-filter/fpga-audio-filter ~/fpga-audio-filter
cd ~/fpga-audio-filter
```
Copies the project into Linux. Later changes on Windows are copied file by file with `cp`.

```bash
python3 asic/run_sweep.py
```
Routes the unpipelined core at 25 ns and the pipelined core at 12 ns (about 30 minutes each) and
prints the shortest period of each.

```bash
python3 asic/run_sweep.py --runs 0:16,1:7
```
Confirmation runs at the shortest periods. Use the numbers the previous command printed.

```bash
python3 asic/run_sweep.py --collect-only
```
Collects the finished runs into `asic/results/sweep.json` and `sweep.csv`.

```bash
ls -t ~/fpga-audio-filter/asic/runs/*/ | head -3
```
Shows which step a running flow has reached (in a second Ubuntu window).

```bash
cp -r ~/fpga-audio-filter/asic/results /mnt/c/Users/ACER/Desktop/fpga-audio-filter/fpga-audio-filter/asic/
cp ~/fpga-audio-filter/asic/runs/p1_t7p0_u45/final/def/fir_par.def /mnt/c/Users/ACER/Desktop/fpga-audio-filter/fpga-audio-filter/asic/results/
cp ~/fpga-audio-filter/asic/runs/p1_t7p0_u45/final/gds/fir_par.gds /mnt/c/Users/ACER/Desktop/fpga-audio-filter/fpga-audio-filter/asic/results/
```
Copies the results, the routed layout (DEF) and the chip layout (GDS) back to Windows.

Back on Windows:

```bat
py asic\run_sweep.py --plot-only
py asic\plot_layout.py asic\results\fir_par.def
```
Draws the slack and area plot, and the layout figure used as Fig. 9 of the paper.

## 7. Linux shortcuts

```bash
make model sim lint synth asic-sim asic-est report
```
The same flow through the Makefile, where Icarus, Yosys and Verilator are installed.
