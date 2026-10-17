# ============================================================================
# Vivado 2020.2 Block Design Script: Bosio 3DoF Display Output System
# Architecture:
#   - Bosio 3DoF Output Core (bosio_output_core)
#   - Direct RTL GY-521 / MPU6050 sensor hub on Pmod B
#   - Four PYNQ-Z2 push buttons exposed as an independent AXI GPIO input
#   - AXI-Lite Software Control via Zynq PS
#   - AXI Master DDR Texture Fetch via Zynq HP0
#   - VTC + Video Out + rgb2dvi driving 720p60 HDMI PHY
# ============================================================================

set proj_name "bosio_out_system_proj"
set root_dir [file normalize [file join [file dirname [info script]] ".."]]
set proj_dir [file join $root_dir "build" "vivado"]
set wm_root [file normalize [file join $root_dir .. ..]]
set ip_repo [file join $wm_root hw ip_repo]
set xdc_file [file join $root_dir "hw" "constrs" "pynq_z2_hdmi.xdc"]
set part "xc7z020clg400-1"

puts "==> Creating Vivado Project: $proj_name in $proj_dir..."
file mkdir $proj_dir
create_project -force $proj_name $proj_dir -part $part

# Add Constraints
if {[file exists $xdc_file]} {
    add_files -fileset constrs_1 -norecurse $xdc_file
}

# Add IP Repositories
set_property ip_repo_paths [list $ip_repo [file join $ip_repo bosio_projection_core build hls solution impl ip]] [current_project]
update_ip_catalog

# Create Block Design
create_bd_design "bosio_out_system"

# 1. Processing System 7 (Zynq PS)
puts "==> Adding Zynq Processing System (PS7)..."
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7_0
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {make_external "FIXED_IO, DDR" apply_board_preset "0" Master "Disable" Slave "Disable" }  [get_bd_cells ps7_0]

source [file join $root_dir scripts ps7_config.tcl]

# Configure PS7: Enable HP0 (Read port for Framebuffer) and GP0 (Control)
set_property -dict [list \
    CONFIG.PCW_USE_S_AXI_HP0 {1} \
    CONFIG.PCW_USE_S_AXI_HP1 {1} \
    CONFIG.PCW_USE_S_AXI_HP2 {1} \
    CONFIG.PCW_USE_S_AXI_HP3 {1} \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} \
] [get_bd_cells ps7_0]

# 2. Reset Generators (100MHz for AXI, 74.25MHz for Video Pixel Clock)
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_ps7_100M
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_ps7_74M

# 3. Clocking Wizard (100MHz AXI, 74.25MHz Pixel)
create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 clk_wiz_0
set_property -dict [list \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {100.000} \
    CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {74.250} \
    CONFIG.CLKOUT2_USED {true} \
    CONFIG.USE_LOCKED {false} \
    CONFIG.USE_RESET {false} \
] [get_bd_cells clk_wiz_0]

# 4. Constants
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 const_vcc
set_property -dict [list CONFIG.CONST_VAL {1}] [get_bd_cells const_vcc]

# 5. Bosio 3DoF Display Output Core
puts "==> Instantiating Bosio 3DoF Output Core..."
create_bd_cell -type ip -vlnv varzero.org:user:bosio_output_core:1.0 output_core_0

# 6. Direct GY-521 / MPU6050 Sensor Hub
puts "==> Instantiating direct GY-521 MPU6050 Sensor Hub..."
create_bd_cell -type ip -vlnv varzero.org:user:bosio_sensor_hub_mpu6050:1.0 sensor_hub_0
connect_bd_net [get_bd_pins const_vcc/dout] [get_bd_pins sensor_hub_0/enable]
make_bd_intf_pins_external [get_bd_intf_pins sensor_hub_0/iic] -name "pmodb_iic"

