# Non-project Vivado build: RTL -> bitstream + every report the paper needs.
#
#   cd fpga-audio-filter
#   vivado -mode batch -source fpga/scripts/build.tcl                            (Nexys A7-50T, default)
#   vivado -mode batch -source fpga/scripts/build.tcl -tclargs xc7a100tcsg324-1   (Nexys A7-100T)
#
# Outputs in build/: top_nexys_a7.bit, .mcs (QSPI flash image), reports/*.rpt, checkpoints.
# Then:  python3 fpga/scripts/parse_reports.py   -> results/fpga_results.json + report macros

set part xc7a50ticsg324-1L
if {[llength $argv] > 0} { set part [lindex $argv 0] }

set root  [file normalize [file join [file dirname [info script]] .. ..]]
set build [file join $root build]
set rpt   [file join $build reports]
file mkdir $build $rpt
cd $build

puts "== part $part, root $root"
set_part $part
read_verilog [glob [file join $root rtl *.v]]
read_xdc [file join $root fpga constraints nexys_a7.xdc]

# ---------------------------------------------------------------- synthesis
synth_design -top top_nexys_a7 -part $part -include_dirs [file join $root rtl] \
    -flatten_hierarchy rebuilt -directive Default
write_checkpoint -force post_synth.dcp
report_utilization -file [file join $rpt utilization_synth.rpt]
report_utilization -hierarchical -file [file join $rpt utilization_synth_hier.rpt]

# ---------------------------------------------------------------- implementation
opt_design
place_design -directive Explore
phys_opt_design
route_design -directive Explore
write_checkpoint -force post_route.dcp

report_timing_summary -max_paths 20 -report_unconstrained -file [file join $rpt timing_summary.rpt]
report_timing -sort_by group -max_paths 10 -path_type full -file [file join $rpt timing_paths.rpt]
report_utilization -file [file join $rpt utilization.rpt]
report_utilization -hierarchical -file [file join $rpt utilization_hier.rpt]
report_power -file [file join $rpt power.rpt]
report_drc -file [file join $rpt drc.rpt]
report_methodology -file [file join $rpt methodology.rpt]
report_clock_utilization -file [file join $rpt clock_utilization.rpt]
report_io -file [file join $rpt io.rpt]

# fail loudly if timing is not met
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "== WNS = $wns ns, WHS = $whs ns"
set fh [open [file join $rpt slack.txt] w]
puts $fh "WNS $wns"
puts $fh "WHS $whs"
close $fh
if {$wns < 0 || $whs < 0} { puts "!! TIMING NOT MET"; }

# ---------------------------------------------------------------- bitstream + flash image
write_bitstream -force top_nexys_a7.bit
write_cfgmem -force -format mcs -size 16 -interface SPIx4 \
    -loadbit "up 0x00000000 top_nexys_a7.bit" -file top_nexys_a7.mcs
puts "== done: [file join $build top_nexys_a7.bit]"
