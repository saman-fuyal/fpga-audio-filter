`timescale 1ns/1ps
// Self-checking testbench for asic/rtl/fir_par.sv (both PIPE variants, bit-exact)
`default_nettype none
module tb_fir_par;
    localparam int NV = 2112;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;
    logic in_valid = 0;
    logic signed [15:0] in_data = 0;
    logic ov0, ov1;
    logic signed [15:0] od0, od1;
    fir_par #(.PIPE(0)) u0 (.clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_data(in_data), .out_valid(ov0), .out_data(od0));
    fir_par #(.PIPE(1)) u1 (.clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_data(in_data), .out_valid(ov1), .out_data(od1));
    logic [15:0] vx [NV], vy [NV];
    initial begin $readmemh("../vectors/x.hex", vx); $readmemh("../vectors/y.hex", vy); end
    int n0 = 0, n1 = 0, nerr = 0;
    always @(posedge clk) begin
        if (ov0) begin if (od0 !== $signed(vy[n0])) begin nerr++; if (nerr < 6) $display("PIPE0 y[%0d] got %0d exp %0d", n0, od0, $signed(vy[n0])); end n0++; end
        if (ov1) begin if (od1 !== $signed(vy[n1])) begin nerr++; if (nerr < 6) $display("PIPE1 y[%0d] got %0d exp %0d", n1, od1, $signed(vy[n1])); end n1++; end
    end
    initial begin
        repeat (3) @(negedge clk); rst_n = 1;
        for (int i = 0; i < NV; i++) begin
            @(negedge clk); in_valid = 1; in_data = $signed(vx[i]);
            if (i % 7 == 3) begin @(negedge clk); in_valid = 0; end   // some gaps, mostly back-to-back
        end
        @(negedge clk); in_valid = 0;
        repeat (20) @(negedge clk);
        if (n0 != NV || n1 != NV) begin nerr++; $display("count %0d %0d", n0, n1); end
        if (nerr == 0) $display("PASS tb_fir_par: %0d samples bit-exact for PIPE=0 and PIPE=1", NV);
        else $display("FAIL tb_fir_par: %0d errors", nerr);
        $finish;
    end
endmodule
`default_nettype wire
