# Physical model and search contract

This version models a static, isotropic, single point with a baseline-isolated
transmitter-point-receiver channel. Coordinates are meters, frequency is Hz,
light speed is 299792458 m/s. IQ means the real and imaginary components of a
complex signal. Its units here are arbitrary, not watts. Points within 15 cm of
any antenna are excluded.

There are two gain contracts: `calibrated` fixes link gain to one; `profiled`
fits a constant complex gain per link using sᴴy / sᴴs. Frequency-dependent phase
slopes are not fitted. The generator can deliberately violate that assumption
or add another reflector, with those controls held outside the inverse packet.

## Inference

The grid uses linspace endpoints with floor(span / requested step)+1 positions
per axis. Thus grid_step_m controls count; actual spacing may differ slightly.
The coarse initializer always profiles gains, even for calibrated final fits.
Up to 40 separated starting points are refined with bounded least squares,
160 function evaluations per stage. Calibrated mode adds its own refinement
after profiled initialization. Max refinement starts reached is reported.

Found candidates within delta weighted squared residual 16.27 are retained for
noisy packets; noise-free fits use a declared numeric floor. These thresholds
are heuristic. They are not a confidence region, exhaustive mode enumeration or
proof that an optimizer found the global minimum. Result seconds measures core
compute only, not network or process startup.

Refusal: best reduced chi-squared above 3, or noise-free relative residual above
1e-6. A mismatch may reflect incomplete search rather than a physical failure.
Weak/noisy hold: deficient local rank, over 5% compatible coarse samples, or a
weak local one-unit-residual displacement above 0.5 m. Numerical local singular
values describe a neighborhood only. Finite differences and a fixed 3-parameter
nominal degrees-of-freedom subtraction are not calibrated statistical coverage.

## Placement

Given a matching measurement hash and selected discovered modes, choose the
most distant competitor to the anchor. Move receiver 3 when present, otherwise
the last receiver. Evaluate a 5×9×5 grid over room bounds and maximize mean
bidirectional relative IQ difference after constant gain profiling. This tests
the chosen pair only. It is neither a global optimum nor a uniqueness guarantee.
The proposal never uses generator truth. Applying it requires a declared scene
and new simulated IQ, not changing antenna metadata on old observed samples.

## Resource boundaries

1..4 transmitters and receivers, 1..128 increasing frequencies within 1 MHz..
10 GHz, 20,000 grid points, 8,000,000 coarse link-frequency-point evaluations,
256-position batches. Coordinate components within ±100 m; room spans 0.05..20 m;
grid count step 0.02..2 m no larger than the smallest span. Measurement/scene
input types are strict; bool, numeric strings, nonfinite values and zero IQ are
rejected. The CLI and server bound worker wall time to 25 s. Dependency allocation
is not a cross-platform hard memory sandbox; never treat this local server as an
internet service without separate deployment design.
