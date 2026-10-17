set root [file normalize [file join [file dirname [info script]] ..]]
set_param general.maxThreads 4
set proj_name bosio_out_system_proj
set proj_dir $root/build/vivado
file copy -force $root/results/timing.rpt $root/results/timing_first.rpt
open_checkpoint $proj_dir/$proj_name.runs/impl_1/bosio_out_system_wrapper_routed.dcp
source $root/scripts/correct_clock.tcl
phys_opt_design -directive AggressiveExplore
route_design -directive Explore
source $root/scripts/validate_hdmi_io.tcl
report_utilization -file $root/results/utilization.rpt
report_utilization -hierarchical -file $root/results/hierarchy.rpt
report_timing_summary -file $root/results/timing.rpt
report_drc -file $root/results/drc.rpt
report_methodology -file $root/results/methodology.rpt
report_bus_skew -file $root/results/bus_skew.rpt
report_io -file $root/results/io.rpt
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup]==0 || [llength $hold]==0} {error "Missing timing paths"}
if {[get_property SLACK $setup]<0 || [get_property SLACK $hold]<0} {error "Timing failed; do not deploy"}
write_checkpoint -force $root/results/validated_routed.dcp
write_bitstream -force $root/bitstream/bosio_output_projection_transform.bit
file copy -force $proj_dir/$proj_name.gen/sources_1/bd/bosio_out_system/hw_handoff/bosio_out_system.hwh $root/bitstream/bosio_output_projection_transform.hwh
puts "BOSIO_OUTPUT_PROJECTION_BUILD_PASS"
exit
