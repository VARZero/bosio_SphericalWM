# ============================================================================
# Vivado 2020.2 IP Packaging Script: Bosio 3DoF Display Output Core
# ============================================================================

set ip_name "bosio_output_core"
set ip_version "1.0"
set ip_vendor "varzero.org"
set ip_library "user"
set ip_display_name "Bosio 3DoF Display Output Core"
set ip_description "Bosio 3DoF Icosahedral Framebuffer Display Output Engine with Sensor Hub Stream & AXI-Lite Control"

set root_dir [file normalize [file join [file dirname [info script]] "../.."]]
set hdl_dir [file join $root_dir "hw" "ip_repo" "bosio_output_core_1.0" "hdl"]
set ip_repo_dir [file join $root_dir "hw" "ip_repo" "bosio_output_core_1.0"]

puts "==> Creating in-memory project for IP packaging..."
create_project -in_memory -part xc7z020clg400-1

puts "==> Adding HDL source files from $hdl_dir..."
add_files [glob [file join $hdl_dir "*.v"]]
update_compile_order -fileset sources_1

puts "==> Packaging IP to $ip_repo_dir..."
ipx::package_project -root_dir $ip_repo_dir -vendor $ip_vendor -library $ip_library -taxonomy /Display -import_files -force

set core [ipx::current_core]

set_property name $ip_name $core
set_property version $ip_version $core
set_property core_revision 24 $core
set_property display_name $ip_display_name $core
set_property description $ip_description $core
set_property vendor_display_name "VARZero Lab" $core

# Associate Clock with all bus interfaces
set aclk_intf [ipx::get_bus_interfaces aclk -of_objects $core]
if {$aclk_intf != ""} {
    set bus_param [ipx::get_bus_parameters ASSOCIATED_BUSIF -of_objects $aclk_intf]
    if {$bus_param != ""} {
        set_property value "s_axi_lite:s_axis_sensor:m_axi:m_axis_video" $bus_param
    }
    set rst_param [ipx::get_bus_parameters ASSOCIATED_RESET -of_objects $aclk_intf]
    if {$rst_param != ""} {
        set_property value "aresetn" $rst_param
    }
}

ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::save_core $core

puts "==> Bosio 3DoF Output Core Successfully Packaged at: $ip_repo_dir"
exit 0
