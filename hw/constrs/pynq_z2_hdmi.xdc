## ============================================================================
## Constraints File for PYNQ-Z2 HDMI Out (TMDS) & Clock Timing
## ============================================================================

# HDMI Out TMDS Clock
set_property -dict { PACKAGE_PIN L16   IOSTANDARD TMDS_33  } [get_ports -quiet { TMDS_Clk_p TMDS_clk_p }];
set_property -dict { PACKAGE_PIN L17   IOSTANDARD TMDS_33  } [get_ports -quiet { TMDS_Clk_n TMDS_clk_n }];

# HDMI Out TMDS Data Channels
set_property -dict { PACKAGE_PIN K17   IOSTANDARD TMDS_33  } [get_ports -quiet { TMDS_Data_p[0] TMDS_data_p[0] }];
set_property -dict { PACKAGE_PIN K18   IOSTANDARD TMDS_33  } [get_ports -quiet { TMDS_Data_n[0] TMDS_data_n[0] }];
set_property -dict { PACKAGE_PIN K19   IOSTANDARD TMDS_33  } [get_ports -quiet { TMDS_Data_p[1] TMDS_data_p[1] }];
set_property -dict { PACKAGE_PIN J19   IOSTANDARD TMDS_33  } [get_ports -quiet { TMDS_Data_n[1] TMDS_data_n[1] }];
set_property -dict { PACKAGE_PIN J18   IOSTANDARD TMDS_33  } [get_ports -quiet { TMDS_Data_p[2] TMDS_data_p[2] }];
set_property -dict { PACKAGE_PIN H18   IOSTANDARD TMDS_33  } [get_ports -quiet { TMDS_Data_n[2] TMDS_data_n[2] }];

# HDMI HPD (Input on PYNQ-Z2 board, port removed from BD)
# set_property -dict { PACKAGE_PIN R19   IOSTANDARD LVCMOS33 } [get_ports -quiet { hdmi_out_hpd }];

## Pmod B - GY-521 / MPU6050 I2C
## PMODB physical pin 3 (pmodb_gpio[2], JB2_P) = SDA, FPGA pin T11
## PMODB physical pin 4 (pmodb_gpio[3], JB2_N) = SCL, FPGA pin T10
## The GY-521 must be powered from the PMOD 3.3 V pin.
set_property -dict { PACKAGE_PIN T11 IOSTANDARD LVCMOS33 } [get_ports -quiet { pmodb_iic_sda_io }];
set_property -dict { PACKAGE_PIN T10 IOSTANDARD LVCMOS33 } [get_ports -quiet { pmodb_iic_scl_io }];
set_property PULLUP true [get_ports -quiet { pmodb_iic_sda_io }];
set_property PULLUP true [get_ports -quiet { pmodb_iic_scl_io }];

# Asynchronous Clock Domain Crossing (100MHz AXI vs 74.25MHz/371.25MHz Video Domain)
set_clock_groups -asynchronous \
    -group [get_clocks -include_generated_clocks -of_objects [get_pins -hier *clk_wiz_0/clk_out1]] \
    -group [get_clocks -include_generated_clocks -of_objects [get_pins -hier *clk_wiz_0/clk_out[23]]]
