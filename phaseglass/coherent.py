# SPDX-License-Identifier: MIT
"""Blind coherent receiver sweeps with analytically profiled hardware response.

Known receiver positions and stable pair/frequency response are trusted model
assumptions. Neither training fit nor held prediction certifies those assumptions.
"""
import hashlib
import json
import math
import time
import numpy as np
from scipy.optimize import least_squares
from .model import (
    MODEL, MIN_DISTANCE, MAX_FORWARD_WORK, bounds_and_grid, channels,
    decode_complex, encode_complex, geometry, number, vector,
)

TRAINING_SCHEMA = "blind-coherent-point-sweep-v1"
VALIDATION_SCHEMA = "held-coherent-point-sweep-v1"
COHERENCE_ASSUMPTION = "unknown complex response per pair/frequency constant across all positions"
MAX_POSES = 8
MAX_SEEDS = 48
MAX_NFEV = 160
MAX_PREDICTION_VALUES = 65_536
TRAINING_KEYS = {
    "schema", "name", "tx_m", "rx_poses_m", "frequencies_hz", "iq",
    "noise_std_per_component", "bounds_m", "grid_step_m", "model",
    "minimum_antenna_distance_m", "gain_assumption",
}
VALIDATION_KEYS = {"schema", "training_sha256", "rx_poses_m", "iq"}
WARNINGS = [
    "Synthetic single isotropic point model; no real CSI capture or room reconstruction established.",
    "Known receiver positions, antenna indexing and stable response are trusted assumptions, not certified by residuals.",
    "Finite grid/local search and local rank do not certify global uniqueness or confidence coverage.",
    "Pose-dependent hardware response can counterfeit a different scene and pass held-position prediction.",
]


def _semantic_json_numbers(value):
    """Integral finite floats share JSON numeric identity with integers.

    Browser JSON.stringify drops Python's integral-float spelling and negative
    zero. Preserve numeric meaning without weakening strict measurement types.
    """
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Nonfinite JSON number")
        return int(value) if value.is_integer() else value
    if type(value) is list:
        return [_semantic_json_numbers(item) for item in value]
    if type(value) is dict:
        return {key: _semantic_json_numbers(item) for key, item in value.items()}
    return value