# 7. Board push buttons. This is a standard Linux-visible AXI GPIO peripheral;
# it does not depend on the BOSIO output core or sensor hub RTL.
puts "==> Instantiating four-bit board button GPIO..."
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 buttons_gpio
set_property -dict [list \
    CONFIG.C_GPIO_WIDTH {4} \
    CONFIG.C_ALL_INPUTS {1} \
    CONFIG.C_INTERRUPT_PRESENT {0} \
] [get_bd_cells buttons_gpio]
make_bd_pins_external [get_bd_pins buttons_gpio/gpio_io_i] -name "buttons"

# 8. Video Timing Controller (VTC) for 720p60
create_bd_cell -type ip -vlnv xilinx.com:ip:v_tc:6.2 vtc_0
set_property -dict [list \
    CONFIG.HAS_AXI4_LITE {false} \
    CONFIG.enable_detection {false} \
    CONFIG.enable_generation {true} \
    CONFIG.GEN_F0_VBLANK_HEND {1280} \
    CONFIG.GEN_F0_VBLANK_HSTART {1280} \
    CONFIG.GEN_F0_VFRAME_SIZE {750} \
    CONFIG.GEN_F0_VSYNC_HEND {1280} \
    CONFIG.GEN_F0_VSYNC_HSTART {1280} \
    CONFIG.GEN_F0_VSYNC_VEND {729} \
    CONFIG.GEN_F0_VSYNC_VSTART {724} \
    CONFIG.GEN_HACTIVE_SIZE {1280} \
    CONFIG.GEN_HFRAME_SIZE {1650} \
    CONFIG.GEN_HSYNC_END {1430} \
    CONFIG.GEN_HSYNC_START {1390} \
    CONFIG.GEN_VACTIVE_SIZE {720} \
] [get_bd_cells vtc_0]

# 9. AXI4-Stream to Video Out: C_VTG_MASTER_SLAVE=1 means Master.
create_bd_cell -type ip -vlnv xilinx.com:ip:v_axi4s_vid_out:4.0 vid_out_0
set_property -dict [list \
    CONFIG.C_VTG_MASTER_SLAVE {1} \
    CONFIG.C_HAS_ASYNC_CLK {1} \
    CONFIG.C_ADDR_WIDTH {13} \
    CONFIG.C_HYSTERESIS_LEVEL {2048} \
    CONFIG.C_SYNC_LOCK_THRESHOLD {4} \
] [get_bd_cells vid_out_0]

# 10. RGB to DVI / TMDS Transmitter
puts "==> Instantiating rgb2dvi HDMI TMDS Core..."
create_bd_cell -type ip -vlnv digilentinc.com:ip:rgb2dvi:1.4 rgb2dvi_0
set_property -dict [list \
    CONFIG.kClkRange {2} \
    CONFIG.kRstActiveHigh {false} \
    CONFIG.kGenerateSerialClk {true} \
] [get_bd_cells rgb2dvi_0]

# ----------------------------------------------------------------------------
# Connect Clocks and Resets
# ----------------------------------------------------------------------------
puts "==> Connecting Clocks & Resets..."
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins clk_wiz_0/clk_in1]

# 100MHz Domain
connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] [get_bd_pins ps7_0/M_AXI_GP0_ACLK]
connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] [get_bd_pins ps7_0/S_AXI_HP0_ACLK]
connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] [get_bd_pins rst_ps7_100M/slowest_sync_clk]
connect_bd_net [get_bd_pins ps7_0/FCLK_RESET0_N] [get_bd_pins rst_ps7_100M/ext_reset_in]

connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] [get_bd_pins output_core_0/aclk]
connect_bd_net [get_bd_pins rst_ps7_100M/peripheral_aresetn] [get_bd_pins output_core_0/aresetn]

connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] [get_bd_pins sensor_hub_0/clk]
connect_bd_net [get_bd_pins rst_ps7_100M/peripheral_aresetn] [get_bd_pins sensor_hub_0/rst_n]

connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] [get_bd_pins vid_out_0/aclk]
connect_bd_net [get_bd_pins rst_ps7_100M/peripheral_aresetn] [get_bd_pins vid_out_0/aresetn]

