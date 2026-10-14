# Caustryn: radio observability studio

Build an original simulation and inverse experiment laboratory, inspired by the user's interest in WiFi 3D projects. No inherited project source or evidence is presented as our work. All shipped evidence is generated and independently evaluated here. Simulation is visible throughout the product. No hardware capture, body-pose estimation, real-world centimeter accuracy, invented algorithm or universal uniqueness claim.

## Defining capability

Generate physical complex channel measurements from a declared 3D point-scatterer scene. A separate blind inverse receives only antenna geometry, frequencies, IQ, noise/model/bounds, never generator truth. It returns found compatible locations, underconstrained families, weak/noisy holds or model-mismatch refusal. Move a receiver to separate a chosen ambiguous pair and evaluate that intervention. Local sensitivity rank is distinct from global identifiability. Unknown timing/phase slopes can produce a good fit at a wrong point and must remain a runnable visible counterexample.

## Physical scope

H(link,f,p)=exp(-i 2pi f(d_TX+d_RX)/c)/(d_TX*d_RX), with c299792458m/s. One isotropic point, declared arbitrary IQ units, static/baseline-isolated channel, known frequencies/antenna geometry; 15cm exclusion. Constant per-link unknown complex gain can be profiled. No direct path/walls/diffraction/polarization/body surfaces. An optional second point or timing slope belongs to generator-only falsification, not silent inverse support. Grid plus bounded local refinement is a finite candidate search, not a global uniqueness proof. c/B is total-path delay scale; fitted errors under the model are not generic RF resolution.

## First complete product

- Editable room bounds, transmitter/receiver positions, scatterer ground truth, bandwidth/carrier/subcarriers, noise, gain calibration and falsifiers. Truth rendered only as explicitly simulated generator truth, distinct from inferred candidates.
- Original interactive 3D viewer: antenna layout, links, actual candidate positions/score field, selected modes and optional truth. Orbit/zoom/reset, accessible numeric controls and responsive layout. No fabricated skeletons, metrics or motion-capture claims.
- Actual complex IQ amplitude/phase plots, found-mode list with residual/sensitivity evidence, finite-search assumptions, contradiction/hold states. Ground-truth errors evaluated separately after inference, optional reveal.
- Receiver intervention chooses positions from a bounded declared grid to separate the current competing pair after profiling nuisance gains. Re-generate with only that receiver move and re-run the blind inverse; report pair separation and found modes without claiming all-space uniqueness.
- Built-in twelve physically generated reproducible experiments, including mirror, intervention, receiver loss, single frequency, bandwidth/noise, independent off-grid scenes, second reflector and counterfeit hardware phase slopes.
- Measurement JSON import/export, portable session containing source/version/config/input/results and separate optional generator truth; standalone CLI solve without GUI/generator. Packages/source/delivery artifacts must be independently runnable.

## Interfaces / owners

Core owns phaseglass/model.py, inverse.py, simulation.py and tests/test_model.py/test_inverse.py/test_simulation.py. Expose simulate(scene)->{measurement,truth}; solve(measurement)->result; suggest_intervention(measurement,result)->proposal. Use explicit limits (<=4TX,4RX,128frequencies,20000gridpoints,40refinements; finite coordinate/frequency/noise bounds; bounded matrix work). Keep existing blind-point-radio-v1 exact key contract or communicate schema changes. Add optional bounded real coarse-field output for the 3D viewer, with axes and finite/null scores, labeled initialization search rather than probability.

Studio owns studio/ only. Parent owns server.py, cli.py, resources.py, export/package/docs/fixtures. API GET/api/examples -> [{id,title,description,scene,measurement,truth}], POST/api/simulate {scene}->{measurement,truth}, POST/api/solve {measurement}->result, POST/api/intervention {measurement,result}->proposal. Browser POST requests do not execute on UI thread; server runs fixed owned subprocesses with caps/time/cancel controls. POST/api/export {measurement,result,scene?,truth?}->portable ZIP with independent solver/source/license/input/result; truth separate optional file.

Fresh review, actual UI/CLI/portable import/export and independent controls are required for consequential inverse claims. Original code MIT; NumPy/SciPy retained dependencies. Relevant research and source comparisons are stated accurately. No paid API/new credentials/account inventory/PIVOT inspection. Preserve all older products.
