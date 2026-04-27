// top.v — Titania on FemtoRV32, Cmod A7-35T
//
// Memory map (ADDR_WIDTH=24):
//   0x000000 – 0x001FFF   8 KB BRAM  (code + data)
//   0x400000              UART register
//     read:  { 22'b0, busy, valid, rx_data[7:0] }
//              bit 9 = TX busy, bit 8 = RX valid, bits 7:0 = received byte
//     write: bits 7:0 = byte to transmit (triggers TX immediately)
//
// Board: Cmod A7-35T, 12 MHz oscillator, onboard FT2232HQ USB-UART.
// No PLL — running directly at 12 MHz for bring-up simplicity.
//
// To build firmware: see firmware/Makefile
// Vivado: add all .v files as sources, add cmod_a7.xdc as constraint.

`default_nettype none

module top (
    input  wire CLK,      // 12 MHz
    input  wire RESET,    // BTN0, active-high → CPU reset while held
    output wire [1:0] LEDS,
    input  wire RXD,      // from PC  (J17 on Cmod A7)
    output wire TXD       // to PC    (J18 on Cmod A7)
);

    // ── Reset ────────────────────────────────────────────────────────────
    // FemtoRV32 reset=0 means reset; buart resetq=0 means reset.
    wire resetn = ~RESET;

    // ── FemtoRV32 CPU bus ────────────────────────────────────────────────
    wire [31:0] mem_addr;
    wire [31:0] mem_wdata;
    wire [3:0]  mem_wmask;
    wire [31:0] mem_rdata;
    wire        mem_rstrb;
    wire        mem_rbusy = 1'b0;   // BRAM and IO respond in one cycle
    wire        mem_wbusy = 1'b0;

    FemtoRV32 #(
        .RESET_ADDR(32'h00000000),
        .ADDR_WIDTH(24)
    ) cpu (
        .clk      (CLK),
        .mem_addr (mem_addr),
        .mem_wdata(mem_wdata),
        .mem_wmask(mem_wmask),
        .mem_rdata(mem_rdata),
        .mem_rstrb(mem_rstrb),
        .mem_rbusy(mem_rbusy),
        .mem_wbusy(mem_wbusy),
        .reset    (resetn)
    );

    // ── Address decode ───────────────────────────────────────────────────
    wire io_sel  = mem_addr[22];   // 0x4xxxxx → IO space
    wire ram_sel = ~io_sel;

    // ── 8 KB BRAM (2048 × 32-bit words) ─────────────────────────────────
    localparam MEM_WORDS = 2048;

    reg [31:0] mem [0:MEM_WORDS-1];
    initial $readmemh("firmware/firmware.hex", mem);

    wire [10:0] word_addr = mem_addr[12:2];
    reg  [31:0] bram_rdata;

    always @(posedge CLK) begin
        if (ram_sel) begin
            if (mem_wmask[0]) mem[word_addr][ 7: 0] <= mem_wdata[ 7: 0];
            if (mem_wmask[1]) mem[word_addr][15: 8] <= mem_wdata[15: 8];
            if (mem_wmask[2]) mem[word_addr][23:16] <= mem_wdata[23:16];
            if (mem_wmask[3]) mem[word_addr][31:24] <= mem_wdata[31:24];
            bram_rdata <= mem[word_addr];
        end
    end

    // ── UART at 0x400000 ─────────────────────────────────────────────────
    wire uart_valid, uart_busy;
    wire [7:0] uart_rx_data;

    // rd pulses when CPU loads from IO address — acknowledges the RX byte
    wire uart_rd = io_sel & mem_rstrb;
    // wr pulses during EXECUTE on a store to IO address
    wire uart_wr = io_sel & |mem_wmask;

    buart #(.CLKFREQ(12_000_000)) uart0 (
        .clk    (CLK),
        .resetq (resetn),
        .baud   (32'd115200),
        .rx     (RXD),
        .tx     (TXD),
        .rd     (uart_rd),
        .wr     (uart_wr),
        .valid  (uart_valid),
        .busy   (uart_busy),
        .tx_data(mem_wdata[7:0]),
        .rx_data(uart_rx_data)
    );

    wire [31:0] io_rdata = {22'b0, uart_busy, uart_valid, uart_rx_data};

    // ── Read mux ─────────────────────────────────────────────────────────
    assign mem_rdata = ram_sel ? bram_rdata : io_rdata;

    // ── LEDs ─────────────────────────────────────────────────────────────
    assign LEDS[0] = uart_valid;   // RX byte waiting
    assign LEDS[1] = uart_busy;    // TX transmitting

endmodule
