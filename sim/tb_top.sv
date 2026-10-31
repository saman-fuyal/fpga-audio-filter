// Top-level testbench for top_nexys_a7: drives the real board pins.
//
//  * ADMP421 model: drives M_DATA (from a PDM file) shortly after each M_CLK rising edge and
//    releases it (high-Z) after each falling edge, like the real stereo-capable mic with
//    L/R = 0. Sampling in the wrong half would read 'z' and corrupt the output (X), so a
//    bit-exact match also proves the PDM timing.
//  * UART host model at 1 Mbaud: 'P', 'S', 'T', 'D', 'C' commands, responses checked
//    against model/golden.py.
//  * AUD_PWM must only ever be '0' or 'z' (open drain), and is silent during UART tests.
`timescale 1ns/1ps
`default_nettype none
`include "af_params.vh"
module tb_top;
    localparam int NMIC = 30000;                  // top_mic.hex
    localparam int NLIVE = NMIC / 50;             // 600 output samples
    localparam int NT = 40, NT4 = 30, ND = 200, NDO = ND * 8 / 50;
    localparam real BIT_NS = 1.0e9 / `AF_BAUD;
    // 2^10 samples = 2048 bytes: more than the 512-byte UART TX FIFO, so the capture dump runs
    // against a full FIFO, the case where a registered push can lose bytes
    localparam int CAP_AW = 10;

    logic clk = 0;
    always #5 clk = ~clk;

    logic        resetn = 0;
    logic [15:0] SW;
    logic        BTNC = 0;
    wire  [15:0] LED;
    wire         LED16_R, LED16_G, LED17_B, M_CLK, M_LRSEL, AUD_PWM, AUD_SD, UART_RXD_OUT;
    wire         CA, CB, CC, CD, CE, CF, CG, DP;
    wire  [7:0]  AN;
    logic        uart_to_fpga = 1;
    logic        m_data_drv = 0, m_data_en = 0;
    wire         M_DATA = m_data_en ? m_data_drv : 1'bz;

    top_nexys_a7 #(.CAP_AW(CAP_AW), .REFRESH_BITS(8), .POR_BITS(4), .WDOG_BITS(16)) dut (
        .CLK100MHZ(clk), .CPU_RESETN(resetn), .SW(SW), .BTNC(BTNC), .LED(LED),
        .LED16_R(LED16_R), .LED16_G(LED16_G), .LED17_B(LED17_B),
        .M_CLK(M_CLK), .M_DATA(M_DATA), .M_LRSEL(M_LRSEL), .AUD_PWM(AUD_PWM), .AUD_SD(AUD_SD),
        .UART_TXD_IN(uart_to_fpga), .UART_RXD_OUT(UART_RXD_OUT),
        .CA(CA), .CB(CB), .CC(CC), .CD(CD), .CE(CE), .CF(CF), .CG(CG), .DP(DP), .AN(AN));

    // ------------------------------------------------------------------ vectors
    logic [0:0]           mic [NMIC];
    logic [`AF_OUT_W-1:0] live_exp [NLIVE];
    logic [`AF_DW-1:0]    t_in [NT], t_exp [NT];
    logic [`AF_DW-1:0]    t4_in [NT4], t4_exp [NT4];
    logic [7:0]           d_in [ND];
    logic [`AF_OUT_W-1:0] d_exp [NDO];
    initial begin
        $readmemh("vectors/top_mic.hex", mic);
        $readmemh("vectors/top_live_exp.hex", live_exp);
        $readmemh("vectors/uart_t_in.hex", t_in);
        $readmemh("vectors/uart_t_exp.hex", t_exp);
        $readmemh("vectors/uart_t4_in.hex", t4_in);
        $readmemh("vectors/uart_t4_exp.hex", t4_exp);
        $readmemh("vectors/uart_d_in.hex", d_in);
        $readmemh("vectors/uart_d_exp.hex", d_exp);
    end

    int nerr = 0;
    task automatic check(input bit cond, input string msg);
        if (!cond) begin nerr++; $display("ERROR @%0t: %s", $time, msg); end
    endtask

    // ------------------------------------------------------------------ microphone model
    int mic_idx = 0;
    always @(posedge M_CLK) begin
        #30;                                 // data-valid delay after the rising edge
        m_data_en  <= 1;
        m_data_drv <= (mic_idx < NMIC) ? mic[mic_idx][0] : 1'($urandom % 2);
        mic_idx++;
    end
    always @(negedge M_CLK) begin
        #15 m_data_en <= 0;                  // release to high-Z in the other half period
    end

    // ------------------------------------------------------------------ live-output checker
    int nlive = 0;
    bit live_chk = 1;     // cleared once the live phase is over (UART tests restart the chain)
    always @(posedge clk) begin
        if (live_chk && dut.out_v && dut.live && nlive < NLIVE) begin
            if (dut.out_d !== $signed(live_exp[nlive])) begin
                nerr++;
                if (nerr < 10) $display("MISMATCH live[%0d]: got %0d exp %0d", nlive, dut.out_d,
                                        $signed(live_exp[nlive]));
            end
            nlive++;
        end
    end

    // open-drain + mute checks
    int pwm_lows = 0, pwm_zs = 0, bad_level = 0, active_during_test = 0;
    logic [1:0] live_d = 2'b11;
    always @(posedge clk) if (!dut.rst) begin
        if (AUD_PWM === 1'b0) pwm_lows++;
        else if (AUD_PWM === 1'bz) pwm_zs++;
        else bad_level++;
        live_d <= {live_d[0], dut.live};
        if (!dut.live && live_d == 2'b00 && dut.u_dac.smp_q != 0) active_during_test++;   // 2-cycle mute latency
    end

    // samples the capture RAM records (reference for the 'C' check)
    logic [15:0] capq[$];
    always @(posedge clk) if (dut.u_cmd.cap_we) capq.push_back(dut.u_cmd.out_data);

    // ------------------------------------------------------------------ UART host model
    byte rxq[$];
    task automatic uart_send(input byte b);
        uart_to_fpga = 0; #(BIT_NS);
        for (int i = 0; i < 8; i++) begin uart_to_fpga = b[i]; #(BIT_NS); end
        uart_to_fpga = 1; #(BIT_NS);
    endtask
    initial forever begin
        byte b;
        @(negedge UART_RXD_OUT);
        #(BIT_NS * 1.5);
        for (int i = 0; i < 8; i++) begin
            // rxq holds 2-state bytes, so catch an X/Z on the pin here, before it becomes 0
            if (UART_RXD_OUT !== 1'b0 && UART_RXD_OUT !== 1'b1) begin
                nerr++; if (nerr < 10) $display("ERROR @%0t: UART data bit is X/Z", $time);
            end
            b[i] = UART_RXD_OUT; #(BIT_NS);
        end
        if (UART_RXD_OUT !== 1'b1) begin nerr++; $display("ERROR: UART stop bit"); end
        rxq.push_back(b);
    end
    task automatic expect_bytes(input int n, input real timeout_us);
        real t0 = $realtime;
        while (rxq.size() < n && ($realtime - t0) < timeout_us * 1000.0) #1000;
        check(rxq.size() >= n, $sformatf("expected %0d bytes, got %0d", n, rxq.size()));
    endtask

    // ------------------------------------------------------------------ sequence
    initial begin
        int got;
        logic [23:0] y24;
        logic [15:0] y16;
        // bank 1 (low-pass), gain 3, PDM high half, PWM, amp on
        SW = 16'h8000 | (16'd3 << 2) | 16'd1;
        #200 resetn = 1;

        // ---------------- 1. live audio path, bit-exact through the real pins
        // +quick: check only the first 60 live samples (faster iteration); default: all 600
        if ($test$plusargs("quick")) wait (nlive == 60);
        else                         wait (nlive == NLIVE);
        live_chk = 0;
        $display("  live path: %0d samples via M_CLK/M_DATA pins bit-exact", nlive);
        check(dut.LED[3] === 1'b1, "level meter shows signal");
        check(AUD_SD === 1'b1, "AUD_SD enabled by SW15");
        check(M_LRSEL === 1'b0, "M_LRSEL low");

        // ---------------- 2. ping
        uart_send("P");
        expect_bytes(4, 200);
        check(rxq[0] == "A" && rxq[1] == "F" && rxq[2] == `AF_VER_MAJOR && rxq[3] == `AF_VER_MINOR,
              $sformatf("ping reply %02x %02x %02x %02x", rxq[0], rxq[1], rxq[2], rxq[3]));
        rxq.delete();
        $display("  'P' ping OK");

        // ---------------- 3. status
        uart_send("S");
        expect_bytes(3, 200);
        check(rxq[0] == SW[15:8] && rxq[1] == SW[7:0], "status switch bytes");
        begin byte fl; fl = rxq[2]; check(fl[2] == 1'b0, "no overrun flagged"); end
        rxq.delete();
        $display("  'S' status OK (flags=%02x)", 8'(dut.u_cmd.rsp2_q));

        // ---------------- 4. 'T': main FIR bank 3, 40 x 24-bit samples
        uart_send("T"); uart_send(8'd3); uart_send(8'(NT)); uart_send(8'(NT >> 8));
        for (int i = 0; i < NT; i++) begin
            uart_send(t_in[i][7:0]); uart_send(t_in[i][15:8]); uart_send(t_in[i][23:16]);
        end
        expect_bytes(3 * NT, 2000);
        got = 0;
        for (int i = 0; i < NT; i++) begin
            y24 = {rxq[3*i+2], rxq[3*i+1], rxq[3*i]};
            if (y24 !== t_exp[i]) begin
                nerr++; if (got++ < 5) $display("MISMATCH T y[%0d]: got %0d exp %0d", i, $signed(y24), $signed(t_exp[i]));
            end
        end
        rxq.delete();
        $display("  'T' FIR test: %0d samples over UART checked", NT);

        // ---------------- 4b. 'T' with bank 4: the 31-tap parallel FIR (ASIC core)
        uart_send("T"); uart_send(8'd4); uart_send(8'(NT4)); uart_send(8'(NT4 >> 8));
        for (int i = 0; i < NT4; i++) begin
            uart_send(t4_in[i][7:0]); uart_send(t4_in[i][15:8]); uart_send(t4_in[i][23:16]);
        end
        expect_bytes(3 * NT4, 2000);
        got = 0;
        for (int i = 0; i < NT4; i++) begin
            y24 = {rxq[3*i+2], rxq[3*i+1], rxq[3*i]};
            if (y24 !== t4_exp[i]) begin
                nerr++; if (got++ < 5) $display("MISMATCH T4 y[%0d]: got %0d exp %0d", i, $signed(y24), $signed(t4_exp[i]));
            end
        end
        rxq.delete();
        $display("  'T' bank 4 (ASIC core) test: %0d samples over UART checked", NT4);

        // ---------------- 5. 'D': whole chain, bank 2, gain 5, 200 PDM bytes
        uart_send("D"); uart_send(8'd2); uart_send(8'd5); uart_send(8'(ND)); uart_send(8'(ND >> 8));
        for (int i = 0; i < ND; i++) uart_send(d_in[i]);
        expect_bytes(2 * NDO, 3000);
        #(200us);
        check(rxq.size() == 2 * NDO, $sformatf("'D' returned %0d bytes, expected %0d", rxq.size(), 2 * NDO));
        got = 0;
        for (int i = 0; i < NDO; i++) begin
            y16 = {rxq[2*i+1], rxq[2*i]};
            if (y16 !== d_exp[i]) begin
                nerr++; if (got++ < 5) $display("MISMATCH D y[%0d]: got %0d exp %0d", i, $signed(y16), $signed(d_exp[i]));
            end
        end
        rxq.delete();
        $display("  'D' chain test: %0d samples over UART checked", NDO);
        wait (dut.live);

        // ---------------- 6. 'C': capture 2^CAP_AW live samples, compared with what was recorded
        capq.delete();
        uart_send("C");
        expect_bytes(2 << CAP_AW, 60000);
        #(100us);
        check(rxq.size() == (2 << CAP_AW), $sformatf("'C' returned %0d bytes, expected %0d", rxq.size(), 2 << CAP_AW));
        got = 0;
        for (int i = 0; i < (2 << CAP_AW); i++) if (rxq[i] !== 8'h00) got++;
        check(got > 16, "capture contains signal");
        check(capq.size() == (1 << CAP_AW), $sformatf("%0d samples written to the capture RAM", capq.size()));
        got = 0;
        for (int i = 0; i < (1 << CAP_AW) && 2 * i + 1 < rxq.size(); i++) begin
            y16 = {rxq[2*i+1], rxq[2*i]};
            if (y16 !== capq[i]) begin
                nerr++; if (got++ < 5) $display("MISMATCH C y[%0d]: got %0d exp %0d", i, $signed(y16), $signed(capq[i]));
            end
        end
        rxq.delete();
        $display("  'C' capture: %0d bytes received and compared with the recorded output", 2 << CAP_AW);

        // ---------------- 7. stalled command must time out back to IDLE
        uart_send("T"); uart_send(8'd0);
        wait (dut.u_cmd.st_q == 5'd0);   // IDLE
        $display("  watchdog: stalled header aborted after %0t", $time);
        uart_send("P");
        expect_bytes(4, 200);
        check(rxq[0] == "A", "ping after watchdog");
        rxq.delete();

        // ---------------- summary
        check(bad_level == 0, $sformatf("AUD_PWM drove a non-open-drain level %0d times", bad_level));
        check(pwm_lows > 0 && pwm_zs > 0, "AUD_PWM toggles");
        check(active_during_test == 0, "audio muted during UART tests");
        check(dut.err_q == 1'b0, "no sticky error");
        $display("  AUD_PWM: %0d cycles low, %0d cycles released (z), 0 driven-high", pwm_lows, pwm_zs);
        if (nerr == 0) $display("PASS tb_top");
        else           $display("FAIL tb_top: %0d errors", nerr);
        $finish;
    end

    initial begin
        #400ms $display("FAIL tb_top: timeout"); $finish;
    end
    initial forever begin
        #1ms $display("    [%0t ns] live=%0d mic_bits=%0d cmd_state=%0d rxq=%0d", $time, nlive, mic_idx,
                      dut.u_cmd.st_q, rxq.size());
        $fflush();
    end
endmodule
`default_nettype wire
