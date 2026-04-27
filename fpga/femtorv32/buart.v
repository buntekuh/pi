// buart.v — UART from the J1 CPU (James Bowman, BSD-2 Clause)
// https://github.com/jamesbowman/swapforth
// resetq is active-low.

`default_nettype none

module baudgen(
  input  wire        clk,
  input  wire        resetq,
  input  wire [31:0] baud,
  input  wire        restart,
  output wire        ser_clk);
  parameter CLKFREQ = 1000000;

  wire [38:0] aclkfreq = CLKFREQ;
  reg  [38:0] d;
  wire [38:0] dInc = d[38] ? ({4'd0, baud}) : (({4'd0, baud}) - aclkfreq);
  wire [38:0] dN   = restart ? 0 : (d + dInc);
  assign ser_clk = ~d[38];

  always @(negedge resetq or posedge clk) begin
    if (!resetq) d <= 0;
    else         d <= dN;
  end
endmodule

module uart(
  input  wire        clk,
  input  wire        resetq,
  output wire        uart_busy,
  output reg         uart_tx,
  input  wire [31:0] baud,
  input  wire        uart_wr_i,
  input  wire [7:0]  uart_dat_i);
  parameter CLKFREQ = 1000000;

  reg [3:0] bitcount;
  reg [8:0] shifter;

  assign uart_busy = |bitcount;
  wire sending  = |bitcount;
  wire ser_clk;
  wire starting = uart_wr_i & ~uart_busy;

  baudgen #(.CLKFREQ(CLKFREQ)) _baudgen(
    .clk(clk), .resetq(resetq), .baud(baud),
    .restart(1'b0), .ser_clk(ser_clk));

  always @(negedge resetq or posedge clk) begin
    if (!resetq) begin
      uart_tx  <= 1; bitcount <= 0; shifter <= 0;
    end else begin
      if (starting) begin
        shifter  <= {uart_dat_i[7:0], 1'b0};
        bitcount <= 10;
      end
      if (sending & ser_clk) begin
        {shifter, uart_tx} <= {1'b1, shifter};
        bitcount <= bitcount - 4'd1;
      end
    end
  end
endmodule

module rxuart(
  input  wire        clk,
  input  wire        resetq,
  input  wire [31:0] baud,
  input  wire        uart_rx,
  input  wire        rd,
  output wire        valid,
  output wire [7:0]  data);
  parameter CLKFREQ = 1000000;

  reg [4:0] bitcount;
  reg [7:0] shifter;
  wire idle     = &bitcount;
  wire ser_clk;
  reg  [2:0] hh = 3'b111;
  wire [2:0] hhN = {hh[1:0], uart_rx};
  wire startbit = idle & (hhN[2:1] == 2'b10);
  wire sample;
  wire [7:0] shifterN = sample ? {hh[1], shifter[7:1]} : shifter;

  baudgen #(.CLKFREQ(CLKFREQ)) _baudgen(
    .clk(clk), .resetq(resetq), .baud({baud[30:0], 1'b0}),
    .restart(startbit), .ser_clk(ser_clk));

  assign valid  = (bitcount == 18);
  assign sample = (bitcount > 2) & bitcount[0] & !valid & ser_clk;
  assign data   = shifter;

  reg [4:0] bitcountN;
  always @* begin
    if      (startbit)           bitcountN = 0;
    else if (!idle & !valid & ser_clk) bitcountN = bitcount + 5'd1;
    else if (valid & rd)         bitcountN = 5'b11111;
    else                         bitcountN = bitcount;
  end

  always @(negedge resetq or posedge clk) begin
    if (!resetq) begin
      hh <= 3'b111; bitcount <= 5'b11111; shifter <= 0;
    end else begin
      hh       <= hhN;
      bitcount <= bitcountN;
      shifter  <= shifterN;
    end
  end
endmodule

module buart(
  input  wire        clk,
  input  wire        resetq,
  input  wire [31:0] baud,
  input  wire        rx,
  output wire        tx,
  input  wire        rd,
  input  wire        wr,
  output wire        valid,
  output wire        busy,
  input  wire [7:0]  tx_data,
  output wire [7:0]  rx_data);
  parameter CLKFREQ = 1000000;

  rxuart #(.CLKFREQ(CLKFREQ)) _rx(
    .clk(clk), .resetq(resetq), .baud(baud),
    .uart_rx(rx), .rd(rd), .valid(valid), .data(rx_data));
  uart #(.CLKFREQ(CLKFREQ)) _tx(
    .clk(clk), .resetq(resetq), .baud(baud),
    .uart_busy(busy), .uart_tx(tx),
    .uart_wr_i(wr), .uart_dat_i(tx_data));
endmodule
