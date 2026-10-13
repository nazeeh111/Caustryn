// Original coherent sweep workflow. MIT. No truth is passed to inference.
import { SceneViewer } from "./viewer.js";
const $ = (id) => document.getElementById(id);
const state = { examples: [], current: null, fit: null, held: null, selected: 0, revision: 0, busy: false, pending: false, controller: null };
const viewer = new SceneViewer($("sweep-canvas"), (index) => { state.selected = index; render(); });
const format = (value, digits = 3) => Number.isFinite(value) ? value.toFixed(digits) : "not defined";
const status = (text, error = false) => { $("sweep-status").textContent = text; $("sweep-dot").style.background = error ? "#f5ad75" : "#d6f87b"; };
function controls() {
  const usable = !!state.current && !state.pending && !state.busy;
  $("fit-button").disabled = !usable;
  $("predict-button").disabled = !usable || !state.fit || !state.current.validation;
  $("sweep-export").disabled = !usable || !state.fit;
  $("sweep-save").disabled = !usable;
  $("cancel-sweep").hidden = !state.busy;
  $("apply-packets").disabled = state.busy;
  $("bind-held").disabled = state.busy;
  $("draft-badge").hidden = !state.pending;
}
function invalidate(pending = true) {
  state.revision++; state.controller?.abort(); state.controller = null; state.busy = false;
  state.pending = pending; state.fit = null; state.held = null; state.selected = 0;
  render(); controls();
}
function readDraft() {
  const text = $("training-editor").value, held = $("validation-editor").value;
  if (new TextEncoder().encode(text).length + new TextEncoder().encode(held).length > 1900000) throw Error("Packets exceed the 2 MB request limit.");
  // The server performs strict number/dimension/schema checks. Duplicate keys
  // are checked before JSON.parse can silently discard them.
  const parse = (text) => {
    let i = 0;
    function value(depth = 0) {
      if (depth > 32) throw Error("JSON nesting exceeds 32 levels.");
      while (/\s/.test(text[i] || "") && i < text.length) i++;
      const start = i;
      if (text[i] === '"') { i++; while (i < text.length) { if (text[i] === '\\') i += 2; else if (text[i++] === '"') break; } return JSON.parse(text.slice(start, i)); }
      if (text[i] === '{') { i++; const seen = new Set(); while (true) { while (/\s/.test(text[i] || "") && i < text.length) i++; if (text[i] === '}') { i++; break; } const key = value(depth + 1); if (typeof key !== 'string' || seen.has(key)) throw Error("Duplicate or invalid JSON object key."); seen.add(key); while (/\s/.test(text[i] || "") && i < text.length) i++; if (text[i++] !== ':') throw Error("Invalid JSON object."); value(depth + 1); while (/\s/.test(text[i] || "") && i < text.length) i++; if (text[i] === '}') { i++; break; } if (text[i++] !== ',') throw Error("Invalid JSON object."); } return null; }
      if (text[i] === '[') { i++; while (true) { while (/\s/.test(text[i] || "") && i < text.length) i++; if (text[i] === ']') { i++; break; } value(depth + 1); while (/\s/.test(text[i] || "") && i < text.length) i++; if (text[i] === ']') { i++; break; } if (text[i++] !== ',') throw Error("Invalid JSON array."); } return null; }
      while (i < text.length && !/[\s,}\]]/.test(text[i])) i++;
      if (start === i) throw Error("Invalid JSON value.");
      return JSON.parse(text.slice(start, i));
    }
    value(); return JSON.parse(text);
  };
  return { training: parse(text), validation: held.trim() ? parse(held) : null };
}
async function api(action, payload, signal) {
  const response = await fetch("/api/" + action, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal });
  if (action === "sweep-export" && response.ok) return response.blob();
  const data = await response.json();
  if (!response.ok) throw Error(data.error || "Operation failed.");
  return data;
}
function payload(current, validation = true) {
  return { training: current.training, ...(validation && current.validation ? { validation: current.validation } : {}) };
}
async function job(action, body, complete) {
  if (state.busy) return;
  const revision = state.revision, controller = new AbortController();
  state.controller = controller; state.busy = true; controls(); status(action === "sweep-validate" ? "Validating packet identity and dimensions…" : "Computing actual bounded inference…");
  try {
    const result = await api(action, body, controller.signal);
    if (revision !== state.revision) return;
    complete(result); $("packet-error").textContent = "";
  } catch (error) {
    if (revision !== state.revision) return;
    if (error.name === "AbortError") status("Cancelled. Existing packets remain available.");
    else { status(error.message, true); $("packet-error").textContent = error.message; }
  } finally {
    if (revision === state.revision) { state.busy = false; state.controller = null; controls(); }
  }
}
function setCurrent(example) {
  state.current = structuredClone(example); state.fit = null; state.held = null; state.selected = 0; state.pending = false;
  $("training-editor").value = JSON.stringify(example.training, null, 2);
  $("validation-editor").value = example.validation ? JSON.stringify(example.validation, null, 2) : "";
  $("case-description").textContent = example.description;
  $("reveal-truth").checked = false; $("include-context").checked = false;
  const view = $("pose-view"); view.replaceChildren();
  example.training.rx_poses_m.forEach((_, i) => view.add(new Option(`Training position ${i + 1}`, `t${i}`)));
  example.validation?.rx_poses_m.forEach((_, i) => view.add(new Option(`Held position ${i + 1}`, `h${i}`)));
  render(); controls();
}
function render() {
  const current = state.current, fit = state.fit, held = state.held;
  if (current) {
    const value = $("pose-view").value || "t0", isHeld = value[0] === "h", index = Number(value.slice(1));
    const positions = isHeld ? current.validation?.rx_poses_m : current.training.rx_poses_m;
    viewer.set({ scene: { bounds_m: current.training.bounds_m, tx_m: current.training.tx_m, rx_m: positions?.[index] || current.training.rx_poses_m[0] }, result: fit, selected: state.selected, showField: true, truth: current.truth, showTruth: $("reveal-truth").checked && !state.pending });
    $("pose-label").textContent = `${isHeld ? "HELD" : "TRAINING"} POSITION ${index + 1} · METERS`;
    $("geometry-count").textContent = `${current.training.rx_poses_m.length} training / ${current.validation?.rx_poses_m.length || 0} held`;
  }
  const summaries = {
    "one-found-mode-conditional-coherence": ["One found mode. Conditional.", "The finite search found one mode under stable response. This is not a global uniqueness certificate."],
    "multiple-compatible-modes": ["Several explanations survive.", "All found compatible modes remain. A local rank of three does not resolve a reflected scene."],
    "unidentifiable-free-gain-family": ["One position cannot identify a point.", "Independent pair/frequency gains can absorb every nonsingular location. The solver deliberately selects none."],
    "model-mismatch-or-search-failure": ["The model did not pass.", "Training residuals exceed the declared diagnostic threshold. Model mismatch or finite search failure may explain this."],
    "weakly-constrained-hold": ["The position is weakly constrained.", "Small modeled changes are difficult to distinguish. Keep this estimate on hold."],
    "unidentifiable-local-family": ["The local geometry is unidentifiable.", "The found solution has deficient local rank. This does not justify selecting a precise location."]
  };
  const summary = fit ? summaries[fit.status] || [fit.status, "Inspect the calculation evidence and model assumptions."] : ["A fit is a question.", "The fit receives only the training packet. Held IQ and simulated truth remain separate."];
  if (held?.status === "held-model-mismatch") { summary[0] = "Held prediction failed."; summary[1] = "The training fit did not predict the unseen receiver observations. It remains recorded as a failed test, without refitting."; }
  $("result-heading").textContent = summary[0]; $("result-copy").textContent = summary[1];
  const list = $("sweep-candidates"); list.replaceChildren();
  (fit?.candidates || []).forEach((candidate, index) => {
    const button = document.createElement("button"); button.className = "sweep-mode"; button.setAttribute("aria-pressed", String(index === state.selected));
    const title = document.createElement("strong"); title.textContent = `Mode ${index + 1} · [${candidate.position_m.map(x => format(x, 4)).join(", ")}] m`; button.append(title);
    const detail = document.createElement("span"); detail.textContent = `Training residual ${format(candidate.reduced_residual)} · local rank ${candidate.local_jacobian_rank}/3`; button.append(detail);
    const prediction = held?.candidates[index];
    if (prediction) { const line = document.createElement("div"); line.className = prediction.compatible ? "" : "refused"; line.textContent = `Held residual ${format(prediction.reduced_residual)} · ${prediction.compatible ? "compatible under assumptions" : "prediction refused"}`; button.append(line); }
    button.onclick = () => { state.selected = index; render(); }; list.append(button);
  });
  $("sweep-diagnostics").replaceChildren();
  if (fit) {
    const lines = [`${fit.grid_positions.toLocaleString()} grid positions · ${fit.refinement_seeds} refinements · ${format(fit.seconds, 2)} s`, `Training identity ${fit.training_sha256.slice(0, 16)}…`, ...(held ? [`Held result: ${held.status.replaceAll("-", " ")}.`, "Gains and locations not refitted. No mode selected using held IQ."] : [])];
    for (const text of lines) { const p = document.createElement("p"); p.textContent = text; $("sweep-diagnostics").append(p); }
  }
  const truth = current?.truth?.position_m;
  $("sweep-truth").hidden = !$("reveal-truth").checked || !truth || state.pending;
  $("sweep-truth").replaceChildren();
  if (!$("sweep-truth").hidden) {
    const p = document.createElement("p"); p.textContent = `Separate supplied simulation context: [${truth.map(x => format(x)).join(", ")}] m. It was never passed to inference.`; $("sweep-truth").append(p);
    for (const [i,c] of (fit?.candidates || []).entries()) { const q = document.createElement("p"); q.textContent = `Mode ${i+1} error versus context: ${format(Math.hypot(...c.position_m.map((x,j) => x-truth[j])), 6)} m. Simulation output, not physical precision.`; $("sweep-truth").append(q); }
    const q = document.createElement("p"); q.textContent = current.truth.warning || "Context is separately supplied and unverified."; $("sweep-truth").append(q);
  }
  $("sweep-evidence").textContent = fit ? JSON.stringify({ fit, validation: held }, null, 2) : "No result yet.";
  drawPrediction(); controls();
}
function drawPrediction() {
  const canvas = $("prediction-plot"), ctx = canvas.getContext("2d"), rect = canvas.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2);
  if (!ctx || !rect.width) return;
  canvas.width = Math.round(rect.width*dpr); canvas.height = Math.round(rect.height*dpr); ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,rect.width,rect.height);
  const prediction = state.held?.candidates[state.selected], measured = state.current?.validation?.iq;
  const residualCanvas = $("residual-plot"), residualCtx = residualCanvas.getContext("2d"), residualRect = residualCanvas.getBoundingClientRect();
  residualCanvas.width = Math.round(residualRect.width*dpr); residualCanvas.height = Math.round(residualRect.height*dpr); residualCtx.setTransform(dpr,0,0,dpr,0,0); residualCtx.clearRect(0,0,residualRect.width,residualRect.height);
  if (!prediction?.predicted_iq || !measured) { ctx.fillStyle="#8ca2b2"; ctx.font="12px sans-serif"; ctx.fillText("Fit first, then predict the held positions.", 16, 35); $("prediction-copy").textContent = "Measured and predicted IQ appear here after held-position evaluation. No held observations are used to refit or select a mode."; return; }
  const predicted = prediction.predicted_iq;
  const series = [measured.real.flatMap(p=>p[0]),predicted.real.flatMap(p=>p[0]),measured.imag.flatMap(p=>p[0]),predicted.imag.flatMap(p=>p[0])];
  const maximum = Math.max(1e-12,...series.flat().map(Math.abs)), w=rect.width-68,h=rect.height-52;
  ctx.strokeStyle="#3b5363";ctx.beginPath();ctx.moveTo(48,16+h/2);ctx.lineTo(48+w,16+h/2);ctx.stroke();
  const colors=["#73d4df","#d6f87b","#f5ad75","#c49eef"];
  series.forEach((values,j)=>{ctx.strokeStyle=colors[j];ctx.lineWidth=1.6;ctx.setLineDash(j%2?[5,3]:[]);ctx.beginPath();values.forEach((v,i)=>{const x=48+w*i/Math.max(1,values.length-1),y=16+h/2-v/maximum*h*.44;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();ctx.setLineDash([])});
  ctx.font="9px sans-serif";["Measured real","Predicted real","Measured imaginary","Predicted imaginary"].forEach((text,i)=>{ctx.fillStyle=colors[i];ctx.fillText(text, 12+(i%2)*Math.max(150,rect.width/2),rect.height-18+Math.floor(i/2)*12)});
  const sigma = state.current.training.noise_std_per_component;
  const denominator = sigma || Math.sqrt(series[0].reduce((s,x,i)=>s+x*x+series[2][i]*series[2][i],0)/series[0].length);
  if (!(denominator > 0)) {
    residualCtx.fillStyle="#a8bac6";residualCtx.font="11px sans-serif";residualCtx.fillText("Noiseless channel has zero amplitude. Relative residual trace is undefined.",12,30);
    $("prediction-copy").textContent=`Mode ${state.selected+1}: channel 0 has zero measured amplitude and declared noise is zero. Its relative trace is undefined; inspect the full-channel prediction evidence. Scalar diagnostic: ${format(prediction.reduced_residual)}.`;
    return;
  }
  const residualSeries = [series[1].map((x,i)=>(x-series[0][i])/denominator), series[3].map((x,i)=>(x-series[2][i])/denominator)];
  const residualMax = Math.max(sigma?3:1e-6,...residualSeries.flat().map(Math.abs));
  const rw=residualRect.width-68,rh=residualRect.height-54;
  residualCtx.strokeStyle="#3b5363"; residualCtx.beginPath();residualCtx.moveTo(48,18+rh/2);residualCtx.lineTo(48+rw,18+rh/2);residualCtx.stroke();
  residualSeries.forEach((values,i)=>{residualCtx.strokeStyle=colors[i*2];residualCtx.lineWidth=1.3;residualCtx.beginPath();values.forEach((v,j)=>{const x=48+rw*j/Math.max(1,values.length-1),y=18+rh/2-v/residualMax*rh*.44;j?residualCtx.lineTo(x,y):residualCtx.moveTo(x,y)});residualCtx.stroke()});
  residualCtx.fillStyle="#a8bac6";residualCtx.font="9px sans-serif";
  residualCtx.fillText(sigma?"(predicted − held) / supplied noise σ · components are not whitened":"Noiseless residual / held channel RMS amplitude",12,15);
  residualCtx.fillText(`Range ±${residualMax.toPrecision(3)} · cyan real / orange imaginary`,12,residualRect.height-8);
  $("prediction-copy").textContent=`Mode ${state.selected+1} · all held positions, channel 0. Diagnostic reduced residual ${format(prediction.reduced_residual)}; ${prediction.compatible?"compatible under the declared model":"prediction mismatch"}. The lower trace uses supplied noise σ, not covariance whitening or confidence bounds. The scalar diagnostic propagates gain-estimation noise; fitted-position uncertainty is not calibrated. More channels are retained in the downloadable calculation.`;
}
function save(data, name) { const blob=data instanceof Blob?data:new Blob([JSON.stringify(data,null,2)+"\n"],{type:"application/json"}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),5000); }
$("fit-button").onclick=()=>job("sweep-solve",payload(state.current,false),fit=>{state.fit=fit;state.held=null;state.selected=0;render();status("Training fit saved. Held observations have not been fitted or evaluated.")});
$("predict-button").onclick=()=>job("sweep-evaluate",payload(state.current),result=>{state.fit=result.fit;state.held=result.validation;render();status("Fresh training-only fit frozen. Held positions predicted without refitting.")});
$("sweep-export").onclick=()=>job("sweep-export",{...payload(state.current),...($("include-context").checked&&state.current.truth?{context:state.current.truth}:{})},blob=>{save(blob,"phaseglass-coherent-sweep.zip");status("Fresh calculation exported with source and independent packets.")});
$("sweep-save").onclick=()=>save(state.current.training,"phaseglass-training.json");
$("cancel-sweep").onclick=()=>{state.revision++;state.controller?.abort();state.controller=null;state.busy=false;controls();status("Cancelled. No late result will replace this experiment.")};
$("apply-packets").onclick=()=>{let draft;try{draft=readDraft()}catch(e){$("packet-error").textContent=e.message;status(e.message,true);return}job("sweep-validate",payload(draft),()=>{setCurrent({...draft,title:"Imported experiment",description:"Supplied observations and receiver positions. Provenance and coherence are not authenticated.",truth:null});status("Packets validated and applied. Run a new blind fit.")})};
$("bind-held").onclick=()=>{let draft;try{draft=readDraft();if(!draft.validation)throw Error("Paste a held packet first.")}catch(e){$("packet-error").textContent=e.message;return}job("sweep-validate",payload(draft,false),result=>{draft.validation.training_sha256=result.training_sha256;$("validation-editor").value=JSON.stringify(draft.validation,null,2);state.pending=true;controls();status("Held packet identity rebound. Apply still checks dimensions and excludes repeated receiver positions.")})};
for (const id of ["training-editor","validation-editor"]) $(id).addEventListener("input",()=>{invalidate(true);status("Draft edited. Apply before fitting or exporting.")});
$("sweep-case").onchange=()=>{invalidate(false);setCurrent(state.examples[Number($("sweep-case").value)]);$("packet-error").textContent="";status("Original example restored. Fit receives training only.")};
$("restore-packets").onclick=()=>$("sweep-case").onchange();
$("pose-view").onchange=()=>render();$("reveal-truth").onchange=()=>render();
$("sweep-left").onclick=()=>viewer.orbit(-.18);$("sweep-right").onclick=()=>viewer.orbit(.18);$("sweep-reset").onclick=()=>viewer.reset();
new ResizeObserver(drawPrediction).observe($("prediction-plot"));
try { const response=await fetch("/api/sweep-examples");if(!response.ok)throw Error("Unable to load packaged experiments.");state.examples=await response.json();const select=$("sweep-case");select.replaceChildren();state.examples.forEach((x,i)=>select.add(new Option(x.title,String(i))));const slope=state.examples.findIndex(x=>x.id==="slope-counterfeit");select.value=String(Math.max(0,slope));setCurrent(state.examples[Number(select.value)]);status("Ready. Fit training positions to start."); } catch(e) { status(e.message,true); }
