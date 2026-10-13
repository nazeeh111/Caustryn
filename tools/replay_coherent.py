# SPDX-License-Identifier: MIT
"""Blind detached child fits first; held predictions and truth evaluation afterward."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from phaseglass.io import encoded, write_new

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args()
    names=sorted(x.name.removesuffix('.training.json') for x in (ROOT/'examples/coherent').glob('*.training.json'))
    rows=[]
    with tempfile.TemporaryDirectory() as folder:
        detached=Path(folder);package=detached/'phaseglass';package.mkdir()
        for source in (ROOT/'phaseglass').glob('*.py'):shutil.copy2(source,package/source.name)
        # No fixture, generator script, validation or truth accompanies the learner.
        env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
        fits={}
        for name in names:
            training=detached/(name+'.training.json');shutil.copy2(ROOT/'examples/coherent'/training.name,training)
            result=detached/(name+'.fit.json')
            subprocess.run([sys.executable,'-m','phaseglass.cli','sweep-solve',str(training),'--output',str(result)],cwd=detached,env=env,capture_output=True,check=True,timeout=30)
            fits[name]=json.loads(result.read_text())
        # These files enter only after all frozen blind fits have been saved.
        for name in names:
            training=detached/(name+'.training.json');validation=detached/(name+'.validation.json');shutil.copy2(ROOT/'examples/coherent'/validation.name,validation)
            result=detached/(name+'.evaluation.json')
            subprocess.run([sys.executable,'-m','phaseglass.cli','sweep-evaluate',str(training),'--validation',str(validation),'--output',str(result)],cwd=detached,env=env,capture_output=True,check=True,timeout=30)
            evaluation=json.loads(result.read_text());fit=evaluation['fit'];held=evaluation['validation']
            assert fit['candidates']==fits[name]['candidates'],'Held packet changed a training candidate'
            truth=json.loads((ROOT/'examples/coherent'/(name+'.truth.json')).read_text())
            rows.append({'name':name,'training_sha256':fit['training_sha256'],'status':fit['status'],'candidate_count':fit['candidate_count'],'oracle_only_errors_m':[math.dist(c['position_m'],truth['position_m']) for c in fit['candidates']],
                'training_reduced_residuals':[c['reduced_residual'] for c in fit['candidates']],'held_status':held['status'],'held_reduced_residuals':[c['reduced_residual'] for c in held['candidates']],
                'gain_refitted':held['gain_refitted'],'location_refitted':held['location_refitted'],'mode_selected_using_held_iq':held['mode_selected_using_held_iq']})
    cases={r['name']:r for r in rows}
    assert cases['slope-counterfeit']['oracle_only_errors_m'][0]<.01
    assert cases['mirror']['candidate_count']==2
    assert cases['single-position']['candidate_count']==0
    assert cases['held-drift']['held_status']=='held-model-mismatch'
    assert cases['pose-drift']['status']=='model-mismatch-or-search-failure'
    assert cases['exact-counterfeit']['oracle_only_errors_m'][0]>3 and cases['exact-counterfeit']['held_reduced_residuals'][0]<3
    receipt={'schema':'phaseglass-coherent-evidence-v1','version':'0.2.0','cases':rows,'training_before_held_and_truth':True,'simulation_only':True,'warnings':['Stable response and exact known geometry are trusted assumptions.','Finite synthetic examples are not a hardware benchmark or global certificate.','Errors are evaluated against separate generator context only after inference.']}
    write_new(args.output,encoded(receipt)+b'\n');print(json.dumps({'cases':len(rows),'receipt':args.output,'defining_checks':'passed'}))
if __name__=='__main__':main()
