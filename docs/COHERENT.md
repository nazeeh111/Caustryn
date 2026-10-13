# Coherent receiver sweeps

A single receiver configuration cannot identify a point when its complex hardware response is independently unknown at every antenna pair and frequency. A coherent sweep adds known receiver positions while requiring that response to remain fixed across them. Phaseglass fits the location by eliminating those response coefficients analytically, then predicts separate held receiver configurations without refitting or choosing a mode from their IQ.

This is a **single-point simulation and inverse-design tool**. Receiver geometry, hardware indexing, stable response and the stationary point model are trusted assumptions. Good training and held residuals cannot certify those assumptions. No real CSI collection, hardware calibration, room reconstruction, physical precision or global uniqueness is established.

## Packet contract

Training uses `blind-coherent-point-sweep-v1`: `name`, `tx_m`, `rx_poses_m`, `frequencies_hz`, `iq`, `noise_std_per_component`, `bounds_m`, `grid_step_m`, `model`, `minimum_antenna_distance_m`, and `gain_assumption`. IQ real/imag arrays are indexed `[receiver configuration][TX × RX pair][frequency]`; receiver configurations contain known XYZ antenna coordinates in meters. Transmitter-major pair order follows the existing point model. The exact gain assumption is `unknown complex response per pair/frequency constant across all positions`.

Held observations use `held-coherent-point-sweep-v1`: `training_sha256`, `rx_poses_m`, and `iq`. The SHA256 refers to canonical sorted compact finite JSON of the training packet, with integral floats normalized to integers and negative zero to zero. Thus Python `0.0` and browser `0` have the same identity; changed nonintegral values still change the digest. Held configurations must be distinct from each other and from training. The same indexed hardware, frequencies and component noise level are assumed. Truth, generator seed and gain fields are forbidden in both measurement packets.

`validate_sweep_inputs(training, validation=None)` validates without fitting. `solve_sweep(training)` reads training only. `evaluate_sweep(training, validation)` freshly solves that same training, then returns separate predictions for **every retained candidate using its own training-fitted gain**. It never refits gain/location or removes/selects a mode using held IQ.

For each candidate location, the response is

`g[p,f] = Σₖ conj(H[k,p,f]) y[k,p,f] / Σₖ |H[k,p,f]|²`.

The fit uses a finite grid and up to 48 local seeds. Bounds: 1–8 distinct training configurations, 1–4 TX and RX antennas, 1–128 frequencies, 20,000 grid points, 8,000,000 coarse channel evaluations and 160 optimizer-reported function evaluations per seed. Numerical Jacobian probes are additional to that counter (up to three per optimizer Jacobian evaluation), plus six local rank probes per found mode. Held configurations also number 1–8; output is bounded to 65,536 predicted complex values, refusing rather than silently dropping modes. The enclosing studio worker adds its existing time bound. Local rank is a numerical diagnostic, not a global uniqueness certificate.

## Examples and refusal

`examples/coherent/index.json` contains nine original generated cases with separate training, validation and generator-truth objects. Separate packet files are included for replay. The generator is `tools/generate_coherent_examples.py`; fitting does not call it or read truth.

- Stable arbitrary frequency response and a stable delay counterfeit demonstrate information gained from known receiver motion. An independently generated second point and a single-frequency sweep test the same solver.
- One configuration retains an unidentifiable family and selects no point. Coplanar motion preserves both reflected modes.
- Random response drift during training causes a mismatch refusal. Drift confined to held configurations causes a prediction refusal.
- An exact position-dependent response can impersonate a different point and **pass both training and held prediction while wrong**. It is an intentional falsifier of calibration claims, not an estimate to trust.

Found modes are retained around the best weighted residual, with delta 16.27 under stated noise or `max(1,dof) × 1e-4` at the numerical residual scale under zero stated noise. This delta always includes the best found mode and is not calibrated uncertainty coverage. Training reduced residual above 3, or noiseless relative residual above 1e-6, refuses under diagnostic heuristics; search failure can also explain refusal. Held noise scaling propagates training gain-estimation noise at the fixed fitted point, but does not calibrate fitted-position uncertainty or confidence coverage. Compatibility remains conditional on the model. Every retained prediction stays visible even when another predicts better.

## Prior work

Motion-derived radio apertures are established: [Wi-Vi](https://people.csail.mit.edu/fadel/wivi/design.html), [synthetic-aperture Wi-Fi imaging](https://arxiv.org/abs/1903.03895), and [X-AR](https://www.usenix.org/conference/nsdi23/presentation/boroushaki) use spatial samples or known motion in different hardware/target settings. [Magnitude-based multi-band phase retrieval](https://arxiv.org/abs/1903.02367) addresses hardware phase distortions by another route. This extension is an accessible falsifiable experiment inside Phaseglass, not an invention of synthetic aperture or an independently validated physical sensing system.