def canonical_training_sha256(training):
    """Hash finite JSON meaning, normalizing integral floats and negative zero."""
    try:
        text = json.dumps(_semantic_json_numbers(training), sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("Training must be bounded finite JSON data") from error
    return hashlib.sha256(text.encode()).hexdigest()


def _receiver_positions(value, receivers=None):
    if type(value) is not list or not 1 <= len(value) <= MAX_POSES:
        raise ValueError("rx_poses_m requires 1..8 known receiver configurations")
    poses = [geometry(item, "rx_poses_m") for item in value]
    count = len(poses[0]) if receivers is None else receivers
    if any(len(item) != count for item in poses):
        raise ValueError("Receiver count and hardware pair indexing must remain unchanged")
    for i, current in enumerate(poses):
        if any(np.array_equal(current, previous) for previous in poses[:i]):
            raise ValueError("Receiver configurations must be distinct; repeated captures add no aperture")
    return np.stack(poses)


def _iq(value, poses, links, frequencies):
    if type(value) is not dict or set(value) != {"real", "imag"}:
        raise ValueError("Sweep IQ requires exactly real and imag tensors")
    for part in ("real", "imag"):
        if type(value[part]) is not list or len(value[part]) != poses:
            raise ValueError("Sweep IQ position dimension must match receiver configurations")
    return np.stack([
        decode_complex({part: value[part][i] for part in ("real", "imag")}, links, frequencies)
        for i in range(poses)
    ])


def validate_training(data):
    """Validate exact blind inputs before allocating a grid or accessing IQ."""
    if type(data) is not dict or set(data) != TRAINING_KEYS or data["schema"] != TRAINING_SCHEMA:
        raise ValueError("Input must contain exactly blind sweep fields; truth, seed and held IQ are forbidden")
    if type(data["name"]) is not str or not 1 <= len(data["name"]) <= 80:
        raise ValueError("name must contain 1..80 characters")
    tx = geometry(data["tx_m"], "tx_m")
    poses = _receiver_positions(data["rx_poses_m"])
    frequencies = data["frequencies_hz"]
    if type(frequencies) is not list or not 1 <= len(frequencies) <= 128:
        raise ValueError("Expected 1..128 frequencies")
    f = vector(frequencies, "frequencies_hz", len(frequencies), 1e6, 10e9)
    if np.any(np.diff(f) < 1000):
        raise ValueError("Frequencies must increase by at least 1000 Hz")
    links = len(tx) * len(poses[0])
    y = _iq(data["iq"], len(poses), links, len(f))
    sigma = number(data["noise_std_per_component"], "noise_std_per_component", 0, 1000)
    if 0 < sigma < 1e-12:
        raise ValueError("Positive noise standard deviation must be at least 1e-12 IQ units")
    number(data["minimum_antenna_distance_m"], "minimum_antenna_distance_m", MIN_DISTANCE, MIN_DISTANCE)
    if data["model"] != MODEL or data["gain_assumption"] != COHERENCE_ASSUMPTION:
        raise ValueError("Unsupported physical model or coherent hardware-response assumption")
    bounds, counts = bounds_and_grid(data["bounds_m"], data["grid_step_m"], links, len(f))
    work = math.prod(counts) * y.size
    if work > MAX_FORWARD_WORK:
        raise ValueError("Sweep grid exceeds 8,000,000 position-pair-frequency channel evaluations")
    canonical_training_sha256(data)
    return tx, poses, f, y, float(sigma), bounds, counts


def _forward(points, tx, poses, frequencies):
    return np.stack([channels(points, tx, rx, frequencies) for rx in poses], axis=1)


def _profile(signal, y):
    """For each pair/frequency eliminate a complex scalar across positions."""
    return np.sum(signal.conj() * y, axis=-3) / np.sum(abs(signal) ** 2, axis=-3)


def _decode_gain(value):
    return np.asarray(value["real"]) + 1j * np.asarray(value["imag"])


def solve_sweep(training):
    """Fit training only. No hidden scene, external files or held IQ are read."""
    started = time.perf_counter()
    tx, poses, f, y, sigma, bounds, counts = validate_training(training)
    digest = canonical_training_sha256(training)
    axes = [np.linspace(low, high, count) for (low, high), count in zip(bounds, counts)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    norm_y = float(np.linalg.norm(y))
    scale = max(sigma if sigma else float(np.sqrt(np.mean(abs(y) ** 2))) * 1e-6, 1e-18)
    scores = np.full(len(grid), np.inf)
    for start in range(0, len(grid), 128):
        signal = _forward(grid[start:start+128], tx, poses, f)
        with np.errstate(invalid="ignore", divide="ignore"):
            gain = _profile(signal, y)
            residual = signal * gain[:, None, :, :] - y
            rss = np.sum(abs(residual) ** 2, axis=(1, 2, 3))
        scores[start:start+128] = np.where(np.isfinite(rss), rss, np.inf)
    valid_indices = np.flatnonzero(np.isfinite(scores))
    if not len(valid_indices):
        raise ValueError("No nonsingular points in the finite initialization grid; change bounds or geometry")
    dof = 2 * (len(poses) - 1) * y.shape[1] * y.shape[2] - 3
    common = {
        "schema": "blind-coherent-point-fit-v1", "training_sha256": digest,
        "input_name": training["name"], "gain_assumption": COHERENCE_ASSUMPTION,
        "training_positions": len(poses), "grid_positions": len(grid),
        "coarse_channel_evaluations": int(len(grid) * y.size),
        "degrees_of_freedom": dof if dof > 0 else None,
        "max_refinement_seeds": MAX_SEEDS, "max_nfev_per_seed": MAX_NFEV,
        "warnings": WARNINGS.copy(),
        "candidate_policy": "Retain found modes around the best RSS: delta 16.27 with stated noise, or max(1,dof)*1e-4 at the numerical scale with zero stated noise. Always retain the best; not exhaustive modes or calibrated coverage.",
        "acceptance_policy": "Refuse if reduced training RSS >3, or noiseless relative residual >1e-6. Search failure may also explain refusal.",
        "coarse_field": {
            "axes_m": [axis.tolist() for axis in axes], "shape": counts,
            "profiled_squared_residual": [float(value) if np.isfinite(value) else None for value in scores],
            "quantity": "Actual unweighted complex residual after per-pair/per-frequency gain profiling across receiver positions",
            "warning": "Finite initialization field; not a probability or global certificate",
        },
    }
    if len(poses) == 1:
        sampled = valid_indices[:12]
        common.update({
            "status": "unidentifiable-free-gain-family", "local_jacobian_rank": 0,
            "effective_position_residual_dimensions": 0, "candidate_count": 0,
            "candidates": [], "best_fit_even_if_refused": None,
            "sampled_compatible_positions_m": grid[sampled].tolist(),
            "max_sampled_relative_residual": float(np.sqrt(scores[sampled].max()) / norm_y),
            "refinement_seeds": 0, "searched_local_modes": 0,
            "candidate_budget_exhausted": False,
            "family_reason": "At one receiver configuration, every nonsingular point can be absorbed by independent complex pair/frequency gains. No point is selected.",
            "seconds": time.perf_counter() - started,
        })
        return common
    seeds = []
    for index in np.argsort(scores, kind="stable"):
        if not np.isfinite(scores[index]):
            break
        p = grid[index]
        if all(np.linalg.norm(p - previous) > .35 for previous in seeds):
            seeds.append(p)
        if len(seeds) == MAX_SEEDS:
            break

    def raw_residual(point):
        signal = _forward(point, tx, poses, f)[0]
        if not np.isfinite(signal).all():
            return None
        gain = _profile(signal, y)
        residual = (signal * gain[None, :, :] - y) / scale
        out = np.concatenate((residual.real.ravel(), residual.imag.ravel()))
        return out if np.isfinite(out).all() else None

    def objective(point):
        value = raw_residual(point)
        return value if value is not None else np.full(2*y.size, 1e20)

    candidates = []
    for seed in seeds:
        fit = least_squares(objective, seed, bounds=(bounds[:, 0], bounds[:, 1]),
                            max_nfev=MAX_NFEV, ftol=1e-11, xtol=1e-11, gtol=1e-9)
        p = fit.x
        r = raw_residual(p)
        if r is None or any(np.linalg.norm(p - item["position_m"]) < .02 for item in candidates):
            continue
        cost = float(r @ r)
        if not math.isfinite(cost):
            continue
        columns = []
        for dim in range(3):
            left, right = p.copy(), p.copy()
            left[dim], right[dim] = max(bounds[dim, 0], p[dim]-1e-5), min(bounds[dim, 1], p[dim]+1e-5)
            lo, hi = raw_residual(left), raw_residual(right)
            if lo is None:
                lo, left = r, p
            if hi is None:
                hi, right = r, p
            span = right[dim] - left[dim]
            columns.append((hi-lo)/span if span > 0 else np.zeros_like(r))
        singular = np.linalg.svd(np.stack(columns, axis=1), compute_uv=False)
        rank = int(np.sum(singular > max(1e-5, singular[0]*1e-5)))
        rank = min(rank, max(0, dof+3))
        signal = _forward(p, tx, poses, f)[0]
        gain = _profile(signal, y)
        candidates.append({
            "position_m": p.tolist(), "weighted_squared_residual": cost,
            "reduced_residual": cost/dof if sigma and dof > 0 else None,
            "relative_iq_residual": float(np.linalg.norm(r)*scale/norm_y),
            "local_jacobian_rank": rank, "jacobian_singular_values": singular.tolist(),
            "weakest_local_one_unit_residual_displacement_m": float(1/singular[-1]) if rank == 3 and sigma else None,
            "optimizer_converged": bool(fit.success), "evaluations": int(fit.nfev),
            "fitted_gain": encode_complex(gain),
        })
    if not candidates:
        raise ValueError("Finite local search found no nonsingular candidate; change bounds or geometry")
    candidates.sort(key=lambda item: item["weighted_squared_residual"])
    best = candidates[0]
    rss_delta = 16.27 if sigma else max(1, dof)*1e-4
    threshold = best["weighted_squared_residual"] + rss_delta
    retained = [item for item in candidates if item["weighted_squared_residual"] <= threshold]
    refused = (sigma and best["reduced_residual"] is not None and best["reduced_residual"] > 3) or (not sigma and best["relative_iq_residual"] > 1e-6)
    weak = sigma and best["local_jacobian_rank"] == 3 and best["jacobian_singular_values"][-1] < 2
    status = ("model-mismatch-or-search-failure" if refused else
              "unidentifiable-local-family" if best["local_jacobian_rank"] < 3 or dof <= 0 else
              "weakly-constrained-hold" if weak else
              "multiple-compatible-modes" if len(retained) > 1 else
              "one-found-mode-conditional-coherence")
    common.update({"status": status, "candidate_count": len(retained), "candidates": retained,
                   "best_fit_even_if_refused": best, "candidate_weighted_rss_delta": rss_delta,
                   "retained_weighted_rss_threshold": threshold, "refinement_seeds": len(seeds),
                   "searched_local_modes": len(candidates), "candidate_budget_exhausted": len(seeds) == MAX_SEEDS,
                   "seconds": time.perf_counter()-started})
    return common


def _validate_held(training, validation, checked):
    if type(validation) is not dict or set(validation) != VALIDATION_KEYS or validation["schema"] != VALIDATION_SCHEMA:
        raise ValueError("Held observations require exactly schema, training_sha256, rx_poses_m and IQ; no truth fields")
    digest = canonical_training_sha256(training)
    if type(validation["training_sha256"]) is not str or validation["training_sha256"] != digest:
        raise ValueError("Held observations reference a different canonical training SHA256")
    tx, train_poses, frequencies, _, _, _, _ = checked
    poses = _receiver_positions(validation["rx_poses_m"], len(train_poses[0]))
    if any(np.array_equal(current, original) for current in poses for original in train_poses):
        raise ValueError("Held receiver configurations must not overlap training configurations")
    y = _iq(validation["iq"], len(poses), len(tx)*len(train_poses[0]), len(frequencies))
    return poses, y


def evaluate_sweep(training, validation):
    """Solve fresh training ONLY, then predict every retained mode without refit."""
    checked = validate_training(training)
    held_poses, held_y = _validate_held(training, validation, checked)
    # Validation is not an argument to the fitting routine and cannot select modes.
    fit = solve_sweep(training)
    tx, train_poses, f, _, sigma, _, _ = checked
    modes = fit["candidates"]
    if len(modes)*held_y.size > MAX_PREDICTION_VALUES:
        raise ValueError("Held prediction output exceeds 65,536 complex values; use fewer held positions or frequencies")
    predictions = []
    for index, candidate in enumerate(modes):
        p = candidate["position_m"]
        signal = _forward(p, tx, held_poses, f)[0]
        if not np.isfinite(signal).all():
            predictions.append({"candidate_index": index, "position_m": p, "status": "held-antenna-exclusion", "compatible": False,
                                "predicted_iq": None, "relative_iq_residual": None, "reduced_residual": None})
            continue
        gain = _decode_gain(candidate["fitted_gain"])
        predicted = signal * gain[None, :, :]
        residual = predicted-held_y
        relative = float(np.linalg.norm(residual)/np.linalg.norm(held_y))
        reduced = None
        if sigma:
            train_signal = _forward(p, tx, train_poses, f)[0]
            strength = np.sum(abs(train_signal)**2, axis=0)
            rss = 0.
            for pair in range(signal.shape[1]):
                for fi in range(signal.shape[2]):
                    h = signal[:, pair, fi]
                    covariance = np.eye(len(h), dtype=complex) + np.outer(h, h.conj())/strength[pair, fi]
                    r = residual[:, pair, fi]/sigma
                    rss += float(np.real(np.vdot(r, np.linalg.solve(covariance, r))))
            reduced = rss/(2*held_y.size)
        compatible = reduced <= 3 if sigma else relative <= 1e-6
        predictions.append({"candidate_index": index, "position_m": p, "status": "compatible-conditional-model" if compatible else "held-model-mismatch",
                            "compatible": bool(compatible), "predicted_iq": encode_complex(predicted), "relative_iq_residual": relative,
                            "reduced_residual": reduced})
    compatible_count = sum(item["compatible"] for item in predictions)
    status = ("unidentifiable-training-family" if not modes else
              "training-refused-or-held" if fit["status"] in {"model-mismatch-or-search-failure", "unidentifiable-local-family", "weakly-constrained-hold"} else
              "held-model-mismatch" if not compatible_count else
              "held-results-vary-no-mode-selection" if compatible_count < len(modes) else
              "all-retained-modes-compatible-conditional-coherence")
    return {"fit": fit, "validation": {
        "schema": "coherent-held-prediction-v1", "training_sha256": fit["training_sha256"],
        "status": status, "held_positions": len(held_poses), "candidate_count": len(predictions),
        "compatible_candidate_count": compatible_count, "candidates": predictions,
        "gain_refitted": False, "location_refitted": False, "mode_selected_using_held_iq": False,
        "acceptance_policy": "Diagnostic reduced held RSS <=3, or noiseless relative residual <=1e-6. No mode is removed or selected from held IQ.",
        "noise_policy": "Propagates circular gain-estimation noise at the fixed fitted point; does not calibrate position uncertainty or confidence coverage.",
        "warnings": WARNINGS.copy(),
    }}


def training_hash(training):
    """Canonical training identity; public alias for packet/export integration."""
    return canonical_training_sha256(training)


def validate_sweep_inputs(training, validation=None):
    """Cheap validation and dimensions only; performs no numerical fitting."""
    checked = validate_training(training)
    tx, poses, frequencies, _, _, _, _ = checked
    held_count = 0
    if validation is not None:
        held_poses, _ = _validate_held(training, validation, checked)
        held_count = len(held_poses)
    return {"training_sha256": canonical_training_sha256(training),
            "training_poses": len(poses), "held_poses": held_count,
            "pairs": len(tx)*len(poses[0]), "frequencies": len(frequencies)}
