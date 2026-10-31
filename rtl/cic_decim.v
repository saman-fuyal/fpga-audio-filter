`timescale 1ns/1ps
// =============================================================================================
// cic_decim : N-stage CIC decimator (Hogenauer), 1-bit PDM input mapped to +1 / -1
// ---------------------------------------------------------------------------------------------
//   H(z) = [ (1 - z^-R) / (1 - z^-1) ]^N        DC gain R^N = 25^4 = 390 625
//
// * N integrators run at the input rate as a register chain (stage k adds the OLD value of
//   stage k-1, i.e. one register per stage).
// * On every R-th input a strobe starts the N combs, which run at the low rate as a pipeline
//   of one clock per stage.
// * All registers are W bits and may overflow and wrap: two's-complement arithmetic is
//   modular, so with W >= 2 + N*log2(R) = 21 the comb output is still exact. Add/subtract
//   are therefore done on plain (unsigned) vectors; only the output is read as signed.
// * Registers are packed into vectors (stage k occupies bits [k*W +: W]).
// Bit-exact model: model/golden.py::cic_decim()
// =============================================================================================
`default_nettype none
module cic_decim #(
    parameter N = 4,                     // stages
    parameter R = 25,                    // decimation factor
    parameter W = 21                     // register width
) (
    // ------------------------------------------------------------------------ ports
    input  wire         clk,
    input  wire         rst,             // synchronous; also used as "clear"
    input  wire         in_valid,        // at most one every 2 clocks
    input  wire         in_bit,
    output wire         out_valid,       // one strobe per R inputs
    output wire [W-1:0] out_data         // signed, two's complement
);
    // ------------------------------------------------------------------------ localparams / wires
    localparam RW = $clog2(R);

    reg  [N*W-1:0] integ_q, integ_d;     // integrator registers
    reg  [N*W-1:0] cdly_q,  cdly_d;      // comb delay registers
    reg  [N*W-1:0] cout_q,  cout_d;      // comb stage outputs
    reg  [N:0]     cv_q,    cv_d;        // comb valid pipeline (cv[k] -> stage k works)
    reg  [RW-1:0]  rcnt_q,  rcnt_d;      // input counter 0..R-1
    reg  [W-1:0]   src;                  // comb stage input (combinational temp)
    integer        k;

    // +1 = 00..01, -1 = 11..11  (in two's complement)
    wire [W-1:0] x = {{(W-1){~in_bit}}, 1'b1};

    assign out_valid = cv_q[N];
    assign out_data  = cout_q[(N-1)*W +: W];

    // ------------------------------------------------------------------------ combinational
    always @(*) begin
        // defaults: hold every register
        integ_d = integ_q;
        cdly_d  = cdly_q;
        cout_d  = cout_q;
        rcnt_d  = rcnt_q;
        src     = {W{1'b0}};

        // integrators (input rate)
        if (in_valid) begin
            integ_d[0 +: W] = integ_q[0 +: W] + x;
            for (k = 1; k < N; k = k + 1)
                integ_d[k*W +: W] = integ_q[k*W +: W] + integ_q[(k-1)*W +: W];
            if (rcnt_q == R - 1) rcnt_d = {RW{1'b0}};
            else                 rcnt_d = rcnt_q + 1'b1;
        end

        // decimation strobe: the cycle AFTER the R-th input, when the last integrator
        // already holds the updated value (matches the model)
        cv_d = {cv_q[N-1:0], (in_valid && (rcnt_q == R - 1))};

        // combs (low rate, one stage per clock)
        for (k = 0; k < N; k = k + 1) begin
            if (k == 0) src = integ_q[(N-1)*W +: W];
            else        src = cout_q[(k-1)*W +: W];
            if (cv_q[k]) begin
                cout_d[k*W +: W] = src - cdly_q[k*W +: W];
                cdly_d[k*W +: W] = src;
            end
        end
    end

    // ------------------------------------------------------------------------ sequential
    always @(posedge clk) begin
        if (rst) begin
            integ_q <= {(N*W){1'b0}};
            cdly_q  <= {(N*W){1'b0}};
            cout_q  <= {(N*W){1'b0}};
            cv_q    <= {(N+1){1'b0}};
            rcnt_q  <= {RW{1'b0}};
        end else begin
            integ_q <= integ_d;
            cdly_q  <= cdly_d;
            cout_q  <= cout_d;
            cv_q    <= cv_d;
            rcnt_q  <= rcnt_d;
        end
    end
endmodule
`default_nettype wire
