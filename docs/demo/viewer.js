// Original dependency-free 3D projection and scientific plots. MIT.
const C = {
  cyan: "#73d4df",
  lime: "#d6f87b",
  orange: "#f5ad75",
  muted: "#8ca2b2",
};
const sub = (a, b) => a.map((v, i) => v - b[i]);
const add = (a, b) => a.map((v, i) => v + b[i]);
const mul = (a, s) => a.map((v) => v * s);
const dot = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0);
const cross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
const norm = (a) => mul(a, 1 / (Math.hypot(...a) || 1));
const validPoint = (p) =>
  Array.isArray(p) && p.length === 3 && p.every(Number.isFinite);

export class SceneViewer {
  constructor(canvas, onSelect) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onSelect = onSelect;
    this.yaw = -0.92;
    this.pitch = 0.49;
    this.zoom = 1;
    this.data = {};
    this.hitTargets = [];
    this.drag = null;
    this.resize = new ResizeObserver(() => this.draw());
    this.resize.observe(canvas);
    canvas.addEventListener("pointerdown", (e) => {
      this.drag = {
        x: e.clientX,
        y: e.clientY,
        startX: e.clientX,
        startY: e.clientY,
        id: e.pointerId,
      };
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!this.drag) return;
      this.yaw += (e.clientX - this.drag.x) * 0.006;
      this.pitch = Math.max(
        0.08,
        Math.min(1.4, this.pitch + (e.clientY - this.drag.y) * 0.005),
      );
      this.drag.x = e.clientX;
      this.drag.y = e.clientY;
      this.draw();
    });
    canvas.addEventListener("pointerup", (e) => {
      if (
        this.drag &&
        Math.hypot(e.clientX - this.drag.startX, e.clientY - this.drag.startY) <
          5
      ) {
        const r = canvas.getBoundingClientRect();
        const x = e.clientX - r.left,
          y = e.clientY - r.top;
        const hit = this.hitTargets.find(
          (p) => Math.hypot(p.x - x, p.y - y) < 23,
        );
        if (hit) this.onSelect(hit.index);
      }
      this.drag = null;
    });
    canvas.addEventListener("pointercancel", () => (this.drag = null));
    canvas.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        this.zoom = Math.max(
          0.55,
          Math.min(2.7, this.zoom * Math.exp(-e.deltaY * 0.001)),
        );
        this.draw();
      },
      { passive: false },
    );
    canvas.addEventListener("keydown", (e) => {
      let handled = true;
      if (e.key === "ArrowLeft") this.yaw -= 0.12;
      else if (e.key === "ArrowRight") this.yaw += 0.12;
      else if (e.key === "ArrowUp")
        this.pitch = Math.min(1.4, this.pitch + 0.08);
      else if (e.key === "ArrowDown")
        this.pitch = Math.max(0.08, this.pitch - 0.08);
      else if (e.key === "+" || e.key === "=")
        this.zoom = Math.min(2.7, this.zoom * 1.12);
      else if (e.key === "-") this.zoom = Math.max(0.55, this.zoom / 1.12);
      else if (e.key === "Home") this.reset();
      else handled = false;
      if (handled) {
        e.preventDefault();
        this.draw();
      }
    });
  }
  set(data) {
    this.data = data;
    this.draw();
  }
  orbit(amount) {
    this.yaw += amount;
    this.draw();
  }
  scale(amount) {
    this.zoom = Math.max(0.55, Math.min(2.7, this.zoom * amount));
    this.draw();
  }
  reset() {
    this.yaw = -0.92;
    this.pitch = 0.49;
    this.zoom = 1;
    this.draw();
  }
  draw() {
    const c = this.canvas,
      ctx = this.ctx;
    if (!ctx) return;
    const r = c.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    c.width = Math.round(r.width * dpr);
    c.height = Math.round(r.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const w = r.width,
      h = r.height;
    ctx.clearRect(0, 0, w, h);
    this.hitTargets = [];
    const scene = this.data.scene || {};
    const bounds = scene.bounds_m || [
      [0, 6],
      [-3, 3],
      [0, 3],
    ];
    if (
      !Array.isArray(bounds) ||
      bounds.length !== 3 ||
      bounds.some(
        (b) =>
          !Array.isArray(b) ||
          b.length !== 2 ||
          !b.every(Number.isFinite) ||
          b[0] >= b[1],
      )
    )
      return;
    const center = bounds.map((b) => (b[0] + b[1]) / 2);
    center[2] -= (bounds[2][1] - bounds[2][0]) * 0.06;
    const diagonal = Math.hypot(...bounds.map((b) => b[1] - b[0]));
    const dist = (diagonal * 1.42) / this.zoom;
    const camera = add(center, [
      Math.sin(this.yaw) * Math.cos(this.pitch) * dist,
      Math.cos(this.yaw) * Math.cos(this.pitch) * dist,
      Math.sin(this.pitch) * dist,
    ]);
    const forward = norm(sub(center, camera)),
      right = norm(cross(forward, [0, 0, 1])),
      up = cross(right, forward);
    const focal = Math.min(w, h * 1.45) * 1.17;
    const project = (p) => {
      const v = sub(p, camera),
        depth = dot(v, forward);
      if (depth <= 0.05) return null;
      return {
        x: w * 0.48 + (dot(v, right) * focal) / depth,
        y: h * 0.51 - (dot(v, up) * focal) / depth,
        depth,
      };
    };
    const line = (a, b, color, width = 1, dash = []) => {
      const p = project(a),
        q = project(b);
      if (!p || !q) return;
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.setLineDash(dash);
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(q.x, q.y);
      ctx.stroke();
      ctx.setLineDash([]);
    };
    const label = (p, text, color, dx = 8, dy = -10) => {
      const q = project(p);
      if (!q) return;
      ctx.font = '9px "SFMono-Regular", Consolas, monospace';
      ctx.fillStyle = "#101a22";
      const size = ctx.measureText(text).width;
      ctx.fillRect(q.x + dx - 4, q.y + dy - 10, size + 8, 15);
      ctx.fillStyle = color;
      ctx.fillText(text, q.x + dx, q.y + dy);
    };
    const z0 = bounds[2][0];
    const corners = [
      [bounds[0][0], bounds[1][0], z0],
      [bounds[0][1], bounds[1][0], z0],
      [bounds[0][1], bounds[1][1], z0],
      [bounds[0][0], bounds[1][1], z0],
    ];
    const pp = corners.map(project);
    if (pp.every(Boolean)) {
      ctx.beginPath();
      pp.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
      ctx.closePath();
      ctx.fillStyle = "#21364045";
      ctx.fill();
    }
    const gridStep = Math.max(
      0.5,
      Math.ceil(Math.max(...bounds.map((b) => b[1] - b[0])) / 12),
    );
    for (
      let x = Math.ceil(bounds[0][0] / gridStep) * gridStep;
      x <= bounds[0][1];
      x += gridStep
    )
      line([x, bounds[1][0], z0], [x, bounds[1][1], z0], "#3b536340");
    for (
      let y = Math.ceil(bounds[1][0] / gridStep) * gridStep;
      y <= bounds[1][1];
      y += gridStep
    )
      line([bounds[0][0], y, z0], [bounds[0][1], y, z0], "#3b536340");
    for (let i = 0; i < 4; i++) {
      line(corners[i], corners[(i + 1) % 4], "#536b7b65");
      const top = [...corners[i]];
      top[2] = bounds[2][1];
      const next = [...corners[(i + 1) % 4]];
      next[2] = bounds[2][1];
      line(corners[i], top, "#46607140", 1, [3, 4]);
      line(top, next, "#46607140", 1, [3, 4]);
    }
    const axesOrigin = [bounds[0][0], bounds[1][0], z0];
    const xEnd = [bounds[0][1], bounds[1][0], z0],
      yEnd = [bounds[0][0], bounds[1][1], z0],
      zEnd = [bounds[0][0], bounds[1][0], bounds[2][1]];
    line(axesOrigin, xEnd, "#68839185");
    line(axesOrigin, yEnd, "#68839185");
    line(axesOrigin, zEnd, "#68839185");
    label(xEnd, `X ${bounds[0][1]} m`, "#7c97a8", 8, 13);
    label(yEnd, `Y ${bounds[1][1]} m`, "#7c97a8", 8, 13);
    label(zEnd, `Z ${bounds[2][1]} m`, "#7c97a8", -25, -10);
    const field = this.data.result?.coarse_field;
    if (
      this.data.showField &&
      field?.axes_m?.length === 3 &&
      Array.isArray(field.profiled_squared_residual)
    ) {
      const values = field.profiled_squared_residual;
      const finite = values.filter(Number.isFinite).sort((a, b) => a - b);
      const ceiling = finite[Math.floor(finite.length * 0.085)] ?? 0;
      const floor = finite[0] ?? 0;
      const ny = field.axes_m[1].length,
        nz = field.axes_m[2].length;
      let drawn = 0;
      const skip = Math.max(1, Math.floor(values.length / 7000));
      for (let i = 0; i < values.length && drawn < 900; i += skip) {
        const score = values[i];
        if (!Number.isFinite(score) || score > ceiling) continue;
        const ix = Math.floor(i / (ny * nz)),
          iy = Math.floor(i / nz) % ny,
          iz = i % nz;
        const p = [
          field.axes_m[0][ix],
          field.axes_m[1][iy],
          field.axes_m[2][iz],
        ];
        if (!validPoint(p)) continue;
        const q = project(p);
        if (!q) continue;
        const quality =
          ceiling === floor ? 1 : 1 - (score - floor) / (ceiling - floor);
        ctx.fillStyle = `rgba(174,215,139,${0.07 + quality * 0.22})`;
        ctx.beginPath();
        ctx.arc(q.x, q.y, 1.1 + quality * 0.8, 0, Math.PI * 2);
        ctx.fill();
        drawn++;
      }
      ctx.fillStyle = "#718777";
      ctx.font = '8px "SFMono-Regular", Consolas, monospace';
      ctx.fillText(
        "COARSE INITIALIZATION SCORES · NOT PROBABILITY",
        22,
        h - 58,
      );
    }
    const candidates = (this.data.result?.candidates || []).filter((c) =>
      validPoint(c.position_m),
    );
    const selected = candidates[this.data.selected || 0];
    if (selected) {
      for (const p of scene.tx_m || [])
        if (validPoint(p))
          line(p, selected.position_m, "#73d4df47", 1.2, [4, 4]);
      for (const p of scene.rx_m || [])
        if (validPoint(p))
          line(selected.position_m, p, "#d6f87b36", 1.2, [4, 4]);
    }
    const points = [];
    (scene.tx_m || []).forEach((p, i) => {
      if (validPoint(p)) points.push({ p, type: "tx", index: i });
    });
    (scene.rx_m || []).forEach((p, i) => {
      if (validPoint(p)) points.push({ p, type: "rx", index: i });
    });
    candidates
      .slice(0, 40)
      .forEach((c, i) =>
        points.push({ p: c.position_m, type: "mode", index: i }),
      );
    if (this.data.showTruth && validPoint(this.data.truth?.position_m))
      points.push({
        p: this.data.truth.position_m,
        type: "truth",
        label: "SIMULATED TRUTH",
      });
    if (
      this.data.showTruth &&
      validPoint(this.data.truth?.extra_reflector?.position_m)
    )
      points.push({
        p: this.data.truth.extra_reflector.position_m,
        type: "truth",
        label: "EXTRA REFLECTOR TRUTH",
      });
    const proposal = this.data.proposal;
    if (validPoint(proposal?.position_m)) {
      const old = scene.rx_m?.[proposal.receiverIndex];
      if (validPoint(old))
        line(old, proposal.position_m, "#73d4dfaa", 1.5, [6, 4]);
      points.push({
        p: proposal.position_m,
        type: "proposal",
        index: proposal.receiverIndex,
      });
    }
    points
      .map((p) => ({ ...p, q: project(p.p) }))
      .filter((p) => p.q)
      .sort((a, b) => b.q.depth - a.q.depth)
      .forEach((item) => {
        const { p, q, type, index } = item;
        const isSelected =
          type === "mode" && index === (this.data.selected || 0);
        const status = this.data.result?.status;
        const modeColor =
          status === "model-mismatch-or-search-failure"
            ? "#ef8c8b"
            : ["unidentifiable-family", "weakly-constrained-hold"].includes(
                  status,
                )
              ? C.orange
              : C.lime;
        let color =
          type === "tx"
            ? C.cyan
            : type === "rx"
              ? "#b7cbd8"
              : type === "truth"
                ? C.orange
                : modeColor;
        const radius = isSelected ? 6 : 4;
        if (type === "mode") {
          ctx.fillStyle = "#d6f87b0b";
          ctx.beginPath();
          ctx.ellipse(
            q.x,
            q.y + 2,
            isSelected ? 20 : 14,
            isSelected ? 10 : 7,
            0,
            0,
            Math.PI * 2,
          );
          ctx.fill();
          ctx.strokeStyle = isSelected ? "#d6f87b99" : "#d6f87b55";
          ctx.lineWidth = 1;
          ctx.stroke();
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(q.x, q.y, radius, 0, Math.PI * 2);
          ctx.fill();
          if (isSelected) {
            ctx.strokeStyle = color;
            ctx.beginPath();
            ctx.arc(q.x, q.y, 10, 0, Math.PI * 2);
            ctx.stroke();
          }
          this.hitTargets.push({ x: q.x, y: q.y, index });
          label(
            p,
            `P${index + 1}${isSelected ? " · SELECTED" : ""}`,
            color,
            14,
            -12,
          );
        } else if (type === "truth") {
          ctx.strokeStyle = color;
          ctx.lineWidth = 1.5;
          ctx.setLineDash([2, 2]);
          ctx.beginPath();
          ctx.moveTo(q.x, q.y - 12);
          ctx.lineTo(q.x + 12, q.y);
          ctx.lineTo(q.x, q.y + 12);
          ctx.lineTo(q.x - 12, q.y);
          ctx.closePath();
          ctx.stroke();
          ctx.setLineDash([]);
          label(p, item.label || "SIMULATED TRUTH", color, 16, 25);
        } else if (type === "proposal") {
          ctx.strokeStyle = C.cyan;
          ctx.lineWidth = 1.5;
          ctx.setLineDash([3, 3]);
          ctx.strokeRect(q.x - 8, q.y - 8, 16, 16);
          ctx.setLineDash([]);
          label(p, `MOVE RX${index + 1} HERE`, C.cyan, 13, -14);
        } else {
          ctx.strokeStyle = "#101a22";
          ctx.lineWidth = 3;
          ctx.fillStyle = color;
          ctx.beginPath();
          if (type === "rx") ctx.rect(q.x - 4, q.y - 4, 8, 8);
          else ctx.arc(q.x, q.y, 5, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
          ctx.fill();
          label(p, `${type.toUpperCase()}${index + 1}`, color, 8, -9);
        }
      });
  }
}

export function drawSignalPlot(canvas, frequencies, values, type) {
  const ctx = canvas.getContext("2d"),
    r = canvas.getBoundingClientRect();
  if (!ctx || r.width < 1) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = r.width * dpr;
  canvas.height = r.height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const w = r.width,
    h = r.height;
  ctx.clearRect(0, 0, w, h);
  const left = 48,
    right = 14,
    top = 17,
    bottom = 30,
    pw = w - left - right,
    ph = h - top - bottom;
  ctx.font = '8px "SFMono-Regular", Consolas, monospace';
  ctx.lineWidth = 1;
  if (!Array.isArray(values) || !values.length || !frequencies?.length) {
    ctx.fillStyle = "#617d8f";
    ctx.textAlign = "center";
    ctx.fillText("GENERATE A MEASUREMENT TO SEE ITS SIGNAL", w / 2, h / 2);
    ctx.textAlign = "left";
    return;
  }
  const data = values
    .map((v, i) => ({ v, f: frequencies[i] }))
    .filter((p) => Number.isFinite(p.v) && Number.isFinite(p.f));
  if (!data.length) return;
  const minF = Math.min(...data.map((p) => p.f)) / 1e9,
    maxF = Math.max(...data.map((p) => p.f)) / 1e9;
  let min = type === "phase" ? -Math.PI : 0,
    max = type === "phase" ? Math.PI : Math.max(...data.map((p) => p.v)) * 1.12;
  if (max <= min) max = min + 1;
  const toX = (f) => left + ((f / 1e9 - minF) / (maxF - minF || 1)) * pw,
    toY = (v) => top + ph - ((v - min) / (max - min)) * ph;
  for (let i = 0; i < 4; i++) {
    const y = top + (ph * i) / 3;
    ctx.strokeStyle = "#2c425155";
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(w - right, y);
    ctx.stroke();
    ctx.fillStyle = "#758e9e";
    ctx.textAlign = "right";
    const value = max - ((max - min) * i) / 3;
    ctx.fillText(
      type === "phase" ? value.toFixed(2) : value.toExponential(1),
      left - 8,
      y + 3,
    );
  }
  const ticks = minF === maxF ? 1 : 4;
  for (let i = 0; i < ticks; i++) {
    const x = ticks === 1 ? left + pw / 2 : left + (pw * i) / 3;
    ctx.strokeStyle = "#2c425133";
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + ph);
    ctx.stroke();
    ctx.fillStyle = "#758e9e";
    ctx.textAlign = "center";
    ctx.fillText((minF + ((maxF - minF) * i) / 3).toFixed(3), x, h - 14);
  }
  ctx.textAlign = "right";
  ctx.fillStyle = "#506c7d";
  ctx.fillText("GHz", w - right, h - 2);
  ctx.textAlign = "left";
  const color = type === "phase" ? C.cyan : C.lime;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  let last = null;
  data.forEach((p) => {
    const x = data.length === 1 ? left + pw / 2 : toX(p.f),
      y = toY(p.v);
    if (!last || (type === "phase" && Math.abs(p.v - last.v) > Math.PI))
      ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
    last = p;
  });
  ctx.stroke();
  ctx.fillStyle = color;
  data.forEach((p) => {
    const x = data.length === 1 ? left + pw / 2 : toX(p.f),
      y = toY(p.v);
    ctx.beginPath();
    ctx.arc(x, y, data.length > 96 ? 1 : 1.7, 0, Math.PI * 2);
    ctx.fill();
  });
  canvas.setAttribute(
    "aria-label",
    `${type === "phase" ? "Wrapped phase in radians" : "Amplitude in arbitrary IQ units"} for ${data.length} actual signal samples, from ${minF.toFixed(4)} to ${maxF.toFixed(4)} gigahertz.`,
  );
}
