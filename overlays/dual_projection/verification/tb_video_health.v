`timescale 1ns/1ps
module tb_video_health;
 reg clk=0,rst_n=0,locked=0,underflow=0,overflow=0,vsync=0;
 wire [31:0] health,status_sync,video_frames;
 always #5 clk=~clk;
 video_health dut(.clk(clk),.rst_n(rst_n),.locked(locked),.underflow(underflow),
  .overflow(overflow),.vsync(vsync),.status(32'h12345678),
  .health(health),.status_sync(status_sync),.video_frames(video_frames));
 task settle;begin repeat(6)@(negedge clk);end endtask
 task frame;begin vsync=1;settle;vsync=0;settle;end endtask
 initial begin
  settle;rst_n=1;settle;locked=1;settle;
  if(health[3:0]!==4'b1001)$fatal(1,"initial lock");
  frame;frame;frame;
  if(video_frames!==3)$fatal(1,"native frame counter");
  // No producer signals exist here: native scanout is measured independently.
  frame;frame;
  if(video_frames!==5)$fatal(1,"repeat frames");
  underflow=1;settle;settle;
  if(health[31:16]!==1)$fatal(1,"underflow counted per level, not edge");
  underflow=0;settle;underflow=1;locked=0;overflow=1;settle;
  if(health[31:16]!==2 || health[15:8]!==1 || !health[4])$fatal(1,"fault counters");
  if(status_sync!==32'h12345678)$fatal(1,"status sample");
  $display("VIDEO_HEALTH_PASS");$finish;
 end
 initial begin #10000;$fatal(1,"timeout");end
endmodule
