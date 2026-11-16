import copy
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from phaseglass.coherent import solve_sweep, validate_training
from phaseglass.coherent_plan import _directed, plan_sweep

ROOT = Path(__file__).resolve().parents[1]
TRAINING = json.loads((ROOT / 'examples/coherent/mirror.training.json').read_text())
ALLOWED = [[[0, 1, 2.6], [6, 1, .4], [3, 1, 1.3]],
           [[0, 0, 2.6], [6, 0, .4], [3, 0, 1.4]]]


def test_directed_matches_joint_complex_least_squares_and_gain_reparameterization():
    a = np.array([1+2j, 2-1j, .3+.7j])[:, None, None]
    b = np.array([.2-1j, 1+3j, 2+.1j])[:, None, None]
    gain, an, bn = 2-3j, .8+1j, -2+.5j
    before = np.linalg.lstsq(b.reshape(-1, 1), (gain*a).ravel(), rcond=None)[0]
    base = np.linalg.norm(gain*a.ravel()-b.ravel()*before[0])**2
    expanded_b = np.r_[b.ravel(), bn]
    expanded_a = gain*np.r_[a.ravel(), an]
    fitted = np.linalg.lstsq(expanded_b[:, None], expanded_a, rcond=None)[0]
    expected = np.linalg.norm(expanded_a-expanded_b*fitted[0])**2-base
    score = _directed(a, an, gain, b, bn)
    assert score == pytest.approx(expected)
    assert _directed(a*(3+2j), an*(3+2j), gain/(3+2j), b*(-1+.5j), bn*(-1+.5j)) == pytest.approx(score)


def test_mirror_rank_order_and_symmetry():
    first = plan_sweep(TRAINING, ALLOWED)
    second = plan_sweep(TRAINING, ALLOWED[::-1])
    assert first['status'] == 'recommended'
    assert first['recommended_pose_m'] == ALLOWED[0]
    assert first['ranked_poses'] == second['ranked_poses']
    assert first['ranked_poses'][1]['worst_pair_score'] < 1e-15
    assert first['training_sha256'] == first['fit']['training_sha256']
    symmetric = plan_sweep(TRAINING, [ALLOWED[1]])
    assert symmetric['status'] == 'no-mode-separation'


def test_refusals_and_limits():
    one = json.loads((ROOT / 'examples/coherent/slope-counterfeit.training.json').read_text())
    assert plan_sweep(one, ALLOWED)['status'] == 'refused-one-found-mode-conditional-coherence'
    fit = solve_sweep(TRAINING)
    for status in ['model-mismatch-or-search-failure', 'unidentifiable-local-family', 'weakly-constrained-hold']:
        bad = copy.deepcopy(fit); bad['status'] = status
        with patch('phaseglass.coherent_plan.solve_sweep', return_value=bad):
            assert plan_sweep(TRAINING, ALLOWED)['status'] == 'refused-' + status
    bad = copy.deepcopy(fit); bad['candidates'][1]['local_jacobian_rank'] = 2
    with patch('phaseglass.coherent_plan.solve_sweep', return_value=bad):
        assert plan_sweep(TRAINING, ALLOWED)['status'].startswith('refused-')
    with pytest.raises(ValueError): plan_sweep(TRAINING, [])
    with pytest.raises(ValueError): plan_sweep(TRAINING, ALLOWED * 33)
    with pytest.raises(ValueError): plan_sweep(TRAINING, [TRAINING['rx_poses_m'][0]])


def test_mode_order_does_not_change_scores():
    fit = solve_sweep(TRAINING)
    with patch('phaseglass.coherent_plan.solve_sweep', return_value=fit):
        first = plan_sweep(TRAINING, ALLOWED)
    fit['candidates'].reverse()
    with patch('phaseglass.coherent_plan.solve_sweep', return_value=fit):
        second = plan_sweep(TRAINING, ALLOWED)
    assert first['ranked_poses'] == second['ranked_poses']


def test_worker_rejects_held_iq_and_zero_modes():
    from phaseglass.worker import execute
    training = json.loads((ROOT / 'examples/coherent/single-position.training.json').read_text())
    assert plan_sweep(training, ALLOWED)['status'] == 'refused-unidentifiable-free-gain-family'
    with pytest.raises(ValueError):
        execute({'action': 'sweep-plan', 'payload': {'training': TRAINING, 'allowed_poses_m': ALLOWED, 'validation': {'iq': 'not allowed'}}})


def test_planner_work_budget():
    fit = solve_sweep(TRAINING)
    fit['candidates'] = fit['candidates'] * 48
    poses = [[[i / 10, 2, 2.6], [6, 2, .4], [3, 2, 1.3]] for i in range(64)]
    with patch('phaseglass.coherent_plan.solve_sweep', return_value=fit):
        with pytest.raises(ValueError, match='work exceeds'):
            plan_sweep(TRAINING, poses)


def test_relative_zero_tolerance_under_iq_scale():
    from phaseglass.coherent import _forward
    from phaseglass.model import encode_complex
    data = copy.deepcopy(TRAINING)
    data['noise_std_per_component'] = 0
    point = np.array([2.37, 1.14, 1.48])
    signal = _forward(point, np.array(data['tx_m']), np.array(data['rx_poses_m']), np.array(data['frequencies_hz']))[0]
    for scale in (1, 1e-11):
        data['iq'] = encode_complex(signal * scale)
        result = plan_sweep(data, ALLOWED)
        assert result['status'] == 'recommended'
        assert result['ranked_poses'][0]['numerically_distinguishable']
        assert not result['ranked_poses'][1]['numerically_distinguishable']


def test_selection_prefers_eligible_pose_to_larger_unreliable_raw_score():
    fit = solve_sweep(TRAINING)
    _, _, _, y, *_ = validate_training(TRAINING)
    for mode in fit['candidates']:
        mode['fitted_gain'] = {'real': np.ones(y.shape[1:]).tolist(), 'imag': np.zeros(y.shape[1:]).tolist()}
    def forward(points, tx, positions, frequencies):
        out = np.ones((2, len(positions), *y.shape[1:]), complex)
        if len(positions) == 1:
            if np.array_equal(positions[0], ALLOWED[0]):
                out[1] += 1e-14
            else:
                out *= 1e-3
                out[1] += 1e-15
        return out
    with patch('phaseglass.coherent_plan._forward', forward), patch('phaseglass.coherent_plan.solve_sweep', return_value=fit):
        result = plan_sweep(TRAINING, ALLOWED)
    eligible, unreliable = result['ranked_poses']
    assert result['recommended_pose_m'] == ALLOWED[1]
    assert eligible['numerically_distinguishable'] and not unreliable['numerically_distinguishable']
    assert eligible['worst_pair_score'] < unreliable['worst_pair_score']
