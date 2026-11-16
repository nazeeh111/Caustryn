# SPDX-License-Identifier: MIT
"""Finite, training-only next-pose discrimination under coherent gains."""
import itertools
import numpy as np
from .coherent import (COHERENCE_ASSUMPTION, _decode_gain, _forward,
                       canonical_training_sha256, solve_sweep, validate_training)
from .model import geometry

MAX_CANDIDATES = 64
MAX_WORK = 2_000_000


def _directed_parts(train_a, new_a, gain_a, train_b, new_b):
    """Extra residual after profiling rival gain, beyond its training residual."""
    strength = np.sum(abs(train_b) ** 2, axis=0)
    ratio = np.sum(train_b.conj() * train_a, axis=0) / strength
    left = gain_a * new_a
    right = gain_a * new_b * ratio
    weight = 1 + abs(new_b) ** 2 / strength
    score = float(np.sum(abs(left - right) ** 2 / weight))
    operand_energy = float(np.sum((abs(left) ** 2 + abs(right) ** 2) / weight))
    return score, operand_energy


def _directed(train_a, new_a, gain_a, train_b, new_b):
    return _directed_parts(train_a, new_a, gain_a, train_b, new_b)[0]


def plan_sweep(training, allowed_poses_m):
    tx, poses, frequencies, y, sigma, _, _ = validate_training(training)
    if type(allowed_poses_m) is not list or not 1 <= len(allowed_poses_m) <= MAX_CANDIDATES:
        raise ValueError("Provide 1..64 explicitly allowed receiver configurations")
    allowed = [geometry(p, "allowed_poses_m") for p in allowed_poses_m]
    if any(len(p) != len(poses[0]) for p in allowed):
        raise ValueError("Allowed poses must preserve receiver count and pair indexing")
    if any(np.array_equal(p, q) for i, p in enumerate(allowed) for q in allowed[:i]) or any(np.array_equal(p, q) for p in allowed for q in poses):
        raise ValueError("Allowed poses must be distinct and different from training positions")
    fit = solve_sweep(training)
    result_hash = canonical_training_sha256(fit)
    out = {"schema": "coherent-next-pose-plan-v1", "training_sha256": fit["training_sha256"],
           "fit_sha256": result_hash, "fit": fit, "gain_assumption": COHERENCE_ASSUMPTION,
           "criterion": "minimum over mode pairs of symmetric directed incremental profiled residual; smaller direction used",
           "units": "squared IQ" if not sigma else "noise-standard-deviation squared",
           "warning": "Conditional on found modes, point model and stable gains; no uniqueness, power, hardware or safety guarantee.",
           "ranked_poses": [], "recommended_pose_m": None}
    modes = fit["candidates"]
    if fit["status"] != "multiple-compatible-modes" or len(modes) < 2:
        out["status"] = "refused-" + fit["status"]
        return out
    if any(m["local_jacobian_rank"] < 3 or (sigma and m["jacobian_singular_values"][-1] < 2) for m in modes):
        out["status"] = "refused-weak-or-rank-deficient-mode"
        return out
    if len(allowed) * len(modes) ** 2 * y.shape[1] * y.shape[2] * len(poses) > MAX_WORK:
        raise ValueError("Candidate/mode/channel work exceeds planner budget")
    points = np.array([m["position_m"] for m in modes])
    train = _forward(points, tx, poses, frequencies)
    gains = [_decode_gain(m["fitted_gain"]) for m in modes]
    for pose in allowed:
        new = _forward(points, tx, pose[None, :, :], frequencies)[:, 0]
        if not np.isfinite(new).all():
            raise ValueError("An allowed pose violates antenna exclusion for a retained mode")
        directed = [(_directed_parts(train[i], new[i], gains[i], train[j], new[j]),
                     _directed_parts(train[j], new[j], gains[j], train[i], new[i]))
                    for i, j in itertools.combinations(range(len(modes)), 2)]
        score = min(min(a[0], b[0]) for a, b in directed) / (sigma ** 2 if sigma else 1)
        # Roundoff in subtracting modeled complex amplitudes is relative to both
        # operands. Compare squared norms in the same units, including exact zero.
        eps2 = (128 * np.finfo(float).eps) ** 2
        distinguishable = all(a[0] > eps2 * a[1] and b[0] > eps2 * b[1] for a, b in directed)
        out["ranked_poses"].append({"rx_pose_m": pose.tolist(), "worst_pair_score": score,
                                    "numerically_distinguishable": distinguishable})
    out["ranked_poses"].sort(key=lambda row: (not row["numerically_distinguishable"],
                                               -row["worst_pair_score"], row["rx_pose_m"]))
    best = out["ranked_poses"][0]
    out["status"] = "recommended" if best["numerically_distinguishable"] else "no-mode-separation"
    if out["status"] == "recommended":
        out["recommended_pose_m"] = best["rx_pose_m"]
    return out
