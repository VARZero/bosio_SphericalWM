# Run against the implemented design before writing or exporting a bitstream.
# XDC supports a restricted Tcl subset, so fail-fast checks belong in this hook.
foreach {name pin} {TMDS_clk_p L16 TMDS_clk_n L17
                    TMDS_data_p[0] K17 TMDS_data_n[0] K18
                    TMDS_data_p[1] K19 TMDS_data_n[1] J19
                    TMDS_data_p[2] J18 TMDS_data_n[2] H18} {
    set port [get_ports -quiet $name]
    if {[llength $port] != 1} {
        error "Required HDMI output port is missing: $name"
    }
    if {[get_property PACKAGE_PIN $port] != $pin ||
        [get_property IOSTANDARD $port] != "TMDS_33"} {
        error "HDMI output pin validation failed: $name must use $pin / TMDS_33"
    }
}
if {[llength [get_cells -hier -filter {REF_NAME == OBUFDS}]] < 4} {
    error "HDMI transmitter output buffers are missing from the implemented design"
}
puts "BOSIO_HDMI_IO_VALIDATED: eight TMDS pins and four differential output buffers"
