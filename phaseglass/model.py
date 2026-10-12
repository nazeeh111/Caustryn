# SPDX-License-Identifier: MIT
"""Original single-point radio model, in meters, Hz and arbitrary complex IQ units."""

import math
import numpy as np

C = 299_792_458.0
MIN_DISTANCE = 0.15
MODEL = "unit-isotropic-single-point-inverse-distance-v1"
MAX_GRID = 20_000
MAX_FORWARD_WORK = 8_000_000


def number(value, label, low, high, *, integer=False):
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite number, not bool or text")
    if integer and type(value) is not int:
        raise ValueError(f"{label} must be an integer")
    # Compare bounds before converting an arbitrary JSON integer to float.
    if not low <= value <= high or not math.isfinite(value):
        raise ValueError(f"{label} must be between {low} and {high}")
    return value


def vector(value, label, length=3, low=-100, high=100):
    if type(value) is not list or len(value) != length:
        raise ValueError(f"{label} must be a list of {length} numbers")
    return np.array([number(v, label, low, high) for v in value], dtype=float)


def geometry(value, label):
    if type(value) is not list or not 1 <= len(value) <= 4:
        raise ValueError(f"{label} requires 1..4 antennas")
    return np.stack([vector(v, label) for v in value])


def bounds_and_grid(value, step, links, frequencies):
    if type(value) is not list or len(value) != 3:
        raise ValueError("bounds_m requires three increasing coordinate pairs")
    bounds = np.stack([vector(v, "bounds_m", length=2) for v in value])
    widths = bounds[:, 1] - bounds[:, 0]
    if np.any(widths < 0.05) or np.any(widths > 20):
        raise ValueError("Each room span must be 0.05..20 meters")
    number(step, "grid_step_m", 0.02, 2)
    if step > float(widths.min()):
        raise ValueError("Grid step must not exceed any room span")
    counts = [math.floor(float(w) / step) + 1 for w in widths]
    count = math.prod(counts)
    if count > MAX_GRID or count * links * frequencies > MAX_FORWARD_WORK:
        raise ValueError(
            "Grid exceeds 20,000 positions or 8,000,000 link-frequency-position work limit"
        )
    return bounds, counts


def channels(positions, tx, rx, frequencies):
    """Internal vectorized forward model: [point, TX*RX link, frequency].

    Input validation belongs to public scene/measurement entry points. Exclude a
    point less than 15 cm from any antenna by returning NaN for all its channels.
    Amplitude is inverse distance product; it is not calibrated received power.
    """
    p = np.atleast_2d(positions)
    dt = np.linalg.norm(p[:, None, :] - np.asarray(tx)[None, :, :], axis=-1)
    dr = np.linalg.norm(p[:, None, :] - np.asarray(rx)[None, :, :], axis=-1)
    lengths = (dt[:, :, None] + dr[:, None, :]).reshape(len(p), -1)
    denominator = dt[:, :, None] * dr[:, None, :]
    amp = (1 / np.maximum(denominator, MIN_DISTANCE**2)).reshape(len(p), -1)
    invalid = (dt.min(axis=1) < MIN_DISTANCE) | (dr.min(axis=1) < MIN_DISTANCE)
    result = amp[:, :, None] * np.exp(
        -2j * np.pi * lengths[:, :, None] * np.asarray(frequencies)[None, None, :] / C
    )
    result[invalid] = np.nan
    return result


def encode_complex(a):
    return {"real": np.real(a).tolist(), "imag": np.imag(a).tolist()}


def decode_complex(value, links, frequencies):
    if type(value) is not dict or set(value) != {"real", "imag"}:
        raise ValueError("IQ requires exactly real and imag matrices")
    arrays = []
    for part in ("real", "imag"):
        matrix = value[part]
        if type(matrix) is not list or len(matrix) != links:
            raise ValueError("IQ link dimension must match antenna geometry")
        arrays.append(
            np.stack(
                [
                    vector(row, "IQ " + part, frequencies, -10000, 10000)
                    for row in matrix
                ]
            )
        )
    iq = arrays[0] + 1j * arrays[1]
    if np.linalg.norm(iq) < 1e-12:
        raise ValueError("Zero or numerically negligible IQ has no identifying signal")
    return iq
