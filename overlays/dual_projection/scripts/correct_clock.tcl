# Clock Wizard's IP XDC creates an unnecessary primary clock at its input.
# The input is driven by PS FCLK0, which already has a 10 ns primary clock.
# Remove only that downstream redefinition and let generated clocks propagate
# from the real PS source; preserve all other IP timing/CDC constraints.
set duplicate_name bosio_out_system_i/clk_wiz_0/inst/clk_in1
set duplicate [get_clocks -quiet $duplicate_name]
if {[llength $duplicate]} {
    # Vivado has no per-clock delete command. Export ALL timing constraints,
    # remove only the named redundant clock (and its input-jitter setting),
    # then reload the complete timing constraint set on the same routed netlist.
    write_xdc -force -type timing $root/results/timing_original.xdc
    set input [open $root/results/timing_original.xdc r]
    set original [read $input]
    close $input
    set filtered {}
    set removed 0
    set in_wizard 0
    foreach line [split $original "\n"] {
        if {[regexp {^current_instance\s} $line]} {
            set in_wizard [expr {$line eq "current_instance bosio_out_system_i/clk_wiz_0/inst"}]
        }
        if {$in_wizard && [string first clk_in1 $line]>=0} {
            if {[regexp {^\s*create_clock\s} $line]} {
                incr removed
                continue
            }
            if {[regexp {^\s*set_input_jitter\s} $line]} {continue}
            error "Unexpected reference to duplicate clock; inspect before changing: $line"
        }
        lappend filtered $line
    }
    if {$removed!=1} {error "Expected exactly one duplicate clock definition"}
    set output [open $root/results/timing_corrected.xdc w]
    puts $output [join $filtered "\n"]
    close $output
    reset_timing
    read_xdc $root/results/timing_corrected.xdc
}
set source_clock [get_clocks clk_fpga_0]
if {[llength $source_clock] != 1} {error "Expected one PS FCLK0 clock"}
if {abs([get_property PERIOD $source_clock]-10.0)>0.001} {error "PS FCLK0 must be 100 MHz"}
set axi_clock [get_clocks -include_generated_clocks -of_objects [get_pins -hier *clk_wiz_0/clk_out1]]
set video_clock [get_clocks -include_generated_clocks -of_objects [get_pins -hier *clk_wiz_0/clk_out2]]
if {![llength $axi_clock] || ![llength $video_clock]} {error "Clock propagation failed"}
set_clock_groups -asynchronous -group $axi_clock -group $video_clock
puts "BOSIO_PS_CLOCK_SOURCE_VALIDATED"
