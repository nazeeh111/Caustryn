// SPDX-License-Identifier: MIT
// Minimal DOM input-event regression; native browser checks are separate.
import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
const path = process.argv[2];
const source = fs.readFileSync(path, "utf8");
const functions = source.slice(
  source.indexOf("function bindSceneInput("),
  source.indexOf("function renderConfig("),
);
const run = source.slice(
  source.indexOf("async function runScene("),
  source.indexOf("async function chooseExample("),
);
class Field {
  constructor(tag, props = {}, ...children) {
    this.tag = tag;
    Object.assign(this, props);
    this.children = children.flat();
    this.handlers = {};
    this.value = String(props.value ?? "");
  }
  append(...nodes) {
    this.children.push(...nodes.flat());
  }
  addEventListener(type, fn) {
    this.handlers[type] = fn;
  }
  dispatch(type) {
    this.handlers[type]?.();
  }
  setAttribute(key, value) {
    this[key] = value;
  }
  removeAttribute(key) {
    delete this[key];
  }
  getAttribute(key) {
    return this[key] ?? null;
  }
  focus() {
    this.focused = true;
  }
  reportValidity() {
    this.reported = true;
    return this.validity.valid;
  }
  get validity() {
    const n = Number(this.value);
    const badInput = this.type === "number" && !Number.isFinite(n);
    const blank = this.type === "number" && this.value.trim() === "";
    return {
      badInput,
      valid:
        !badInput &&
        !blank &&
        (this.min === undefined || n >= Number(this.min)) &&
        (this.max === undefined || n <= Number(this.max)),
    };
  }
}
let tree = null;
const collect = (node) =>
  node instanceof Field ? [node, ...node.children.flatMap(collect)] : [];
const find = (label) =>
  collect(tree).find((node) => node["aria-label"] === label);
const state = {
  scene: {
    name: "Input event probe",
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
    bandwidth_hz: 20e6,
  },
  imported: false,
  inputDrafts: new Map(),
  dirty: false,
};
const requests = [];
let dirtyEvents = 0;
const nodes = {
  "config-error": {},
  "config-fields": {
    querySelectorAll: () =>
      collect(tree).filter(
        (node) =>
          node.tag === "input" && node.type === "number" && !node.disabled,
      ),
  },
};
const context = {
  state,
  el: (...args) => new Field(...args),
  $: (id) => nodes[id],
  clone: (value) => JSON.parse(JSON.stringify(value)),
  markDirty: () => {
    state.dirty = true;
    dirtyEvents++;
  },
  setStatus: () => {},
  openDialog: () => {},
  beginJob: () => ({}),
  current: () => true,
  api: async (path, body) => {
    requests.push({ path, body });
    return { measurement: {}, truth: {} };
  },
  renderConfig: () => {},
  renderMeasurement: () => {},
  renderResults: () => {},
  renderViewer: () => {},
  syncControls: () => {},
  solvePacket: async () => {},
  handleError: (error) => {
    throw error;
  },
  endJob: () => {},
};
vm.createContext(context);
vm.runInContext(functions + "\n" + run, context);
tree = context.antennaInputs("rx_m", "Receiver");
let field = find("Receiver 3, Y in meters");
field.value = "1.1";
field.dispatch("input");
assert.equal(state.scene.rx_m[2][1], 1.1);
assert.equal(state.dirty, true);
assert.equal(dirtyEvents, 1);
await context.runScene();
assert.equal(requests.length, 1);
assert.equal(requests[0].body.scene.rx_m[2][1], 1.1);
field.value = "";
field.dispatch("input");
assert.equal(state.scene.rx_m[2][1], 1.1);
assert.equal(state.dirty, true);
assert.equal(state.inputDrafts.get("Receiver 3, Y in meters"), "");
await context.runScene();
assert.equal(
  requests.length,
  1,
  "blank draft must not issue another simulation",
);
assert.match(nodes["config-error"].textContent, /finite number/);
tree = context.antennaInputs("rx_m", "Receiver");
field = find("Receiver 3, Y in meters");
assert.equal(field.value, "", "blank draft must survive an editor rerender");
await context.runScene();
assert.equal(requests.length, 1);
field.value = "Infinity";
field.dispatch("input");
await context.runScene();
assert.equal(requests.length, 1, "nonfinite draft must not issue a simulation");
field.value = "1.137";
field.dispatch("input");
await context.runScene();
assert.equal(requests.length, 2);
assert.equal(requests[1].body.scene.rx_m[2][1], 1.137);
tree = context.input(
  "Bandwidth",
  20,
  (v) => (state.scene.bandwidth_hz = v * 1e6),
  { min: 0, max: 1000 },
);
field = find("Bandwidth");
field.value = "40";
field.dispatch("input");
assert.equal(state.scene.bandwidth_hz, 40e6);
field.value = "";
field.dispatch("input");
await context.runScene();
assert.equal(requests.length, 2);
assert.equal(state.scene.bandwidth_hz, 40e6);
tree = context.input(
  "Noise SNR",
  null,
  () => {
    throw Error("disabled noise must not update");
  },
  { disabled: true },
);
await context.runScene();
assert.equal(requests.length, 3, "disabled empty numeric field does not block");
tree = context.input("Name", "old", (v) => (state.scene.name = v), {
  type: "text",
});
field = find("Name");
field.value = "New typed name";
field.dispatch("input");
assert.equal(state.scene.name, "New typed name");
state.scene.rx_m = [
  [0, 0, 2.6],
  [6, 0, 0.4],
  [3, 0, 1.3],
];
state.inputDrafts.clear();
tree = context.antennaInputs("rx_m", "Receiver");
field = find("Receiver 3, Y in meters");
field.value = "";
field.dispatch("input");
find("Remove Receiver 2").onclick();
tree = context.antennaInputs("rx_m", "Receiver");
field = find("Receiver 2, Y in meters");
assert.equal(
  field.value,
  "",
  "later blank draft must follow its antenna after removal",
);
assert.equal(state.inputDrafts.has("Receiver 3, Y in meters"), false);
const prior = requests.length;
await context.runScene();
assert.equal(requests.length, prior);
find("Remove Receiver 2").onclick();
tree = context.antennaInputs("rx_m", "Receiver");
await context.runScene();
assert.equal(
  requests.length,
  prior + 1,
  "removed invalid antenna must not leave a phantom invalid field",
);
console.log(
  "PASS: antenna + generic fields commit on input; outgoing scene includes edited coordinates; blank/nonfinite drafts block all simulation; drafts survive rerender/removal of earlier rows; removing invalid row clears only its draft; restored arbitrary coordinates work; disabled fields ignored; name input commits.",
);
