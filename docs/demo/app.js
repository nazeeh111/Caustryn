// Original read-only explorer for actual frozen Phaseglass calculations. MIT.
import { SceneViewer } from "./viewer.js";
const $ = (id) => document.getElementById(id);
const state = { data: null, selected: 0, revision: 0 };
const release = "https://github.com/nazeeh111/Caustryn/releases/download/v0.2.0/";
const viewer = new SceneViewer($("scene"), (index) => { state.selected = index; render(); });
const fmt = (x, n = 3) => Number.isFinite(x) ? x.toFixed(n) : "not defined";
const pct = (x) => Number.isFinite(x) ? (100*x).toFixed(2) + "%" : "not defined";
function chooseMode(index) { state.selected = index; render(); }
function render() {
  const d = state.data; if (!d) return;
  const fit = d.result.fit, held = d.result.validation, candidate = fit.candidates[state.selected];
  const prediction = held.candidates[state.selected];
  const pose = $("pose-select").value || "t0", pi = Number(pose.slice(1));
  const rx = pose[0] === "h" ? d.validation.rx_poses_m[pi] : d.training.rx_poses_m[pi];
  viewer.set({ scene: { tx_m: d.training.tx_m, rx_m: rx, bounds_m: d.training.bounds_m },
    result: fit, selected: state.selected, showTruth: $("reveal-truth").checked,
    truth: d.truth, showField: false });
  $("fit-summary").textContent = fit.candidates.length === 1 ? "One found mode, conditional on coherence" : `${fit.candidates.length} compatible modes remain`;
  $("fit-policy").textContent = `${d.training.rx_poses_m.length} training configurations · ${d.training.tx_m.length * d.training.rx_poses_m[0].length} hardware pairs · ${d.training.frequencies_hz.length} frequencies. Finite search; no global uniqueness claim.`;
  $("mode-buttons").replaceChildren();
  fit.candidates.forEach((mode, i) => {
    const button = document.createElement("button"), title = document.createElement("strong"), info = document.createElement("small");
    title.textContent = `Mode ${i+1} · (${mode.position_m.map(x=>fmt(x)).join(", ")}) m`;
    info.textContent = `Training relative IQ residual ${pct(mode.relative_iq_residual)} · held compatible: ${held.candidates[i].compatible ? "yes, under assumptions" : "no"}`;
    button.append(title, info); button.setAttribute("aria-pressed", String(state.selected === i));
    button.onclick = () => chooseMode(i); $("mode-buttons").append(button);
  });
  $("train-metric").textContent = fmt(candidate?.reduced_residual);
  $("held-metric").textContent = fmt(prediction?.reduced_residual);
  $("held-summary").textContent = `${held.compatible_candidate_count} / ${held.candidate_count} retained modes pass the recorded held diagnostic. No mode was selected or removed.`;
  const truthVisible = $("reveal-truth").checked;
  $("truth-evaluation").hidden = !truthVisible;
  if (truthVisible && candidate) {
    const distance = Math.hypot(...candidate.position_m.map((x,i)=>x-d.truth.position_m[i]));
    const box = $("truth-evaluation"), value = document.createElement("strong"), detail = document.createElement("p");
    value.textContent = `${fmt(distance, distance < .01 ? 6 : 3)} m from synthetic truth`;
    detail.textContent = d.id === "exact-counterfeit" ? "The recorded held test passes at a point about 3.49 m from the generator's point. Deliberately pose-dependent response counterfeits a coherent scene. This falsifies using a passing residual as proof of coherent hardware." : d.id === "mirror" ? "The two branches are reflections across Y = 0. The solver and held evaluation retain both. Revealing synthetic truth does not authorize the solver to select a branch." : "Matched-model simulation, exact known geometry, and stable response. This synthetic distance is not measured device accuracy or a hardware precision claim.";
    box.replaceChildren(value, detail);
  }
  drawSignals();
}

