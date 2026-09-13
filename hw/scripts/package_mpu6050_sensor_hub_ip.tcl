set root [file normalize [file join [file dirname [info script]] ../..]]
set repo [file join $root hw ip_repo bosio_sensor_hub_mpu6050_1.0]

create_project -in_memory -part xc7z020clg400-1
add_files [glob [file join $repo hdl *.v]]
set_property top bosio_sensor_hub_mpu6050 [current_fileset]
update_compile_order -fileset sources_1

ipx::package_project -root_dir $repo -vendor varzero.org -library user \
    -taxonomy /Sensor -import_files -force
set core [ipx::current_core]
set_property name bosio_sensor_hub_mpu6050 $core
set_property version 1.0 $core
set_property core_revision 1 $core
set_property display_name {Bosio GY-521 MPU6050 Sensor Hub} $core
set_property description {Direct I2C MPU6050 reader and 96-bit mrad AXI4-Stream pose source} $core
set_property vendor_display_name {VARZero Lab} $core
ipx::associate_bus_interfaces -busif m_axis_sensor -clock clk $core
ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::save_core $core
puts {BOSIO_MPU6050_SENSOR_HUB_PACKAGED}
exit 0
