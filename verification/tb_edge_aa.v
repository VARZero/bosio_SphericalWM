`timescale 1ns/1ps
module tb_edge_aa;
 reg clk=0,rst_n=0,enable=1,iv=0;
 reg [7:0] threshold=24,strength=64;
 reg [23:0] pixel_in=0;
 wire ov;wire [23:0] pixel_out;
 reg [23:0] captured[0:15];integer count=0,i;
 always #5 clk=~clk;
 bosio_v2_edge_aa #(.SCREEN_WIDTH(4)) dut(
  .clk(clk),.rst_n(rst_n),.enable(enable),.threshold(threshold),.strength(strength),
  .iv(iv),.pixel_in(pixel_in),.ov(ov),.pixel_out(pixel_out));
 always @(negedge clk)if(ov)begin captured[count]=pixel_out;count=count+1;end
 task send;
  input [23:0] value;
  begin @(negedge clk);iv=1;pixel_in=value;end
 endtask
 initial begin
  repeat(3)@(negedge clk);rst_n=1;
  // First row is black. The second row has a horizontal black-to-white edge.
  for(i=0;i<4;i=i+1)send(24'h000000);
  send(24'h000000);
  for(i=1;i<4;i=i+1)send(24'hffffff);
  @(negedge clk);iv=0;repeat(6)@(negedge clk);
  if(count!=8)begin $display("COUNT_FAIL %0d",count);$fatal;end
  if(captured[4]!==24'h000000)begin $display("BYPASS_FAIL %h",captured[4]);$fatal;end
  for(i=5;i<8;i=i+1)if(captured[i]!==24'hbfbfbf)begin
   $display("BLEND_FAIL index=%0d value=%h",i,captured[i]);$fatal;
  end
  $display("EDGE_AA_PASS count=%0d blended=%h",count,captured[5]);$finish;
 end
 initial begin #5000;$display("TIMEOUT");$fatal;end
endmodule
