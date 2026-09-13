`timescale 1ns/1ps
// GY-521 / MPU6050 direct hardware sensor hub.
// Reads the IMU over I2C, estimates orientation, and emits signed mrad as
// AXI4-Stream: {roll[31:0], pitch[31:0], yaw[31:0]}.
module bosio_sensor_hub_mpu6050 #(
    parameter integer CLK_HZ = 100000000,
    parameter integer I2C_HZ = 100000,
    parameter integer SAMPLE_HZ = 100,
    parameter integer CALIBRATION_SAMPLES = 256
)(
    input  wire         clk,
    input  wire         rst_n,
    input  wire         enable,
    (* X_INTERFACE_INFO = "xilinx.com:interface:iic:1.0 iic SCL_I" *) input wire iic_scl_i,
    (* X_INTERFACE_INFO = "xilinx.com:interface:iic:1.0 iic SCL_O" *) output wire iic_scl_o,
    (* X_INTERFACE_INFO = "xilinx.com:interface:iic:1.0 iic SCL_T" *) output wire iic_scl_t,
    (* X_INTERFACE_INFO = "xilinx.com:interface:iic:1.0 iic SDA_I" *) input wire iic_sda_i,
    (* X_INTERFACE_INFO = "xilinx.com:interface:iic:1.0 iic SDA_O" *) output wire iic_sda_o,
    (* X_INTERFACE_INFO = "xilinx.com:interface:iic:1.0 iic SDA_T" *) output wire iic_sda_t,
    output reg  [95:0]  m_axis_sensor_tdata,
    output reg          m_axis_sensor_tvalid,
    input  wire         m_axis_sensor_tready,
    output reg          sensor_ready,
    output reg          sensor_error
);
    localparam integer POWERUP_CYCLES = CLK_HZ / 10;
    localparam integer SAMPLE_CYCLES  = CLK_HZ / SAMPLE_HZ;
    // A 14-byte register read occupies about 160 I2C bit periods. Subtract it
    // from the idle interval so read-to-read cadence remains close to SAMPLE_HZ.
    localparam integer READ_CYCLES = (CLK_HZ / I2C_HZ) * 160;
    localparam integer SAMPLE_WAIT_CYCLES =
        (SAMPLE_CYCLES > READ_CYCLES) ? SAMPLE_CYCLES - READ_CYCLES : 1;
    localparam [3:0] S_POWERUP=0, S_INIT_CMD=1, S_INIT_WAIT=2,
                     S_SAMPLE_WAIT=3, S_READ_CMD=4, S_READ_WAIT=5,
                     S_CALIBRATE=6, S_FILTER_DELTA=7, S_FILTER_GYRO=8,
                     S_FILTER_DECAY=9, S_FILTER_BLEND=10,
                     S_FILTER_WRAP=11, S_FILTER_EMIT=12;
    localparam integer CALIBRATION_SHIFT = $clog2(CALIBRATION_SAMPLES);

    reg [3:0] state;
    reg [31:0] timer;
    reg [2:0] init_index;
    reg cmd_valid, cmd_read;
    wire cmd_ready, cmd_done, cmd_nack;
    reg [7:0] cmd_reg, cmd_wdata;
    reg [4:0] cmd_length;
    wire [127:0] read_data;
    wire [4:0] read_count;

    reg signed [31:0] gyro_sum_x, gyro_sum_y, gyro_sum_z;
    reg signed [15:0] gyro_bias_x, gyro_bias_y, gyro_bias_z;
    reg [8:0] calibration_count;
    reg signed [47:0] yaw_q16, pitch_q16, roll_q16;
    reg signed [15:0] sample_ax, sample_ay, sample_gx, sample_gy, sample_gz;
    reg signed [31:0] delta_gx_q16, delta_gy_q16, delta_gz_q16;
    reg signed [47:0] accel_pitch_target_q16, accel_roll_target_q16;
    reg signed [47:0] pitch_gyro_q16, roll_gyro_q16, yaw_gyro_q16;
    reg signed [47:0] pitch_decay_q16, roll_decay_q16;

    wire signed [15:0] ax = {read_data[7:0],read_data[15:8]};
    wire signed [15:0] ay = {read_data[23:16],read_data[31:24]};
    wire signed [15:0] az = {read_data[39:32],read_data[47:40]};
    wire signed [15:0] gx = {read_data[71:64],read_data[79:72]};
    wire signed [15:0] gy = {read_data[87:80],read_data[95:88]};
    wire signed [15:0] gz = {read_data[103:96],read_data[111:104]};

    localparam signed [47:0] PI_Q16 = 48'sd205914112; // 3142 mrad * 65536
    localparam signed [47:0] TAU_Q16 = 48'sd411828224;

    bosio_i2c_reg_master #(.CLK_HZ(CLK_HZ),.I2C_HZ(I2C_HZ)) i2c (
        .clk(clk),.rst_n(rst_n),.cmd_valid(cmd_valid),.cmd_ready(cmd_ready),
        .cmd_read(cmd_read),.cmd_addr(7'h68),.cmd_reg(cmd_reg),
        .cmd_wdata(cmd_wdata),.cmd_length(cmd_length),.read_data(read_data),
        .read_count(read_count),.done(cmd_done),.nack(cmd_nack),
        .scl_i(iic_scl_i),.scl_o(iic_scl_o),.scl_t(iic_scl_t),
        .sda_i(iic_sda_i),.sda_o(iic_sda_o),.sda_t(iic_sda_t));

    task load_init;
        input [2:0] index;
        begin
            cmd_read <= 0; cmd_length <= 1;
            case(index)
                0: begin cmd_reg<=8'h6b; cmd_wdata<=8'h01; end
                1: begin cmd_reg<=8'h1a; cmd_wdata<=8'h03; end
                2: begin cmd_reg<=8'h1b; cmd_wdata<=8'h08; end
                3: begin cmd_reg<=8'h1c; cmd_wdata<=8'h08; end
                default: begin cmd_reg<=8'h19; cmd_wdata<=8'h09; end
            endcase
        end
    endtask

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=S_POWERUP; timer<=0; init_index<=0; cmd_valid<=0;
            cmd_read<=0; cmd_reg<=0; cmd_wdata<=0; cmd_length<=1;
            gyro_sum_x<=0; gyro_sum_y<=0; gyro_sum_z<=0;
            gyro_bias_x<=0; gyro_bias_y<=0; gyro_bias_z<=0;
            calibration_count<=0; yaw_q16<=0; pitch_q16<=0; roll_q16<=0;
            sample_ax<=0; sample_ay<=0; sample_gx<=0; sample_gy<=0; sample_gz<=0;
            delta_gx_q16<=0; delta_gy_q16<=0; delta_gz_q16<=0;
            accel_pitch_target_q16<=0; accel_roll_target_q16<=0;
            pitch_gyro_q16<=0; roll_gyro_q16<=0; yaw_gyro_q16<=0;
            pitch_decay_q16<=0; roll_decay_q16<=0;
            m_axis_sensor_tdata<=0; m_axis_sensor_tvalid<=0;
            sensor_ready<=0; sensor_error<=0;
        end else begin
            if (m_axis_sensor_tvalid && m_axis_sensor_tready)
                m_axis_sensor_tvalid <= 0;
            cmd_valid <= 0;
            if (!enable) begin
                state<=S_POWERUP; timer<=0; init_index<=0;
                calibration_count<=0; gyro_sum_x<=0; gyro_sum_y<=0; gyro_sum_z<=0;
                yaw_q16<=0; pitch_q16<=0; roll_q16<=0;
                sensor_ready<=0; sensor_error<=0; m_axis_sensor_tvalid<=0;
            end else case(state)
                S_POWERUP: begin
                    if (timer >= POWERUP_CYCLES-1) begin timer<=0; state<=S_INIT_CMD; end
                    else timer<=timer+1'b1;
                end
                S_INIT_CMD: if (cmd_ready) begin
                    load_init(init_index); cmd_valid<=1; state<=S_INIT_WAIT;
                end
                S_INIT_WAIT: if (cmd_done) begin
                    if (cmd_nack) begin
                        sensor_error<=1; timer<=0; init_index<=0; state<=S_POWERUP;
                    end
                    else if (init_index==4) begin
                        sensor_error<=0; timer<=0; state<=S_SAMPLE_WAIT;
                    end
                    else begin init_index<=init_index+1'b1; state<=S_INIT_CMD; end
                end
                S_SAMPLE_WAIT: begin
                    if (timer >= SAMPLE_WAIT_CYCLES-1) begin timer<=0; state<=S_READ_CMD; end
                    else timer<=timer+1'b1;
                end
                S_READ_CMD: if (cmd_ready) begin
                    cmd_read<=1; cmd_reg<=8'h3b; cmd_length<=14;
                    cmd_valid<=1; state<=S_READ_WAIT;
                end
                S_READ_WAIT: if (cmd_done) begin
                    if (cmd_nack || read_count!=14) begin
                        sensor_error<=1; timer<=0; state<=S_SAMPLE_WAIT;
                    end else begin
                        sensor_error<=0;
                        // Break the read-data-to-filter path at a register boundary.
                        sample_ax<=ax; sample_ay<=ay;
                        sample_gx<=gx; sample_gy<=gy; sample_gz<=gz;
                        if (!sensor_ready) state<=S_CALIBRATE;
                        else state<=S_FILTER_DELTA;
                    end
                end
                S_CALIBRATE: begin
                    gyro_sum_x<=gyro_sum_x+sample_gx;
                    gyro_sum_y<=gyro_sum_y+sample_gy;
                    gyro_sum_z<=gyro_sum_z+sample_gz;
                    if (calibration_count==CALIBRATION_SAMPLES-1) begin
                        // CALIBRATION_SAMPLES must be a power of two (default 256).
                        gyro_bias_x <= (gyro_sum_x+sample_gx) >>> CALIBRATION_SHIFT;
                        gyro_bias_y <= (gyro_sum_y+sample_gy) >>> CALIBRATION_SHIFT;
                        gyro_bias_z <= (gyro_sum_z+sample_gz) >>> CALIBRATION_SHIFT;
                        calibration_count<=0; sensor_ready<=1; state<=S_SAMPLE_WAIT;
                    end else begin calibration_count<=calibration_count+1'b1; state<=S_SAMPLE_WAIT; end
                end
                // The filter is deliberately spread over several 100 MHz cycles.
                // A sample only arrives every 10 ms, so this adds negligible latency
                // while keeping each fixed-point adder/multiplier path short.
                S_FILTER_DELTA: begin
                    // At 100 Hz and +/-500 dps: delta mrad Q16 ~= raw * 174.6.
                    delta_gx_q16<=($signed(sample_gx)-$signed(gyro_bias_x))*32'sd175;
                    delta_gy_q16<=($signed(sample_gy)-$signed(gyro_bias_y))*32'sd175;
                    delta_gz_q16<=($signed(sample_gz)-$signed(gyro_bias_z))*32'sd175;
                    // Near-level gravity estimate in mrad Q16: raw * 125 / 1024.
                    accel_pitch_target_q16<=-($signed(sample_ax)*32'sd125) <<< 6;
                    accel_roll_target_q16<= ($signed(sample_ay)*32'sd125) <<< 6;
                    state<=S_FILTER_GYRO;
                end
                S_FILTER_GYRO: begin
                    pitch_gyro_q16<=pitch_q16+delta_gy_q16;
                    roll_gyro_q16<=roll_q16+delta_gx_q16;
                    yaw_gyro_q16<=yaw_q16+delta_gz_q16;
                    state<=S_FILTER_DECAY;
                end
                S_FILTER_DECAY: begin
                    // alpha = 63/64, expressed as x - x/64.
                    pitch_decay_q16<=pitch_gyro_q16-(pitch_gyro_q16>>>6);
                    roll_decay_q16<=roll_gyro_q16-(roll_gyro_q16>>>6);
                    state<=S_FILTER_BLEND;
                end
                S_FILTER_BLEND: begin
                    pitch_q16<=pitch_decay_q16+(accel_pitch_target_q16>>>6);
                    roll_q16<=roll_decay_q16+(accel_roll_target_q16>>>6);
                    state<=S_FILTER_WRAP;
                end
                S_FILTER_WRAP: begin
                    yaw_q16 <= yaw_gyro_q16 > PI_Q16 ? yaw_gyro_q16-TAU_Q16 :
                               yaw_gyro_q16 < -PI_Q16 ? yaw_gyro_q16+TAU_Q16 : yaw_gyro_q16;
                    state<=S_FILTER_EMIT;
                end
                S_FILTER_EMIT: begin
                    if (!m_axis_sensor_tvalid) begin
                        m_axis_sensor_tdata[31:0] <= yaw_q16 >>> 16;
                        m_axis_sensor_tdata[63:32] <= pitch_q16 >>> 16;
                        m_axis_sensor_tdata[95:64] <= roll_q16 >>> 16;
                        m_axis_sensor_tvalid<=1;
                        state<=S_SAMPLE_WAIT;
                    end
                end
                default: state<=S_POWERUP;
            endcase
        end
    end
endmodule
