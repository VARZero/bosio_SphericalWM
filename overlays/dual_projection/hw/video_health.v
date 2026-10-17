`timescale 1ns/1ps
module video_health(input wire clk,rst_n,locked,underflow,overflow,vsync,
 input wire [31:0] status,output wire [31:0] health,output wire [31:0] status_sync,output reg [31:0] video_frames);
 (* ASYNC_REG="TRUE" *) reg [2:0] flags_meta,flags_sync;
 (* ASYNC_REG="TRUE" *) reg [31:0] status_meta,status_sample;
 reg [2:0] previous;
 (* ASYNC_REG="TRUE" *) reg [2:0] vsync_sync;
 reg [7:0] lock_losses;
 reg [15:0] underflows;
 reg ever_locked,overflow_seen;
 assign health={underflows,lock_losses,3'b0,overflow_seen,ever_locked,flags_sync};
 assign status_sync=status_sample;
 always @(posedge clk)begin
  if(!rst_n)begin
   flags_meta<=0;flags_sync<=0;status_meta<=0;status_sample<=0;previous<=0;
   video_frames<=0;vsync_sync<=0;
   lock_losses<=0;underflows<=0;ever_locked<=0;overflow_seen<=0;
  end else begin
   vsync_sync<={vsync_sync[1:0],vsync};
   if(vsync_sync[1]&&!vsync_sync[2])video_frames<=video_frames+1'b1;
   flags_meta<={overflow,underflow,locked};flags_sync<=flags_meta;
   status_meta<=status;status_sample<=status_meta;previous<=flags_sync;
   if(flags_sync[0])ever_locked<=1;
   if(previous[0]&&!flags_sync[0]&&lock_losses!=8'hff)lock_losses<=lock_losses+1'b1;
   if(!previous[1]&&flags_sync[1]&&underflows!=16'hffff)underflows<=underflows+1'b1;
   if(flags_sync[2])overflow_seen<=1;
  end
 end
endmodule
