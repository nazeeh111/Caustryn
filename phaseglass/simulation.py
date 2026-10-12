# SPDX-License-Identifier: MIT
"""Scene-to-IQ simulation. Generator truth never enters inverse measurement fields."""

import numpy as np
from .model import (
    C,
    MIN_DISTANCE,
    MODEL,
    bounds_and_grid,
    channels,
    decode_complex,
    encode_complex,
    geometry,
    number,
    vector,
)

SCENE_REQUIRED = {
    "name",
    "tx_m",
    "rx_m",
    "bounds_m",
    "position_m",
    "carrier_hz",
    "bandwidth_hz",
    "subcarriers",
    "noise_snr_db",
    "gain_mode",
    "seed",
    "grid_step_m",
}
SCENE_OPTIONAL = {"extra_reflector", "phase_slope_target_m"}


def simulate(scene):
    if (
        type(scene) is not dict
        or not SCENE_REQUIRED <= set(scene)
        or set(scene) - SCENE_REQUIRED - SCENE_OPTIONAL
    ):
        raise ValueError(
            "Scene requires the documented keys; unknown fields are forbidden"
        )
    name = scene["name"]
    if type(name) is not str or not 1 <= len(name) <= 80:
        raise ValueError("name must be 1..80 characters")
    tx, rx = geometry(scene["tx_m"], "tx_m"), geometry(scene["rx_m"], "rx_m")
    n = number(scene["subcarriers"], "subcarriers", 1, 128, integer=True)
    carrier = number(scene["carrier_hz"], "carrier_hz", 1e6, 10e9)
    bandwidth = number(scene["bandwidth_hz"], "bandwidth_hz", 0, 1e9)
    if n > 1 and bandwidth / (n - 1) < 1000:
        raise ValueError(
            "Multiple subcarriers require at least 1000 Hz frequency spacing"
        )
    if n == 1 and bandwidth != 0:
        raise ValueError("A single subcarrier requires bandwidth_hz=0")
    f = (
        np.linspace(carrier - bandwidth / 2, carrier + bandwidth / 2, n)
        if n > 1
        else np.array([carrier])
    )
    if f.min() < 1e6 or f.max() > 10e9:
        raise ValueError("All frequencies must lie within 1 MHz..10 GHz")
    bounds, _ = bounds_and_grid(
        scene["bounds_m"], scene["grid_step_m"], len(tx) * len(rx), n
    )
    point = vector(scene["position_m"], "position_m")
    if np.any(point < bounds[:, 0]) or np.any(point > bounds[:, 1]):
        raise ValueError("Generator point must be inside room bounds")
    mode = scene["gain_mode"]
    if type(mode) is not str or mode not in ("calibrated", "profiled"):
        raise ValueError("gain_mode must be calibrated or profiled")
    seed = number(scene["seed"], "seed", 0, 2**32 - 1, integer=True)
    snr = scene["noise_snr_db"]
    if snr is not None:
        number(snr, "noise_snr_db", 0, 100)
    ideal = channels(point, tx, rx, f)[0]
    if not np.isfinite(ideal).all():
        raise ValueError("Generator point is within the 15 cm antenna exclusion")
    rng = np.random.default_rng(seed)
    gains = np.ones(len(ideal), dtype=complex)
    if mode == "profiled":
        gains = rng.uniform(0.65, 1.35, len(ideal)) * np.exp(
            1j * rng.uniform(-np.pi, np.pi, len(ideal))
        )
    signal = ideal * gains[:, None]
    target = scene.get("phase_slope_target_m")
    if target is not None:
        target = vector(target, "phase_slope_target_m")
        if np.any(target < bounds[:, 0]) or np.any(target > bounds[:, 1]):
            raise ValueError("Slope-counterfeit target must be inside room bounds")
        counterfeit = channels(target, tx, rx, f)[0]
        if not np.isfinite(counterfeit).all():
            raise ValueError("Slope target violates antenna exclusion")
        signal *= (counterfeit / abs(counterfeit)) / (ideal / abs(ideal))
    extra = scene.get("extra_reflector")
    if extra is not None:
        if type(extra) is not dict or set(extra) != {
            "position_m",
            "gain_real",
            "gain_imag",
        }:
            raise ValueError(
                "extra_reflector requires position_m, gain_real and gain_imag"
            )
        ep = vector(extra["position_m"], "extra reflector position")
        if np.any(ep < bounds[:, 0]) or np.any(ep > bounds[:, 1]):
            raise ValueError("Extra reflector must be inside room bounds")
        amplitude = complex(
            number(extra["gain_real"], "gain_real", -2, 2),
            number(extra["gain_imag"], "gain_imag", -2, 2),
        )
        additional = channels(ep, tx, rx, f)[0]
        if not np.isfinite(additional).all():
            raise ValueError("Extra reflector violates antenna exclusion")
        signal += amplitude * additional
        extra = {
            "position_m": ep.tolist(),
            "gain_real": float(amplitude.real),
            "gain_imag": float(amplitude.imag),
        }
    rms = np.sqrt(np.mean(abs(signal) ** 2))
    if rms < 1e-12:
        raise ValueError("Scene produces negligible signal")
    sigma = float(rms / np.sqrt(2) * 10 ** (-snr / 20)) if snr is not None else 0.0
    if 0 < sigma < 1e-12:
        raise ValueError(
            "Scene noise is below the supported numerical floor of 1e-12 IQ units"
        )
    iq = signal + sigma * (
        rng.normal(size=signal.shape) + 1j * rng.normal(size=signal.shape)
    )
    encoded_iq = encode_complex(iq)
    decode_complex(encoded_iq, len(tx) * len(rx), n)
    measurement = {
        "schema": "blind-point-radio-v1",
        "name": name,
        "tx_m": tx.tolist(),
        "rx_m": rx.tolist(),
        "frequencies_hz": f.tolist(),
        "iq": encoded_iq,
        "noise_std_per_component": sigma,
        "bounds_m": bounds.tolist(),
        "grid_step_m": scene["grid_step_m"],
        "gain_mode": mode,
        "model": MODEL,
        "minimum_antenna_distance_m": MIN_DISTANCE,
    }
    truth = {
        "kind": "simulated-generator-truth-not-measurement",
        "position_m": point.tolist(),
        "generator_only_link_gains": encode_complex(gains),
        "seed": seed,
        "noise_snr_db": snr,
        "extra_reflector": extra,
        "phase_slope_target_m": target.tolist() if target is not None else None,
        "bandwidth_hz": float(np.ptp(f)),
        "total_path_delay_scale_m": C / float(np.ptp(f)) if n > 1 else None,
        "warning": "Point-scattering simulation; no hardware capture or human pose inferred",
    }
    return {"measurement": measurement, "truth": truth}
