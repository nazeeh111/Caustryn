# SPDX-License-Identifier: MIT
"""Original blind finite-grid/local inverse and pair-specific receiver intervention."""

import hashlib
import json
import time
import numpy as np
from scipy.optimize import least_squares
from .model import (
    MIN_DISTANCE,
    MODEL,
    bounds_and_grid,
    channels,
    decode_complex,
    geometry,
    number,
    vector,
)

KEYS = {
    "schema",
    "name",
    "tx_m",
    "rx_m",
    "frequencies_hz",
    "iq",
    "noise_std_per_component",
    "bounds_m",
    "grid_step_m",
    "gain_mode",
    "model",
    "minimum_antenna_distance_m",
}


def measurement_hash(data):
    return hashlib.sha256(
        json.dumps(
            data, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def validate(data):
    if (
        type(data) is not dict
        or set(data) != KEYS
        or data["schema"] != "blind-point-radio-v1"
    ):
        raise ValueError(
            "Input must contain exactly blind measurement fields; truth/pose fields forbidden"
        )
    if type(data["name"]) is not str or not 1 <= len(data["name"]) <= 80:
        raise ValueError("name must contain 1..80 characters")
    tx, rx = geometry(data["tx_m"], "tx_m"), geometry(data["rx_m"], "rx_m")
    frequencies = data["frequencies_hz"]
    if type(frequencies) is not list or not 1 <= len(frequencies) <= 128:
        raise ValueError("Expected 1..128 frequencies")
    f = vector(frequencies, "frequencies_hz", len(frequencies), 1e6, 10e9)
    if np.any(np.diff(f) < 1000):
        raise ValueError("Frequencies must increase by at least 1000 Hz")
    y = decode_complex(data["iq"], len(tx) * len(rx), len(f))
    sigma = number(data["noise_std_per_component"], "noise_std_per_component", 0, 1000)
    if 0 < sigma < 1e-12:
        raise ValueError(
            "Positive noise standard deviation must be at least 1e-12 IQ units"
        )
    if (
        number(
            data["minimum_antenna_distance_m"], "minimum_antenna_distance_m", 0.15, 0.15
        )
        != MIN_DISTANCE
    ):
        raise ValueError("Declared antenna exclusion must be 0.15 m")
    if (
        type(data["gain_mode"]) is not str
        or data["gain_mode"] not in ("profiled", "calibrated")
        or data["model"] != MODEL
    ):
        raise ValueError("Unsupported calibration mode or physical model")
    bounds, counts = bounds_and_grid(
        data["bounds_m"], data["grid_step_m"], len(tx) * len(rx), len(f)
    )
    return tx, rx, f, y, bounds, counts, sigma


def fit_gain(s, y):
    """Per-link constant complex least-squares gain: s^H y / s^H s."""
    return np.sum(s.conj() * y, axis=-1) / np.sum(abs(s) ** 2, axis=-1)


def solve(data):
    started = time.perf_counter()
    tx, rx, f, y, bounds, counts, sigma = validate(data)
    mode = data["gain_mode"]
    axes = [np.linspace(a, b, n) for (a, b), n in zip(bounds, counts)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    norm_y = float(np.linalg.norm(y))
    scale = sigma if sigma else float(np.sqrt(np.mean(abs(y) ** 2))) * 1e-6
    scale = max(scale, 1e-18)
    scores = np.full(len(grid), np.inf)
    for start in range(0, len(grid), 256):
        s = channels(grid[start : start + 256], tx, rx, f)
        with np.errstate(invalid="ignore", divide="ignore"):
            alpha = fit_gain(s, y)
            residual = s * alpha[..., None] - y
            values = np.sum(abs(residual) ** 2, axis=(1, 2))
        scores[start : start + 256] = np.where(np.isfinite(values), values, np.inf)
    if not np.isfinite(scores).any():
        raise ValueError("No nonsingular points in the finite initialization grid")
    seeds = []
    for index in np.argsort(scores):
        if not np.isfinite(scores[index]):
            break
        p = grid[index]
        if all(np.linalg.norm(p - prev) > 0.45 for prev in seeds):
            seeds.append(p)
        if len(seeds) == 40:
            break

    def raw_residual(p, gain_mode):
        s = channels(p, tx, rx, f)[0]
        if not np.isfinite(s).all():
            return None
        if gain_mode == "profiled":
            s = s * fit_gain(s, y)[:, None]
        r = (s - y) / scale
        return np.concatenate((r.real.ravel(), r.imag.ravel()))

    def residual(p, gain_mode):
        actual = raw_residual(p, gain_mode)
        return actual if actual is not None else np.full(2 * y.size, 1e20)

    degenerate = len(f) == 1 and mode == "profiled"
    dof = 2 * y.size - (2 * len(y) if mode == "profiled" else 0) - 3
    candidates = []
    for seed in seeds:
        if degenerate:
            p, converged, evaluations = seed, None, 0
        else:
            first = least_squares(
                lambda p: residual(p, "profiled"),
                seed,
                bounds=(bounds[:, 0], bounds[:, 1]),
                max_nfev=160,
                ftol=1e-11,
                xtol=1e-11,
                gtol=1e-9,
            )
            final = (
                first
                if mode == "profiled"
                else least_squares(
                    lambda p: residual(p, mode),
                    first.x,
                    bounds=(bounds[:, 0], bounds[:, 1]),
                    max_nfev=160,
                    ftol=1e-11,
                    xtol=1e-11,
                    gtol=1e-9,
                )
            )
            p, converged = final.x, bool(final.success)
            evaluations = first.nfev + (0 if final is first else final.nfev)
        r = raw_residual(p, mode)
        if r is None or any(
            np.linalg.norm(p - prev["position_m"]) < 0.02 for prev in candidates
        ):
            continue
        cost = float(np.dot(r, r))
        # A numerical local diagnostic, with one-sided differences at active bounds
        # or antenna exclusions. Never use excluded-point penalty as a derivative.
        columns = []
        for i in range(3):
            lo, hi = p.copy(), p.copy()
            lo[i], hi[i] = (
                max(bounds[i, 0], p[i] - 1e-5),
                min(bounds[i, 1], p[i] + 1e-5),
            )
            left, right = raw_residual(lo, mode), raw_residual(hi, mode)
            if left is None:
                left, lo = r, p
            if right is None:
                right, hi = r, p
            span = hi[i] - lo[i]
            columns.append((right - left) / span if span > 0 else np.zeros_like(r))
        singular = np.linalg.svd(np.stack(columns, axis=1), compute_uv=False)
        rank = (
            0 if degenerate else int(np.sum(singular > max(1e-5, singular[0] * 1e-5)))
        )
        # The residual dimensionality caps rank even when finite-difference noise
        # perturbs a theoretically zero singular value.
        rank = min(rank, max(0, 2 * y.size - (2 * len(y) if mode == "profiled" else 0)))
        candidates.append(
            {
                "position_m": p.tolist(),
                "weighted_squared_residual": cost,
                "reduced_chi_squared": cost / dof if sigma and dof > 0 else None,
                "degrees_of_freedom": dof if dof > 0 else None,
                "relative_iq_residual": float(np.linalg.norm(r) * scale / norm_y),
                "local_jacobian_rank": rank,
                "jacobian_singular_values": singular.tolist(),
                "weakest_local_one_unit_residual_displacement_m": float(
                    1 / singular[-1]
                )
                if rank == 3 and sigma
                else None,
                "optimizer_converged": converged,
                "evaluations": evaluations,
            }
        )
    if not candidates:
        raise ValueError("Finite local search found no admissible candidate")
    candidates.sort(key=lambda a: a["weighted_squared_residual"])
    best = candidates[0]
    threshold = (
        best["weighted_squared_residual"] + 16.27 if sigma else max(1, dof) * 1e-4
    )
    retained = [a for a in candidates if a["weighted_squared_residual"] <= threshold]
    chi = best["reduced_chi_squared"]
    refusal = (chi is not None and chi > 3) or (
        not sigma and best["relative_iq_residual"] > 1e-6
    )
    broad_fraction = float(
        np.mean(scores <= (best["weighted_squared_residual"] + 16.27) * scale**2)
    )
    weak = bool(
        sigma
        and (
            broad_fraction > 0.05
            or (
                best["local_jacobian_rank"] == 3
                and best["jacobian_singular_values"][-1] < 2
            )
        )
    )
    status = (
        "model-mismatch-or-search-failure"
        if refusal
        else (
            "unidentifiable-family"
            if degenerate or best["local_jacobian_rank"] < 3 or dof <= 0
            else (
                "weakly-constrained-hold"
                if weak
                else (
                    "multiple-compatible-modes"
                    if len(retained) > 1
                    else "one-found-mode-no-global-guarantee"
                )
            )
        )
    )
    return {
        "schema": "blind-point-fit-v1",
        "measurement_sha256": measurement_hash(data),
        "input_name": data["name"],
        "gain_mode": mode,
        "status": status,
        "candidate_count": len(retained),
        "candidates": retained,
        "best_fit_even_if_refused": best,
        "grid_positions": len(grid),
        "chunk_positions": 256,
        "coarse_profiled_grid_compatible_fraction": broad_fraction,
        "refinement_seeds": len(seeds),
        "searched_local_modes": len(candidates),
        "candidate_budget_exhausted": len(seeds) == 40,
        "coarse_field": {
            "axes_m": [a.tolist() for a in axes],
            "shape": counts,
            "profiled_squared_residual": [
                float(v) if np.isfinite(v) else None for v in scores
            ],
            "quantity": "Actual unweighted squared complex residual after constant gain profiling",
            "warning": "Finite coarse initialization field, including in calibrated mode; not probability, ground truth, a calibrated-mode fit or a global uniqueness certificate",
        },
        "candidate_policy": "Finite discovered modes within delta weighted RSS 16.27; no calibrated coverage, exhaustive modes or unique-space certificate",
        "acceptance_policy": "Refuse if best reduced chi squared >3, or noiseless relative residual >1e-6. May mean search failure. No truth-based selection.",
        "hold_policy": "Hold for deficient local rank, >5% compatible coarse points, or weakest local one-unit residual displacement >0.5m; diagnostic heuristics, not uncertainty coverage.",
        "noise_free_numeric_floor_fraction": 1e-6 if not sigma else None,
        "model_warning": "Constant gain profiling assumes calibrated phase slopes. A good residual cannot validate that assumption; no body pose or hardware accuracy claim.",
        "seconds": time.perf_counter() - started,
    }


def suggest_intervention(measurement, result):
    tx, rx, f, _, bounds, _, _ = validate(measurement)
    if (
        type(result) is not dict
        or result.get("schema") != "blind-point-fit-v1"
        or result.get("measurement_sha256") != measurement_hash(measurement)
    ):
        raise ValueError("Intervention requires the matching blind solver result")
    candidates = result.get("candidates")
    if type(candidates) is not list or len(candidates) > 40:
        raise ValueError("Result requires at most 40 candidate entries")
    positions = []
    for candidate in candidates:
        if type(candidate) is not dict or "position_m" not in candidate:
            raise ValueError("Each candidate requires a position")
        p = vector(candidate["position_m"], "candidate position")
        if (
            np.any(p < bounds[:, 0])
            or np.any(p > bounds[:, 1])
            or not np.isfinite(channels(p, tx, rx, f)).all()
        ):
            raise ValueError("Candidate violates model bounds or antenna exclusion")
        positions.append(p)
    empty = {
        "status": "no-competing-pair",
        "receiverIndex": None,
        "position_m": None,
        "pairSeparationBefore": None,
        "pairSeparationAfter": None,
        "search": {
            "candidateSites": 0,
            "validSites": 0,
            "method": "No pair available",
            "warning": "One found mode is not proof of unique space; this method needs a competing pair",
        },
    }
    if len(positions) < 2:
        return empty
    if result.get("status") == "model-mismatch-or-search-failure":
        return {
            **empty,
            "status": "refused-model-fit",
            "search": {
                **empty["search"],
                "warning": "Resolve model mismatch before interpreting a receiver intervention",
            },
        }
    a = positions[0]
    b = max(positions[1:], key=lambda p: np.linalg.norm(p - a))
    # Move the third receiver when present, otherwise the last existing receiver.
    receiver_index = min(2, len(rx) - 1)
    sites = np.stack(
        np.meshgrid(
            np.linspace(*bounds[0], 5),
            np.linspace(*bounds[1], 9),
            np.linspace(*bounds[2], 5),
            indexing="ij",
        ),
        axis=-1,
    ).reshape(-1, 3)

    def separation(geometry_rx):
        s = channels(np.stack([a, b]), tx, geometry_rx, f)
        if not np.isfinite(s).all():
            return None
        alpha = fit_gain(s[1], s[0])
        forward = float(
            np.linalg.norm(s[1] * alpha[:, None] - s[0]) / np.linalg.norm(s[0])
        )
        alpha_reverse = fit_gain(s[0], s[1])
        reverse = float(
            np.linalg.norm(s[0] * alpha_reverse[:, None] - s[1]) / np.linalg.norm(s[1])
        )
        return (forward + reverse) / 2

    before = separation(rx)
    best, best_position, valid = before, rx[receiver_index].copy(), 0
    for site in sites:
        changed = rx.copy()
        changed[receiver_index] = site
        contrast = separation(changed)
        if contrast is None:
            continue
        valid += 1
        if contrast > best:
            best, best_position = contrast, site
    return {
        "status": "proposed" if best > before + 1e-9 else "no-improvement-found",
        "receiverIndex": receiver_index,
        "position_m": best_position.tolist(),
        "pairSeparationBefore": before,
        "pairSeparationAfter": best,
        "selectedPair_m": [a.tolist(), b.tolist()],
        "search": {
            "candidateSites": len(sites),
            "validSites": valid,
            "method": "225 declared receiver sites; maximize mean bidirectional relative IQ separation after per-link constant complex gain profiling",
            "warning": "Chosen pair and finite placement grid only; no globally optimal placement or unique-space guarantee",
        },
    }
