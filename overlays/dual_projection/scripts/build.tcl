set root [file normalize [file join [file dirname [info script]] ..]]
file mkdir $root/results
file mkdir $root/bitstream
set_param general.maxThreads 4
set_param synth.maxThreads 1
source $root/scripts/create_system.tcl
set hdmi_check $root/scripts/validate_hdmi_io.tcl
add_files -fileset utils_1 -norecurse $hdmi_check
set_property STEPS.WRITE_BITSTREAM.TCL.PRE $hdmi_check [get_runs impl_1]
generate_target all [get_files bosio_out_system.bd]
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Implementation failed"}
open_run impl_1
source $root/scripts/correct_clock.tcl
source $hdmi_check
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
file copy -force $proj_dir/$proj_name.runs/impl_1/bosio_out_system_wrapper.bit $root/bitstream/bosio_output_projection_dual.bit
file copy -force $proj_dir/$proj_name.gen/sources_1/bd/bosio_out_system/hw_handoff/bosio_out_system.hwh $root/bitstream/bosio_output_projection_dual.hwh
write_bd_tcl -force $root/results/recreate_bd.tcl
puts "BOSIO_OUTPUT_PROJECTION_BUILD_PASS"
exit
