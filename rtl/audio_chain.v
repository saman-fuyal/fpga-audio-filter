`timescale 1ns/1ps
// =============================================================================================
// audio_chain : the complete DSP chain
// ---------------------------------------------------------------------------------------------
//   PDM bit (2.5 MHz) -> CIC N=4 R=25 -> <<3 -> comp FIR 63 taps, /2 -> DC block
//        -> bank 0-3: 511-tap FIR (one DSP)  |  bank 4: 31-tap parallel FIR (ASIC core)
//        -> gain 2^g with saturation -> top 16 bits                          @ 50 kHz
//
// Test hooks used by the UART command controller:
//   * bit_valid/bit_in can come from the microphone or the host ('D' command)
//   * inj_sel feeds the FIR input from the host instead of the DC blocker ('T' command)
// Every stage is bit-exact with model/golden.py::chain().
// =============================================================================================
`default_nettype none
`include "af_params.vh"
module audio_chain (
    // ------------------------------------------------------------------------ ports
    input  wire                         clk,
    input  wire                         rst,
    input  wire                         clr,         // clears every stage (restart)
    input  wire [2:0]                   bank,        // 0-3 main FIR banks, 4 parallel FIR
    input  wire [3:0]                   gain,        // digital gain 2^gain
    // PDM input
    input  wire                         bit_valid,
    input  wire                         bit_in,
    // FIR injection (test)
    input  wire                         inj_sel,
    input  wire                         inj_valid,
    input  wire signed [`AF_DW-1:0]     inj_data,
    // outputs
    output wire                         fir_valid,   // selected FIR output (24 bit), for 'T'
    output wire signed [`AF_DW-1:0]     fir_data,
    output reg                          out_valid,   // final 16-bit audio sample
    output reg  signed [`AF_OUT_W-1:0]  out_data,
    output reg                          overrun      // a FIR lost a sample (pulse)
);
    // ------------------------------------------------------------------------ localparams
    localparam DW  = `AF_DW;
    localparam OW  = `AF_OUT_W;
    localparam GW  = DW + 16;                        // gain stage width
    localparam CIC_W = `AF_CIC_W;
    localparam signed [GW-1:0] SAT_HI = (1 << (DW - 1)) - 1;
    localparam signed [GW-1:0] SAT_LO = -(1 << (DW - 1));

    // ------------------------------------------------------------------------ wires
    wire                    srst = rst | clr;
    wire                    cic_v;
    wire [CIC_W-1:0]        cic_d;
    wire signed [DW-1:0]    cic_s;
    wire                    comp_v, comp_ovr;
    /* verilator lint_off UNUSEDSIGNAL */
    wire                    comp_rdy, main_rdy;  // ready flags: only used by the unit testbench
    /* verilator lint_on UNUSEDSIGNAL */
    wire signed [DW-1:0]    comp_d;
    /* verilator lint_off UNUSEDSIGNAL */
    wire [6:0]              comp_caddr;          // bit 6 = bank bit, always 0 (one bank)
    /* verilator lint_on UNUSEDSIGNAL */
    wire signed [`AF_CW-1:0] comp_cdata;
    wire                    dc_v;
    wire signed [DW-1:0]    dc_d;
    wire                    f_in_v;
    wire signed [DW-1:0]    f_in_d;
    wire                    main_v, main_ovr;
    wire signed [DW-1:0]    main_d;
    wire [`AF_MAIN_AW+1:0]  main_caddr;
    wire signed [`AF_CW-1:0] main_cdata;
    wire                    par_v;
    wire signed [15:0]      par_d;
    wire                    use_par = (bank == 3'd4);
    wire signed [GW-1:0]    gx;
    reg                     out_valid_d, overrun_d;
    reg  signed [OW-1:0]    out_data_d;
    /* verilator lint_off UNUSEDSIGNAL */
    reg  signed [DW-1:0]    gsat;                // only the top 16 bits are kept
    /* verilator lint_on UNUSEDSIGNAL */

    // ------------------------------------------------------------------------ CIC decimator
    cic_decim #(.N(`AF_CIC_N), .R(`AF_CIC_R), .W(CIC_W)) u_cic (
        .clk(clk), .rst(srst), .in_valid(bit_valid), .in_bit(bit_in),
        .out_valid(cic_v), .out_data(cic_d));

    // sign-extend to 24 bits and scale by 2^3
    assign cic_s = {{(DW-CIC_W-`AF_CIC_SHIFT){cic_d[CIC_W-1]}}, cic_d, {`AF_CIC_SHIFT{1'b0}}};

    // ------------------------------------------------------------------------ compensation FIR (/2)
    fir_mac #(.NTAPS(`AF_COMP_TAPS), .AW(`AF_COMP_AW), .DW(DW), .CW(`AF_CW), .CFRAC(`AF_CFRAC),
              .ACC_W(`AF_ACC_W), .DECIM(`AF_COMP_DECIM), .BW(1), .SHIFTS(`AF_COMP_SHIFT)) u_comp (
        .clk(clk), .rst(rst), .clr(clr), .bank(1'b0), .in_valid(cic_v), .in_data(cic_s),
        .out_valid(comp_v), .out_data(comp_d), .ready(comp_rdy), .overrun(comp_ovr),
        .coef_addr(comp_caddr), .coef_data(comp_cdata));
    coef_rom_comp u_comp_rom (.clk(clk), .addr(comp_caddr[`AF_COMP_AW-1:0]), .q(comp_cdata));

    // ------------------------------------------------------------------------ DC blocker
    dc_block #(.DW(DW), .K(`AF_DC_K)) u_dc (
        .clk(clk), .rst(srst), .in_valid(comp_v), .in_data(comp_d),
        .out_valid(dc_v), .out_data(dc_d));

    // ------------------------------------------------------------------------ filter input select
    assign f_in_v = inj_sel ? inj_valid : dc_v;
    assign f_in_d = inj_sel ? inj_data  : dc_d;

    // ------------------------------------------------------------------------ 511-tap FIR, 4 banks
    fir_mac #(.NTAPS(`AF_MAIN_TAPS), .AW(`AF_MAIN_AW), .DW(DW), .CW(`AF_CW), .CFRAC(`AF_CFRAC),
              .ACC_W(`AF_ACC_W), .DECIM(1), .BW(2), .SHIFTS(`AF_MAIN_SHIFTS)) u_main (
        .clk(clk), .rst(rst), .clr(clr), .bank(bank[1:0]), .in_valid(f_in_v), .in_data(f_in_d),
        .out_valid(main_v), .out_data(main_d), .ready(main_rdy), .overrun(main_ovr),
        .coef_addr(main_caddr), .coef_data(main_cdata));
    coef_rom_main u_main_rom (.clk(clk), .addr(main_caddr), .q(main_cdata));

    // ------------------------------------------------------------------------ 31-tap parallel FIR (ASIC core)
    fir_par #(.PIPE(1)) u_par (
        .clk(clk), .rst_n(~srst), .in_valid(f_in_v), .in_data(f_in_d[DW-1 -: 16]),
        .out_valid(par_v), .out_data(par_d));

    assign fir_valid = use_par ? par_v : main_v;
    assign fir_data  = use_par ? {par_d, {(DW-16){1'b0}}} : main_d;

    // ------------------------------------------------------------------------ combinational: gain
    assign gx = {{(GW-DW){fir_data[DW-1]}}, fir_data} <<< gain;

    always @(*) begin
        if (gx > SAT_HI)      gsat = SAT_HI[DW-1:0];
        else if (gx < SAT_LO) gsat = SAT_LO[DW-1:0];
        else                  gsat = gx[DW-1:0];
        out_valid_d = fir_valid;
        out_data_d  = fir_valid ? gsat[DW-1 -: OW] : out_data;   // keep the top 16 bits
        overrun_d   = comp_ovr | main_ovr;
    end

    // ------------------------------------------------------------------------ sequential
    always @(posedge clk) begin
        if (srst) begin
            out_valid <= 1'b0;
            out_data  <= {OW{1'b0}};
            overrun   <= 1'b0;
        end else begin
            out_valid <= out_valid_d;
            out_data  <= out_data_d;
            overrun   <= overrun_d;
        end
    end
endmodule
`default_nettype wire
