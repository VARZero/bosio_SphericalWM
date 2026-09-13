# ============================================================================
# Vivado 2020.2 Block Design Script: Bosio 3DoF Display Output System
# Architecture:
#   - Bosio 3DoF Output Core (bosio_output_core)
#   - Direct RTL GY-521 / MPU6050 sensor hub on Pmod B
#   - AXI-Lite Software Control via Zynq PS
#   - AXI Master DDR Texture Fetch via Zynq HP0
#   - VTC + Video Out + rgb2dvi driving 720p60 HDMI PHY
# ============================================================================

set proj_name "bosio_out_system_proj"
set root_dir [file normalize [file join [file dirname [info script]] "../.."]]
set proj_dir [file join $root_dir "hw" "vivado_proj_output"]
set ip_repo  [file join $root_dir "hw" "ip_repo"]
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
set_property ip_repo_paths $ip_repo [current_project]
update_ip_catalog

# Create Block Design
create_bd_design "bosio_out_system"

# 1. Processing System 7 (Zynq PS)
puts "==> Adding Zynq Processing System (PS7)..."
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7_0
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {make_external "FIXED_IO, DDR" apply_board_preset "1" Master "Disable" Slave "Disable" }  [get_bd_cells ps7_0]

# Configure PS7: Enable HP0 (Read port for Framebuffer) and GP0 (Control)
set_property -dict [list \
    CONFIG.PCW_USE_S_AXI_HP0 {1} \
    CONFIG.PCW_USE_S_AXI_HP1 {0} \
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

# 7. Video Timing Controller (VTC) for 720p60
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

# 8. AXI4-Stream to Video Out
create_bd_cell -type ip -vlnv xilinx.com:ip:v_axi4s_vid_out:4.0 vid_out_0
set_property -dict [list \
    CONFIG.C_VTG_MASTER_SLAVE {1} \
    CONFIG.C_HAS_ASYNC_CLK {1} \
    CONFIG.C_ADDR_WIDTH {11} \
    CONFIG.C_HYSTERESIS_LEVEL {12} \
    CONFIG.C_SYNC_LOCK_THRESHOLD {4} \
] [get_bd_cells vid_out_0]

# 9. RGB to DVI / TMDS Transmitter
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
connect_bd_net [get_bd_pins vid_out_0/vtg_ce] [get_bd_pins vtc_0/gen_clken]
connect_bd_net [get_bd_pins const_vcc/dout] [get_bd_pins vid_out_0/aclken]
connect_bd_net [get_bd_pins const_vcc/dout] [get_bd_pins vid_out_0/vid_io_out_ce]

# ----------------------------------------------------------------------------
# Connect AXI Buses
# ----------------------------------------------------------------------------
puts "==> Connecting AXI-Lite Control Interface..."
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Master "/ps7_0/M_AXI_GP0" Clk "Auto" }  [get_bd_intf_pins output_core_0/s_axi_lite]

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
puts "==> Connecting Video Pipeline..."
connect_bd_intf_net [get_bd_intf_pins output_core_0/m_axis_video] [get_bd_intf_pins vid_out_0/video_in]
connect_bd_intf_net [get_bd_intf_pins vtc_0/vtiming_out] [get_bd_intf_pins vid_out_0/vtiming_in]

# Connect vid_out signals to rgb2dvi
connect_bd_net [get_bd_pins vid_out_0/vid_data] [get_bd_pins rgb2dvi_0/vid_pData]
connect_bd_net [get_bd_pins vid_out_0/vid_active_video] [get_bd_pins rgb2dvi_0/vid_pVDE]
connect_bd_net [get_bd_pins vid_out_0/vid_hsync] [get_bd_pins rgb2dvi_0/vid_pHSync]
connect_bd_net [get_bd_pins vid_out_0/vid_vsync] [get_bd_pins rgb2dvi_0/vid_pVSync]

# External TMDS port for HDMI Output
make_bd_intf_pins_external [get_bd_intf_pins rgb2dvi_0/TMDS] -name "TMDS"

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
