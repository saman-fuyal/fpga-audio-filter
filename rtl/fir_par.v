`timescale 1ns/1ps
// =============================================================================================
// fir_par : parallel symmetric (linear-phase) 31-tap FIR - the SAME file is used on the FPGA
//           (bank 4, SW8) and in the SKY130 ASIC flow (Project 3)
// ---------------------------------------------------------------------------------------------
//   x[n] shift register, 31 x 16 bit
//   pre[i]  = x[15-i] + x[15+i]   (pre[0] = x[15])   16 pre-adders: symmetry halves multipliers
//   prod[i] = pre[i] * coef(i)                        16 constant multipliers (shift/add)
//   sum     = adder tree 16 -> 8 -> 4 -> 2 -> 1
//   y       = sat16( (sum + 2^14) >>> 15 )
//
// PIPE = 0 : registers only on the input shift register and the output -> one long
//            combinational path (pre-add, multiply, 4 adder levels, round, saturate)
// PIPE = 1 : a register after the pre-adders, the multipliers and every adder level ->
//            critical path ~ one multiplier; latency 8 clocks
// Throughput is one sample per clock in both cases.
// Bit-exact model: asic/design_asic_fir.py::fir_model()
// =============================================================================================
`default_nettype none
module fir_par #(
    parameter PIPE = 1
) (
    // ------------------------------------------------------------------------ ports
    input  wire               clk,
    input  wire               rst_n,         // synchronous, active low
    input  wire               in_valid,
    input  wire signed [15:0] in_data,
    output reg                out_valid,
    output reg  signed [15:0] out_data
);
    `include "fir_par_coefs.vh"              // function coef(i), generated

    // ------------------------------------------------------------------------ localparams
    localparam N   = 31;                     // taps
    localparam H   = 16;                     // unique coefficients
    localparam PW  = 17;                     // pre-add width
    localparam MW  = PW + 16;                // product width
    localparam SW  = MW + 4;                 // adder-tree width (16 terms -> +4 bits)
    localparam LAT = (PIPE != 0) ? 7 : 1;    // clocks from x update to y ready

    // ------------------------------------------------------------------------ registers / wires
    reg  [N*16-1:0] x_q, x_d;                // x_q[j*16 +: 16] = x[n-j]
    reg  [LAT:0]    v_q, v_d;                // valid pipeline
    reg             out_valid_d;
    reg  signed [15:0] out_data_d;

    wire [H*PW-1:0] pre_c,  pre_s;           // _c combinational, _s as seen by the next stage
    wire [H*MW-1:0] prod_c, prod_s;
    wire [8*SW-1:0] l1_c,   l1_s;
    wire [4*SW-1:0] l2_c,   l2_s;
    wire [2*SW-1:0] l3_c,   l3_s;
    wire [SW-1:0]   l4_c,   l4_s;

    genvar g;

    // ------------------------------------------------------------------------ combinational: datapath
    // pre-adders
    assign pre_c[0 +: PW] = {x_q[15*16+15], x_q[15*16 +: 16]};
    generate
        for (g = 1; g < H; g = g + 1) begin : g_pre
            assign pre_c[g*PW +: PW] = $signed({x_q[(15-g)*16+15], x_q[(15-g)*16 +: 16]})
                                     + $signed({x_q[(15+g)*16+15], x_q[(15+g)*16 +: 16]});
        end
        // constant multipliers
        for (g = 0; g < H; g = g + 1) begin : g_mul
            assign prod_c[g*MW +: MW] = $signed(pre_s[g*PW +: PW]) * $signed(coef(g));
        end
        // adder tree
        for (g = 0; g < 8; g = g + 1) begin : g_l1
            assign l1_c[g*SW +: SW] = {{(SW-MW){prod_s[(2*g+1)*MW-1]}}, prod_s[(2*g)*MW +: MW]}
                                    + {{(SW-MW){prod_s[(2*g+2)*MW-1]}}, prod_s[(2*g+1)*MW +: MW]};
        end
        for (g = 0; g < 4; g = g + 1) begin : g_l2
            assign l2_c[g*SW +: SW] = l1_s[(2*g)*SW +: SW] + l1_s[(2*g+1)*SW +: SW];
        end
        for (g = 0; g < 2; g = g + 1) begin : g_l3
            assign l3_c[g*SW +: SW] = l2_s[(2*g)*SW +: SW] + l2_s[(2*g+1)*SW +: SW];
        end
    endgenerate
    assign l4_c = l3_s[0 +: SW] + l3_s[SW +: SW];

    // round (+2^14), arithmetic shift by 15, saturate to 16 bits
    wire signed [SW-1:0] rnd = ($signed(l4_s) + $signed({{(SW-15){1'b0}}, 15'h4000})) >>> 15;

    // ------------------------------------------------------------------------ combinational: control
    always @(*) begin
        x_d = x_q;
        if (in_valid) x_d = {x_q[(N-1)*16-1:0], in_data};
        v_d         = {v_q[LAT-1:0], in_valid};
        out_valid_d = v_q[LAT-1];
        out_data_d  = out_data;
        if (v_q[LAT-1]) begin
            if (rnd > 32767)       out_data_d = 16'sh7FFF;
            else if (rnd < -32768) out_data_d = 16'sh8000;
            else                   out_data_d = rnd[15:0];
        end
    end

    // ------------------------------------------------------------------------ sequential: pipeline (PIPE = 1 only)
    generate
        if (PIPE != 0) begin : g_pipe
            reg [H*PW-1:0] pre_q;
            reg [H*MW-1:0] prod_q;
            reg [8*SW-1:0] l1_q;
            reg [4*SW-1:0] l2_q;
            reg [2*SW-1:0] l3_q;
            reg [SW-1:0]   l4_q;
            always @(posedge clk) begin
                pre_q  <= pre_c;
                prod_q <= prod_c;
                l1_q   <= l1_c;
                l2_q   <= l2_c;
                l3_q   <= l3_c;
                l4_q   <= l4_c;
            end
            assign pre_s  = pre_q;
            assign prod_s = prod_q;
            assign l1_s   = l1_q;
            assign l2_s   = l2_q;
            assign l3_s   = l3_q;
            assign l4_s   = l4_q;
        end else begin : g_comb
            assign pre_s  = pre_c;
            assign prod_s = prod_c;
            assign l1_s   = l1_c;
            assign l2_s   = l2_c;
            assign l3_s   = l3_c;
            assign l4_s   = l4_c;
        end
    endgenerate

    // ------------------------------------------------------------------------ sequential: registers
    always @(posedge clk) begin
        if (!rst_n) begin
            x_q       <= {(N*16){1'b0}};
            v_q       <= {(LAT+1){1'b0}};
            out_valid <= 1'b0;
            out_data  <= 16'sd0;
        end else begin
            x_q       <= x_d;
            v_q       <= v_d;
            out_valid <= out_valid_d;
            out_data  <= out_data_d;
        end
    end
endmodule
`default_nettype wire
