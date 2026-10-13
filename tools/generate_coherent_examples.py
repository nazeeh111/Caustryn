# SPDX-License-Identifier: MIT
"""Generate original coherent-sweep simulations. Scene truth stays separate."""
import json
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phaseglass.model import MODEL, channels, encode_complex
from phaseglass.coherent import COHERENCE_ASSUMPTION, TRAINING_SCHEMA, VALIDATION_SCHEMA, training_hash

ROOT = Path(__file__).resolve().parents[1]/"examples"/"coherent"
TX = np.array([[0,0,.4],[6,0,2.6]], dtype=float)
RX = np.array([[0,0,2.6],[6,0,.4],[3,1.1,1.3]], dtype=float)
DISPLACEMENTS = np.array([[0,0,0],[.055,0,0],[0,.062,0],[0,0,.049],[-.035,.03,.025],[.022,-.045,.037],[.043,.036,-.024]])
TRUE = np.array([2.371,1.137,1.483])
COUNTERFEIT = np.array([4.427,-1.613,.873])
CASES = [
    ("free-response", "Unknown response, known motion", "A separate unknown complex response at every pair and frequency stays fixed across receiver positions.", 174, "stable", TRUE),
    ("slope-counterfeit", "Break a stable phase-slope counterfeit", "The base capture impersonates a false delay. Coherent motion retains a different spatial response.", 175, "stable-slope", TRUE),
    ("unseen-point", "A second hidden point", "An independently generated scene tests the same blind solver without changing its policy.", 521, "stable", np.array([4.127,-.863,.927])),
    ("single-frequency", "One frequency, several positions", "Known coherent receiver motion adds information even with one carrier sample under this matched point model.", 211, "single-frequency", TRUE),
    ("single-position", "One position cannot identify the point", "Free gain at every pair/frequency absorbs every nonsingular proposed point. No location is selected.", 114, "single-snapshot", TRUE),
    ("mirror", "Keep both reflected explanations", "Coplanar antennas and receiver motion retain two compatible scene reflections.", 311, "mirror", TRUE),
    ("pose-drift", "Response changes during training", "Independent phase changes violate the trusted coherence assumption; large residuals may expose them.", 512, "drift", TRUE),
    ("held-drift", "Training fits, held positions fail", "Only the withheld receiver captures change hardware response. Prediction exposes the change without refitting.", 612, "heldout-drift", TRUE),
    ("exact-counterfeit", "A wrong scene can still pass", "Unrestricted position-dependent complex response exactly impersonates another scene in training and held captures.", 714, "forgery", TRUE),
]


def generate(case):
    identifier,title,description,seed,kind,point=case
    rng=np.random.default_rng(seed)
    frequencies=np.linspace(5.31e9,5.33e9,16)
    rx=RX.copy(); displacements=DISPLACEMENTS.copy()
    if kind=="mirror":
        rx[:,1]=0; displacements[:,1]=0
        displacements[2]=[0,0,.025]
    if kind=="single-frequency":
        frequencies=np.array([5.32e9])
    poses=rx[None,:,:]+displacements[:,None,:]
    h=np.stack([channels(point,TX,pose,frequencies)[0] for pose in poses])
    gain=rng.uniform(.65,1.35,h.shape[1:])*np.exp(1j*rng.uniform(-np.pi,np.pi,h.shape[1:]))
    if kind=="stable-slope":
        link_gain=rng.uniform(.65,1.35,h.shape[1])*np.exp(1j*rng.uniform(-np.pi,np.pi,h.shape[1]))
        gain=np.broadcast_to(link_gain[:,None],h.shape[1:]).copy()
        wrong=channels(COUNTERFEIT,TX,poses[0],frequencies)[0]
        gain *= (wrong/abs(wrong))/(h[0]/abs(h[0]))
    response=np.broadcast_to(gain,h.shape).copy()
    if kind=="drift":
        response *= np.exp(1j*rng.uniform(-.6,.6,h.shape))
    if kind=="forgery":
        wrong=np.stack([channels(COUNTERFEIT,TX,pose,frequencies)[0] for pose in poses])
        response *= wrong/h
    if kind=="heldout-drift":
        response[5:] *= np.exp(1j*rng.uniform(-1,1,h[5:].shape))
    signal=h*response
    sigma=float(np.sqrt(np.mean(abs(signal)**2)/2)*10**(-35/20))
    iq=signal+sigma*(rng.normal(size=signal.shape)+1j*rng.normal(size=signal.shape))
    selected=[0] if kind=="single-snapshot" else list(range(5))
    training={"schema":TRAINING_SCHEMA,"name":identifier,"tx_m":TX.tolist(),
              "rx_poses_m":poses[selected].tolist(),"frequencies_hz":frequencies.tolist(),"iq":encode_complex(iq[selected]),
              "noise_std_per_component":sigma,"bounds_m":[[0,6],[-3,3],[0,3]],"grid_step_m":.3,
              "model":MODEL,"minimum_antenna_distance_m":.15,"gain_assumption":COHERENCE_ASSUMPTION}
    validation={"schema":VALIDATION_SCHEMA,"training_sha256":training_hash(training),
                "rx_poses_m":poses[5:].tolist(),"iq":encode_complex(iq[5:])}
    truth={"kind":"synthetic-generator-truth-not-measurement","position_m":point.tolist(),"seed":seed,
           "response_condition":kind,"noise_snr_db":35,
           "counterfeit_target_m":COUNTERFEIT.tolist() if kind in ("stable-slope","forgery") else None,
           "hardware_response_relative_pose_variation":float(np.linalg.norm(response-response[0])/np.linalg.norm(response)),
           "warning":"Original matched-model simulation with exact known geometry; no real hardware precision or coherence established."}
    return {"id":identifier,"title":title,"description":description,"training":training,"validation":validation,"truth":truth}


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    examples=[generate(case) for case in CASES]
    (ROOT/"index.json").write_text(json.dumps(examples,indent=2,allow_nan=False)+"\n")
    for example in examples:
        for key in ("training","validation","truth"):
            (ROOT/f"{example['id']}.{key}.json").write_text(json.dumps(example[key],indent=2,allow_nan=False)+"\n")
    print(f"Generated {len(examples)} original cases with separate blind training, held observations and generator truth.")

if __name__=="__main__":main()
