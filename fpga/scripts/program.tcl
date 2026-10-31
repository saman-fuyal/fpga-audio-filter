# Program the Nexys A7 over USB-JTAG.
#   vivado -mode batch -source fpga/scripts/program.tcl                 (volatile, SRAM)
#   vivado -mode batch -source fpga/scripts/program.tcl -tclargs flash  (QSPI flash, survives power-off)
set root  [file normalize [file join [file dirname [info script]] .. ..]]
set bit   [file join $root build top_nexys_a7.bit]
set mcs   [file join $root build top_nexys_a7.mcs]
set target sram
if {[llength $argv] > 0} { set target [lindex $argv 0] }

# Vivado 2018.2 calls these open_hw / close_hw; 2020.1 and later renamed them open_hw_manager /
# close_hw_manager. Use whichever this Vivado has.
if {[llength [info commands open_hw_manager]] > 0} { open_hw_manager } else { open_hw }
connect_hw_server
# A freshly started hw_server needs a moment to find the board's JTAG cable: retry for about 10 s.
set targets {}
for {set i 0} {$i < 10} {incr i} {
    catch {refresh_hw_server -quiet}
    set targets [get_hw_targets -quiet]
    if {[llength $targets] > 0} { break }
    after 1000
}
if {[llength $targets] == 0} {
    puts "== ERROR: hw_server sees no JTAG cable."
    puts "== Board powered on, cable in PROG/UART, Vivado GUI closed? If yes, the Digilent JTAG"
    puts "== driver is missing: run C:/Xilinx/Vivado/2018.2/data/xicom/cable_drivers/nt64/digilent/install_digilent.exe"
    puts "== as administrator, then unplug and replug the board."
    exit 1
}
puts "== JTAG target: [lindex $targets 0]"
current_hw_target [lindex $targets 0]
open_hw_target
set dev [lindex [get_hw_devices xc7a*] 0]
if {$dev eq ""} { error "no Artix-7 found on the USB cable: check power, cable and drivers" }
current_hw_device $dev
refresh_hw_device -update_hw_probes false $dev

if {$target eq "flash"} {
    # Nexys A7 QSPI flash (Spansion/Infineon S25FL128S)
    create_hw_cfgmem -hw_device $dev -mem_dev [lindex [get_cfgmem_parts {s25fl128sxxxxxx0-spi-x1_x2_x4}] 0]
    set cm [get_property PROGRAM.HW_CFGMEM $dev]
    set_property PROGRAM.ADDRESS_RANGE {use_file} $cm
    set_property PROGRAM.FILES [list $mcs] $cm
    set_property PROGRAM.BLANK_CHECK 0 $cm
    set_property PROGRAM.ERASE 1 $cm
    set_property PROGRAM.CFG_PROGRAM 1 $cm
    set_property PROGRAM.VERIFY 1 $cm
    create_hw_bitstream -hw_device $dev [get_property PROGRAM.HW_CFGMEM_BITFILE $dev]
    program_hw_devices $dev
    program_hw_cfgmem -hw_cfgmem $cm
    boot_hw_device $dev
} else {
    set_property PROGRAM.FILE $bit $dev
    program_hw_devices $dev
}
puts "== programmed ($target)"
if {[llength [info commands close_hw_manager]] > 0} { close_hw_manager } else { close_hw }
