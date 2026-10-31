# Create a Vivado GUI project (if you prefer clicking "Generate Bitstream").
#   vivado -mode batch -source fpga/scripts/create_project.tcl
#   then: vivado vivado_proj/audio_filter.xpr
set part xc7a50ticsg324-1L    ;# Nexys A7-50T (use xc7a100tcsg324-1 for the 100T)
if {[llength $argv] > 0} { set part [lindex $argv 0] }
set root [file normalize [file join [file dirname [info script]] .. ..]]

create_project -force audio_filter [file join $root vivado_proj] -part $part
set_property target_language Verilog [current_project]
add_files [glob [file join $root rtl *.v]]
add_files [file join $root rtl af_params.vh] [file join $root rtl fir_par_coefs.vh]
set_property file_type {Verilog Header} [get_files *.vh]
add_files -fileset constrs_1 [file join $root fpga constraints nexys_a7.xdc]
set_property top top_nexys_a7 [current_fileset]
set_property include_dirs [file join $root rtl] [current_fileset]

# simulation: plain-Verilog waveform testbench (runs in Vivado 2018.2 xsim as-is).
# In the GUI: Run Simulation -> Run Behavioral Simulation, then type  run 6 ms
add_files -fileset sim_1 [file join $root sim tb_vivado.v]
set_property top tb_vivado [get_filesets sim_1]
set_property -name {xsim.simulate.runtime} -value {6ms} -objects [get_filesets sim_1]
set_property include_dirs [file join $root rtl] [get_filesets sim_1]

set_property STEPS.PLACE_DESIGN.ARGS.DIRECTIVE Explore [get_runs impl_1]
set_property STEPS.ROUTE_DESIGN.ARGS.DIRECTIVE Explore [get_runs impl_1]
puts "== project created: [file join $root vivado_proj audio_filter.xpr]"
