`timescale 1ns/1ps
// Single-master I2C register transaction engine.
// Supports one-byte register writes and 1..16 byte repeated-start reads.
module bosio_i2c_reg_master #(
    parameter integer CLK_HZ = 100000000,
    parameter integer I2C_HZ = 100000
)(
    input  wire         clk,
    input  wire         rst_n,
    input  wire         cmd_valid,
    output wire         cmd_ready,
    input  wire         cmd_read,
    input  wire [6:0]   cmd_addr,
    input  wire [7:0]   cmd_reg,
    input  wire [7:0]   cmd_wdata,
    input  wire [4:0]   cmd_length,
    output reg  [127:0] read_data,
    output reg  [4:0]   read_count,
    output reg          done,
    output reg          nack,
    input  wire         scl_i,
    output wire         scl_o,
    output wire         scl_t,
    input  wire         sda_i,
    output wire         sda_o,
    output wire         sda_t
);
    localparam integer QUARTER_DIV = CLK_HZ / (I2C_HZ * 4);
    localparam [4:0] ST_IDLE=0, ST_START_A=1, ST_START_B=2, ST_START_C=3,
                     ST_TX_SETUP=4, ST_TX_HIGH=5, ST_TX_LOW=6,
                     ST_ACK_SETUP=7, ST_ACK_HIGH=8, ST_ACK_LOW=9,
                     ST_RESTART_A=10, ST_RESTART_B=11, ST_RESTART_C=12,
                     ST_RX_SETUP=13, ST_RX_HIGH=14, ST_RX_LOW=15,
                     ST_MACK_SETUP=16, ST_MACK_HIGH=17, ST_MACK_LOW=18,
                     ST_STOP_A=19, ST_STOP_B=20, ST_STOP_C=21;
    localparam [2:0] SEQ_ADDR_W=0, SEQ_REG=1, SEQ_WDATA=2,
                     SEQ_ADDR_R=3, SEQ_READ=4;

    reg [4:0] state;
    reg [2:0] sequence;
    reg [31:0] div_count;
    reg scl_low, sda_low;
    reg latched_read;
    reg [6:0] latched_addr;
    reg [7:0] latched_reg, latched_wdata;
    reg [4:0] latched_length;
    reg [7:0] shift;
    reg [2:0] bit_index;
    reg [4:0] byte_index;

    assign scl_o = 1'b0;
    assign sda_o = 1'b0;
    assign scl_t = ~scl_low;
    assign sda_t = ~sda_low;
    assign cmd_ready = (state == ST_IDLE);

    wire tick = (div_count == QUARTER_DIV-1);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            div_count <= 0;
        else if (tick)
            div_count <= 0;
        else
            div_count <= div_count + 1'b1;
    end

    task load_tx;
        input [7:0] value;
        begin
            shift <= value;
            bit_index <= 3'd7;
            state <= ST_TX_SETUP;
        end
    endtask

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            sequence <= SEQ_ADDR_W;
            scl_low <= 1'b0;
            sda_low <= 1'b0;
            done <= 1'b0;
            nack <= 1'b0;
            read_data <= 0;
            read_count <= 0;
            latched_read <= 0;
            latched_addr <= 0;
            latched_reg <= 0;
            latched_wdata <= 0;
            latched_length <= 0;
            shift <= 0;
            bit_index <= 0;
            byte_index <= 0;
        end else begin
            done <= 1'b0;
            if (state == ST_IDLE) begin
                scl_low <= 1'b0;
                sda_low <= 1'b0;
                if (cmd_valid) begin
                    latched_read <= cmd_read;
                    latched_addr <= cmd_addr;
                    latched_reg <= cmd_reg;
                    latched_wdata <= cmd_wdata;
                    latched_length <= (cmd_length == 0) ? 1 :
                                      (cmd_length > 16 ? 16 : cmd_length);
                    read_data <= 0;
                    read_count <= 0;
                    byte_index <= 0;
                    nack <= 1'b0;
                    sequence <= SEQ_ADDR_W;
                    state <= ST_START_A;
                end
            end else if (tick) begin
                case (state)
                    ST_START_A: begin scl_low<=0; sda_low<=0; state<=ST_START_B; end
                    ST_START_B: begin
                        if (scl_i) begin sda_low<=1; state<=ST_START_C; end
                    end
                    ST_START_C: begin
                        scl_low<=1;
                        load_tx({latched_addr,1'b0});
                    end
                    ST_TX_SETUP: begin
                        scl_low <= 1;
                        sda_low <= ~shift[bit_index];
                        state <= ST_TX_HIGH;
                    end
                    ST_TX_HIGH: begin
                        scl_low <= 0;
                        if (scl_i) state <= ST_TX_LOW;
                    end
                    ST_TX_LOW: begin
                        scl_low <= 1;
                        if (bit_index == 0) state <= ST_ACK_SETUP;
                        else begin bit_index<=bit_index-1'b1; state<=ST_TX_SETUP; end
                    end
                    ST_ACK_SETUP: begin sda_low<=0; scl_low<=1; state<=ST_ACK_HIGH; end
                    ST_ACK_HIGH: begin
                        scl_low<=0;
                        if (scl_i) begin
                            if (sda_i) nack<=1;
                            state<=ST_ACK_LOW;
                        end
                    end
                    ST_ACK_LOW: begin
                        scl_low<=1;
                        if (nack) begin
                            state<=ST_STOP_A;
                        end else case (sequence)
                            SEQ_ADDR_W: begin sequence<=SEQ_REG; load_tx(latched_reg); end
                            SEQ_REG: begin
                                if (latched_read) state<=ST_RESTART_A;
                                else begin sequence<=SEQ_WDATA; load_tx(latched_wdata); end
                            end
                            SEQ_WDATA: state<=ST_STOP_A;
                            SEQ_ADDR_R: begin
                                sequence<=SEQ_READ; bit_index<=7; shift<=0;
                                state<=ST_RX_SETUP;
                            end
                            default: state<=ST_STOP_A;
                        endcase
                    end
                    ST_RESTART_A: begin sda_low<=0; scl_low<=1; state<=ST_RESTART_B; end
                    ST_RESTART_B: begin
                        scl_low<=0;
                        if (scl_i) begin sda_low<=1; state<=ST_RESTART_C; end
                    end
                    ST_RESTART_C: begin
                        scl_low<=1; sequence<=SEQ_ADDR_R;
                        load_tx({latched_addr,1'b1});
                    end
                    ST_RX_SETUP: begin sda_low<=0; scl_low<=1; state<=ST_RX_HIGH; end
                    ST_RX_HIGH: begin
                        scl_low<=0;
                        if (scl_i) begin shift[bit_index]<=sda_i; state<=ST_RX_LOW; end
                    end
                    ST_RX_LOW: begin
                        scl_low<=1;
                        if (bit_index==0) begin
                            read_data[byte_index*8 +: 8] <= {shift[7:1],sda_i};
                            read_count <= byte_index + 1'b1;
                            state<=ST_MACK_SETUP;
                        end else begin bit_index<=bit_index-1'b1; state<=ST_RX_SETUP; end
                    end
                    ST_MACK_SETUP: begin
                        scl_low<=1;
                        sda_low <= ((byte_index + 1'b1) < latched_length);
                        state<=ST_MACK_HIGH;
                    end
                    ST_MACK_HIGH: begin
                        scl_low<=0;
                        if (scl_i) state<=ST_MACK_LOW;
                    end
                    ST_MACK_LOW: begin
                        scl_low<=1; sda_low<=0;
                        if ((byte_index + 1'b1) >= latched_length)
                            state<=ST_STOP_A;
                        else begin
                            byte_index<=byte_index+1'b1;
                            bit_index<=7; shift<=0; state<=ST_RX_SETUP;
                        end
                    end
                    ST_STOP_A: begin scl_low<=1; sda_low<=1; state<=ST_STOP_B; end
                    ST_STOP_B: begin
                        scl_low<=0;
                        if (scl_i) state<=ST_STOP_C;
                    end
                    ST_STOP_C: begin sda_low<=0; done<=1; state<=ST_IDLE; end
                    default: state<=ST_IDLE;
                endcase
            end
        end
    end
endmodule
