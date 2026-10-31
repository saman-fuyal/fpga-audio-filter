`timescale 1ns/1ps
// =============================================================================================
// pdm_rx : PDM microphone interface for the ADMP421 on the Nexys A7
// ---------------------------------------------------------------------------------------------
// * Generates M_CLK = clk / DIV from a register (no derived clock: the whole design stays in
//   the 100 MHz domain, M_CLK is only a data output).
// * The microphone drives DATA during one half of the M_CLK period and releases the line
//   (high impedance) in the other half, because it is a stereo-capable part. DATA is sampled,
//   after a 2-flop synchronizer, near the END of the selected half for the largest margin.
//   phase_lo = 0 : end of the high half (default)   phase_lo = 1 : end of the low half
//   With phase_lo = 1 the line is read while the microphone has released it; on the Nexys A7
//   the line keeps its last driven value, so both settings return valid bits.
// * Emits one bit_valid strobe per M_CLK period (2.5 MHz).
//
// Timing (DIV = 40, S_HI = 38): M_CLK rises when cnt goes 20 -> 21; the synchronizer adds
// 2 clocks, so the pin is effectively sampled at cnt ~36 (150 ns after the rising edge,
// 50 ns before the falling edge).
// =============================================================================================
`default_nettype none
module pdm_rx #(
    parameter DIV  = 40,                 // M_CLK divider (even)
    parameter S_HI = 38,                 // sample count, high half
    parameter S_LO = 18                  // sample count, low half
) (
    // ------------------------------------------------------------------------ ports
    input  wire clk,
    input  wire rst,                     // synchronous, active high
    input  wire phase_lo,                // 0: high half, 1: low half
    input  wire m_data_async,            // pin M_DATA
    (* IOB = "TRUE" *)
    output reg  m_clk,                   // pin M_CLK (flop packed into the I/O tile)
    output reg  bit_valid,               // one strobe per PDM bit
    output reg  bit_out                  // the PDM bit
);
    // ------------------------------------------------------------------------ localparams / wires
    localparam CW = $clog2(DIV);

    reg  [CW-1:0] cnt_q, cnt_d;
    reg           m_clk_d, bit_valid_d, bit_out_d;
    wire          m_data_s;              // synchronized DATA

    sync2 #(.W(1)) u_sync (.clk(clk), .d(m_data_async), .q(m_data_s));

    // ------------------------------------------------------------------------ combinational
    always @(*) begin
        if (cnt_q == DIV - 1) cnt_d = {CW{1'b0}};
        else                  cnt_d = cnt_q + 1'b1;
        m_clk_d     = (cnt_q >= DIV / 2);
        bit_valid_d = phase_lo ? (cnt_q == S_LO) : (cnt_q == S_HI);
        bit_out_d   = m_data_s;
    end

    // ------------------------------------------------------------------------ sequential
    always @(posedge clk) begin
        if (rst) begin
            cnt_q     <= {CW{1'b0}};
            m_clk     <= 1'b0;
            bit_valid <= 1'b0;
            bit_out   <= 1'b0;
        end else begin
            cnt_q     <= cnt_d;
            m_clk     <= m_clk_d;
            bit_valid <= bit_valid_d;
            bit_out   <= bit_out_d;
        end
    end
endmodule
`default_nettype wire
