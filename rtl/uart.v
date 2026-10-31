`timescale 1ns/1ps
// =============================================================================================
// uart.v : 8N1 UART receiver, transmitter and a small synchronous FIFO
// ---------------------------------------------------------------------------------------------
// CLKS_PER_BIT = F_SYS / BAUD = 100 at 1 Mbaud. 8N1 = 1 start bit (0), 8 data bits LSB
// first, 1 stop bit (1). The line idles high.
// =============================================================================================
`default_nettype none

// ---------------------------------------------------------------------------------------------
// uart_rx : waits for a falling edge, checks the start bit in its middle, then samples the
// 8 data bits and the stop bit in the middle of each bit period.
// ---------------------------------------------------------------------------------------------
module uart_rx #(
    parameter CLKS_PER_BIT = 100
) (
    // ------------------------------------------------------------------------ ports
    input  wire       clk,
    input  wire       rst,
    input  wire       rx_async,          // pin (asynchronous)
    output reg        valid,             // 1-clock strobe: data holds a new byte
    output reg  [7:0] data,
    output reg        frame_err          // 1-clock strobe: stop bit was 0
);
    // ------------------------------------------------------------------------ localparams / wires
    localparam CW = $clog2(CLKS_PER_BIT + 1);
    localparam [1:0] IDLE = 2'd0, START = 2'd1, BITS = 2'd2, STOP = 2'd3;

    reg [1:0]    st_q,   st_d;
    reg [CW-1:0] cnt_q,  cnt_d;
    reg [2:0]    nbit_q, nbit_d;
    reg [7:0]    sh_q,   sh_d;
    reg          valid_d, frame_err_d;
    reg [7:0]    data_d;
    wire         rx;

    sync2 #(.W(1)) u_sync (.clk(clk), .d(rx_async), .q(rx));

    // ------------------------------------------------------------------------ combinational
    always @(*) begin
        st_d = st_q;  cnt_d = cnt_q;  nbit_d = nbit_q;  sh_d = sh_q;  data_d = data;
        valid_d = 1'b0;  frame_err_d = 1'b0;
        case (st_q)
            IDLE: begin
                if (!rx) begin                              // possible start bit
                    st_d  = START;
                    cnt_d = CLKS_PER_BIT / 2 - 1;           // wait half a bit
                end
            end
            START: begin
                if (cnt_q == 0) begin
                    if (!rx) begin                          // still low: real start bit
                        st_d   = BITS;
                        cnt_d  = CLKS_PER_BIT - 1;
                        nbit_d = 3'd0;
                    end else begin
                        st_d = IDLE;                        // glitch
                    end
                end else begin
                    cnt_d = cnt_q - 1'b1;
                end
            end
            BITS: begin
                if (cnt_q == 0) begin
                    sh_d   = {rx, sh_q[7:1]};               // LSB first
                    cnt_d  = CLKS_PER_BIT - 1;
                    nbit_d = nbit_q + 1'b1;
                    if (nbit_q == 3'd7) st_d = STOP;
                end else begin
                    cnt_d = cnt_q - 1'b1;
                end
            end
            STOP: begin
                if (cnt_q == 0) begin
                    st_d = IDLE;
                    if (rx) begin valid_d = 1'b1; data_d = sh_q; end
                    else          frame_err_d = 1'b1;
                end else begin
                    cnt_d = cnt_q - 1'b1;
                end
            end
            default: st_d = IDLE;
        endcase
    end

    // ------------------------------------------------------------------------ sequential
    always @(posedge clk) begin
        if (rst) begin
            st_q <= IDLE;  cnt_q <= {CW{1'b0}};  nbit_q <= 3'd0;  sh_q <= 8'd0;
            valid <= 1'b0;  data <= 8'd0;  frame_err <= 1'b0;
        end else begin
            st_q <= st_d;  cnt_q <= cnt_d;  nbit_q <= nbit_d;  sh_q <= sh_d;
            valid <= valid_d;  data <= data_d;  frame_err <= frame_err_d;
        end
    end
endmodule

// ---------------------------------------------------------------------------------------------
// uart_tx : loads a byte when idle and `valid` is high, shifts out start, 8 data, stop.
// ---------------------------------------------------------------------------------------------
module uart_tx #(
    parameter CLKS_PER_BIT = 100
) (
    // ------------------------------------------------------------------------ ports
    input  wire       clk,
    input  wire       rst,
    input  wire       valid,             // byte available (loaded when ready)
    input  wire [7:0] data,
    output wire       ready,             // idle, can load a byte
    output reg        tx                 // pin
);
    // ------------------------------------------------------------------------ localparams / wires
    localparam CW = $clog2(CLKS_PER_BIT);

    reg [CW-1:0] cnt_q,  cnt_d;
    reg [3:0]    nbit_q, nbit_d;
    reg [9:0]    sh_q,   sh_d;           // {stop, data[7:0], start}, shifted out LSB first
    reg          busy_q, busy_d;
    reg          tx_d;

    assign ready = !busy_q;

    // ------------------------------------------------------------------------ combinational
    always @(*) begin
        cnt_d = cnt_q;  nbit_d = nbit_q;  sh_d = sh_q;  busy_d = busy_q;
        tx_d  = 1'b1;
        if (!busy_q) begin
            if (valid) begin
                sh_d   = {1'b1, data, 1'b0};
                busy_d = 1'b1;
                cnt_d  = {CW{1'b0}};
                nbit_d = 4'd0;
            end
        end else begin
            tx_d = sh_q[0];
            if (cnt_q == CLKS_PER_BIT - 1) begin
                cnt_d  = {CW{1'b0}};
                sh_d   = {1'b1, sh_q[9:1]};
                nbit_d = nbit_q + 1'b1;
                if (nbit_q == 4'd9) busy_d = 1'b0;
            end else begin
                cnt_d = cnt_q + 1'b1;
            end
        end
    end

    // ------------------------------------------------------------------------ sequential
    always @(posedge clk) begin
        if (rst) begin
            cnt_q <= {CW{1'b0}};  nbit_q <= 4'd0;  sh_q <= 10'h3FF;  busy_q <= 1'b0;  tx <= 1'b1;
        end else begin
            cnt_q <= cnt_d;  nbit_q <= nbit_d;  sh_q <= sh_d;  busy_q <= busy_d;  tx <= tx_d;
        end
    end
endmodule

// ---------------------------------------------------------------------------------------------
// sync_fifo : first-word-fall-through FIFO (dout shows the oldest entry while !empty).
// Pointers have one extra bit to tell full from empty.
// afull is high when at most one slot is free. A writer that registers its push (one clock from
// decision to write, like cmd_ctrl) must stop on afull: it can have one byte in flight that the
// full flag does not show yet. Using full there drops every second byte once the FIFO fills.
// ---------------------------------------------------------------------------------------------
module sync_fifo #(
    parameter DW = 8,
    parameter AW = 9                     // depth 2^AW
) (
    // ------------------------------------------------------------------------ ports
    input  wire          clk,
    input  wire          rst,
    input  wire          push,
    input  wire [DW-1:0] din,
    input  wire          pop,
    output wire [DW-1:0] dout,
    output wire          empty,
    output wire          full,
    output wire          afull               // at most one free slot
);
    // ------------------------------------------------------------------------ registers / wires
    reg [DW-1:0] mem [0:(1<<AW)-1];
    reg [AW:0]   wp_q, wp_d, rp_q, rp_d;
    wire [AW:0]  level   = wp_q - rp_q;          // entries in use, 0 .. 2^AW
    wire         do_push = push && !full;
    wire         do_pop  = pop && !empty;

    assign dout  = mem[rp_q[AW-1:0]];
    assign empty = (wp_q == rp_q);
    assign full  = (wp_q[AW-1:0] == rp_q[AW-1:0]) && (wp_q[AW] != rp_q[AW]);
    assign afull = (level >= ((1 << AW) - 1));

    // ------------------------------------------------------------------------ combinational
    always @(*) begin
        wp_d = do_push ? wp_q + 1'b1 : wp_q;
        rp_d = do_pop  ? rp_q + 1'b1 : rp_q;
    end

    // ------------------------------------------------------------------------ sequential: RAM
    always @(posedge clk) begin
        if (do_push) mem[wp_q[AW-1:0]] <= din;
    end

    // ------------------------------------------------------------------------ sequential: pointers
    always @(posedge clk) begin
        if (rst) begin
            wp_q <= {(AW+1){1'b0}};
            rp_q <= {(AW+1){1'b0}};
        end else begin
            wp_q <= wp_d;
            rp_q <= rp_d;
        end
    end
endmodule
`default_nettype wire
