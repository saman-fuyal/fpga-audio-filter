`timescale 1ns/1ps
// =============================================================================================
// audio_dac : audio output modulators for the Nexys A7 mono audio jack
// ---------------------------------------------------------------------------------------------
// The board's 4th-order Sallen-Key Butterworth low-pass filter turns the 1-bit stream back
// into an analog voltage (reconstruction filter).
//   mode = 0 : PWM, PWM_BITS resolution, carrier = clk / 2^PWM_BITS = 97.66 kHz
//              (Digilent: carrier >= 50 kHz). Duty changes only at a period boundary.
//   mode = 1 : first-order delta-sigma (PDM) at 100 MHz on all 16 bits; the quantization
//              noise is pushed far above the audio band where the board filter removes it.
// dac_out is a logic level; the top level drives the pin open-drain (0 -> '0', 1 -> 'Z').
// =============================================================================================
`default_nettype none
module audio_dac #(
    parameter OW       = 16,
    parameter PWM_BITS = 10
) (
    // ------------------------------------------------------------------------ ports
    input  wire                 clk,
    input  wire                 rst,
    input  wire                 mode,           // 0 PWM, 1 delta-sigma
    input  wire                 in_valid,
    input  wire signed [OW-1:0] in_data,
    output reg                  dac_out
);
    // ------------------------------------------------------------------------ registers / wires
    reg  signed [OW-1:0]   smp_q,  smp_d;       // held sample
    reg  [PWM_BITS-1:0]    pcnt_q, pcnt_d;      // PWM counter
    reg  [PWM_BITS-1:0]    duty_q, duty_d;      // PWM duty (offset binary)
    reg  [OW-1:0]          sacc_q, sacc_d;      // delta-sigma accumulator
    reg                    sbit_q, sbit_d;      // delta-sigma output bit
    reg                    dac_d;

    wire [OW-1:0] u   = {~smp_q[OW-1], smp_q[OW-2:0]};   // signed -> offset binary
    wire [OW:0]   sum = {1'b0, sacc_q} + {1'b0, u};
    wire          pwm = (pcnt_q < duty_q);


    // ------------------------------------------------------------------------ combinational
    always @(*) begin
        smp_d  = in_valid ? in_data : smp_q;
        pcnt_d = pcnt_q + 1'b1;
        duty_d = (pcnt_q == {PWM_BITS{1'b1}}) ? u[OW-1 -: PWM_BITS] : duty_q;
        sacc_d = sum[OW-1:0];
        sbit_d = sum[OW];                            // carry = output bit
        dac_d  = mode ? sbit_q : pwm;
    end

    // ------------------------------------------------------------------------ sequential
    always @(posedge clk) begin
        if (rst) begin
            smp_q   <= {OW{1'b0}};
            pcnt_q  <= {PWM_BITS{1'b0}};
            duty_q  <= {1'b1, {(PWM_BITS-1){1'b0}}};  // 50 %
            sacc_q  <= {OW{1'b0}};
            sbit_q  <= 1'b0;
            dac_out <= 1'b0;
        end else begin
            smp_q   <= smp_d;
            pcnt_q  <= pcnt_d;
            duty_q  <= duty_d;
            sacc_q  <= sacc_d;
            sbit_q  <= sbit_d;
            dac_out <= dac_d;
        end
    end
endmodule
`default_nettype wire
