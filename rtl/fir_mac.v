`timescale 1ns/1ps
// =============================================================================================
// fir_mac : time-multiplexed (serial multiply-accumulate) FIR with selectable coefficient
//           banks and optional decimation
// ---------------------------------------------------------------------------------------------
//   y[m] = sat_DW( (sum_k h_b[k] * x[n-k] + 2^(S-1)) >>> S ),   S = CFRAC + s_b
//   n = m*DECIM + DECIM-1      (an output after every DECIM-th input)
//
// One multiplier (one DSP48E1 on Artix-7) computes all NTAPS products of an output in NTAPS
// clocks. At 100 MHz and 50 kHz there are 2000 clocks per sample; 511 taps use 517 of them.
//
// Datapath, one product per clock:
//   address -> sample RAM / coefficient ROM (1 clk) -> A,B regs -> M = A*B -> ACC += M
//           -> ACC + rounding constant -> shift by S and saturate -> out_data
// * Sample delay line: circular buffer in a simple-dual-port RAM (block RAM).
// * Coefficients: external ROM (coef_rom_*.v), address {bank, tap}, 1-clock latency.
// * After reset or `clr` the delay line is overwritten with zeros (2^AW clocks) so that
//   hardware and model start from the same state.
// * An input that arrives while the filter is busy is lost; `overrun` pulses so it is seen.
// Bit-exact model: model/golden.py::fir()
// =============================================================================================
`default_nettype none
module fir_mac #(
    parameter NTAPS  = 511,
    parameter AW     = 9,                // 2^AW >= NTAPS
    parameter DW     = 24,               // data width
    parameter CW     = 18,               // coefficient width
    parameter CFRAC  = 16,               // coefficient fraction bits (Q2.16)
    parameter ACC_W  = 48,               // accumulator width
    parameter DECIM  = 1,                // decimation factor (1 or 2)
    parameter BW     = 2,                // bank-select bits (>= 1)
    parameter SHIFTS = 16'h0000          // extra scaling s_b per bank, 4 bits each, bank 0 = LSBs
) (
    // ------------------------------------------------------------------------ ports
    input  wire                 clk,
    input  wire                 rst,
    input  wire                 clr,       // clear the delay line, restart
    input  wire [BW-1:0]        bank,
    input  wire                 in_valid,
    input  wire signed [DW-1:0] in_data,
    output reg                  out_valid,
    output reg  signed [DW-1:0] out_data,
    output wire                 ready,     // in_valid is accepted this cycle
    output reg                  overrun,   // pulse: in_valid arrived while not ready
    // coefficient ROM interface (data arrives one clock after the address)
    output wire [BW+AW-1:0]     coef_addr,
    input  wire signed [CW-1:0] coef_data
);
    // ------------------------------------------------------------------------ localparams
    localparam DEPTH = 1 << AW;
    localparam KW    = $clog2(NTAPS + 1);
    localparam DCW   = (DECIM > 1) ? $clog2(DECIM) : 1;
    localparam PW    = DW + CW;            // full product width
    localparam integer   DLAST_I = DECIM - 1;      // last decimation phase
    localparam integer   KLAST_I = NTAPS - 1;      // last tap index
    localparam [KW-1:0]  KLAST   = KLAST_I[KW-1:0];
    localparam [DCW-1:0] DLAST   = DLAST_I[DCW-1:0];
    localparam [5:0]     CFRAC6 = CFRAC;
    localparam [1:0] S_CLEAR = 2'd0, S_IDLE = 2'd1, S_MAC = 2'd2, S_DRAIN = 2'd3;
    localparam signed [ACC_W-1:0] SAT_HI = (1 << (DW - 1)) - 1;
    localparam signed [ACC_W-1:0] SAT_LO = -(1 << (DW - 1));

    // ------------------------------------------------------------------------ registers
    reg [1:0]       state_q,  state_d;
    reg [AW-1:0]    clr_q,    clr_d;       // clear address
    reg [AW-1:0]    wp_q,     wp_d;        // write pointer (next free slot)
    reg [AW-1:0]    newest_q, newest_d;    // address of the newest sample
    reg [DCW-1:0]   dcnt_q,   dcnt_d;      // decimation counter
    reg [KW-1:0]    k_q,      k_d;         // tap index
    reg [BW-1:0]    bank_q,   bank_d;      // bank latched for this output
    reg [5:0]       sh_q,     sh_d;        // total shift S
    reg [3:0]       drain_q,  drain_d;
    reg [2:0]       v_q, v_d, f_q, f_d;            // valid / first flags, stages 0..2
    reg [3:0]       l_q, l_d;                      // last flag, stages 0..3
    reg             rnd_v_q,  rnd_v_d;
    reg signed [CW-1:0]    b_q,   b_d;
    reg signed [DW-1:0]    a_q,   a_d;
    reg signed [PW-1:0]    m_q,   m_d;
    reg signed [ACC_W-1:0] acc_q, acc_d;
    reg signed [ACC_W-1:0] rnd_q, rnd_d;
    reg                    out_valid_d, overrun_d;
    reg signed [DW-1:0]    out_data_d;

    // sample RAM
    (* ram_style = "block" *) reg signed [DW-1:0] dmem [0:DEPTH-1];
    reg signed [DW-1:0] rd_q;                    // RAM read data (1-clock latency)

    // ------------------------------------------------------------------------ wires
    wire                  issue  = (state_q == S_MAC);
    wire                  last   = issue && (k_q == KLAST);
    wire                  accept = (state_q == S_IDLE) && in_valid && !clr;
    wire                  we     = (state_q == S_CLEAR) || accept;
    wire [AW-1:0]         waddr  = (state_q == S_CLEAR) ? clr_q : wp_q;
    wire signed [DW-1:0]  wdata  = (state_q == S_CLEAR) ? {DW{1'b0}} : in_data;
    wire [AW-1:0]         raddr  = newest_q - k_q[AW-1:0];
    wire signed [ACC_W-1:0] m_ext   = {{(ACC_W-PW){m_q[PW-1]}}, m_q};
    wire signed [ACC_W-1:0] rnd_c   = {{(ACC_W-1){1'b0}}, 1'b1} << (sh_q - 1'b1);
    wire signed [ACC_W-1:0] shifted = rnd_q >>> sh_q;

    assign ready     = (state_q == S_IDLE) && !clr;
    assign coef_addr = {bank_q, k_q[AW-1:0]};

    // ------------------------------------------------------------------------ combinational
    always @(*) begin
        // defaults: hold
        state_d  = state_q;   clr_d   = clr_q;   wp_d   = wp_q;    newest_d = newest_q;
        dcnt_d   = dcnt_q;    k_d     = k_q;     bank_d = bank_q;  sh_d     = sh_q;
        drain_d  = drain_q;
        a_d = a_q;  b_d = b_q;  m_d = m_q;  acc_d = acc_q;  rnd_d = rnd_q;
        out_data_d  = out_data;
        out_valid_d = 1'b0;
        overrun_d   = in_valid && (state_q != S_IDLE) && !clr;

        // ---------------- control FSM
        if (clr) begin
            state_d = S_CLEAR;
            clr_d   = {AW{1'b0}};
            wp_d    = {AW{1'b0}};
            dcnt_d  = {DCW{1'b0}};
        end else begin
            case (state_q)
                S_CLEAR: begin
                    clr_d = clr_q + 1'b1;
                    if (clr_q == DEPTH - 1) state_d = S_IDLE;
                end
                S_IDLE: begin
                    if (in_valid) begin
                        newest_d = wp_q;
                        wp_d     = wp_q + 1'b1;
                        if (dcnt_q == DLAST) begin
                            dcnt_d  = {DCW{1'b0}};
                            k_d     = {KW{1'b0}};
                            bank_d  = bank;
                            sh_d    = CFRAC6 + {2'b00, SHIFTS[4*bank +: 4]};
                            state_d = S_MAC;
                        end else begin
                            dcnt_d = dcnt_q + 1'b1;
                        end
                    end
                end
                S_MAC: begin
                    k_d = k_q + 1'b1;
                    if (last) begin
                        state_d = S_DRAIN;
                        drain_d = 4'd0;
                    end
                end
                S_DRAIN: begin
                    drain_d = drain_q + 1'b1;
                    if (drain_q == 4'd7) state_d = S_IDLE;
                end
                default: state_d = S_CLEAR;
            endcase
        end

        // ---------------- MAC pipeline flags (bit i: stage i holds valid data)
        //   v[0]: rd_q / coef_data   v[1]: a_q / b_q   v[2]: m_q   l[3]: acc_q complete
        v_d     = {v_q[1:0], issue};
        f_d     = {f_q[1:0], issue && (k_q == {KW{1'b0}})};
        l_d     = {l_q[2:0], last};
        rnd_v_d = l_q[3];

        if (v_q[0]) begin
            a_d = rd_q;
            b_d = coef_data;
        end
        if (v_q[1]) m_d   = a_q * b_q;
        if (v_q[2]) acc_d = f_q[2] ? m_ext : (acc_q + m_ext);
        if (l_q[3]) rnd_d = acc_q + rnd_c;            // add rounding constant 2^(S-1)
        if (rnd_v_q) begin                            // shift and saturate
            out_valid_d = 1'b1;
            if (shifted > SAT_HI)      out_data_d = SAT_HI[DW-1:0];
            else if (shifted < SAT_LO) out_data_d = SAT_LO[DW-1:0];
            else                       out_data_d = shifted[DW-1:0];
        end
    end

    // ------------------------------------------------------------------------ sequential: RAM
    // (standard simple-dual-port block-RAM template)
    always @(posedge clk) begin
        if (we) dmem[waddr] <= wdata;
        rd_q <= dmem[raddr];
    end

    // ------------------------------------------------------------------------ sequential: registers
    always @(posedge clk) begin
        if (rst) begin
            state_q <= S_CLEAR;   clr_q <= {AW{1'b0}};  wp_q <= {AW{1'b0}};  newest_q <= {AW{1'b0}};
            dcnt_q  <= {DCW{1'b0}}; k_q <= {KW{1'b0}};  bank_q <= {BW{1'b0}}; sh_q <= CFRAC6;
            drain_q <= 4'd0;
            v_q <= 3'd0;  f_q <= 3'd0;  l_q <= 4'd0;  rnd_v_q <= 1'b0;
            a_q <= {DW{1'b0}};  b_q <= {CW{1'b0}};  m_q <= {PW{1'b0}};
            acc_q <= {ACC_W{1'b0}};  rnd_q <= {ACC_W{1'b0}};
            out_valid <= 1'b0;  out_data <= {DW{1'b0}};  overrun <= 1'b0;
        end else begin
            state_q <= state_d;   clr_q <= clr_d;       wp_q <= wp_d;         newest_q <= newest_d;
            dcnt_q  <= dcnt_d;    k_q <= k_d;           bank_q <= bank_d;     sh_q <= sh_d;
            drain_q <= drain_d;
            v_q <= v_d;  f_q <= f_d;  l_q <= l_d;  rnd_v_q <= rnd_v_d;
            a_q <= a_d;  b_q <= b_d;  m_q <= m_d;
            acc_q <= acc_d;  rnd_q <= rnd_d;
            out_valid <= out_valid_d;  out_data <= out_data_d;  overrun <= overrun_d;
        end
    end
endmodule
`default_nettype wire
