# Real-time audio filter on Nexys A7 -- simulation / model / report targets
#
#   make model      design filters, write ROM modules + af_params.vh, test vectors
#   make sim        run every self-checking testbench (Icarus Verilog), write results/sim_summary.json
#   make lint       Verilator lint (if installed) + Yosys parse check
#   make synth      Yosys synth_xilinx resource estimate (no Vivado needed)
#   make asic-sim   Project 3 core testbench;  make asic-est  Yosys+ABC SKY130 area/delay estimate
#   make report     build docs/report/paper.docx (IEEE Word template)
#   make all        everything above
#   make fpga       Vivado bitstream (needs Vivado on PATH)
#   make program    program the board over JTAG
#
SHELL   := /bin/bash
IVERILOG ?= iverilog
VVP      ?= vvp
YOSYS    ?= yosys
PY       ?= python3
RTL      := $(wildcard rtl/*.v)
TBS      := tb_cic tb_fir tb_chain tb_top

.PHONY: all model sim lint synth asic-sim asic-est report fpga program clean $(TBS)

all: model sim lint synth asic-sim asic-est report

model:
	$(PY) model/design_filters.py > results/design_filters.log
	$(PY) model/gen_vectors.py
	$(PY) asic/design_asic_fir.py > /dev/null

sim/%.vvp: sim/%.sv $(RTL)
	cd sim && $(IVERILOG) -g2012 -I ../rtl -s $* -o $*.vvp $*.sv $(addprefix ../,$(RTL))

$(TBS): %: sim/%.vvp
	cd sim && $(VVP) -n $*.vvp | tee ../results/$*.log | grep -E "PASS|FAIL|MISMATCH|ERROR|  "

sim: $(TBS)
	$(PY) model/summarize_sim.py

lint:
	@if command -v verilator >/dev/null; then \
	  verilator --lint-only -Wall -Wno-DECLFILENAME -Irtl --top-module top_nexys_a7 $(RTL) && echo "verilator lint: clean"; \
	else echo "verilator not installed - skipped"; fi
	$(YOSYS) -q -p "read_verilog -Irtl $(RTL); hierarchy -check -top top_nexys_a7; proc; check -assert" && echo "yosys check: clean"

synth:
	mkdir -p build_yosys
	cd build_yosys && $(YOSYS) -l ../results/yosys_xilinx.log -s ../fpga/scripts/yosys_xilinx.ys > /dev/null
	$(PY) fpga/scripts/parse_yosys.py

asic-sim:
	cd asic/sim && $(IVERILOG) -g2012 -I ../../rtl -o tb_fir_par.vvp tb_fir_par.sv ../../rtl/fir_par.v && $(VVP) -n tb_fir_par.vvp | tee ../results/tb_fir_par.log | grep -E "PASS|FAIL"

asic-est:
	$(PY) asic/estimate_sky130.py

report:
	$(PY) docs/report/build_paper.py

fpga:
	vivado -mode batch -nojournal -log build/vivado.log -source fpga/scripts/build.tcl
	$(PY) fpga/scripts/parse_reports.py

program:
	vivado -mode batch -nojournal -nolog -source fpga/scripts/program.tcl

clean:
	rm -rf sim/*.vvp sim/*.vcd asic/sim/*.vvp build_yosys build vivado_proj .Xil
