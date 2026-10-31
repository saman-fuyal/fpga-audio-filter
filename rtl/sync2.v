`timescale 1ns/1ps
// =============================================================================================
// sync2 : two-flop synchronizer
// ---------------------------------------------------------------------------------------------
// Brings an asynchronous input (switch, button, UART RX, microphone DATA) into the 100 MHz
// clock domain. The first flop may go metastable; the second gives it one full clock period
// to settle, which makes the failure probability negligible at these rates.
// Each bit is synchronized on its own, so use it only for signals whose bits do not have to
// change together (true for every use in this design).
// No reset and no initial value: the flops simply follow the input after two clocks.
// =============================================================================================
`default_nettype none
module sync2 #(
    parameter W = 1                      // number of independent bits
) (
    // ------------------------------------------------------------------------ ports
    input  wire         clk,
    input  wire [W-1:0] d,               // asynchronous input
    output wire [W-1:0] q                // synchronized output (2 clocks later)
);
    // ------------------------------------------------------------------------ registers
    (* ASYNC_REG = "TRUE" *) reg [W-1:0] s1_q;
    (* ASYNC_REG = "TRUE" *) reg [W-1:0] s2_q;

    // ------------------------------------------------------------------------ combinational
    assign q = s2_q;

    // ------------------------------------------------------------------------ sequential
    always @(posedge clk) begin
        s1_q <= d;
        s2_q <= s1_q;
    end
endmodule
`default_nettype wire
