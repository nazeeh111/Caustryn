# SPDX-License-Identifier: MIT
import copy
from decimal import Decimal
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from phaseglass.coherent import (
    solve_sweep, evaluate_sweep, validate_training, validate_sweep_inputs,
    training_hash, MAX_PREDICTION_VALUES,
)
from phaseglass.model import channels, encode_complex
from phaseglass.inverse import solve as solve_single

ROOT = Path(__file__).resolve().parents[1]


class CoherentPhysicalControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples = {item['id']: item for item in json.loads((ROOT/'examples/coherent/index.json').read_text())}
        cls.results = {}
        with patch('phaseglass.simulation.simulate', side_effect=AssertionError('Generator reached during blind fit')):
            for name, sample in cls.examples.items():
                cls.results[name] = evaluate_sweep(sample['training'], sample['validation'])

    def test_stable_unknown_response_and_independent_scene(self):
        for name in ('free-response', 'slope-counterfeit', 'unseen-point', 'single-frequency'):
            with self.subTest(name=name):
                sample, result = self.examples[name], self.results[name]
                fit = result['fit']; best = fit['best_fit_even_if_refused']
                self.assertEqual(fit['status'], 'one-found-mode-conditional-coherence')
                self.assertEqual(best['local_jacobian_rank'], 3)
                self.assertLess(math.dist(best['position_m'], sample['truth']['position_m']), .05)
                self.assertLess(best['reduced_residual'], 3)
                self.assertEqual(result['validation']['compatible_candidate_count'], 1)
                self.assertLess(result['validation']['candidates'][0]['reduced_residual'], 3)
                self.assertLess(fit['coarse_channel_evaluations'], 8_000_001)
                self.assertLessEqual(fit['refinement_seeds'], 48)
                self.assertLessEqual(best['evaluations'], 160)
                json.dumps(result, allow_nan=False)

    def test_stable_slope_removes_actual_single_pose_false_fit(self):
        source=self.examples['slope-counterfeit']['training']
        one={'schema':'blind-point-radio-v1','name':'slope-base','tx_m':source['tx_m'],'rx_m':source['rx_poses_m'][0],
             'frequencies_hz':source['frequencies_hz'],'iq':{part:source['iq'][part][0] for part in ('real','imag')},
             'noise_std_per_component':source['noise_std_per_component'],'bounds_m':source['bounds_m'],
             'grid_step_m':source['grid_step_m'],'gain_mode':'profiled','model':source['model'],'minimum_antenna_distance_m':.15}
        wrong=solve_single(one)['best_fit_even_if_refused']
        truth=self.examples['slope-counterfeit']['truth']['position_m']
        self.assertLess(wrong['reduced_chi_squared'],3)
        self.assertGreater(math.dist(wrong['position_m'],truth),3)
        self.assertLess(math.dist(self.results['slope-counterfeit']['fit']['best_fit_even_if_refused']['position_m'],truth),.01)

    def test_one_pose_free_gain_is_unidentifiable(self):
        fit=self.results['single-position']['fit']
        self.assertEqual(fit['status'],'unidentifiable-free-gain-family')
        self.assertEqual(fit['local_jacobian_rank'],0)
        self.assertEqual(fit['effective_position_residual_dimensions'],0)
        self.assertIsNone(fit['best_fit_even_if_refused'])
        self.assertEqual(fit['candidates'],[])
        self.assertLess(fit['max_sampled_relative_residual'],1e-12)
        self.assertEqual(self.results['single-position']['validation']['status'],'unidentifiable-training-family')

    def test_mirror_modes_both_keep_own_predictions(self):
        result=self.results['mirror'];modes=result['fit']['candidates']; predictions=result['validation']['candidates']
        self.assertEqual(len(modes),2)
        self.assertEqual(len(predictions),2)
        self.assertLess(modes[0]['position_m'][1]*modes[1]['position_m'][1],0)
        self.assertEqual(result['fit']['status'],'multiple-compatible-modes')
        self.assertTrue(all(p['compatible'] for p in predictions))
        for index,(mode,prediction) in enumerate(zip(modes,predictions)):
            self.assertEqual(prediction['candidate_index'],index)
            self.assertEqual(prediction['position_m'],mode['position_m'])
            gain=np.array(mode['fitted_gain']['real'])+1j*np.array(mode['fitted_gain']['imag'])
            sample=self.examples['mirror']; h=np.stack([channels(mode['position_m'],sample['training']['tx_m'],rx,sample['training']['frequencies_hz'])[0] for rx in sample['validation']['rx_poses_m']])
            actual=np.array(prediction['predicted_iq']['real'])+1j*np.array(prediction['predicted_iq']['imag'])
            np.testing.assert_allclose(actual,h*gain[None,:,:],rtol=0,atol=0)

    def test_random_and_held_only_coherence_breaks_are_exposed(self):
        random=self.results['pose-drift'];held=self.results['held-drift']
        self.assertEqual(random['fit']['status'],'model-mismatch-or-search-failure')
        self.assertGreater(random['fit']['best_fit_even_if_refused']['reduced_residual'],100)
        self.assertEqual(random['validation']['status'],'training-refused-or-held')
        self.assertLess(held['fit']['best_fit_even_if_refused']['reduced_residual'],3)
        self.assertEqual(held['validation']['status'],'held-model-mismatch')
        self.assertGreater(held['validation']['candidates'][0]['reduced_residual'],100)

    def test_unrestricted_changing_gain_can_counterfeit_both_train_and_held(self):
        result=self.results['exact-counterfeit']; truth=self.examples['exact-counterfeit']['truth']
        best=result['fit']['best_fit_even_if_refused']
        self.assertLess(best['reduced_residual'],3)
        self.assertTrue(result['validation']['candidates'][0]['compatible'])
        self.assertGreater(math.dist(best['position_m'],truth['position_m']),3)
        self.assertLess(math.dist(best['position_m'],truth['counterfeit_target_m']),.05)
        self.assertTrue(any('counterfeit' in x for x in result['fit']['warnings']))

    def test_held_iq_never_refits_or_selects_training_modes(self):
        sample=self.examples['mirror'];validation=copy.deepcopy(sample['validation'])
        validation['iq']['real'][0][0][0] += 5
        # Assert the actual training-only entry point receives no held argument.
        expected=copy.deepcopy(self.results['mirror']['fit'])
        with patch('phaseglass.coherent.solve_sweep',return_value=expected) as fitting:
            changed=evaluate_sweep(sample['training'],validation)
        fitting.assert_called_once_with(sample['training'])
        self.assertEqual(changed['fit'],expected)
        self.assertEqual(len(changed['validation']['candidates']),2)
        self.assertFalse(changed['validation']['gain_refitted'])
        self.assertFalse(changed['validation']['location_refitted'])
        self.assertFalse(changed['validation']['mode_selected_using_held_iq'])
        self.assertTrue(all(not x['compatible'] for x in changed['validation']['candidates']))


class CoherentBoundaryControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        examples=json.loads((ROOT/'examples/coherent/index.json').read_text())
        cls.base=examples[0]['training'];cls.held=examples[0]['validation']

    def test_canonical_identity_and_cheap_validator(self):
        reordered=dict(reversed(list(self.base.items())))
        self.assertEqual(training_hash(reordered),training_hash(self.base))
        before=copy.deepcopy(self.base)
        with patch('phaseglass.coherent.solve_sweep',side_effect=AssertionError('Validation fitted')):
            summary=validate_sweep_inputs(self.base,self.held)
        self.assertEqual(summary,{'training_sha256':training_hash(self.base),'training_poses':5,'held_poses':2,'pairs':6,'frequencies':16})
        self.assertEqual(self.base,before)

    def test_browser_integral_number_roundtrip_keeps_held_identity(self):
        # Independent decimal-token conversion models JSON.stringify dropping
        # integral-float spelling, including -0.0. No production helper used.
        def browser_number(token):
            decimal = Decimal(token)
            return int(decimal) if decimal == decimal.to_integral_value() else float(token)
        packet = copy.deepcopy(self.base)
        packet['tx_m'][0][0] = -0.0
        transported = json.loads(json.dumps(packet), parse_float=browser_number)
        self.assertIs(type(transported['tx_m'][0][0]), int)
        self.assertEqual(training_hash(packet), training_hash(transported))
        self.assertEqual(training_hash(packet), training_hash(self.base))
        result = evaluate_sweep(transported, self.held)
        self.assertEqual(result['fit']['training_sha256'], self.held['training_sha256'])
        self.assertTrue(result['validation']['candidates'][0]['compatible'])
        changed = copy.deepcopy(transported)
        changed['tx_m'][0][0] = .000001
        self.assertNotEqual(training_hash(changed), training_hash(transported))
        with self.assertRaisesRegex(ValueError, 'different canonical'):
            validate_sweep_inputs(changed, self.held)
        self.assertNotEqual(training_hash(dict(transported, noise_std_per_component=.125)), training_hash(transported))

    def test_truth_and_unknown_fields_are_rejected(self):
        for field,value in [('position_m',[1,2,3]),('seed',10),('gain',{}),('validation',self.held)]:
            with self.subTest(field=field),self.assertRaises(ValueError):validate_training(dict(self.base,**{field:value}))
        held=dict(self.held,truth=[1,2,3])
        with self.assertRaises(ValueError):validate_sweep_inputs(self.base,held)

    def test_noise_and_numeric_coercion_forbidden(self):
        for value in (True,'0.1',None,-1,float('nan'),float('inf'),1e-13,10**500):
            bad=dict(self.base,noise_std_per_component=value)
            with self.subTest(value=str(value)[:30]),self.assertRaises(ValueError):validate_training(bad)
        for field,value in [('grid_step_m',True),('minimum_antenna_distance_m',True),('gain_assumption','assume whatever'),('frequencies_hz',[5.32e9,5.32e9]),('name','')]:
            with self.subTest(field=field),self.assertRaises(ValueError):validate_training(dict(self.base,**{field:value}))

    def test_dimensions_zero_iq_and_position_overlap(self):
        changes=[('rx_poses_m',[]),('rx_poses_m',self.base['rx_poses_m']*2),('rx_poses_m',[self.base['rx_poses_m'][0]]*2),('tx_m',[]),('frequencies_hz',[]),('frequencies_hz',[5.32e9]*129),('iq',{'real':[],'imag':[]})]
        for field,value in changes:
            with self.subTest(field=field),self.assertRaises(ValueError):validate_training(dict(self.base,**{field:value}))
        wrong=copy.deepcopy(self.base);wrong['iq']['real'][0][0]=[True]*16
        with self.assertRaises(ValueError):validate_training(wrong)
        zero=copy.deepcopy(self.base);zero['iq']=encode_complex(np.zeros((5,6,16),complex))
        with self.assertRaises(ValueError):validate_training(zero)
        wrong=copy.deepcopy(self.held);wrong['training_sha256']='0'*64
        with self.assertRaises(ValueError):validate_sweep_inputs(self.base,wrong)
        wrong=copy.deepcopy(self.held);wrong['rx_poses_m'][0]=self.base['rx_poses_m'][0]
        with self.assertRaisesRegex(ValueError,'overlap'):validate_sweep_inputs(self.base,wrong)
        wrong=copy.deepcopy(self.held);wrong['rx_poses_m'][0]=wrong['rx_poses_m'][0][:-1]
        with self.assertRaises(ValueError):validate_sweep_inputs(self.base,wrong)

    def test_combined_sweep_work_budget(self):
        bad=copy.deepcopy(self.base)
        bad['tx_m']=[[0,0,0],[1,0,0],[2,0,0],[3,0,0]]
        bad['rx_poses_m']=[[[0,float(k),1],[1,float(k),1],[2,float(k),1],[3,float(k),1]] for k in range(5)]
        bad['frequencies_hz']=np.linspace(5.31e9,5.33e9,128).tolist()
        bad['iq']=encode_complex(np.ones((5,16,128),complex));bad['grid_step_m']=.5
        with self.assertRaisesRegex(ValueError,'Sweep grid'):validate_training(bad)

    def test_all_singular_grid_and_tiny_grid_are_explicit(self):
        bad=copy.deepcopy(self.base);bad['bounds_m']=[[0,.05],[0,.05],[0,.05]];bad['grid_step_m']=.05
        bad['tx_m']=[[0,0,0],[.04,.04,.04]]
        with self.assertRaisesRegex(ValueError,'No nonsingular'):solve_sweep(bad)
        tiny=copy.deepcopy(self.base);tiny['bounds_m']=[[2.3,2.41],[1.1,1.21],[1.4,1.51]];tiny['grid_step_m']=.1
        result=solve_sweep(tiny)
        self.assertGreaterEqual(result['grid_positions'],1)
        self.assertLessEqual(result['grid_positions'],8)
        self.assertGreater(result['refinement_seeds'],0)
        json.dumps(result,allow_nan=False)

    def test_noiseless_matched_case_returns_finite_json(self):
        training=copy.deepcopy(self.base);point=[2.371,1.137,1.483]
        h=np.stack([channels(point,training['tx_m'],rx,training['frequencies_hz'])[0] for rx in training['rx_poses_m']])
        training['iq']=encode_complex(h*(1+.3j));training['noise_std_per_component']=0
        result=solve_sweep(training)
        best=result['best_fit_even_if_refused']
        self.assertLess(best['relative_iq_residual'],1e-6)
        self.assertIsNone(best['reduced_residual'])
        json.dumps(result,allow_nan=False)

    def test_small_noiseless_mismatch_always_retains_the_accepted_best(self):
        training=copy.deepcopy(self.base);point=[2.371,1.137,1.483]
        signal=np.stack([channels(point,training['tx_m'],rx,training['frequencies_hz'])[0] for rx in training['rx_poses_m']])*(1+.3j)
        signal[0,0,0] += 1e-7
        training['iq']=encode_complex(signal);training['noise_std_per_component']=0
        training['bounds_m']=[[2.3,2.41],[1.1,1.21],[1.4,1.51]];training['grid_step_m']=.05
        result=solve_sweep(training);best=result['best_fit_even_if_refused']
        self.assertLess(best['relative_iq_residual'],1e-6)
        self.assertGreater(best['weighted_squared_residual'],result['candidate_weighted_rss_delta'])
        self.assertGreaterEqual(result['candidate_count'],1)
        self.assertEqual(result['candidates'][0],best)
        self.assertEqual(result['retained_weighted_rss_threshold'],best['weighted_squared_residual']+result['candidate_weighted_rss_delta'])
        self.assertEqual(result['status'],'one-found-mode-conditional-coherence')
        json.dumps(result,allow_nan=False)

    def test_prediction_output_bound_refuses_without_dropping_modes(self):
        fake={'training_sha256':training_hash(self.base),'status':'multiple-compatible-modes','candidates':[{}]*(MAX_PREDICTION_VALUES//(2*6*16)+1)}
        with patch('phaseglass.coherent.solve_sweep',return_value=fake),self.assertRaisesRegex(ValueError,'65,536'):evaluate_sweep(self.base,self.held)


if __name__=='__main__':unittest.main()
