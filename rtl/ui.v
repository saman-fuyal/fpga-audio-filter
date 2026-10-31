`timescale 1ns/1ps
// =============================================================================================
// ui.v : board user interface - LED level meter and 8-digit seven-segment status display
// =============================================================================================
`default_nettype none

// ---------------------------------------------------------------------------------------------
// vu_meter : 16-LED log-scale peak meter, 6 dB per LED (LED i on when |x| >= 2^i),
// LED15 = clip (|x| >= 32000). Peak decays by 1/8 every 256 samples (~5 ms at 50 kHz).
// ---------------------------------------------------------------------------------------------
module vu_meter (
    // ------------------------------------------------------------------------ ports
    input  wire               clk,
    input  wire               rst,
    input  wire               in_valid,
    input  wire signed [15:0] in_data,
    output reg  [15:0]        led
);
    // ------------------------------------------------------------------------ registers / wires
    reg  [15:0] peak_q, peak_d;
    reg  [7:0]  dcnt_q, dcnt_d;
    reg  [15:0] led_d;
    reg  [15:0] mag;
    integer     i;

    // ------------------------------------------------------------------------ combinational
    always @(*) begin
        // magnitude (|-32768| clipped to 32767)
        if (!in_data[15])               mag = in_data;
        else if (in_data == 16'h8000)   mag = 16'h7FFF;
        else                            mag = -in_data;

        peak_d = peak_q;
        dcnt_d = dcnt_q;
        if (in_valid) begin
            dcnt_d = dcnt_q + 1'b1;
            if (mag > peak_q)         peak_d = mag;
            else if (&dcnt_q)         peak_d = peak_q - (peak_q >> 3);
        end

        for (i = 0; i < 15; i = i + 1)
            led_d[i] = (peak_q >= (16'd1 << i));
        led_d[15] = (peak_q >= 16'd32000);
    end

    // ------------------------------------------------------------------------ sequential
    always @(posedge clk) begin
        if (rst) begin
            peak_q <= 16'd0;  dcnt_q <= 8'd0;  led <= 16'd0;
        end else begin
            peak_q <= peak_d; dcnt_q <= dcnt_d; led <= led_d;
        end
    end
endmodule

// ---------------------------------------------------------------------------------------------
// seg7_status : multiplexed 8-digit display, left to right:
//     b <bank>   G <gain tens><gain ones>   <H|L> <P|d>
//   H/L = PDM sampling half (SW6), P/d = PWM or delta-sigma output (SW7)
//   during a UART test the right half shows "tESt-"
// Each digit is lit for 2^(REFRESH_BITS-3) clocks (164 us at 100 MHz): ~760 Hz full scan.
// Segments and anodes are active low on the Nexys A7.
// ---------------------------------------------------------------------------------------------
module seg7_status #(
    parameter REFRESH_BITS = 17
) (
    // ------------------------------------------------------------------------ ports
    input  wire       clk,
    input  wire       rst,
    input  wire [2:0] bank,
    input  wire [3:0] gain,
    input  wire       phase_lo,
    input  wire       sdm,
    input  wire       test,
    output reg  [6:0] seg_n,             // {g,f,e,d,c,b,a}, active low
    output reg        dp_n,
    output reg  [7:0] an_n
);
    // ------------------------------------------------------------------------ localparams
    // glyphs, bit order {g,f,e,d,c,b,a}, active high
    localparam [6:0] G_0 = 7'b0111111, G_1 = 7'b0000110, G_2 = 7'b1011011, G_3 = 7'b1001111,
                     G_4 = 7'b1100110, G_5 = 7'b1101101, G_6 = 7'b1111101, G_7 = 7'b0000111,
                     G_8 = 7'b1111111, G_9 = 7'b1101111, G_b = 7'b1111100, G_G = 7'b0111101,
                     G_H = 7'b1110110, G_L = 7'b0111000, G_P = 7'b1110011, G_d = 7'b1011110,
                     G_DASH = 7'b1000000, G_OFF = 7'b0000000, G_t = 7'b1111000,
                     G_E = 7'b1111001, G_S = 7'b1101101;

    // ------------------------------------------------------------------------ registers / wires
    reg  [REFRESH_BITS-1:0] rcnt_q;
    wire [2:0] pos  = rcnt_q[REFRESH_BITS-1 -: 3];
    wire [3:0] tens = (gain >= 4'd10) ? 4'd1 : 4'd0;
    wire [3:0] ones = (gain >= 4'd10) ? (gain - 4'd10) : gain;
    reg  [6:0] glyph, g_bank, g_tens, g_ones;
    reg  [REFRESH_BITS-1:0] rcnt_d;
    reg  [6:0] seg_d;
    reg  [7:0] an_d;

    // decimal digit -> glyph
    function [6:0] digit;
        input [3:0] v;
        begin
            case (v)
                4'd0: digit = G_0;  4'd1: digit = G_1;  4'd2: digit = G_2;  4'd3: digit = G_3;
                4'd4: digit = G_4;  4'd5: digit = G_5;  4'd6: digit = G_6;  4'd7: digit = G_7;
                4'd8: digit = G_8;  4'd9: digit = G_9;
                default: digit = G_DASH;
            endcase
        end
    endfunction

    // ------------------------------------------------------------------------ combinational
    always @(*) begin
        g_bank = digit({1'b0, bank});
        g_tens = digit(tens);
        g_ones = digit(ones);
        case (pos)
            3'd7:    glyph = G_b;
            3'd6:    glyph = g_bank;
            3'd5:    glyph = G_OFF;
            3'd4:    glyph = test ? G_t    : G_G;
            3'd3:    glyph = test ? G_E    : g_tens;
            3'd2:    glyph = test ? G_S    : g_ones;
            3'd1:    glyph = test ? G_t    : (phase_lo ? G_L : G_H);
            default: glyph = test ? G_DASH : (sdm ? G_d : G_P);
        endcase
        rcnt_d = rcnt_q + 1'b1;
        seg_d  = ~glyph;
        an_d   = ~(8'd1 << pos);
    end

    // ------------------------------------------------------------------------ sequential
    always @(posedge clk) begin
        if (rst) begin
            rcnt_q <= {REFRESH_BITS{1'b0}};
            seg_n  <= 7'h7F;
            an_n   <= 8'hFF;
            dp_n   <= 1'b1;
        end else begin
            rcnt_q <= rcnt_d;
            seg_n  <= seg_d;
            an_n   <= an_d;
            dp_n   <= 1'b1;
        end
    end
endmodule
`default_nettype wire
