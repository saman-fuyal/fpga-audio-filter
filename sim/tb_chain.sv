// Self-checking testbench: complete audio_chain (PDM bits -> 16-bit audio) vs
// model/golden.py::chain(), 5 bank/gain settings (bank 4 = ASIC core), 1500 samples each.
// Also checks the DC blocker in isolation.
`timescale 1ns/1ps
`default_nettype none
`include "af_params.vh"
module tb_chain;
    localparam int NB   = 75000;
    localparam int NO   = NB / (`AF_CIC_R * `AF_COMP_DECIM);
    localparam int NDC  = 4000;
    localparam int BIT_PERIOD = 16;    // clocks between PDM bits (live = 40; 16 = stress)

    logic clk = 0, rst = 1, clr = 0;
    always #5 clk = ~clk;

    logic [2:0] bank = 0;
    logic [3:0] gain = 0;
    logic       bit_valid = 0, bit_in = 0;
    logic       fir_ready, fir_valid, out_valid, overrun;
    logic signed [`AF_DW-1:0]    fir_data;
    logic signed [`AF_OUT_W-1:0] out_data;

    audio_chain dut (
        .clk(clk), .rst(rst), .clr(clr), .bank(bank), .gain(gain),
        .bit_valid(bit_valid), .bit_in(bit_in),
        .inj_sel(1'b0), .inj_valid(1'b0), .inj_data({`AF_DW{1'b0}}),
        .fir_valid(fir_valid), .fir_data(fir_data), .out_valid(out_valid), .out_data(out_data),
        .overrun(overrun));

    // ---------------- DC blocker unit
    logic dc_iv = 0, dc_ov;
    logic signed [`AF_DW-1:0] dc_id = 0, dc_od;
    dc_block #(.DW(`AF_DW), .K(`AF_DC_K)) u_dc (.clk(clk), .rst(rst), .in_valid(dc_iv),
        .in_data(dc_id), .out_valid(dc_ov), .out_data(dc_od));

    logic [0:0]            vin [NB];
    logic [`AF_OUT_W-1:0]  vexp0[NO], vexp1[NO], vexp2[NO], vexp3[NO], vexp4[NO];
    logic [`AF_DW-1:0]     dcin[NDC], dcexp[NDC];
    initial begin
        $readmemh("vectors/chain_in.hex", vin);
        $readmemh("vectors/chain_exp_0.hex", vexp0);
        $readmemh("vectors/chain_exp_1.hex", vexp1);
        $readmemh("vectors/chain_exp_2.hex", vexp2);
        $readmemh("vectors/chain_exp_3.hex", vexp3);
        $readmemh("vectors/chain_exp_4.hex", vexp4);
        $readmemh("vectors/dc_in.hex", dcin);
        $readmemh("vectors/dc_exp.hex", dcexp);
    end
    function automatic logic [`AF_OUT_W-1:0] vexp(input int s, input int i);
        case (s) 0: return vexp0[i]; 1: return vexp1[i]; 2: return vexp2[i]; 3: return vexp3[i]; default: return vexp4[i]; endcase
    endfunction

    int set = 0, nout = 0, nerr = 0, ndc = 0, novr = 0;
    int fd;
    always @(posedge clk) begin
        if (out_valid) begin
            if (out_data !== $signed(vexp(set, nout))) begin
                nerr++;
                if (nerr < 10) $display("MISMATCH set%0d out[%0d]: got %0d exp %0d", set, nout,
                                        out_data, $signed(vexp(set, nout)));
            end
            $fdisplay(fd, "%0d %0d %0d", set, nout, out_data);
            nout++;
        end
        if (dc_ov) begin
            if (dc_od !== $signed(dcexp[ndc])) begin
                nerr++;
                if (nerr < 10) $display("MISMATCH dc[%0d]: got %0d exp %0d", ndc, dc_od, $signed(dcexp[ndc]));
            end
            ndc++;
        end
        if (overrun) novr++;
    end

    // settings must match model/gen_vectors.py
    // (functions, not array literals: Icarus 12 cannot assign a whole array)
    function automatic int sb(input int s);
        sb = s;                                  // bank = setting index 0..4
    endfunction
    function automatic int sg(input int s);
        case (s) 0: sg = 1; 1: sg = 4; 2: sg = 0; 3: sg = 1; default: sg = 2; endcase
    endfunction

    initial begin
        fd = $fopen("../results/sim_chain_out.txt", "w");
        repeat (5) @(posedge clk);
        rst <= 0;
        // DC blocker
        for (int i = 0; i < NDC; i++) begin
            @(negedge clk); dc_iv = 1; dc_id = $signed(dcin[i]);
            @(negedge clk); dc_iv = 0;
        end
        // full chain, 4 settings
        for (int s = 0; s < 5; s++) begin
            @(negedge clk);
            set = s; nout = 0; bank = 3'(sb(s)); gain = 4'(sg(s));
            clr = 1; @(negedge clk); clr = 0;
            repeat (600) @(negedge clk);             // FIR delay lines cleared
            for (int i = 0; i < NB; i++) begin
                bit_valid = 1; bit_in = vin[i][0];
                @(negedge clk);
                bit_valid = 0;
                repeat (BIT_PERIOD - 1) @(negedge clk);
            end
            repeat (2000) @(negedge clk);
            if (nout != NO) begin $display("FAIL set%0d: %0d outputs (exp %0d)", s, nout, NO); nerr++; end
            else $display("  setting %0d (bank %0d, gain %0d): %0d samples bit-exact so far", s, sb(s), sg(s), nout);
        end
        $fclose(fd);
        if (ndc != NDC) begin $display("FAIL dc count %0d", ndc); nerr++; end
        else $display("  dc_block: %0d samples checked", ndc);
        if (novr != 0) begin $display("FAIL: %0d overruns", novr); nerr++; end
        if (nerr == 0) $display("PASS tb_chain");
        else           $display("FAIL tb_chain: %0d errors", nerr);
        $finish;
    end
endmodule
`default_nettype wire
