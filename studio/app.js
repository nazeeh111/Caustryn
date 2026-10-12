// Phaseglass original browser studio. MIT. No runtime external dependencies.
import { SceneViewer, drawSignalPlot } from "./viewer.js";

const $ = (id) => document.getElementById(id);
const clone = (v) => JSON.parse(JSON.stringify(v));
const number = (v, d = 3) => (Number.isFinite(v) ? v.toFixed(d) : "—");
const scientific = (v) => (Number.isFinite(v) ? v.toExponential(2) : "—");
const distance = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));
const pointText = (p) =>
  Array.isArray(p) ? p.map((v) => number(v)).join(", ") : "—";
const validPoint = (p) =>
  Array.isArray(p) && p.length === 3 && p.every(Number.isFinite);
const defaultScene = {
  name: "Planar mirror ambiguity",
  tx_m: [
    [0, 0, 0.4],
    [6, 0, 2.6],
  ],
  rx_m: [
    [0, 0, 2.6],
    [6, 0, 0.4],
    [3, 0, 1.3],
  ],
  bounds_m: [
    [0, 6],
    [-3, 3],
    [0, 3],
  ],
  position_m: [2.371, 1.137, 1.483],
  carrier_hz: 5.32e9,
  bandwidth_hz: 20e6,
  subcarriers: 64,
  noise_snr_db: 35,
  gain_mode: "profiled",
  seed: 128,
  grid_step_m: 0.2,
  extra_reflector: null,
  phase_slope_target_m: null,
};
const state = {
  scene: clone(defaultScene),
  examples: [],
  example: null,
  measurement: null,
  truth: null,
  result: null,
  proposal: null,
  selected: 0,
  revision: 0,
  controller: null,
  busy: false,
  dirty: false,
  imported: false,
  link: 0,
  interventionApplied: null,
  inputDrafts: new Map(),
};
const selectCandidate = (index) => {
  if (state.busy) return;
  state.selected = index;
  state.proposal = null;
  renderResults();
  renderViewer();
};
const viewer = new SceneViewer($("scene-canvas"), selectCandidate);
const el = (tag, props = {}, ...children) => {
  const node = ["svg", "path"].includes(tag)
    ? document.createElementNS("http://www.w3.org/2000/svg", tag)
    : document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.setAttribute("class", v);
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "checked" || k === "disabled") node[k] = v;
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined)
      node.append(
        child instanceof Node ? child : document.createTextNode(String(child)),
      );
  }
  return node;
};
const setStatus = (message, type = "ready") => {
  $("status-text").textContent = message;
  $("status-dot").className = `status-dot ${type}`;
};
const openDialog = (id) => {
  const dialog = $(id);
  if (!dialog.open) dialog.showModal();
};

