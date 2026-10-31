`timescale 1ns/1ps
// =============================================================================================
// top_nexys_a7 : real-time audio filter on the Digilent Nexys A7-50T (XC7A50T; the 100T works
//                unchanged). Single 100 MHz clock domain.
// ---------------------------------------------------------------------------------------------
//   mic (ADMP421 PDM) -> CIC -> comp FIR -> DC block -> FIR (4 banks + ASIC core) -> gain
//        -> PWM / delta-sigma -> AUD_PWM (open drain) -> on-board 4th-order LPF -> jack
//
// Controls
//   SW[1:0]   filter bank: 0 bypass, 1 low-pass 1 kHz, 2 high-pass 2 kHz, 3 band-pass 0.4-3.4 kHz
//   SW[8]     1 = use the 31-tap parallel FIR (the same RTL as the SKY130 chip), overrides SW[1:0]
//   SW[5:2]   digital gain 2^g, g = 0..15 (0..90 dB)
//   SW[6]     PDM sampling half: 0 = end of the M_CLK high phase (default), 1 = low phase
//   SW[7]     output modulator: 0 = PWM 97.7 kHz, 1 = first-order delta-sigma
//   SW[15]    audio amplifier enable (AUD_SD) - keep OFF until the gain is set
//   BTNC      clear the sticky error LED
//   CPU_RESETN reset
// Indicators
//   LED[15:0] level meter (6 dB/LED, LED15 = clip)
//   LED16 red = sticky error (sample overrun / UART framing / protocol), green = heartbeat
//   LED17 blue = UART test or capture in progress
//   7-seg: "b<bank> G<gain> <H|L><P|d>"
// UART: 1 Mbaud 8N1 through the USB-UART port (host/af_host.py)
// =============================================================================================
`default_nettype none
`include "af_params.vh"
module top_nexys_a7 #(
    parameter CAP_AW       = `AF_CAP_AW,     // capture depth (testbench uses less)
    parameter REFRESH_BITS = 17,             // 7-seg refresh
    parameter POR_BITS     = 16,             // power-on reset length 2^16 clocks
    parameter WDOG_BITS    = 24              // UART command watchdog
) (
    // ------------------------------------------------------------------------ ports
    input  wire        CLK100MHZ,
    input  wire        CPU_RESETN,
    input  wire [15:0] SW,
    input  wire        BTNC,
    output wire [15:0] LED,
    output wire        LED16_R,
    output wire        LED16_G,
    output wire        LED17_B,
    // PDM microphone
    output wire        M_CLK,
    input  wire        M_DATA,
    output wire        M_LRSEL,
    // mono audio out
    output wire        AUD_PWM,
    output reg         AUD_SD,
    // USB-UART (names from the FPGA's point of view, as in the Digilent XDC)
    input  wire        UART_TXD_IN,
    output wire        UART_RXD_OUT,
    // seven-segment display
    output wire        CA, CB, CC, CD, CE, CF, CG, DP,
    output wire [7:0]  AN
);
    // ------------------------------------------------------------------------ localparams
    localparam CPB = `AF_F_SYS / `AF_BAUD;   // UART clocks per bit

    // ------------------------------------------------------------------------ wires / registers
    wire                 clk = CLK100MHZ;
    wire                 rst_btn;
    reg  [POR_BITS-1:0]  por_q, por_d;
    reg                  rst, rst_d;
    wire [15:0]          sw_s;            // synchronized switches
    wire                 btnc_s;          // synchronized centre button
    // microphone
    wire                 mic_v, mic_b;
    // UART
    wire                 rx_v, rx_ferr;
    wire [7:0]           rx_d;
    wire                 f_push, f_empty, f_afull, tx_rdy;
    /* verilator lint_off UNUSEDSIGNAL */
    wire                 f_full;             // exact full flag; the writer uses f_afull instead
    /* verilator lint_on UNUSEDSIGNAL */
    wire [7:0]           f_din, f_dout;
    // command controller
    wire [1:0]           mode;
    wire [2:0]           t_bank;
    wire [3:0]           t_gain;
    wire                 chain_clr, ib_v, ib_b, inj_v, cap_busy, cmd_err;
    wire signed [`AF_DW-1:0]    inj_d, fir_d;
    wire                 fir_v, out_v, ovr;
    wire signed [`AF_OUT_W-1:0] out_d;
    // chain control
    wire                 live      = (mode == 2'd0);
    wire [2:0]           live_bank = sw_s[8] ? 3'd4 : {1'b0, sw_s[1:0]};
    wire [2:0]           bank      = live ? live_bank : t_bank;
    wire [3:0]           gain      = live ? sw_s[5:2]   : t_gain;
    wire                 c_bit_v   = (mode == 2'd2) ? ib_v : mic_v;
    wire                 c_bit     = (mode == 2'd2) ? ib_b : mic_b;
    // audio out
    wire                 dac;
    wire                 dac_in_v  = live ? out_v : 1'b1;              // test/amp off: hold 0
    wire signed [`AF_OUT_W-1:0] dac_in_d = (live && sw_s[15]) ? out_d : {`AF_OUT_W{1'b0}};
    reg                  aud_sd_d;
    // status
    reg                  err_q, err_d;
    reg  [26:0]          hb_q, hb_d;
    wire [6:0]           seg_n;

    // ------------------------------------------------------------------------ input synchronizers
    sync2 #(.W(1))  u_rst_sync (.clk(clk), .d(~CPU_RESETN), .q(rst_btn));
    sync2 #(.W(16)) u_sw_sync  (.clk(clk), .d(SW),          .q(sw_s));
    sync2 #(.W(1))  u_bt_sync  (.clk(clk), .d(BTNC),        .q(btnc_s));

    // ------------------------------------------------------------------------ submodules
    pdm_rx #(.DIV(`AF_MCLK_DIV), .S_HI(`AF_SAMPLE_HI), .S_LO(`AF_SAMPLE_LO)) u_pdm (
        .clk(clk), .rst(rst), .phase_lo(sw_s[6]), .m_data_async(M_DATA),
        .m_clk(M_CLK), .bit_valid(mic_v), .bit_out(mic_b));

    uart_rx #(.CLKS_PER_BIT(CPB)) u_urx (
        .clk(clk), .rst(rst), .rx_async(UART_TXD_IN),
        .valid(rx_v), .data(rx_d), .frame_err(rx_ferr));

    sync_fifo #(.DW(8), .AW(9)) u_txf (
        .clk(clk), .rst(rst), .push(f_push), .din(f_din), .pop(tx_rdy && !f_empty),
        .dout(f_dout), .empty(f_empty), .full(f_full), .afull(f_afull));

    uart_tx #(.CLKS_PER_BIT(CPB)) u_utx (
        .clk(clk), .rst(rst), .valid(!f_empty), .data(f_dout), .ready(tx_rdy), .tx(UART_RXD_OUT));

    cmd_ctrl #(.CAP_AW(CAP_AW), .WDOG_BITS(WDOG_BITS)) u_cmd (
        .clk(clk), .rst(rst), .rx_valid(rx_v), .rx_data(rx_d),
        .tx_push(f_push), .tx_din(f_din), .tx_full(f_afull),   // afull: cmd_ctrl pushes one clock late
        .sw(sw_s), .flags_in({err_q, rx_ferr}),
        .mode(mode), .t_bank(t_bank), .t_gain(t_gain), .chain_clr(chain_clr),
        .inj_bit_valid(ib_v), .inj_bit(ib_b), .inj_valid(inj_v), .inj_data(inj_d),
        .fir_valid(fir_v), .fir_data(fir_d), .out_valid(out_v), .out_data(out_d),
        .cap_busy(cap_busy), .err_pulse(cmd_err));

    audio_chain u_chain (
        .clk(clk), .rst(rst), .clr(chain_clr), .bank(bank), .gain(gain),
        .bit_valid(c_bit_v), .bit_in(c_bit),
        .inj_sel(mode == 2'd1), .inj_valid(inj_v), .inj_data(inj_d),
        .fir_valid(fir_v), .fir_data(fir_d), .out_valid(out_v), .out_data(out_d),
        .overrun(ovr));

    audio_dac #(.OW(`AF_OUT_W), .PWM_BITS(`AF_PWM_BITS)) u_dac (
        .clk(clk), .rst(rst), .mode(sw_s[7]), .in_valid(dac_in_v), .in_data(dac_in_d),
        .dac_out(dac));

    vu_meter u_vu (.clk(clk), .rst(rst), .in_valid(out_v && live), .in_data(out_d), .led(LED));

    seg7_status #(.REFRESH_BITS(REFRESH_BITS)) u_seg (
        .clk(clk), .rst(rst), .bank(live_bank), .gain(sw_s[5:2]), .phase_lo(sw_s[6]), .sdm(sw_s[7]),
        .test(!live), .seg_n(seg_n), .dp_n(DP), .an_n(AN));

    // ------------------------------------------------------------------------ combinational
    // open drain: drive low for '0', release (on-board pull-up) for '1'
    assign AUD_PWM = dac ? 1'bz : 1'b0;
    assign M_LRSEL = 1'b0;
    assign {CG, CF, CE, CD, CC, CB, CA} = seg_n;
    assign LED16_R = err_q;
    assign LED16_G = hb_q[26];
    assign LED17_B = !live || cap_busy;

    always @(*) begin
        // power-on reset: count 2^POR_BITS clocks after configuration or the reset button
        if (rst_btn)          por_d = {POR_BITS{1'b0}};
        else if (!(&por_q))   por_d = por_q + 1'b1;
        else                  por_d = por_q;
        rst_d    = rst_btn || !(&por_q);
        aud_sd_d = sw_s[15] && !rst;
        hb_d     = hb_q + 1'b1;
        if (btnc_s)                        err_d = 1'b0;
        else if (ovr || rx_ferr || cmd_err) err_d = 1'b1;
        else                               err_d = err_q;
    end

    // ------------------------------------------------------------------------ sequential
    // reset generator (registers start at 0 after FPGA configuration)
    always @(posedge clk) begin
        por_q  <= por_d;
        rst    <= rst_d;
        AUD_SD <= aud_sd_d;
    end

    always @(posedge clk) begin
        if (rst) begin
            err_q <= 1'b0;
            hb_q  <= 27'd0;
        end else begin
            err_q <= err_d;
            hb_q  <= hb_d;
        end
    end
endmodule
`default_nettype wire