# 74.25MHz Domain (Pixel Clock)
connect_bd_net [get_bd_pins clk_wiz_0/clk_out2] [get_bd_pins rst_ps7_74M/slowest_sync_clk]
connect_bd_net [get_bd_pins ps7_0/FCLK_RESET0_N] [get_bd_pins rst_ps7_74M/ext_reset_in]

connect_bd_net [get_bd_pins clk_wiz_0/clk_out2] [get_bd_pins vtc_0/clk]
connect_bd_net [get_bd_pins rst_ps7_74M/peripheral_aresetn] [get_bd_pins vtc_0/resetn]

connect_bd_net [get_bd_pins clk_wiz_0/clk_out2] [get_bd_pins vid_out_0/vid_io_out_clk]

connect_bd_net [get_bd_pins clk_wiz_0/clk_out2] [get_bd_pins rgb2dvi_0/PixelClk]
connect_bd_net [get_bd_pins rst_ps7_74M/peripheral_aresetn] [get_bd_pins rgb2dvi_0/aRst_n]

# Video Timing Controller and Video Out Synchronization
connect_bd_net [get_bd_pins const_vcc/dout] [get_bd_pins vtc_0/clken]
connect_bd_net [get_bd_pins const_vcc/dout] [get_bd_pins vtc_0/gen_clken]
connect_bd_net [get_bd_pins const_vcc/dout] [get_bd_pins vid_out_0/aclken]
connect_bd_net [get_bd_pins const_vcc/dout] [get_bd_pins vid_out_0/vid_io_out_ce]

# ----------------------------------------------------------------------------
# Connect AXI Buses
# ----------------------------------------------------------------------------
puts "==> Connecting AXI-Lite Control Interface..."
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Master "/ps7_0/M_AXI_GP0" Clk "Auto" }  [get_bd_intf_pins output_core_0/s_axi_lite]

puts "==> Connecting independent board button GPIO..."
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Master "/ps7_0/M_AXI_GP0" Clk "Auto" } [get_bd_intf_pins buttons_gpio/S_AXI]
assign_bd_address -offset 0x41200000 -range 64K -target_address_space [get_bd_addr_spaces ps7_0/Data] [get_bd_addr_segs buttons_gpio/S_AXI/Reg] -force

puts "==> Connecting Framebuffer DMA AXI Master to Zynq HP0..."
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Master "/output_core_0/m_axi" Clk "Auto" }  [get_bd_intf_pins ps7_0/S_AXI_HP0]

# ----------------------------------------------------------------------------
# Connect Sensor Hub to Output Core
# ----------------------------------------------------------------------------
puts "==> Connecting Sensor Hub Stream to Output Core..."
connect_bd_intf_net [get_bd_intf_pins sensor_hub_0/m_axis_sensor] [get_bd_intf_pins output_core_0/s_axis_sensor]

