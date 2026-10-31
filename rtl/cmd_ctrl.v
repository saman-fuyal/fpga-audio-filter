`timescale 1ns/1ps
// =============================================================================================
// cmd_ctrl : UART command controller = hardware-in-the-loop test port + live capture
// ---------------------------------------------------------------------------------------------
// Protocol (host -> FPGA, multi-byte fields little-endian):
//   'P'                        -> 'A' 'F' VER_MAJOR VER_MINOR                      (ping)
//   'S'                        -> SW[15:8] SW[7:0] FLAGS                           (status)
//        FLAGS = {4'b0, capture_busy, error_sticky, uart_frame_err, test_active}
//   'T' bank nlo nhi x[0..n-1] (3 bytes each, signed 24-bit)
//                              -> n x 3-byte outputs of the selected FIR only
//                                 (bank 0-3: 511-tap FIR, bank 4: 31-tap parallel FIR)
//   'D' bank gain nlo nhi p[0..n-1] (PDM bytes, LSB = first bit)
//                              -> floor(8n/50) x 2-byte outputs of the WHOLE chain
//   'C'                        -> 2^CAP_AW live 16-bit output samples (2 bytes each)
// Every 'T'/'D' command first clears the chain (so the board reproduces the Python model
// exactly), mutes the audio, and restarts live operation at the end. A command that waits
// for the host for 2^WDOG_BITS clocks (0.17 s) is aborted.
//
// The host may send the next data byte while the chain is still being cleared. CLR_WAIT is
// shorter than one UART byte (600 < 1000 clocks), and a byte that arrives during the wait is
// kept in a one-byte holding register (hold_*), so no byte is lost.
// =============================================================================================
`default_nettype none
`include "af_params.vh"
module cmd_ctrl #(
    parameter CAP_AW    = `AF_CAP_AW,     // capture depth 2^CAP_AW samples
    parameter CLR_WAIT  = 600,            // > 512 (FIR clear), < 1000 (one UART byte)
    parameter WDOG_BITS = 24              // stall timeout 2^24 clocks = 0.17 s
) (
    // ------------------------------------------------------------------------ ports
    input  wire                       clk,
    input  wire                       rst,
    // UART receiver
    input  wire                       rx_valid,
    input  wire [7:0]                 rx_data,
    // UART transmit FIFO
    output reg                        tx_push,
    output reg  [7:0]                 tx_din,
    input  wire                       tx_full,
    // board state
    input  wire [15:0]                sw,
    input  wire [1:0]                 flags_in,      // {error_sticky, uart_frame_err}
    // chain control
    output reg  [1:0]                 mode,          // 0 live, 1 FIR test ('T'), 2 chain test ('D')
    output reg  [2:0]                 t_bank,
    output reg  [3:0]                 t_gain,
    output reg                        chain_clr,
    output reg                        inj_bit_valid,
    output reg                        inj_bit,
    output reg                        inj_valid,
    output reg  signed [`AF_DW-1:0]   inj_data,
    // chain observation
    input  wire                       fir_valid,
    input  wire signed [`AF_DW-1:0]   fir_data,
    input  wire                       out_valid,
    input  wire signed [`AF_OUT_W-1:0] out_data,
    output reg                        cap_busy,
    output reg                        err_pulse      // protocol / data-path error
);
    // ------------------------------------------------------------------------ localparams
    localparam [4:0] IDLE   = 5'd0,  RESP   = 5'd1,
                     T_BANK = 5'd2,  T_NLO  = 5'd3,  T_NHI  = 5'd4,
                     D_BANK = 5'd5,  D_GAIN = 5'd6,  D_NLO  = 5'd7,  D_NHI = 5'd8,
                     CLRW   = 5'd9,  T_RUN  = 5'd10, D_RUN  = 5'd11, D_DRAIN = 5'd12,
                     FINISH = 5'd13, C_ARM  = 5'd14, C_RD   = 5'd15, C_WAIT  = 5'd16,
                     C_LO   = 5'd17, C_HI   = 5'd18;
    localparam [CAP_AW:0]    CAP_LAST_W = (1 << CAP_AW) - 1;
    localparam [CAP_AW-1:0]  CAP_LAST_R = (1 << CAP_AW) - 1;

    // ------------------------------------------------------------------------ registers
    reg [4:0]  st_q, st_d, after_q, after_d;
    reg [7:0]  rsp0_q, rsp1_q, rsp2_q, rsp3_q, rsp0_d, rsp1_d, rsp2_d, rsp3_d;
    reg [2:0]  rlen_q, rlen_d, ridx_q, ridx_d;
    reg [15:0] nreq_q, nreq_d, nin_q, nin_d, nout_q, nout_d;
    reg [1:0]  bcnt_q, bcnt_d;               // byte index inside a 24-bit sample
    reg [23:0] acc24_q, acc24_d;             // incoming sample assembly
    reg [23:0] out24_q, out24_d;             // outgoing 'T' result
    reg [15:0] o16_q, o16_d;                 // outgoing 'D' result
    reg [1:0]  pend_q, pend_d;               // bytes still to push
    reg [10:0] wcnt_q, wcnt_d;               // clear wait
    reg [WDOG_BITS-1:0] wdog_q, wdog_d;      // stall watchdog
    reg [12:0] drain_q, drain_d;
    reg [7:0]  psh_q, psh_d;                 // PDM byte being unpacked
    reg [3:0]  pbits_q, pbits_d;             // bits left
    reg [2:0]  ptick_q, ptick_d;             // one bit every 8 clocks
    reg        hold_v_q, hold_v_d;           // byte held during CLRW
    reg [7:0]  hold_q, hold_d;
    reg [CAP_AW:0]   capw_q, capw_d;         // capture write address
    reg [CAP_AW-1:0] capr_q, capr_d;         // capture read address
    reg        cap_arm_q, cap_arm_d;
    // registered outputs, next values
    reg [1:0]  mode_d;
    reg [2:0]  t_bank_d;
    reg [3:0]  t_gain_d;
    reg        chain_clr_d, inj_bit_valid_d, inj_bit_d, inj_valid_d, cap_busy_d, err_d;
    reg signed [`AF_DW-1:0] inj_data_d;
    reg        tx_push_d;
    reg [7:0]  tx_din_d;
    reg [7:0]  rsp_sel;                      // combinational response byte

    // capture RAM
    (* ram_style = "block" *) reg [15:0] cap_mem [0:(1<<CAP_AW)-1];
    reg [15:0] cap_rd_q;

    // ------------------------------------------------------------------------ wires
    wire       in_v      = rx_valid || hold_v_q;          // byte available (live or held)
    wire [7:0] in_d      = hold_v_q ? hold_q : rx_data;
    wire       timeout   = &wdog_q;
    wire       hdr_state = (st_q == T_BANK) || (st_q == T_NLO) || (st_q == T_NHI) ||
                           (st_q == D_BANK) || (st_q == D_GAIN) || (st_q == D_NLO) ||
                           (st_q == D_NHI);
    wire       waiting   = hdr_state || (st_q == T_RUN) || (st_q == D_RUN);
    wire       cap_we    = cap_arm_q && out_valid && (mode == 2'd0);

    // ------------------------------------------------------------------------ combinational
    always @(*) begin
        // ---- defaults: hold state, pulses low
        st_d = st_q;  after_d = after_q;
        rsp0_d = rsp0_q;  rsp1_d = rsp1_q;  rsp2_d = rsp2_q;  rsp3_d = rsp3_q;
        rlen_d = rlen_q;  ridx_d = ridx_q;
        nreq_d = nreq_q;  nin_d = nin_q;  nout_d = nout_q;  bcnt_d = bcnt_q;
        acc24_d = acc24_q;  out24_d = out24_q;  o16_d = o16_q;  pend_d = pend_q;
        wcnt_d = wcnt_q;  drain_d = drain_q;
        psh_d = psh_q;  pbits_d = pbits_q;  ptick_d = ptick_q;
        hold_v_d = hold_v_q;  hold_d = hold_q;
        capw_d = capw_q;  capr_d = capr_q;  cap_arm_d = cap_arm_q;
        mode_d = mode;  t_bank_d = t_bank;  t_gain_d = t_gain;  cap_busy_d = cap_busy;
        inj_data_d = inj_data;  inj_bit_d = inj_bit;  tx_din_d = tx_din;
        chain_clr_d = 1'b0;  inj_bit_valid_d = 1'b0;  inj_valid_d = 1'b0;
        err_d = 1'b0;  tx_push_d = 1'b0;

        case (ridx_q[1:0])
            2'd0:    rsp_sel = rsp0_q;
            2'd1:    rsp_sel = rsp1_q;
            2'd2:    rsp_sel = rsp2_q;
            default: rsp_sel = rsp3_q;
        endcase

        // ---- watchdog: counts only while waiting for bytes from the host
        if (rx_valid || !waiting) wdog_d = {WDOG_BITS{1'b0}};
        else if (!timeout)        wdog_d = wdog_q + 1'b1;
        else                      wdog_d = wdog_q;

        // ---- capture writer (independent of the FSM)
        if (cap_we) begin
            capw_d = capw_q + 1'b1;
            if (capw_q == CAP_LAST_W) cap_arm_d = 1'b0;
        end

        // ---- command FSM
        case (st_q)
            // ================================================================ decode
            IDLE: begin
                if (rx_valid) begin
                    case (rx_data)
                        8'h50: begin                              // 'P' ping
                            rsp0_d = 8'h41;  rsp1_d = 8'h46;
                            rsp2_d = `AF_VER_MAJOR;  rsp3_d = `AF_VER_MINOR;
                            rlen_d = 3'd4;  ridx_d = 3'd0;  st_d = RESP;
                        end
                        8'h53: begin                              // 'S' status
                            rsp0_d = sw[15:8];  rsp1_d = sw[7:0];
                            rsp2_d = {4'b0000, cap_busy, flags_in, (mode != 2'd0)};
                            rlen_d = 3'd3;  ridx_d = 3'd0;  st_d = RESP;
                        end
                        8'h54:   st_d = T_BANK;                   // 'T'
                        8'h44:   st_d = D_BANK;                   // 'D'
                        8'h43: begin                              // 'C' capture
                            capw_d = {(CAP_AW+1){1'b0}};  cap_arm_d = 1'b1;
                            cap_busy_d = 1'b1;  st_d = C_ARM;
                        end
                        default: st_d = IDLE;                     // unknown byte: ignore
                    endcase
                end
            end
            RESP: begin
                if (!tx_full) begin
                    tx_push_d = 1'b1;  tx_din_d = rsp_sel;
                    ridx_d = ridx_q + 1'b1;
                    if (ridx_q + 1'b1 == rlen_q) st_d = IDLE;
                end
            end

            // ================================================================ headers
            T_BANK: if (rx_valid) begin t_bank_d = rx_data[2:0];  st_d = T_NLO; end
                    else if (timeout) st_d = IDLE;
            T_NLO:  if (rx_valid) begin nreq_d[7:0] = rx_data;   st_d = T_NHI; end
                    else if (timeout) st_d = IDLE;
            T_NHI:  if (rx_valid) begin
                        nreq_d[15:8] = rx_data;
                        mode_d = 2'd1;  chain_clr_d = 1'b1;  wcnt_d = 11'd0;
                        after_d = T_RUN;  st_d = CLRW;
                        nin_d = 16'd0;  nout_d = 16'd0;  bcnt_d = 2'd0;  pend_d = 2'd0;
                    end else if (timeout) st_d = IDLE;
            D_BANK: if (rx_valid) begin t_bank_d = rx_data[2:0];  st_d = D_GAIN; end
                    else if (timeout) st_d = IDLE;
            D_GAIN: if (rx_valid) begin t_gain_d = rx_data[3:0];  st_d = D_NLO; end
                    else if (timeout) st_d = IDLE;
            D_NLO:  if (rx_valid) begin nreq_d[7:0] = rx_data;   st_d = D_NHI; end
                    else if (timeout) st_d = IDLE;
            D_NHI:  if (rx_valid) begin
                        nreq_d[15:8] = rx_data;
                        mode_d = 2'd2;  chain_clr_d = 1'b1;  wcnt_d = 11'd0;
                        after_d = D_RUN;  st_d = CLRW;
                        nin_d = 16'd0;  pend_d = 2'd0;  pbits_d = 4'd0;
                    end else if (timeout) st_d = IDLE;

            // ================================================================ clear wait
            CLRW: begin
                wcnt_d = wcnt_q + 1'b1;
                if (rx_valid) begin
                    if (hold_v_q) err_d = 1'b1;          // impossible with CLR_WAIT < 1000
                    hold_v_d = 1'b1;  hold_d = rx_data;
                end
                if (wcnt_q == CLR_WAIT) st_d = after_q;
            end

            // ================================================================ 'T' : FIR only
            T_RUN: begin
                hold_v_d = 1'b0;
                if (in_v && (nin_q != nreq_q)) begin
                    acc24_d = {in_d, acc24_q[23:8]};
                    if (bcnt_q == 2'd2) begin
                        bcnt_d      = 2'd0;
                        inj_valid_d = 1'b1;
                        inj_data_d  = {in_d, acc24_q[23:8]};
                        nin_d       = nin_q + 1'b1;
                    end else begin
                        bcnt_d = bcnt_q + 1'b1;
                    end
                end
                if (fir_valid) begin
                    if (pend_q != 2'd0) err_d = 1'b1;    // previous result not sent yet
                    out24_d = fir_data;  pend_d = 2'd3;
                end else if ((pend_q != 2'd0) && !tx_full) begin
                    tx_push_d = 1'b1;  tx_din_d = out24_q[7:0];
                    out24_d   = {8'h00, out24_q[23:8]};
                    pend_d    = pend_q - 1'b1;
                    if (pend_q == 2'd1) nout_d = nout_q + 1'b1;
                end
                if (((nout_q == nreq_q) && (pend_q == 2'd0)) || timeout) st_d = FINISH;
            end

            // ================================================================ 'D' : whole chain
            D_RUN, D_DRAIN: begin
                // unpack one PDM bit every 8 clocks
                if (pbits_q != 4'd0) begin
                    ptick_d = ptick_q + 1'b1;
                    if (ptick_q == 3'd7) begin
                        inj_bit_valid_d = 1'b1;  inj_bit_d = psh_q[0];
                        psh_d   = {1'b0, psh_q[7:1]};
                        pbits_d = pbits_q - 1'b1;
                    end
                end
                hold_v_d = 1'b0;
                if ((st_q == D_RUN) && in_v && (nin_q != nreq_q)) begin
                    if (pbits_q != 4'd0) err_d = 1'b1;   // byte arrived while unpacking
                    psh_d = in_d;  pbits_d = 4'd8;  ptick_d = 3'd0;
                    nin_d = nin_q + 1'b1;
                end
                // send outputs
                if (out_valid) begin
                    if (pend_q != 2'd0) err_d = 1'b1;
                    o16_d = out_data;  pend_d = 2'd2;
                end else if ((pend_q != 2'd0) && !tx_full) begin
                    tx_push_d = 1'b1;  tx_din_d = o16_q[7:0];
                    o16_d     = {8'h00, o16_q[15:8]};
                    pend_d    = pend_q - 1'b1;
                end
                // end of command: all bytes in, all bits out, pipeline drained
                if (st_q == D_RUN) begin
                    drain_d = 13'd0;
                    if ((nin_q == nreq_q) && (pbits_q == 4'd0) && !in_v) st_d = D_DRAIN;
                    if (timeout) st_d = FINISH;
                end else begin
                    if (out_valid)  drain_d = 13'd0;
                    else            drain_d = drain_q + 1'b1;
                    if ((&drain_q) && (pend_q == 2'd0)) st_d = FINISH;
                end
            end

            FINISH: begin
                mode_d = 2'd0;  chain_clr_d = 1'b1;  st_d = IDLE;
            end

            // ================================================================ 'C' : dump capture
            C_ARM:  if (!cap_arm_q) begin capr_d = {CAP_AW{1'b0}};  st_d = C_RD; end
            C_RD:   st_d = C_WAIT;                       // RAM read data valid next clock
            C_WAIT: st_d = C_LO;
            C_LO:   if (!tx_full) begin
                        tx_push_d = 1'b1;  tx_din_d = cap_rd_q[7:0];  st_d = C_HI;
                    end
            C_HI:   if (!tx_full) begin
                        tx_push_d = 1'b1;  tx_din_d = cap_rd_q[15:8];
                        capr_d = capr_q + 1'b1;
                        if (capr_q == CAP_LAST_R) begin st_d = IDLE;  cap_busy_d = 1'b0; end
                        else                            st_d = C_RD;
                    end
            default: st_d = IDLE;
        endcase
    end

    // ------------------------------------------------------------------------ sequential: RAM
    always @(posedge clk) begin
        if (cap_we) cap_mem[capw_q[CAP_AW-1:0]] <= out_data;
        cap_rd_q <= cap_mem[capr_q];
    end

    // ------------------------------------------------------------------------ sequential: registers
    always @(posedge clk) begin
        if (rst) begin
            st_q <= IDLE;  after_q <= IDLE;
            rsp0_q <= 8'd0;  rsp1_q <= 8'd0;  rsp2_q <= 8'd0;  rsp3_q <= 8'd0;
            rlen_q <= 3'd0;  ridx_q <= 3'd0;
            nreq_q <= 16'd0;  nin_q <= 16'd0;  nout_q <= 16'd0;  bcnt_q <= 2'd0;
            acc24_q <= 24'd0;  out24_q <= 24'd0;  o16_q <= 16'd0;  pend_q <= 2'd0;
            wcnt_q <= 11'd0;  wdog_q <= {WDOG_BITS{1'b0}};  drain_q <= 13'd0;
            psh_q <= 8'd0;  pbits_q <= 4'd0;  ptick_q <= 3'd0;
            hold_v_q <= 1'b0;  hold_q <= 8'd0;
            capw_q <= {(CAP_AW+1){1'b0}};  capr_q <= {CAP_AW{1'b0}};  cap_arm_q <= 1'b0;
            mode <= 2'd0;  t_bank <= 3'd0;  t_gain <= 4'd0;  cap_busy <= 1'b0;
            chain_clr <= 1'b0;  inj_bit_valid <= 1'b0;  inj_bit <= 1'b0;
            inj_valid <= 1'b0;  inj_data <= {`AF_DW{1'b0}};
            tx_push <= 1'b0;  tx_din <= 8'd0;  err_pulse <= 1'b0;
        end else begin
            st_q <= st_d;  after_q <= after_d;
            rsp0_q <= rsp0_d;  rsp1_q <= rsp1_d;  rsp2_q <= rsp2_d;  rsp3_q <= rsp3_d;
            rlen_q <= rlen_d;  ridx_q <= ridx_d;
            nreq_q <= nreq_d;  nin_q <= nin_d;  nout_q <= nout_d;  bcnt_q <= bcnt_d;
            acc24_q <= acc24_d;  out24_q <= out24_d;  o16_q <= o16_d;  pend_q <= pend_d;
            wcnt_q <= wcnt_d;  wdog_q <= wdog_d;  drain_q <= drain_d;
            psh_q <= psh_d;  pbits_q <= pbits_d;  ptick_q <= ptick_d;
            hold_v_q <= hold_v_d;  hold_q <= hold_d;
            capw_q <= capw_d;  capr_q <= capr_d;  cap_arm_q <= cap_arm_d;
            mode <= mode_d;  t_bank <= t_bank_d;  t_gain <= t_gain_d;  cap_busy <= cap_busy_d;
            chain_clr <= chain_clr_d;  inj_bit_valid <= inj_bit_valid_d;  inj_bit <= inj_bit_d;
            inj_valid <= inj_valid_d;  inj_data <= inj_data_d;
            tx_push <= tx_push_d;  tx_din <= tx_din_d;  err_pulse <= err_d;
        end
    end
endmodule
`default_nettype wire
