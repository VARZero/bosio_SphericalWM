# Definitional proc to organize widgets for parameters.
proc init_gui { IPINST } {
  ipgui::add_param $IPINST -name "Component_Name"
  #Adding Page
  set Page_0 [ipgui::add_page $IPINST -name "Page 0"]
  ipgui::add_param $IPINST -name "CALIBRATION_SAMPLES" -parent ${Page_0}
  ipgui::add_param $IPINST -name "CLK_HZ" -parent ${Page_0}
  ipgui::add_param $IPINST -name "I2C_HZ" -parent ${Page_0}
  ipgui::add_param $IPINST -name "SAMPLE_HZ" -parent ${Page_0}


}

proc update_PARAM_VALUE.CALIBRATION_SAMPLES { PARAM_VALUE.CALIBRATION_SAMPLES } {
	# Procedure called to update CALIBRATION_SAMPLES when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.CALIBRATION_SAMPLES { PARAM_VALUE.CALIBRATION_SAMPLES } {
	# Procedure called to validate CALIBRATION_SAMPLES
	return true
}

proc update_PARAM_VALUE.CLK_HZ { PARAM_VALUE.CLK_HZ } {
	# Procedure called to update CLK_HZ when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.CLK_HZ { PARAM_VALUE.CLK_HZ } {
	# Procedure called to validate CLK_HZ
	return true
}

proc update_PARAM_VALUE.I2C_HZ { PARAM_VALUE.I2C_HZ } {
	# Procedure called to update I2C_HZ when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.I2C_HZ { PARAM_VALUE.I2C_HZ } {
	# Procedure called to validate I2C_HZ
	return true
}

proc update_PARAM_VALUE.SAMPLE_HZ { PARAM_VALUE.SAMPLE_HZ } {
	# Procedure called to update SAMPLE_HZ when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.SAMPLE_HZ { PARAM_VALUE.SAMPLE_HZ } {
	# Procedure called to validate SAMPLE_HZ
	return true
}


proc update_MODELPARAM_VALUE.CLK_HZ { MODELPARAM_VALUE.CLK_HZ PARAM_VALUE.CLK_HZ } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.CLK_HZ}] ${MODELPARAM_VALUE.CLK_HZ}
}

proc update_MODELPARAM_VALUE.I2C_HZ { MODELPARAM_VALUE.I2C_HZ PARAM_VALUE.I2C_HZ } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.I2C_HZ}] ${MODELPARAM_VALUE.I2C_HZ}
}

proc update_MODELPARAM_VALUE.SAMPLE_HZ { MODELPARAM_VALUE.SAMPLE_HZ PARAM_VALUE.SAMPLE_HZ } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.SAMPLE_HZ}] ${MODELPARAM_VALUE.SAMPLE_HZ}
}

proc update_MODELPARAM_VALUE.CALIBRATION_SAMPLES { MODELPARAM_VALUE.CALIBRATION_SAMPLES PARAM_VALUE.CALIBRATION_SAMPLES } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.CALIBRATION_SAMPLES}] ${MODELPARAM_VALUE.CALIBRATION_SAMPLES}
}
