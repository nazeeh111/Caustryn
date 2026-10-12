# Measurement JSON

The inverse accepts exactly these fields:

| Field                      | Meaning                                                                |
| -------------------------- | ---------------------------------------------------------------------- |
| schema                     | `blind-point-radio-v1`                                                 |
| name                       | 1..80 character label                                                  |
| tx_m, rx_m                 | Lists of 3-coordinate antenna positions, 1..4 each                     |
| frequencies_hz             | 1..128 increasing values, ≥1000 Hz apart                               |
| iq                         | `{real: [[...]], imag: [[...]]}`; one row per TX×RX link               |
| noise_std_per_component    | Standard deviation for each real/imag component; zero means noise-free |
| bounds_m                   | Three increasing coordinate pairs                                      |
| grid_step_m                | Finite initialization count control                                    |
| gain_mode                  | `calibrated` or `profiled`                                             |
| model                      | `unit-isotropic-single-point-inverse-distance-v1`                      |
| minimum_antenna_distance_m | Exactly 0.15                                                           |

Link order is transmitter-major: TX1/RX1, TX1/RX2, then TX2/RX1, etc.
IQ rows have exactly as many entries as frequencies. Values are finite numbers
within ±10000. Positive noise standard deviation is at least 1e-12 and at most
1000 IQ units. Optional generator truth, seed, motion labels, body joints and
unknown additional fields are refused rather than ignored.

The schema declares an already baseline-isolated channel under the given model.
It does not make an arbitrary WiFi packet suitable for inversion. Raw ESP32 or
Nexmon data is not a supported import in this release.

Scene JSON uses the twelve examples' `scenes/` schema. Generator-only
`extra_reflector` and `phase_slope_target_m` deliberately violate the inverse
model; these fields never enter measurement JSON. `noise_snr_db=null` is
noise-free, `subcarriers=1` requires `bandwidth_hz=0`.
