# SPDX-License-Identifier: MIT
"""Run with the installed interpreter outside the source checkout."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
from phaseglass.resources import resource_root

root=resource_root(); assert (root/'studio/sweep.js').is_file()
examples=json.loads((root/'examples/coherent/index.json').read_text())
case=next(x for x in examples if x['id']=='slope-counterfeit')
with tempfile.TemporaryDirectory() as folder:
    path=Path(folder);training=path/'training.json';held=path/'validation.json'
    training.write_text(json.dumps(case['training']));held.write_text(json.dumps(case['validation']))
    result=path/'result.json'
    subprocess.run([sys.executable,'-m','phaseglass.cli','sweep-evaluate',str(training),'--validation',str(held),'--output',str(result)],cwd=path,check=True,timeout=30)
    answer=json.loads(result.read_text());assert answer['fit']['candidate_count']==1;assert answer['validation']['candidates'][0]['compatible'];assert not answer['validation']['gain_refitted']
    output=path/'experiment.zip'
    subprocess.run([sys.executable,'-m','phaseglass.cli','sweep-export',str(training),'--validation',str(held),'--output',str(output)],cwd=path,check=True,timeout=30)
    target=path/'portable';target.mkdir()
    with zipfile.ZipFile(output) as archive:archive.extractall(target)
    subprocess.run([sys.executable,str(target/'rerun.py'),'--output',str(path/'rerun.json')],cwd=path,check=True,timeout=30)
    replay=json.loads((path/'rerun.json').read_text())
    assert replay['fit']['candidates']==answer['fit']['candidates'];assert replay['validation']==answer['validation']
    print(json.dumps({'installed_package':str(root),'outside_cwd_portable':'passed','training_sha256':answer['fit']['training_sha256']}))