# ----------------------------------------------------------------------------
# Connect Video Pipeline
# ----------------------------------------------------------------------------
# Complete-frame handoff: producer may stall; scanout repeats completed frames.
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_vdma:6.3 scanout_vdma
set_property -dict [list \
 CONFIG.c_include_sg {0} CONFIG.c_num_fstores {3} \
 CONFIG.c_include_mm2s {1} CONFIG.c_include_s2mm {1} \
 CONFIG.c_m_axi_mm2s_data_width {64} CONFIG.c_m_axi_s2mm_data_width {64} \
 CONFIG.c_m_axis_mm2s_tdata_width {24} CONFIG.c_s_axis_s2mm_tdata_width {24} \
 CONFIG.c_include_mm2s_dre {1} CONFIG.c_include_s2mm_dre {1} \
 CONFIG.c_mm2s_genlock_mode {3} CONFIG.c_s2mm_genlock_mode {2} \
 CONFIG.c_include_internal_genlock {1} \
 CONFIG.c_use_fsync {1} CONFIG.c_use_mm2s_fsync {0} CONFIG.c_use_s2mm_fsync {2} \
 CONFIG.c_mm2s_linebuffer_depth {8192} CONFIG.c_s2mm_linebuffer_depth {4096} \
 CONFIG.c_mm2s_max_burst_length {16} CONFIG.c_s2mm_max_burst_length {16} \
] [get_bd_cells scanout_vdma]
foreach pin {s_axi_lite_aclk m_axi_mm2s_aclk m_axi_s2mm_aclk m_axis_mm2s_aclk s_axis_s2mm_aclk} {
 connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] [get_bd_pins scanout_vdma/$pin]
}
connect_bd_net [get_bd_pins rst_ps7_100M/peripheral_aresetn] [get_bd_pins scanout_vdma/axi_resetn]
connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] [get_bd_pins ps7_0/S_AXI_HP3_ACLK]
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Master "/ps7_0/M_AXI_GP0" Clk "Auto"} [get_bd_intf_pins scanout_vdma/S_AXI_LITE]
assign_bd_address -offset 0x43000000 -range 64K -target_address_space [get_bd_addr_spaces ps7_0/Data] [get_bd_addr_segs scanout_vdma/S_AXI_LITE/Reg] -force
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 scanout_ddr
set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] [get_bd_cells scanout_ddr]
foreach pin {ACLK S00_ACLK S01_ACLK M00_ACLK} {connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] [get_bd_pins scanout_ddr/$pin]}
foreach pin {ARESETN S00_ARESETN S01_ARESETN M00_ARESETN} {connect_bd_net [get_bd_pins rst_ps7_100M/peripheral_aresetn] [get_bd_pins scanout_ddr/$pin]}
connect_bd_intf_net [get_bd_intf_pins scanout_vdma/M_AXI_MM2S] [get_bd_intf_pins scanout_ddr/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins scanout_vdma/M_AXI_S2MM] [get_bd_intf_pins scanout_ddr/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins scanout_ddr/M00_AXI] [get_bd_intf_pins ps7_0/S_AXI_HP3]

# Read-only video health and native frame counter, independent of producer FPS.
add_files -norecurse [file join $root_dir hw video_health.v]
create_bd_cell -type module -reference video_health video_health_0
connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] [get_bd_pins video_health_0/clk]
connect_bd_net [get_bd_pins rst_ps7_100M/peripheral_aresetn] [get_bd_pins video_health_0/rst_n]
foreach pin {locked underflow overflow status} {connect_bd_net [get_bd_pins vid_out_0/$pin] [get_bd_pins video_health_0/$pin]}
connect_bd_net [get_bd_pins vid_out_0/vid_vsync] [get_bd_pins video_health_0/vsync]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 video_health_gpio
set_property -dict [list CONFIG.C_GPIO_WIDTH {32} CONFIG.C_ALL_INPUTS {1} CONFIG.C_IS_DUAL {1} CONFIG.C_GPIO2_WIDTH {32} CONFIG.C_ALL_INPUTS_2 {1}] [get_bd_cells video_health_gpio]
connect_bd_net [get_bd_pins video_health_0/health] [get_bd_pins video_health_gpio/gpio_io_i]
connect_bd_net [get_bd_pins video_health_0/video_frames] [get_bd_pins video_health_gpio/gpio2_io_i]
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Master "/ps7_0/M_AXI_GP0" Clk "Auto"} [get_bd_intf_pins video_health_gpio/S_AXI]
assign_bd_address -offset 0x41210000 -range 64K -target_address_space [get_bd_addr_spaces ps7_0/Data] [get_bd_addr_segs video_health_gpio/S_AXI/Reg] -force

puts "==> Connecting Video Pipeline..."
connect_bd_intf_net [get_bd_intf_pins output_core_0/m_axis_video] [get_bd_intf_pins scanout_vdma/S_AXIS_S2MM]
connect_bd_intf_net [get_bd_intf_pins scanout_vdma/M_AXIS_MM2S] [get_bd_intf_pins vid_out_0/video_in]
connect_bd_intf_net [get_bd_intf_pins vtc_0/vtiming_out] [get_bd_intf_pins vid_out_0/vtiming_in]

