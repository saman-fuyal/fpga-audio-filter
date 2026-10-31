`timescale 1ns/1ps
// =============================================================================================
// tb_vivado : plain Verilog-2001 testbench for the Vivado simulator (xsim) - waveform demo
// ---------------------------------------------------------------------------------------------
// No files, no SystemVerilog: it runs in Vivado 2018.2 out of the box (Run Simulation ->
// Run Behavioral Simulation, then "run 6 ms" in the Tcl console).
//
// * A microphone model turns a 1 kHz + 6 kHz test tone into a PDM bit stream with a
//   second-order delta-sigma modulator (real arithmetic) and drives M_DATA after each
//   rising edge of M_CLK, releasing the line (high-Z) after each falling edge.
// * The switches select bank 1 (1 kHz low-pass), gain 2^2, PWM output, amplifier on.
// * Useful signals to add to the waveform window (all under tb_vivado/dut):
//     M_CLK, M_DATA, u_pdm/bit_valid, u_chain/u_cic/out_valid, u_chain/u_cic/out_data,
//     u_chain/dc_d, u_chain/fir_data (set radix Signed Decimal, waveform style Analog),
//     u_chain/out_data, AUD_PWM, LED
// * Self-check at the end: audio samples were produced and the open-drain pin never
//   drove a '1'. The bit-exact checks are in sim/tb_*.sv (Icarus Verilog, run_sim.py).
// =============================================================================================
module tb_vivado;
    // ------------------------------------------------------------------------ clock / reset
    reg clk = 1'b0;
    always #5 clk = ~clk;                         // 100 MHz
    reg resetn = 1'b0;

    // ------------------------------------------------------------------------ DUT
    reg  [15:0] SW = 16'h8000 | (16'd2 << 2) | 16'd1;   // amp on, gain 2, bank 1
    wire [15:0] LED;
    wire        LED16_R, LED16_G, LED17_B, M_CLK, M_LRSEL, AUD_PWM, AUD_SD, UART_RXD_OUT;
    wire        CA, CB, CC, CD, CE, CF, CG, DP;
    wire [7:0]  AN;
    reg         m_drv = 1'b0, m_en = 1'b0;
    wire        M_DATA = m_en ? m_drv : 1'bz;

    top_nexys_a7 #(.CAP_AW(6), .REFRESH_BITS(8), .POR_BITS(4), .WDOG_BITS(16)) dut (
        .CLK100MHZ(clk), .CPU_RESETN(resetn), .SW(SW), .BTNC(1'b0), .LED(LED),
        .LED16_R(LED16_R), .LED16_G(LED16_G), .LED17_B(LED17_B),
        .M_CLK(M_CLK), .M_DATA(M_DATA), .M_LRSEL(M_LRSEL), .AUD_PWM(AUD_PWM), .AUD_SD(AUD_SD),
        .UART_TXD_IN(1'b1), .UART_RXD_OUT(UART_RXD_OUT),
        .CA(CA), .CB(CB), .CC(CC), .CD(CD), .CE(CE), .CF(CF), .CG(CG), .DP(DP), .AN(AN));

    // ------------------------------------------------------------------------ microphone model
    real t_s = 0.0, x = 0.0, i1 = 0.0, i2 = 0.0, fb = 1.0;
    always @(posedge M_CLK) begin
        t_s = t_s + 400.0e-9;                     // 2.5 MHz bit period
        x   = 0.30 * $sin(6.2831853 * 1000.0 * t_s) + 0.20 * $sin(6.2831853 * 6000.0 * t_s);
        i1  = i1 + x - fb;
        i2  = i2 + i1 - fb;
        fb  = (i2 >= 0.0) ? 1.0 : -1.0;
        #30 m_en = 1'b1;                          // data valid 30 ns after the rising edge
        m_drv = (fb > 0.0);
    end
    always @(negedge M_CLK) begin
        #15 m_en = 1'b0;                          // released in the other half period
    end

    // ------------------------------------------------------------------------ checks
    integer n_out = 0, n_bad_pin = 0;
    always @(posedge clk) begin
        if (dut.out_v) n_out = n_out + 1;
        if (resetn && (AUD_PWM === 1'b1)) n_bad_pin = n_bad_pin + 1;
    end

`ifdef DUMP
    // waveform dump for the report figure (Icarus: iverilog -DDUMP ...)
    initial begin
        $dumpfile("wave.vcd");
        $dumpvars(0, clk, M_CLK, M_DATA, dut.u_pdm.bit_valid, dut.u_pdm.bit_out,
                  dut.u_chain.u_cic.out_valid, dut.u_chain.u_main.state_q, dut.u_chain.u_main.k_q,
                  dut.u_chain.u_main.out_valid, dut.u_chain.dc_v);
        $dumpoff;
        #3000000 $dumpon;
        #12000   $dumpoff;
    end
`endif

    initial begin
        #200 resetn = 1'b1;
        #6000000;                                 // 6 ms
        $display("tb_vivado: %0d audio samples, LED = %b, open-drain violations = %0d",
                 n_out, LED, n_bad_pin);
        if (n_out > 250 && n_bad_pin == 0) $display("PASS tb_vivado");
        else                               $display("FAIL tb_vivado");
        $finish;
    end
endmodule
