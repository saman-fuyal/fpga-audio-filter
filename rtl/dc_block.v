`timescale 1ns/1ps
// =============================================================================================
// dc_block : first-order DC-blocking high-pass, no multiplier
// ---------------------------------------------------------------------------------------------
//   est = acc >>> K ;   y = sat(x - est) ;   acc <= acc + (x - est)
// The accumulator is a leaky integrator that tracks the DC level of x (scaled by 2^K).
// Pole at z = 1 - 2^-K  ->  corner ~ fs / (2*pi*2^K) = 7.8 Hz at 50 kHz for K = 10.
// MEMS microphones and the CIC produce a DC offset; without this block the digital gain
// stage would saturate on the offset long before the audio is loud enough.
// Bit-exact model: model/golden.py::dc_block()
// =============================================================================================
`default_nettype none
module dc_block #(
    parameter DW = 24,
    parameter K  = 10
) (
    // ------------------------------------------------------------------------ ports
    input  wire                 clk,
    input  wire                 rst,
    input  wire                 in_valid,
    input  wire signed [DW-1:0] in_data,
    output reg                  out_valid,
    output reg  signed [DW-1:0] out_data
);
    // ------------------------------------------------------------------------ localparams / wires
    localparam AW = DW + K + 2;          // accumulator width
    localparam signed [AW-1:0] SAT_HI = (1 << (DW - 1)) - 1;
    localparam signed [AW-1:0] SAT_LO = -(1 << (DW - 1));

    reg  signed [AW-1:0] acc_q, acc_d;
    reg  signed [DW-1:0] out_data_d;
    reg                  out_valid_d;

    wire signed [AW-1:0] x_ext = {{(AW-DW){in_data[DW-1]}}, in_data};
    wire signed [AW-1:0] est   = acc_q >>> K;
    wire signed [AW-1:0] diff  = x_ext - est;

    // ------------------------------------------------------------------------ combinational
    always @(*) begin
        acc_d       = acc_q;
        out_data_d  = out_data;
        out_valid_d = in_valid;
        if (in_valid) begin
            acc_d = acc_q + diff;
            if (diff > SAT_HI)      out_data_d = SAT_HI[DW-1:0];
            else if (diff < SAT_LO) out_data_d = SAT_LO[DW-1:0];
            else                    out_data_d = diff[DW-1:0];
        end
    end

    // ------------------------------------------------------------------------ sequential
    always @(posedge clk) begin
        if (rst) begin
            acc_q     <= {AW{1'b0}};
            out_valid <= 1'b0;
            out_data  <= {DW{1'b0}};
        end else begin
            acc_q     <= acc_d;
            out_valid <= out_valid_d;
            out_data  <= out_data_d;
        end
    end
endmodule
`default_nettype wire