# Connect vid_out signals to rgb2dvi
connect_bd_net [get_bd_pins vid_out_0/vid_data] [get_bd_pins rgb2dvi_0/vid_pData]
connect_bd_net [get_bd_pins vid_out_0/vid_active_video] [get_bd_pins rgb2dvi_0/vid_pVDE]
connect_bd_net [get_bd_pins vid_out_0/vid_hsync] [get_bd_pins rgb2dvi_0/vid_pHSync]
connect_bd_net [get_bd_pins vid_out_0/vid_vsync] [get_bd_pins rgb2dvi_0/vid_pVSync]

# Export physical TMDS pins explicitly. The rgb2dvi custom bus abstraction is
# optional in a locally installed IP repository: exporting only its interface
# can silently omit all HDMI ports from the generated HDL wrapper when that
# abstraction is unavailable. Scalar/vector ports do not need that definition.
foreach {pin port} {TMDS_Clk_p TMDS_clk_p TMDS_Clk_n TMDS_clk_n} {
    create_bd_port -dir O $port
    connect_bd_net [get_bd_pins rgb2dvi_0/$pin] [get_bd_ports $port]
}
foreach {pin port} {TMDS_Data_p TMDS_data_p TMDS_Data_n TMDS_data_n} {
    create_bd_port -dir O -from 2 -to 0 $port
    connect_bd_net [get_bd_pins rgb2dvi_0/$pin] [get_bd_ports $port]
}

# Two independent projection engines, each with its own HP port.
foreach {index hp base} {0 1 0x43C10000 1 2 0x43C20000} {
    create_bd_cell -type ip -vlnv bosio.org:hls:bosio_projector:1.0 projector_$index
    connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] [get_bd_pins projector_$index/ap_clk] [get_bd_pins ps7_0/S_AXI_HP${hp}_ACLK]
    connect_bd_net [get_bd_pins rst_ps7_100M/peripheral_aresetn] [get_bd_pins projector_$index/ap_rst_n]
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Master "/ps7_0/M_AXI_GP0" Clk "Auto"} [get_bd_intf_pins projector_$index/s_axi_control]
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config [list Master "/projector_$index/m_axi_gmem" Clk "Auto"] [get_bd_intf_pins ps7_0/S_AXI_HP${hp}]
    assign_bd_address -offset $base -range 64K -target_address_space [get_bd_addr_spaces ps7_0/Data] [get_bd_addr_segs projector_$index/s_axi_control/Reg] -force
}
assign_bd_address -offset 0x43C00000 -range 64K -target_address_space [get_bd_addr_spaces ps7_0/Data] [get_bd_addr_segs output_core_0/s_axi_lite/reg0] -force
assign_bd_address

# Validate and Save BD
puts "==> Validating Block Design..."
validate_bd_design
save_bd_design

# Create Top HDL Wrapper
puts "==> Generating Top HDL Wrapper..."
set bd_file [get_files "bosio_out_system.bd"]
make_wrapper -files $bd_file -top
set wrapper_gen [file join $proj_dir "$proj_name.gen" "sources_1" "bd" "bosio_out_system" "hdl" "bosio_out_system_wrapper.v"]
set wrapper_src [file join $proj_dir "$proj_name.srcs" "sources_1" "bd" "bosio_out_system" "hdl" "bosio_out_system_wrapper.v"]
if {[file exists $wrapper_gen]} {
    add_files -norecurse $wrapper_gen
} elseif {[file exists $wrapper_src]} {
    add_files -norecurse $wrapper_src
}
update_compile_order -fileset sources_1

puts "=========================================================================="
puts "  Bosio 3DoF Output System Block Design Successfully Created!"
puts "=========================================================================="
