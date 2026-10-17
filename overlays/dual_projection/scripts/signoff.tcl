set root [file normalize [file join [file dirname [info script]] ..]]
set_param general.maxThreads 4
open_checkpoint $root/build/vivado/bosio_out_system_proj.runs/impl_1/bosio_out_system_wrapper_routed.dcp
source $root/scripts/correct_clock.tcl
source $root/scripts/validate_hdmi_io.tcl
report_timing_summary -report_unconstrained -file $root/results/timing.rpt
report_bus_skew -file $root/results/bus_skew.rpt
report_methodology -file $root/results/methodology.rpt
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup]==0 || [llength $hold]==0} {error "Missing timing paths"}
if {[get_property SLACK $setup]<0 || [get_property SLACK $hold]<0} {error "Corrected timing failed; do not deploy"}
write_checkpoint -force $root/results/validated_routed.dcp
puts "BOSIO_CORRECTED_CLOCK_SIGNOFF_PASS"
exit
