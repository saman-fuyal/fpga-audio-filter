// Self-checking testbench for fir_mac:
//   part 1: main FIR, all 4 banks (impulse, random full-scale, saturation, sine)
//   part 2: comp FIR (63 taps, decimate by 2)
//   part 3: overrun detection (input while busy must raise `overrun`)
// Expected data from model/gen_vectors.py (bit-exact).
`timescale 1ns/1ps
`default_nettype none
`include "af_params.vh"
module tb_fir;
    localparam int DW = `AF_DW;
    localparam int NX = 2939;            // keep in sync with gen_vectors.py
    localparam int NC_IN = 624 + 400;

    logic clk = 0, rst = 1;
    always #5 clk = ~clk;

    // ---------------- main FIR
    logic        clr = 0;
    logic [1:0]  bank = 0;
    logic        in_valid = 0;
    logic signed [DW-1:0] in_data = 0;
    logic        out_valid, ready, overrun;
    logic signed [DW-1:0] out_data;

    logic [`AF_MAIN_AW+1:0]      m_caddr;
    logic signed [`AF_CW-1:0]    m_cdata;
    fir_mac #(.NTAPS(`AF_MAIN_TAPS), .AW(`AF_MAIN_AW), .DW(DW), .CW(`AF_CW), .CFRAC(`AF_CFRAC),
              .ACC_W(`AF_ACC_W), .DECIM(1), .BW(2), .SHIFTS(`AF_MAIN_SHIFTS)) dut (
        .clk(clk), .rst(rst), .clr(clr), .bank(bank), .in_valid(in_valid), .in_data(in_data),
        .out_valid(out_valid), .out_data(out_data), .ready(ready), .overrun(overrun),
        .coef_addr(m_caddr), .coef_data(m_cdata));
    coef_rom_main u_mrom (.clk(clk), .addr(m_caddr), .q(m_cdata));

    // ---------------- comp FIR
    logic        c_valid = 0;
    logic signed [DW-1:0] c_data = 0;
    logic        c_out_valid, c_ready, c_overrun;
    logic signed [DW-1:0] c_out;
    logic [`AF_COMP_AW:0]        c_caddr;
    logic signed [`AF_CW-1:0]    c_cdata;
    fir_mac #(.NTAPS(`AF_COMP_TAPS), .AW(`AF_COMP_AW), .DW(DW), .CW(`AF_CW), .CFRAC(`AF_CFRAC),
              .ACC_W(`AF_ACC_W), .DECIM(`AF_COMP_DECIM), .BW(1), .SHIFTS(`AF_COMP_SHIFT)) comp (
        .clk(clk), .rst(rst), .clr(1'b0), .bank(1'b0), .in_valid(c_valid), .in_data(c_data),
        .out_valid(c_out_valid), .out_data(c_out), .ready(c_ready), .overrun(c_overrun),
        .coef_addr(c_caddr), .coef_data(c_cdata));
    coef_rom_comp u_crom (.clk(clk), .addr(c_caddr[`AF_COMP_AW-1:0]), .q(c_cdata));

    logic [DW-1:0] vin [NX];
    logic [DW-1:0] vexp0[NX], vexp1[NX], vexp2[NX], vexp3[NX];
    function automatic logic [DW-1:0] vexp(input int b, input int i);
        case (b) 0: return vexp0[i]; 1: return vexp1[i]; 2: return vexp2[i]; default: return vexp3[i]; endcase
    endfunction
    logic [DW-1:0] cin [NC_IN];
    logic [DW-1:0] cexp[NC_IN/2];
    initial begin
        $readmemh("vectors/fir_in.hex", vin);
        $readmemh("vectors/fir_exp_b0.hex", vexp0);
        $readmemh("vectors/fir_exp_b1.hex", vexp1);
        $readmemh("vectors/fir_exp_b2.hex", vexp2);
        $readmemh("vectors/fir_exp_b3.hex", vexp3);
        $readmemh("vectors/comp_in.hex", cin);
        $readmemh("vectors/comp_exp.hex", cexp);
    end

    int nout = 0, nerr = 0, cur_bank = 0, nc = 0, n_ovr = 0, max_lat = 0, t_in = 0;
    always @(posedge clk) begin
        if (out_valid) begin
            if (nout < NX && out_data !== $signed(vexp(cur_bank, nout))) begin
                nerr++;
                if (nerr < 10) $display("MISMATCH bank%0d y[%0d]: got %0d exp %0d", cur_bank, nout,
                                        out_data, $signed(vexp(cur_bank, nout)));
            end
            nout++;
            if ($time/10 - t_in > max_lat) max_lat = $time/10 - t_in;
        end
        if (c_out_valid) begin
            if (c_out !== $signed(cexp[nc])) begin
                nerr++;
                if (nerr < 10) $display("MISMATCH comp y[%0d]: got %0d exp %0d", nc, c_out, $signed(cexp[nc]));
            end
            nc++;
        end
        if (overrun) n_ovr++;
    end

    // stimulus is driven on the falling edge so `ready` is sampled after the DUT has updated
    task automatic push(input logic signed [DW-1:0] v);
        @(negedge clk);
        while (!ready) @(negedge clk);
        in_valid = 1; in_data = v; t_in = $time/10;
        @(negedge clk);
        in_valid = 0;
    endtask

    initial begin
        repeat (5) @(posedge clk);
        rst <= 0;
        // comp FIR runs in parallel, fed every 600 clocks... drive it from a separate process
        for (int b = 0; b < 4; b++) begin
            cur_bank = b; nout = 0;
            @(negedge clk); bank = 2'(b); clr = 1; @(negedge clk); clr = 0;
            for (int i = 0; i < NX; i++) push($signed(vin[i]));
            while (!ready) @(posedge clk);
            repeat (10) @(posedge clk);
            if (nout != NX) begin $display("FAIL bank%0d: %0d outputs", b, nout); nerr++; end
            else $display("  bank %0d: %0d outputs checked", b, nout);
        end
        // overrun: two inputs back-to-back must flag exactly one overrun
        if (n_ovr != 0) begin $display("FAIL: spurious overrun"); nerr++; end
        push(1);
        in_valid = 1; in_data = 2; @(negedge clk); in_valid = 0;
        repeat (600) @(posedge clk);
        if (n_ovr != 1) begin $display("FAIL: overrun count %0d (exp 1)", n_ovr); nerr++; end
        else $display("  overrun detection OK");
        $display("  main FIR latency (input -> output): %0d clocks", max_lat);
        wait (nc == NC_IN/2);
        repeat (10) @(posedge clk);
        $display("  comp FIR: %0d outputs checked", nc);
        if (nerr == 0) $display("PASS tb_fir");
        else           $display("FAIL tb_fir: %0d errors", nerr);
        $finish;
    end

    initial begin
        @(negedge rst);
        for (int i = 0; i < NC_IN; i++) begin
            @(negedge clk);
            while (!c_ready) @(negedge clk);
            c_valid = 1; c_data = $signed(cin[i]);
            @(negedge clk);
            c_valid = 0;
        end
    end

    initial begin
        #200ms $display("FAIL tb_fir: timeout"); $finish;
    end
endmodule
`default_nettype wire