function plot(canvas, frequencies, series, label) {
  const ctx = canvas.getContext("2d"), box = canvas.getBoundingClientRect();
  if (!ctx || box.width < 1) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(box.width*ratio); canvas.height = Math.round(box.height*ratio);
  ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,box.width,box.height);
  const left = 55, top = 15, width = box.width-left-14, height = box.height-top-32;
  const finite = series.flatMap(s=>s.values).filter(Number.isFinite), maximum = Math.max(1e-18,...finite)*1.1;
  const first=frequencies[0],last=frequencies.at(-1), fx=(f)=>left+(f-first)/(last-first || 1)*width, fy=(v)=>top+height*(1-v/maximum);
  ctx.font="9px ui-monospace,monospace";ctx.lineWidth=1;
  for(let i=0;i<4;i++){const value=maximum*i/3,y=fy(value);ctx.strokeStyle="#38505e77";ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(left+width,y);ctx.stroke();ctx.fillStyle="#9bb0bd";ctx.textAlign="right";ctx.fillText(value.toExponential(1),left-7,y+3);}
  for(let i=0;i<3;i++){const f=first+(last-first)*i/2;ctx.textAlign="center";ctx.fillText((f/1e9).toFixed(3),fx(f),box.height-13);}
  ctx.textAlign="right";ctx.fillText("GHz",box.width-14,box.height-1);ctx.textAlign="left";
  for(const s of series){ctx.strokeStyle=s.color;ctx.setLineDash(s.dashed?[4,3]:[]);ctx.beginPath();s.values.forEach((v,i)=>i?ctx.lineTo(fx(frequencies[i]),fy(v)):ctx.moveTo(fx(frequencies[i]),fy(v)));ctx.stroke();ctx.setLineDash([]);}
  canvas.setAttribute("aria-label", `${label}. ${frequencies.length} frequency samples, ${first/1e9} to ${last/1e9} GHz. Maximum plotted value ${maximum}.`);
}
function drawSignals() {
  const d=state.data;if(!d)return;
  const candidate=d.result.validation.candidates[state.selected];
  const hi=Number($("held-select").value||0),pair=Number($("pair-select").value||0);
  if(!candidate?.predicted_iq)return;
  const observed=d.validation.iq, predicted=candidate.predicted_iq;
  const real=observed.real[hi][pair],imag=observed.imag[hi][pair],pr=predicted.real[hi][pair],pi=predicted.imag[hi][pair];
  const obs=real.map((v,i)=>Math.hypot(v,imag[i])),pred=pr.map((v,i)=>Math.hypot(v,pi[i]));
  const residual=real.map((v,i)=>Math.hypot(pr[i]-v,pi[i]-imag[i]));
  plot($("amplitude"),d.training.frequencies_hz,[{values:obs,color:"#73d4df"},{values:pred,color:"#d6f87b",dashed:true}],"Observed and training-fitted predicted held amplitude, arbitrary IQ units");
  plot($("residual"),d.training.frequencies_hz,[{values:residual,color:"#f5ad75"}],"Absolute complex prediction residual, arbitrary IQ units");
  const rms=Math.sqrt(residual.reduce((s,x)=>s+x*x,0)/residual.length);
  $("signal-summary").textContent=`Mode ${state.selected+1}, held configuration ${hi+1}, pair ${pair+1}: complex residual RMS ${rms.toExponential(3)} IQ units. Relative residual over every held pair/frequency: ${pct(candidate.relative_iq_residual)}. Plot scales adapt to this selection; compare numeric diagnostics.`;
}
async function load(entry) {
  const revision=++state.revision;$("reveal-truth").checked=false;$("reveal-truth").disabled=true;
  $("load-status").textContent="Loading a frozen calculation. No inference is running in this page.";
  try{
    const response=await fetch(entry.file);if(!response.ok)throw Error(`Recorded data unavailable (${response.status}).`);
    const data=await response.json();if(revision!==state.revision)return;
    state.data=data;state.selected=0;
    $("case-title").textContent=data.title;$("case-description").textContent=data.description;
    const poses=$("pose-select");poses.replaceChildren();
    data.training.rx_poses_m.forEach((_,i)=>poses.add(new Option(`Training ${i+1} / ${data.training.rx_poses_m.length}`,`t${i}`)));
    data.validation.rx_poses_m.forEach((_,i)=>poses.add(new Option(`Held ${i+1} / ${data.validation.rx_poses_m.length}`,`h${i}`)));
    $("held-select").replaceChildren();data.validation.rx_poses_m.forEach((_,i)=>$("held-select").add(new Option(`Held ${i+1}`,i)));
    $("pair-select").replaceChildren();const receivers=data.training.rx_poses_m[0].length;
    for(let tx=0;tx<data.training.tx_m.length;tx++)for(let rx=0;rx<receivers;rx++)$("pair-select").add(new Option(`TX${tx+1} → RX${rx+1}`,tx*receivers+rx));
    for(const id of ["pose-select","held-select","pair-select"])$(id).disabled=false;
    $("replay-download").href=release+data.replayAsset;$("replay-download").setAttribute("aria-disabled","false");
    $("raw-download").href=entry.file;
    $("record").textContent=JSON.stringify(data.result,null,2);
    $("identities").textContent=`Canonical training SHA-256: ${data.result.fit.training_sha256}\nHeld packet is tied to that exact training identity. Optional truth is frozen synthetic context, never a fitting input.`;
    $("load-status").textContent="Frozen actual calculation loaded. Camera, configuration, modes and signal selection change only the view.";
    render();$("reveal-truth").disabled=false;
  }catch(error){if(revision===state.revision)$("load-status").textContent=error.message+" Serve these files as static content; no solver service is needed.";}
}
$("pose-select").onchange=render;$("held-select").onchange=drawSignals;$("pair-select").onchange=drawSignals;
$("reveal-truth").onchange=render;$("turn-left").onclick=()=>viewer.orbit(-.2);$("turn-right").onclick=()=>viewer.orbit(.2);$("reset-camera").onclick=()=>viewer.reset();
window.addEventListener("resize",drawSignals);
try{
  const response=await fetch("cases.json");if(!response.ok)throw Error("Case index unavailable");
  const entries=await response.json(),select=$("case-select");
  select.replaceChildren();entries.forEach(e=>select.add(new Option(e.title,e.id)));select.disabled=false;
  select.onchange=()=>{
    const entry=entries.find(e=>e.id===select.value);if(!entry)return;
    const url=new URL(window.location.href);url.searchParams.set("case",entry.id);
    window.history.replaceState(null,"",url);
    load(entry);
  };
  const url=new URL(window.location.href),requested=url.searchParams.get("case");
  const initial=entries.find(e=>e.id===requested)||entries[0];
  if(requested!==null&&requested!==initial.id){url.searchParams.delete("case");window.history.replaceState(null,"",url);}
  select.value=initial.id;
  await load(initial);
}
catch(error){$("load-status").textContent=error.message+". Open this demo from a static web host.";}
