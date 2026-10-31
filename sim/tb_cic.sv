// Self-checking testbench: cic_decim vs model/golden.py::cic_decim (bit-exact)
`timescale 1ns/1ps
`default_nettype none
`include "af_params.vh"
module tb_cic;
    localparam int NIN  = 15600;
    localparam int NOUT = NIN / `AF_CIC_R;
    logic clk = 0, rst = 1;
    always #5 clk = ~clk;

    logic in_valid = 0, in_bit = 0;
    logic out_valid;
    logic signed [`AF_CIC_W-1:0] out_data;

    cic_decim #(.N(`AF_CIC_N), .R(`AF_CIC_R), .W(`AF_CIC_W)) dut (.*);

    logic [0:0]               vin [NIN];
    logic [`AF_CIC_W-1:0]     vexp[NOUT];
    initial begin
        $readmemh("vectors/cic_in.hex", vin);
        $readmemh("vectors/cic_exp.hex", vexp);
    end

    int nout = 0, nerr = 0;
    always @(posedge clk) if (out_valid) begin
        if (out_data !== $signed(vexp[nout])) begin
            nerr++;
            if (nerr < 10) $display("MISMATCH cic[%0d]: got %0d exp %0d", nout, out_data, $signed(vexp[nout]));
        end
        nout++;
    end

    initial begin
        repeat (5) @(posedge clk);
        rst <= 0;
        @(posedge clk);
        for (int i = 0; i < NIN; i++) begin
            in_valid <= 1; in_bit <= vin[i][0];
            @(posedge clk);
            in_valid <= 0;
            repeat ((i % 3) + 1) @(posedge clk);   // irregular spacing (>=2 clocks)
        end
        repeat (20) @(posedge clk);
        if (nout != NOUT) begin $display("FAIL tb_cic: %0d outputs, expected %0d", nout, NOUT); nerr++; end
        if (nerr == 0) $display("PASS tb_cic: %0d outputs bit-exact", nout);
        else           $display("FAIL tb_cic: %0d mismatches", nerr);
        $finish;
    end
endmodule
`default_nettype wire