function cancelJob(
  message = "Cancelled. The previous measurement is retained.",
) {
  state.revision++;
  state.controller?.abort();
  state.controller = null;
  state.busy = false;
  syncControls();
  if (message) {
    renderResults();
    setStatus(message);
  }
}
function beginJob(message) {
  cancelJob(null);
  state.controller = new AbortController();
  state.busy = true;
  syncControls();
  setStatus(message, "busy");
  return { revision: state.revision, signal: state.controller.signal };
}
const current = (job) => job.revision === state.revision && !job.signal.aborted;
function endJob(job) {
  if (current(job)) {
    state.busy = false;
    state.controller = null;
    syncControls();
  }
}
async function request(path, body, job) {
  const response = await fetch(`/api/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: job.signal,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const error = await response.json();
      message = error.error || error.detail || message;
    } catch {}
    throw new Error(
      typeof message === "string" ? message : JSON.stringify(message),
    );
  }
  return response;
}
async function api(path, body, job) {
  return (await request(path, body, job)).json();
}
function handleError(error, job, target) {
  if (!current(job) || error.name === "AbortError") return;
  const message = error.message || String(error);
  setStatus(message, "error");
  if (target) $(target).textContent = message;
}

function syncControls() {
  $("cancel-button").hidden = !state.busy;
  $("run-button").disabled = state.busy || state.imported;
  $("config-run").disabled = state.busy || state.imported;
  $("run-button").title = state.imported
    ? "Import a scene to generate new measurements. Imported IQ has no known generator."
    : "";
  $("intervention-button").disabled =
    state.busy ||
    state.dirty ||
    !state.result ||
    state.result.status === "model-mismatch-or-search-failure" ||
    (state.result.candidates?.length || 0) < 2;
  $("measurement-download").disabled = !state.measurement;
  $("export-button").disabled = state.busy || !state.measurement;
  $("truth-toggle").disabled = !state.truth;
  $("export-truth").disabled = !state.truth;
  $("scene-download").disabled = state.imported;
  for (const row of document.querySelectorAll(".candidate-row"))
    row.disabled = state.busy;
  const apply = $("proposal").querySelector(".apply-intervention");
  if (apply)
    apply.disabled =
      state.busy || state.imported || state.proposal?.status !== "proposed";
  $("stale-badge").hidden = !state.dirty;
  $("config-dirty").textContent = state.dirty
    ? "Edited · new packet required"
    : state.imported
      ? "Imported packet · generator unavailable"
      : "Current declared scene";
  $("packet-label").textContent = state.measurement
    ? `${state.measurement.schema.toUpperCase()}${state.result?.measurement_sha256 ? " / " + state.result.measurement_sha256.slice(0, 8) : ""}`
    : "NO MEASUREMENT";
  if (state.imported) {
    $("configure-button").textContent = "Measurement geometry";
    $("configure-button").title =
      "Imported packet geometry is read-only. Load a scene to generate new measurements.";
  } else {
    $("configure-button").replaceChildren(
      el(
        "svg",
        { viewBox: "0 0 24 24", "aria-hidden": "true" },
        el("path", { d: "M4 6h16M4 12h16M4 18h16M8 3v6M16 9v6M10 15v6" }),
      ),
      "Edit scene",
    );
    $("configure-button").title = "Edit the next generated scene";
  }
}
function markDirty() {
  if (state.busy) cancelJob("Operation stopped because the scene changed.");
  else state.revision++;
  state.dirty = true;
  state.proposal = null;
  state.interventionApplied = null;
  $("scene-json").value = JSON.stringify(state.scene, null, 2);
  $("config-error").textContent = "";
  syncControls();
  renderViewer();
  renderProposal();
  updateWorkEstimate();
  setStatus("Scene changed. Generate a new measurement to update the inverse.");
}

async function solvePacket(job) {
  // The exact blind packet is the only input. Generator scene and truth are excluded.
  const result = await api("solve", { measurement: state.measurement }, job);
  if (!current(job)) return;
  state.result = result;
  state.selected = 0;
  state.proposal = null;
  renderResults();
  renderViewer();
  syncControls();
  setStatus(
    state.interventionApplied
      ? "New receiver position measured and blindly solved. Compare the found modes below."
      : "Blind search complete. Select a position to inspect its fit.",
  );
}
async function runScene(scene = state.scene, intervention = null) {
  if (state.imported) return;
  if (!validateSceneControls()) return;
  $("config-error").textContent = "";
  const snapshot = clone(scene);
  const job = beginJob("Generating complex IQ from the declared 3D scene…");
  try {
    const packet = await api("simulate", { scene: snapshot }, job);
    if (!current(job)) return;
    state.scene = snapshot;
    state.inputDrafts.clear();
    state.measurement = packet.measurement;
    state.truth = packet.truth;
    state.result = null;
    state.selected = 0;
    state.proposal = null;
    state.dirty = false;
    state.link = 0;
    state.interventionApplied = intervention;
    renderConfig();
    renderMeasurement();
    renderResults();
    renderViewer();
    syncControls();
    setStatus(
      "Measured packet ready. Searching without generator truth…",
      "busy",
    );
    await solvePacket(job);
  } catch (error) {
    handleError(error, job, "config-error");
  } finally {
    endJob(job);
  }
}
async function chooseExample(id) {
  const example = state.examples.find((e) => e.id === id);
  if (!example) return;
  const job = beginJob(
    "Loading the declared experiment and blind measurement…",
  );
  state.example = id;
  state.scene = clone(example.scene);
  state.inputDrafts.clear();
  state.measurement = clone(example.measurement);
  state.truth = clone(example.truth);
  state.result = null;
  state.selected = 0;
  state.proposal = null;
  state.dirty = false;
  state.imported = false;
  state.link = 0;
  state.interventionApplied = null;
  $("truth-toggle").checked = false;
  $("export-truth").checked = false;
  $("example-select").value = id;
  $("example-description").textContent = example.description;
  renderConfig();
  renderMeasurement();
  renderResults();
  renderViewer();
  syncControls();
  try {
    await solvePacket(job);
  } catch (error) {
    handleError(error, job);
  } finally {
    endJob(job);
  }
}

const statusCopy = {
  "multiple-compatible-modes": {
    label: "AMBIGUITY FOUND",
    title: "More than one place fits.",
    description:
      "These discovered modes explain the same packet under the declared model. A good fit alone cannot choose between them.",
    story: "Compatible positions, one measurement",
    color: "var(--lime)",
  },
  "one-found-mode-no-global-guarantee": {
    label: "ONE FOUND MODE",
    title: "One position found.",
    description:
      "The finite search retained one mode. This is useful evidence within the tested model and bounds, not a proof of global uniqueness.",
    story: "One found mode · finite search",
    color: "var(--lime)",
  },
  "unidentifiable-family": {
    label: "UNDERDETERMINED · HOLD",
    title: "The signal leaves a family.",
    description:
      "The local constraints do not determine all three coordinates. Listed trial points are representatives of an underdetermined family, not isolated locations.",
    story: "A family, not isolated positions",
    color: "var(--orange)",
  },
  "weakly-constrained-hold": {
    label: "WEAK CONSTRAINT · HOLD",
    title: "Too weak to localize.",
    description:
      "The declared noise or frequency span leaves weak constraints. These fits are exploratory; the solver holds the location claim.",
    story: "Weak constraints · location held",
    color: "var(--orange)",
  },
  "model-mismatch-or-search-failure": {
    label: "FIT REFUSED",
    title: "No compatible fit found.",
    description:
      "The best discovered fit fails the declared residual gate. Model mismatch and finite-search failure remain possible; no compatible position is claimed.",
    story: "Fit refused · investigate the model",
    color: "var(--red)",
  },
};
function metric(label, value, title) {
  return el(
    "div",
    { class: "metric-row", ...(title ? { title } : {}) },
    el("span", { text: label }),
    el("strong", { text: value }),
  );
}
function renderResults() {
  const result = state.result;
  const list = $("candidate-list"),
    diagnostics = $("diagnostics");
  list.replaceChildren();
  diagnostics.replaceChildren();
  if (!result) {
    $("result-status").textContent = state.busy
      ? "SEARCH PENDING"
      : state.measurement
        ? "MEASUREMENT READY"
        : "AWAITING INPUT";
    $("result-status").style.color = "";
    $("result-summary").replaceChildren(
      el("span", { class: "result-kicker", text: "BLIND INVERSE" }),
      el("h3", {
        text: state.measurement
          ? state.busy
            ? "Searching the signal…"
            : "Measurement ready."
          : "No hidden coordinates.",
      }),
      el("p", {
        text: state.measurement
          ? "The solver receives antenna geometry, frequencies and IQ. Generating truth stays outside."
          : "The solver sees antenna positions and complex signals. The generating point is held separately.",
      }),
    );
    $("mode-count").textContent = "—";
    $("mode-count").style.color = "";
    $("story-title").textContent = "Search for compatible positions";
    $("story-description").textContent =
      "A good fit tells you what could explain a signal. It does not prove a unique location.";
    renderProposal();
    renderTruth();
    return;
  }
  const copy = statusCopy[result.status] || {
    label: "SEARCH RESULT",
    title: result.status,
    description: result.model_warning || "",
    story: "Finite search result",
    color: "var(--muted)",
  };
  $("result-status").textContent = copy.label;
  $("result-status").style.color = copy.color;
  $("result-summary").replaceChildren(
    el("span", {
      class: "result-kicker",
      text: "BLIND INVERSE · TRUTH WITHHELD",
    }),
    el("h3", { text: copy.title }),
    el("p", { text: copy.description }),
  );
  const candidates = result.candidates || [];
  const refused = result.status === "model-mismatch-or-search-failure",
    family = result.status === "unidentifiable-family";
  candidates.slice(0, 40).forEach((candidate, i) => {
    const row = el(
      "button",
      {
        class: `candidate-row${i === state.selected ? " selected" : ""}`,
        disabled: state.busy,
        "aria-pressed": i === state.selected,
        "aria-label": `${refused ? "Refused trial" : family ? "Family representative" : "Candidate"} P${i + 1}, X ${number(candidate.position_m[0])}, Y ${number(candidate.position_m[1])}, Z ${number(candidate.position_m[2])} meters`,
        onclick: () => selectCandidate(i),
      },
      el(
        "div",
        { class: "candidate-heading" },
        el(
          "span",
          { class: "candidate-name" },
          el("i"),
          `${refused ? "Trial" : family ? "Point" : "Position"} ${i + 1}`,
        ),
        el("span", {
          class: "residual",
          title: "Relative complex IQ residual",
          text: `IQ ${scientific(candidate.relative_iq_residual)}`,
        }),
      ),
      el(
        "div",
        { class: "candidate-coordinates" },
        candidate.position_m.map((v, j) =>
          el("span", {}, el("small", { text: ["X", "Y", "Z"][j] }), number(v)),
        ),
      ),
    );
    list.append(row);
  });
  const selected =
    candidates[state.selected] || result.best_fit_even_if_refused;
  if (selected) {
    diagnostics.append(
      metric(
        "Local sensitivity rank",
        `${selected.local_jacobian_rank} / 3`,
        "Nearby numerical constraints only. Rank 3 does not establish global uniqueness.",
      ),
      metric(
        "Relative IQ residual",
        scientific(selected.relative_iq_residual),
        "Norm of complex residual divided by measured complex signal norm.",
      ),
      metric(
        "Reduced χ²",
        selected.reduced_chi_squared === null
          ? "Not applicable"
          : number(selected.reduced_chi_squared, 3),
        "Weighted residual divided by nominal residual degrees of freedom. Not applicable for noise-free packets or insufficient degrees of freedom. The noisy fit gate refuses above 3.",
      ),
      metric(
        "Weighted residual²",
        scientific(selected.weighted_squared_residual),
      ),
    );
  }
  const frequencies = state.measurement.frequencies_hz,
    bandwidth = frequencies[frequencies.length - 1] - frequencies[0];
  diagnostics.append(
    metric(
      "Total-path delay scale · c/B",
      bandwidth > 0
        ? `${number(299792458 / bandwidth, 2)} m`
        : "Single frequency",
      "Total-path delay scale from the measured frequency span. This is not generic spatial resolution or accuracy.",
    ),
    metric(
      "Grid / refinements",
      `${Number(result.grid_positions).toLocaleString()} / ${result.refinement_seeds}`,
    ),
    metric("Search time", `${number(result.seconds, 2)} s`),
    el("div", {
      class: "diagnostic-note",
      text: result.candidate_budget_exhausted
        ? "40 refinement starts used. Finite candidate coverage; additional modes may exist."
        : "Finite grid + local refinement. Local rank ≠ global uniqueness. Acceptance bands are heuristics, not probabilities.",
    }),
  );
  $("mode-count").textContent = refused
    ? "!"
    : family
      ? "∞"
      : String(candidates.length);
  $("mode-count").style.color = copy.color;
  $("story-title").textContent = copy.story;
  if (state.interventionApplied) {
    $("story-description").textContent =
      `Receiver ${state.interventionApplied.receiverIndex + 1} moved; new IQ generated. ${state.interventionApplied.previousCount} previous modes → ${candidates.length} newly found modes. Pair-specific evidence, not all-space uniqueness.`;
  } else if (candidates.length >= 2 && !family && !refused) {
    const other = candidates.find((_, i) => i !== state.selected);
    $("story-description").textContent =
      `P${state.selected + 1} and P${candidates.indexOf(other) + 1} are ${number(distance(candidates[state.selected].position_m, other.position_m))} m apart. Both fit this measurement within the declared candidate band.`;
  } else
    $("story-description").textContent = refused
      ? "The residual gate refused a location claim. Inspect falsifiers and finite-search assumptions."
      : family
        ? "A finite list of trial points cannot enumerate this compatible family."
        : copy.description;
  renderProposal();
  renderTruth();
  syncControls();
}
function renderTruth() {
  const shown = $("truth-toggle").checked && state.truth;
  const box = $("truth-evaluation");
  box.hidden = !shown;
  $("truth-key").hidden = !shown;
  if (!shown) {
    box.replaceChildren();
    return;
  }
  const truth = state.truth,
    candidates = state.result?.candidates || [];
  box.replaceChildren(
    el("strong", { text: "Generator truth · evaluated after inference" }),
    el("div", { text: `X, Y, Z = ${pointText(truth.position_m)} m` }),
  );
  if (validPoint(truth.position_m) && candidates.length) {
    const selected = candidates[state.selected];
    const closest = Math.min(
      ...candidates.map((c) => distance(c.position_m, truth.position_m)),
    );
    box.append(
      el("div", {
        text: `Selected-point error ${number(distance(selected.position_m, truth.position_m))} m · nearest found point ${number(closest)} m.`,
      }),
    );
  }
  if (truth.phase_slope_target_m)
    box.append(
      el("div", {
        text: "Counterexample active: generator-only phase slope. A good IQ fit can be at the wrong point.",
      }),
    );
  if (truth.extra_reflector)
    box.append(
      el("div", {
        text: "Counterexample active: an extra reflector outside the one-point inverse model.",
      }),
    );
  box.append(
    el("div", {
      text: "These are simulation errors, not hardware accuracy claims.",
    }),
  );
}
function renderViewer() {
  const packet = state.measurement;
  const scene = packet
    ? { bounds_m: packet.bounds_m, tx_m: packet.tx_m, rx_m: packet.rx_m }
    : state.scene;
  const status = state.result?.status;
  const legend = document.querySelector(".key-mode").parentElement;
  legend.replaceChildren(
    el("i", { class: "key-mode" }),
    status === "model-mismatch-or-search-failure"
      ? "Refused trial"
      : status === "unidentifiable-family"
        ? "Family representative"
        : status === "weakly-constrained-hold"
          ? "Held trial point"
          : "Compatible position",
  );
  viewer.set({
    scene,
    result: state.result,
    selected: state.selected,
    truth: state.truth,
    proposal: state.proposal,
    showField: $("field-toggle").checked,
    showTruth: $("truth-toggle").checked,
  });
  $("viewport-empty").hidden = !!packet;
  $("scene-title").textContent = packet?.name || state.scene.name;
  $("scene-subtitle").textContent = state.dirty
    ? "MEASURED GEOMETRY · EDITS PENDING"
    : state.imported
      ? "IMPORTED MEASUREMENT · NO GENERATOR TRUTH"
      : "POINT SCATTERER · BASELINE ISOLATED";
}
function renderMeasurement() {
  const measurement = state.measurement,
    select = $("link-select");
  select.replaceChildren();
  if (!measurement) {
    select.append(el("option", { text: "No measurement" }));
    select.disabled = true;
    $("measurement-summary").textContent = "No signal generated yet";
    renderPlots();
    return;
  }
  const tx = measurement.tx_m.length,
    rx = measurement.rx_m.length;
  for (let i = 0; i < tx; i++)
    for (let j = 0; j < rx; j++)
      select.append(
        el("option", { value: i * rx + j, text: `TX${i + 1} → RX${j + 1}` }),
      );
  select.value = state.link;
  select.disabled = false;
  const f = measurement.frequencies_hz,
    band = (f[f.length - 1] - f[0]) / 1e6;
  $("measurement-summary").textContent =
    `${tx * rx} links · ${f.length} frequency samples · ${number(band, 3)} MHz span · noise σ ${scientific(measurement.noise_std_per_component)} IQ · ${measurement.gain_mode === "profiled" ? "constant link gains profiled" : "calibrated gains"}`;
  renderPlots();
  syncControls();
}
function renderPlots() {
  const m = state.measurement,
    real = m?.iq?.real?.[state.link],
    imag = m?.iq?.imag?.[state.link];
  let amplitude = [],
    phase = [];
  if (Array.isArray(real) && Array.isArray(imag)) {
    amplitude = real.map((v, i) => Math.hypot(v, imag[i]));
    phase = real.map((v, i) => Math.atan2(imag[i], v));
  }
  drawSignalPlot(
    $("amplitude-canvas"),
    m?.frequencies_hz,
    amplitude,
    "amplitude",
  );
  drawSignalPlot($("phase-canvas"), m?.frequencies_hz, phase, "phase");
}

async function proposeIntervention() {
  if (state.dirty || !state.result) return;
  const job = beginJob(
    "Searching declared receiver sites to separate a competing pair…",
  );
  // Put the selected mode first. Core compares it with the most distant found mode.
  const result = clone(state.result),
    selected = result.candidates.splice(state.selected, 1)[0];
  result.candidates.unshift(selected);
  try {
    const proposal = await api(
      "intervention",
      { measurement: state.measurement, result },
      job,
    );
    if (!current(job)) return;
    state.proposal = proposal;
    renderProposal();
    renderViewer();
    setStatus(
      proposal.status === "proposed"
        ? "Receiver move found. Apply creates new IQ and a new blind inverse."
        : "No useful receiver move found in the declared search.",
    );
  } catch (error) {
    handleError(error, job);
  } finally {
    endJob(job);
  }
}
function renderProposal() {
  const container = $("proposal");
  container.replaceChildren();
  container.hidden = !state.proposal;
  const candidates = state.result?.candidates || [];
  $("intervention-description").textContent = state.imported
    ? "A move can be proposed from imported IQ. Applying it requires a known generator scene; existing observations cannot be changed."
    : candidates.length >= 2
      ? `Compare selected P${state.selected + 1} with its most distant found competitor. Search a bounded set of receiver positions for stronger predicted contrast.`
      : "Two locations can fit the same signal. Find a receiver position where their predictions diverge.";
  const proposal = state.proposal;
  if (!proposal) return;
  if (!validPoint(proposal.position_m)) {
    container.append(
      el("p", {
        text: proposal.search?.warning || "A competing pair is required.",
      }),
    );
    return;
  }
  container.append(
    el("div", {
      class: "proposal-coordinate",
      text: `RX${proposal.receiverIndex + 1} → [${pointText(proposal.position_m)}] m`,
    }),
    el(
      "div",
      { class: "proposal-metrics" },
      el(
        "div",
        {},
        "Predicted IQ contrast",
        el("strong", { text: scientific(proposal.pairSeparationBefore) }),
      ),
      el(
        "div",
        {},
        "After receiver move",
        el("strong", { text: scientific(proposal.pairSeparationAfter) }),
      ),
    ),
  );
  const button = el(
    "button",
    {
      class: "primary-button apply-intervention",
      disabled: state.busy || state.imported || proposal.status !== "proposed",
      onclick: () => {
        if (state.imported) return;
        const moved = clone(state.scene);
        moved.rx_m[proposal.receiverIndex] = clone(proposal.position_m);
        moved.name = `${state.scene.name.slice(0, 55)} · receiver moved`;
        runScene(moved, {
          ...clone(proposal),
          previousCount: candidates.length,
        });
      },
    },
    state.imported ? "Known generator required" : "Move receiver & remeasure",
    el("span", { "aria-hidden": "true", text: "→" }),
  );
  container.append(
    button,
    el("p", {
      class: "proposal-warning",
      text: `${proposal.search?.validSites ?? "—"} valid sites / ${proposal.search?.candidateSites ?? "—"} tested. Bidirectional relative IQ contrast after constant gain profiling. ${proposal.search?.warning || "Chosen pair only; finite placement search."}`,
    }),
  );
}

function bindSceneInput(node, key, callback, type = "number") {
  node.addEventListener("input", () => {
    const draft = node.value;
    if (
      type === "number" &&
      (draft.trim() === "" ||
        !Number.isFinite(Number(draft)) ||
        node.validity.badInput)
    ) {
      state.inputDrafts.set(key, draft);
      node.setAttribute("aria-invalid", "true");
      markDirty();
      $("config-error").textContent =
        `${key}: enter a finite number before generating.`;
      return;
    }
    state.inputDrafts.delete(key);
    node.removeAttribute("aria-invalid");
    callback(type === "number" ? Number(draft) : draft);
    markDirty();
  });
}
function validateSceneControls() {
  const numericFields = $("config-fields").querySelectorAll(
    'input[type="number"]:not(:disabled)',
  );
  const invalid = Array.from(numericFields).find(
    (field) =>
      field.value.trim() === "" ||
      !Number.isFinite(Number(field.value)) ||
      !field.validity.valid,
  );
  if (!invalid) return true;
  const label = invalid.getAttribute("aria-label") || "Numeric field";
  const message = `${label}: enter a finite number within the displayed limits before generating.`;
  $("config-error").textContent = message;
  setStatus(message, "error");
  openDialog("config-dialog");
  invalid.focus();
  invalid.reportValidity();
  return false;
}
function input(
  label,
  value,
  callback,
  { min, max, step = "any", type = "number", unit = "", disabled = false } = {},
) {
  const node = el("input", {
    type,
    value: state.inputDrafts.has(label)
      ? state.inputDrafts.get(label)
      : (value ?? ""),
    step,
    ...(min === undefined ? {} : { min }),
    ...(max === undefined ? {} : { max }),
    disabled: state.imported || disabled,
    ...(type === "number" ? { required: "" } : {}),
    "aria-label": label,
  });
  bindSceneInput(node, label, callback, type);
  return el("label", {}, `${label}${unit ? " · " + unit : ""}`, node);
}
function section(title, units, ...children) {
  return el(
    "section",
    { class: "control-section" },
    el("h3", {}, title, el("span", { text: units })),
    children,
  );
}
function positionInputs(
  position,
  callback,
  label = "Point",
  limits = { min: -100, max: 100 },
) {
  return el(
    "div",
    { class: "input-grid" },
    position.map((v, i) =>
      input(`${label} ${["X", "Y", "Z"][i]}`, v, (n) => callback(i, n), limits),
    ),
  );
}
function antennaInputs(key, title) {
  const points = state.scene[key];
  const wrapper = el(
    "div",
    {},
    el(
      "div",
      { class: "coordinate-head" },
      el("span"),
      ...["X / m", "Y / m", "Z / m"].map((text) => el("span", { text })),
      el("span"),
    ),
  );
  points.forEach((point, i) => {
    const row = el(
      "div",
      { class: "position-row" },
      el("span", { text: `${key === "tx_m" ? "TX" : "RX"}${i + 1}` }),
    );
    point.forEach((value, j) => {
      const label = `${title} ${i + 1}, ${["X", "Y", "Z"][j]} in meters`;
      const field = el("input", {
        type: "number",
        value: state.inputDrafts.has(label)
          ? state.inputDrafts.get(label)
          : value,
        step: "any",
        min: -100,
        max: 100,
        disabled: state.imported,
        required: "",
        "aria-label": label,
      });
      bindSceneInput(field, label, (coordinate) => {
        state.scene[key][i][j] = coordinate;
      });
      row.append(field);
    });
    row.append(
      el("button", {
        class: "remove-antenna",
        disabled: state.imported || points.length <= 1,
        "aria-label": `Remove ${title} ${i + 1}`,
        onclick: () => {
          // Preserve invalid drafts on retained antennas when row labels shift.
          const shiftedDrafts = [];
          for (let rowIndex = i; rowIndex < points.length; rowIndex++) {
            for (const axis of ["X", "Y", "Z"]) {
              const oldLabel = `${title} ${rowIndex + 1}, ${axis} in meters`;
              if (state.inputDrafts.has(oldLabel)) {
                if (rowIndex > i) {
                  shiftedDrafts.push([
                    `${title} ${rowIndex}, ${axis} in meters`,
                    state.inputDrafts.get(oldLabel),
                  ]);
                }
                state.inputDrafts.delete(oldLabel);
              }
            }
          }
          points.splice(i, 1);
          for (const [label, draft] of shiftedDrafts)
            state.inputDrafts.set(label, draft);
          markDirty();
          renderConfig();
        },
        text: "×",
      }),
    );
    wrapper.append(row);
  });
  wrapper.append(
    el("button", {
      class: "add-antenna",
      disabled: state.imported || points.length >= 4,
      onclick: () => {
        points.push(state.scene.bounds_m.map((b) => (b[0] + b[1]) / 2));
        markDirty();
        renderConfig();
      },
      text: `+ Add ${title.toLowerCase()} (${points.length}/4)`,
    }),
  );
  return section(title + "s", "METERS", wrapper);
}
function renderConfig() {
  const scene = state.scene,
    fields = $("config-fields");
  fields.replaceChildren();
  if (state.imported) {
    fields.append(
      section(
        "Imported blind packet",
        "READ-ONLY",
        el("p", {
          class: "control-note",
          text: "Generator coordinates, seed and noise SNR are unavailable. These are the supplied measurement geometry and declared inverse bounds, not a reconstructed generator scene.",
        }),
      ),
      section(
        "Search bounds",
        "METERS",
        ...scene.bounds_m.map((bounds, i) =>
          el(
            "div",
            { class: "input-grid two", style: "margin-bottom:10px" },
            input(`${["X", "Y", "Z"][i]} minimum`, bounds[0], () => {}),
            input(`${["X", "Y", "Z"][i]} maximum`, bounds[1], () => {}),
          ),
        ),
      ),
      antennaInputs("tx_m", "Transmitter"),
      antennaInputs("rx_m", "Receiver"),
      section(
        "Measured packet",
        "ACTUAL INPUT",
        el("p", {
          class: "control-note",
          text: `${state.measurement.frequencies_hz.length} frequencies · noise σ ${scientific(state.measurement.noise_std_per_component)} IQ units · ${state.measurement.gain_mode} gain model. Load a scene JSON to run a new generator experiment.`,
        }),
      ),
    );
    $("scene-json").value = JSON.stringify(state.measurement, null, 2);
    $("scene-json").disabled = true;
    $("apply-json").disabled = true;
    document.querySelector(".advanced-json summary").textContent =
      "Imported measurement JSON";
    document.querySelector(".advanced-json p").textContent =
      "Exact imported inverse packet. Generator context is unavailable.";
    syncControls();
    return;
  }
  document.querySelector(".advanced-json summary").textContent =
    "Advanced scene JSON";
  document.querySelector(".advanced-json p").textContent =
    "Full declared generator input. Apply validates JSON; the server validates physical limits when run.";
  fields.append(
    section(
      "Experiment",
      "DECLARED INPUT",
      el(
        "div",
        { class: "input-grid two" },
        input("Name", scene.name, (v) => (scene.name = v), { type: "text" }),
        input("Random seed", scene.seed, (v) => (scene.seed = v), {
          min: 0,
          max: 4294967295,
          step: 1,
        }),
      ),
    ),
  );
  fields.append(
    section(
      "Room / search bounds",
      "METERS",
      ...scene.bounds_m.map((bounds, i) =>
        el(
          "div",
          { class: "input-grid two", style: "margin-bottom:10px" },
          input(
            `${["X", "Y", "Z"][i]} minimum`,
            bounds[0],
            (v) => (scene.bounds_m[i][0] = v),
            { min: -100, max: 100 },
          ),
          input(
            `${["X", "Y", "Z"][i]} maximum`,
            bounds[1],
            (v) => (scene.bounds_m[i][1] = v),
            { min: -100, max: 100 },
          ),
        ),
      ),
      el("p", {
        class: "control-note",
        text: "Each axis span: 0.05–20 m. The grid is a finite initializer; local refinement can find positions between grid points.",
      }),
    ),
  );
  fields.append(
    antennaInputs("tx_m", "Transmitter"),
    antennaInputs("rx_m", "Receiver"),
  );
  fields.append(
    section(
      "Simulated generating point",
      "TRUTH · NEVER IN INVERSE",
      positionInputs(
        scene.position_m,
        (i, v) => (scene.position_m[i] = v),
        "Truth",
      ),
      el("p", {
        class: "control-note",
        text: "This point generates IQ. Reveal truth explicitly to compare it with the blind result. Keep it at least 0.15 m from each antenna.",
      }),
    ),
  );
  const gain = el(
    "select",
    {
      disabled: state.imported,
      "aria-label": "Constant complex gain calibration",
    },
    el("option", { value: "profiled", text: "Unknown · profile each link" }),
    el("option", { value: "calibrated", text: "Known · calibrated unit gain" }),
  );
  gain.value = scene.gain_mode;
  gain.addEventListener("change", () => {
    scene.gain_mode = gain.value;
    markDirty();
  });
  const noiseless = el("input", {
    type: "checkbox",
    checked: scene.noise_snr_db === null,
    disabled: state.imported,
  });
  noiseless.addEventListener("change", () => {
    scene.noise_snr_db = noiseless.checked ? null : 35;
    markDirty();
    renderConfig();
  });
  fields.append(
    section(
      "Signal & inverse",
      "BOUNDED NUMERIC WORK",
      el(
        "div",
        { class: "input-grid two" },
        input(
          "Carrier",
          scene.carrier_hz / 1e9,
          (v) => (scene.carrier_hz = v * 1e9),
          { min: 0.001, max: 10, unit: "GHz" },
        ),
        input(
          "Bandwidth",
          scene.bandwidth_hz / 1e6,
          (v) => (scene.bandwidth_hz = v * 1e6),
          { min: 0, max: 1000, unit: "MHz" },
        ),
        input(
          "Subcarriers",
          scene.subcarriers,
          (v) => (scene.subcarriers = v),
          { min: 1, max: 128, step: 1 },
        ),
        input("Grid step", scene.grid_step_m, (v) => (scene.grid_step_m = v), {
          min: 0.02,
          max: 2,
          unit: "m",
        }),
      ),
      el(
        "div",
        { class: "input-grid two", style: "margin-top:13px" },
        el("label", {}, "Complex link gain", gain),
        input(
          "Noise SNR",
          scene.noise_snr_db,
          (v) => (scene.noise_snr_db = v),
          {
            min: 0,
            max: 100,
            unit: "dB",
            disabled: scene.noise_snr_db === null,
          },
        ),
      ),
      el(
        "label",
        { class: "toggle", style: "margin-top:13px" },
        noiseless,
        "Noiseless simulation",
      ),
      el("p", {
        class: "control-note",
        text: "One subcarrier requires 0 MHz bandwidth. Multiple carriers need ≥ 1 kHz spacing. Constant gain profiling does not model a frequency-dependent phase slope.",
      }),
      el("p", { class: "control-note", id: "work-estimate" }),
    ),
  );
  const extraToggle = el("input", {
    type: "checkbox",
    checked: !!scene.extra_reflector,
    disabled: state.imported,
  });
  extraToggle.addEventListener("change", () => {
    scene.extra_reflector = extraToggle.checked
      ? { position_m: [4.2, -0.8, 2.1], gain_real: 0.4, gain_imag: 0.44 }
      : null;
    markDirty();
    renderConfig();
  });
  const extraBox = el(
    "div",
    { class: "falsifier-box" },
    el("label", { class: "toggle" }, extraToggle, "Add a second reflector"),
    el("p", {
      text: "Generator-only falsifier. The inverse still assumes one point; the fit may be refused.",
    }),
  );
  if (scene.extra_reflector) {
    extraBox.append(
      positionInputs(
        scene.extra_reflector.position_m,
        (i, v) => (scene.extra_reflector.position_m[i] = v),
        "Extra",
      ),
      el(
        "div",
        { class: "input-grid two", style: "margin-top:12px" },
        input(
          "Gain real",
          scene.extra_reflector.gain_real,
          (v) => (scene.extra_reflector.gain_real = v),
          { min: -2, max: 2 },
        ),
        input(
          "Gain imaginary",
          scene.extra_reflector.gain_imag,
          (v) => (scene.extra_reflector.gain_imag = v),
          { min: -2, max: 2 },
        ),
      ),
    );
  }
  const slopeToggle = el("input", {
    type: "checkbox",
    checked: !!scene.phase_slope_target_m,
    disabled: state.imported,
  });
  slopeToggle.addEventListener("change", () => {
    scene.phase_slope_target_m = slopeToggle.checked
      ? [4.95, -0.93, 2.57]
      : null;
    markDirty();
    renderConfig();
  });
  const slopeBox = el(
    "div",
    { class: "falsifier-box" },
    el("label", { class: "toggle" }, slopeToggle, "Counterfeit a phase slope"),
    el("p", {
      text: "Generator-only falsifier. Link timing slopes imitate a different point. A very good fit can still be wrong. Reveal truth after inference.",
    }),
  );
  if (scene.phase_slope_target_m)
    slopeBox.append(
      positionInputs(
        scene.phase_slope_target_m,
        (i, v) => (scene.phase_slope_target_m[i] = v),
        "Target",
      ),
    );
  fields.append(
    section(
      "Test the assumptions",
      "OUTSIDE INVERSE MODEL",
      extraBox,
      slopeBox,
    ),
  );
  $("scene-json").value = JSON.stringify(scene, null, 2);
  $("scene-json").disabled = state.imported;
  $("apply-json").disabled = state.imported;
  updateWorkEstimate();
  syncControls();
}
function updateWorkEstimate() {
  const node = $("work-estimate");
  if (!node) return;
  const s = state.scene;
  const counts = s.bounds_m.map(
      (b) => Math.floor((b[1] - b[0]) / s.grid_step_m) + 1,
    ),
    grid = counts.reduce((a, b) => a * b, 1),
    work = grid * s.tx_m.length * s.rx_m.length * s.subcarriers;
  const valid = counts.every((n) => n > 0) && grid <= 20000 && work <= 8000000;
  node.style.color = valid ? "" : "var(--orange)";
  node.textContent = `Estimated coarse work: ${grid.toLocaleString()} positions · ${(work / 1e6).toFixed(2)} million link-frequency samples. Limits: 20,000 positions / 8 million samples. ${valid ? "Within work limits." : "Increase grid step or reduce samples/antennas."}`;
}

function download(name, content, type = "application/json") {
  const blob =
    content instanceof Blob
      ? content
      : new Blob(
          [
            typeof content === "string"
              ? content
              : JSON.stringify(content, null, 2) + "\n",
          ],
          { type },
        );
  const url = URL.createObjectURL(blob),
    a = el("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function validateJSON(text) {
  if (text.length > 2 * 1024 * 1024)
    throw new Error("JSON must be smaller than 2 MB.");
  const data = JSON.parse(text);
  if (!data || typeof data !== "object" || Array.isArray(data))
    throw new Error("Expected a JSON object.");
  return data;
}
function validateSceneStructure(scene) {
  if (!scene || typeof scene !== "object" || Array.isArray(scene))
    throw new Error("Expected a declared scene object.");
  const required = Object.keys(defaultScene).filter(
    (k) => !["extra_reflector", "phase_slope_target_m"].includes(k),
  );
  for (const key of required)
    if (!(key in scene))
      throw new Error(
        `Scene is missing ${key}. Download a scene JSON for the complete format.`,
      );
  if (
    typeof scene.name !== "string" ||
    !scene.name.length ||
    scene.name.length > 80
  )
    throw new Error("Scene name must contain 1–80 characters.");
  for (const key of ["tx_m", "rx_m"])
    if (
      !Array.isArray(scene[key]) ||
      scene[key].length < 1 ||
      scene[key].length > 4 ||
      scene[key].some((p) => !validPoint(p))
    )
      throw new Error(
        `${key} must contain 1–4 finite [X,Y,Z] coordinate rows.`,
      );
  if (
    !Array.isArray(scene.bounds_m) ||
    scene.bounds_m.length !== 3 ||
    scene.bounds_m.some(
      (b) =>
        !Array.isArray(b) ||
        b.length !== 2 ||
        !b.every(Number.isFinite) ||
        b[0] >= b[1],
    )
  )
    throw new Error(
      "bounds_m must contain three increasing finite [minimum,maximum] pairs.",
    );
  if (!validPoint(scene.position_m))
    throw new Error("position_m must contain three finite coordinates.");
  for (const key of [
    "carrier_hz",
    "bandwidth_hz",
    "subcarriers",
    "seed",
    "grid_step_m",
  ])
    if (!Number.isFinite(scene[key]))
      throw new Error(`${key} must be a finite number.`);
  if (scene.noise_snr_db !== null && !Number.isFinite(scene.noise_snr_db))
    throw new Error("noise_snr_db must be a finite number or null.");
  if (!["profiled", "calibrated"].includes(scene.gain_mode))
    throw new Error("gain_mode must be profiled or calibrated.");
  if (
    scene.extra_reflector !== null &&
    scene.extra_reflector !== undefined &&
    (!validPoint(scene.extra_reflector?.position_m) ||
      !Number.isFinite(scene.extra_reflector.gain_real) ||
      !Number.isFinite(scene.extra_reflector.gain_imag))
  )
    throw new Error(
      "extra_reflector requires position_m, gain_real and gain_imag.",
    );
  if (
    scene.phase_slope_target_m !== null &&
    scene.phase_slope_target_m !== undefined &&
    !validPoint(scene.phase_slope_target_m)
  )
    throw new Error(
      "phase_slope_target_m must be three finite coordinates or null.",
    );
}
function loadSceneJSON(text) {
  const data = validateJSON(text);
  const scene = data.scene || data;
  validateSceneStructure(scene);
  state.scene = clone(scene);
  state.inputDrafts.clear();
  state.imported = false;
  state.example = null;
  markDirty();
  renderConfig();
  $("example-select").value = "custom";
  $("example-description").textContent =
    "Custom declared scene. Generate a new packet, then solve without truth.";
}
async function importMeasurement(text) {
  $("import-error").textContent = "";
  let measurement;
  try {
    const data = validateJSON(text);
    measurement = data.measurement || data;
    if (measurement.schema !== "blind-point-radio-v1")
      throw new Error(
        "Expected a blind-point-radio-v1 measurement. Use Load as scene for generator configurations.",
      );
  } catch (error) {
    $("import-error").textContent = error.message;
    return;
  }
  const job = beginJob("Validating imported IQ and running a blind inverse…");
  try {
    // Obtain server validation before trusting imported coordinates in the renderer.
    const result = await api("solve", { measurement }, job);
    if (!current(job)) return;
    state.measurement = measurement;
    state.truth = null;
    state.result = result;
    state.scene = {
      ...clone(defaultScene),
      name: measurement.name,
      tx_m: clone(measurement.tx_m),
      rx_m: clone(measurement.rx_m),
      bounds_m: clone(measurement.bounds_m),
      grid_step_m: measurement.grid_step_m,
      gain_mode: measurement.gain_mode,
    };
    state.imported = true;
    state.inputDrafts.clear();
    state.example = null;
    state.dirty = false;
    state.selected = 0;
    state.link = 0;
    state.proposal = null;
    state.interventionApplied = null;
    $("truth-toggle").checked = false;
    $("export-truth").checked = false;
    $("example-select").value = "custom";
    $("example-description").textContent =
      "Imported blind measurement. Generator truth is unavailable; geometry is read-only.";
    renderConfig();
    renderMeasurement();
    renderResults();
    renderViewer();
    $("data-dialog").close();
    setStatus(
      "Imported measurement independently solved. Generator truth was not supplied.",
    );
  } catch (error) {
    handleError(error, job, "import-error");
  } finally {
    endJob(job);
  }
}
async function exportPortable() {
  if (!state.measurement) return;
  $("export-error").textContent = "";
  const job = beginJob(
    "Packaging measured IQ, standalone solver and independently recomputed evidence…",
  );
  const body = { measurement: state.measurement, result: state.result };
  if (!state.imported && !state.dirty) body.scene = state.scene;
  if ($("export-truth").checked && state.truth) body.truth = state.truth;
  try {
    const response = await request("export", body, job);
    const blob = await response.blob();
    if (!current(job)) return;
    download("phaseglass-portable-experiment.zip", blob, "application/zip");
    setStatus(
      "Portable experiment downloaded. Run its standalone solver to independently recheck.",
    );
  } catch (error) {
    handleError(error, job, "export-error");
  } finally {
    endJob(job);
  }
}

$("configure-button").addEventListener("click", () => {
  renderConfig();
  openDialog("config-dialog");
});
$("data-button").addEventListener("click", () => openDialog("data-dialog"));
for (const id of ["assumptions-button", "fit-details-button"])
  $(id).addEventListener("click", () => openDialog("assumptions-dialog"));
$("run-button").addEventListener("click", () => runScene());
$("config-run").addEventListener("click", () => {
  if (!validateSceneControls()) return;
  $("config-dialog").close();
  runScene();
});
$("cancel-button").addEventListener("click", () => cancelJob());
$("example-select").addEventListener("change", (e) => {
  if (e.target.value === "custom") return;
  chooseExample(e.target.value);
});
$("reset-experiment").addEventListener("click", () => {
  const id = state.example || state.examples[0]?.id;
  if (id) chooseExample(id);
  else {
    state.scene = clone(defaultScene);
    state.inputDrafts.clear();
    state.imported = false;
    markDirty();
    renderConfig();
  }
  viewer.reset();
});
$("field-toggle").addEventListener("change", renderViewer);
$("truth-toggle").addEventListener("change", () => {
  renderTruth();
  renderViewer();
});
$("link-select").addEventListener("change", (e) => {
  state.link = Number(e.target.value);
  renderPlots();
});
$("intervention-button").addEventListener("click", proposeIntervention);
$("orbit-left").addEventListener("click", () => viewer.orbit(-0.2));
$("orbit-right").addEventListener("click", () => viewer.orbit(0.2));
$("zoom-in").addEventListener("click", () => viewer.scale(1.15));
$("zoom-out").addEventListener("click", () => viewer.scale(1 / 1.15));
$("reset-view").addEventListener("click", () => viewer.reset());
$("measurement-download").addEventListener(
  "click",
  () =>
    state.measurement &&
    download("phaseglass-measurement.json", state.measurement),
);
$("scene-download").addEventListener("click", () =>
  download("phaseglass-scene.json", state.scene),
);
$("export-button").addEventListener("click", exportPortable);
$("apply-json").addEventListener("click", () => {
  try {
    loadSceneJSON($("scene-json").value);
    setStatus("Scene JSON applied. Generate a new measurement when ready.");
  } catch (error) {
    $("config-error").textContent = error.message;
  }
});
$("import-scene-button").addEventListener("click", () => {
  try {
    loadSceneJSON($("import-json").value);
    $("import-error").textContent = "";
    $("data-dialog").close();
    openDialog("config-dialog");
  } catch (error) {
    $("import-error").textContent = error.message;
  }
});
$("import-measurement-button").addEventListener("click", () =>
  importMeasurement($("import-json").value),
);
$("import-file").addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  try {
    if (file.size > 2 * 1024 * 1024)
      throw new Error("File must be smaller than 2 MB.");
    $("import-json").value = await file.text();
    $("import-error").textContent =
      "JSON loaded. Choose Load as scene or Solve measurement.";
  } catch (error) {
    $("import-error").textContent = error.message;
  }
});
for (const dialog of document.querySelectorAll("dialog"))
  dialog.addEventListener("click", (e) => {
    if (e.target !== dialog) return;
    const r = dialog.getBoundingClientRect();
    if (
      e.clientX < r.left ||
      e.clientX > r.right ||
      e.clientY < r.top ||
      e.clientY > r.bottom
    )
      dialog.close();
  });
new ResizeObserver(renderPlots).observe($("signals-panel"));
window.addEventListener("pagehide", () => state.controller?.abort());

async function initialize() {
  renderConfig();
  renderMeasurement();
  renderViewer();
  syncControls();
  const initialRevision = state.revision;
  try {
    const response = await fetch("/api/examples");
    if (!response.ok)
      throw new Error(`Cannot load experiments (${response.status}).`);
    const data = await response.json();
    state.examples = Array.isArray(data) ? data : data.examples;
    if (!Array.isArray(state.examples) || !state.examples.length)
      throw new Error("No experiment fixtures are available.");
    const select = $("example-select");
    select.replaceChildren(
      ...state.examples.slice(0, 24).map((example, i) =>
        el("option", {
          value: example.id,
          text: `${String(i + 1).padStart(2, "0")} / ${example.title}`,
        }),
      ),
      el("option", {
        value: "custom",
        text: "CUSTOM / Imported or edited scene",
      }),
    );
    const mirror =
      state.examples.find((e) => /mirror/i.test(e.id + " " + e.title)) ||
      state.examples[0];
    if (state.revision === initialRevision) await chooseExample(mirror.id);
    else select.value = state.example || "custom";
  } catch (error) {
    $("example-select").replaceChildren(
      el("option", { value: "custom", text: "CUSTOM / Create a scene" }),
    );
    setStatus(
      `${error.message} Use Edit scene to generate your own experiment.`,
      "error",
    );
  }
}
initialize();
