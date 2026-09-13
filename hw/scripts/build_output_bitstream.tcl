# ============================================================================
# Vivado 2020.2 Batch Build Script: Bosio 3DoF Output Core Bitstream
# ============================================================================

set_param general.maxThreads 4
set_param synth.maxThreads 1

set root_dir [file normalize [file join [file dirname [info script]] "../.."]]
set create_script [file join $root_dir "hw" "scripts" "create_output_system.tcl"]

# 1. Create Project and Block Design
source $create_script

# 2. Launch Synthesis, Implementation, and Write Bitstream
puts "==> Starting Synthesis & Implementation (Jobs: 4)..."
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    puts "ERROR: Implementation failed!"
    exit 1
}

# 3. Export Bitstream & Hardware Handoff
set bit_dir [file join $root_dir "sw" "bitstream"]
file mkdir $bit_dir

set bit_file [file join $proj_dir "$proj_name.runs" "impl_1" "bosio_out_system_wrapper.bit"]
set hwh_file [file join $proj_dir "$proj_name.gen" "sources_1" "bd" "bosio_out_system" "hw_handoff" "bosio_out_system.hwh"]

if {[file exists $bit_file]} {
    file copy -force $bit_file [file join $bit_dir "bosio_output_disp.bit"]
    puts "==> Bitstream successfully saved to [file join $bit_dir "bosio_output_disp.bit"]"
}
if {[file exists $hwh_file]} {
    file copy -force $hwh_file [file join $bit_dir "bosio_output_disp.hwh"]
    puts "==> HWH successfully saved to [file join $bit_dir "bosio_output_disp.hwh"]"
}

puts "=========================================================================="
puts "  BOSIO 3DOF OUTPUT BITSTREAM GENERATION COMPLETED SUCCESSFULLY!"
puts "=========================================================================="
exit 0
