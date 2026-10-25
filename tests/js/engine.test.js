// Unit tests for dashboard/assets/engine.js (run: node --test tests/js)
const test = require("node:test");
const assert = require("node:assert/strict");
const E = require("../../dashboard/assets/engine.js");

// ---------------------------------------------------------------- helpers
// Synthetic hand: wrist at origin, finger tips far (open) or near (closed), thumb tip far from / near the pinky base.
function hand(code) {
  const lm = Array.from({ length: 21 }, () => [0.5, 0.5]);
  lm[0] = [0.5, 0.9];
  lm[2] = [0.42, 0.75];                 // thumb MCP
  lm[17] = [0.6, 0.78];                 // pinky MCP
  const tips = [[8, 5, 0.46], [12, 9, 0.5], [16, 13, 0.54], [20, 17, 0.58]];
  tips.forEach(([tip, mcp, x], i) => {
    lm[mcp] = [x, 0.65];
    lm[tip] = code[i + 1] === "1" ? [x, 0.3] : [x, 0.7];
  });
  lm[4] = code[0] === "1" ? [0.2, 0.7] : [0.55, 0.77];
  return lm;
}
const H = (side, code) => E.buildHandState(side, hand(code));

class Param {
  constructor() { this.value = 0; this.calls = []; }
  setValueAtTime(v, t) { this.calls.push(["set", v, t]); return this; }
  linearRampToValueAtTime(v, t) { this.calls.push(["ramp", v, t]); return this; }
  setTargetAtTime(v, t, tau) { this.calls.push(["target", v, t, tau]); return this; }
  cancelScheduledValues(t) { this.calls.push(["cancel", t]); return this; }
}
class Node {
  constructor(kind, ctx) { this.kind = kind; this.ctx = ctx; this.connections = []; this.started = false; this.stopped = null; ctx.nodes.push(this); }
  connect(n) { this.connections.push(n); return n; }
  disconnect() { this.disconnected = true; }
  start() { this.started = true; }
  stop(t) { this.stopped = t; }
  setPeriodicWave(w) { this.wave = w; }
}
function mockContext(initialState = "suspended") {
  return class MockCtx {
    constructor(opts) {
      this.state = initialState; this.currentTime = 1; this.nodes = []; this.opts = opts;
      this.destination = new Node("destination", this); this.baseLatency = 0.01; this.outputLatency = 0.02;
      MockCtx.last = this;
    }
    resume() { this.state = "running"; return Promise.resolve(); }
    _node(kind, params) { const n = new Node(kind, this); (params || []).forEach((p) => { n[p] = new Param(); }); return n; }
    createGain() { return this._node("gain", ["gain"]); }
    createDynamicsCompressor() { return this._node("compressor"); }
    createBiquadFilter() { return this._node("filter", ["frequency", "Q"]); }
    createOscillator() { return this._node("osc", ["frequency", "detune"]); }
    createPeriodicWave(real, imag) { return { real, imag }; }
  };
}

// ---------------------------------------------------------------- finger detection
test("synthetic hands give the expected 5-bit codes", () => {
  for (const code of ["10000", "11000", "11100", "11110", "11111", "01111", "01110", "01100", "00000"]) {
    assert.equal(E.fingerStates5(hand(code)).join(""), code, code);
    assert.equal(H("right", code).code, code);
  }
});

test("side_from_label swaps by default, like Python", () => {
  assert.equal(E.sideFromLabel("Left"), "right");
  assert.equal(E.sideFromLabel("Right"), "left");
  assert.equal(E.sideFromLabel("Left", false), "left");
});

test("pickBestPerSide keeps the highest score per side", () => {
  const a = H("left", "10000"), b = H("left", "11000"), c = H("right", "11111");
  const out = E.pickBestPerSide([[0.6, a], [0.9, b], [0.7, c]]);
  assert.equal(out.length, 2);
  assert.equal(out.find((h) => h.side === "left").code, "11000");
});

// ---------------------------------------------------------------- notes
test("resolvePair: major, minor toggle, silent cases", () => {
  const n = E.resolvePair([1, 1, 0, 0, 0], null);
  assert.deepEqual([n.solfege, n.midi, n.minor, n.name, n.label], ["D", 62, false, "D4", "D"]);
  const m = E.resolvePair([1, 1, 0, 0, 0], [1, 0, 0, 0, 0]);
  assert.deepEqual([m.midi, m.minor, m.name, m.label], [61, true, "C#4", "D\u266d (Minor)"]);
  assert.equal(E.resolvePair(null, [1, 0, 0, 0, 0]), null);       // modifier alone is silent
  assert.equal(E.resolvePair([0, 0, 0, 0, 0], null), null);       // fist
  assert.equal(E.resolvePair([0, 0, 1, 0, 0], null), null);       // unknown pattern
});

// ---------------------------------------------------------------- GestureLogic
test("GestureLogic: first change is immediate, debounce blocks flicker, grace keeps sound", () => {
  const g = new E.GestureLogic(100, 150);
  let r = g.update([H("right", "10000")], 1.0);
  assert.deepEqual(r.commands, [{ type: "note_on", midi: 60 }]);
  r = g.update([H("right", "11000")], 1.05);                      // within debounce -> ignored
  assert.deepEqual(r.commands, []);
  r = g.update([H("right", "11000")], 1.2);                       // applied: off + on
  assert.deepEqual(r.commands, [{ type: "note_off" }, { type: "note_on", midi: 62 }]);
  r = g.update([], 1.25);                                         // hand lost, inside 150 ms grace
  assert.deepEqual(r.commands, []);
  assert.equal(g.current.midi, 62);
  r = g.update([], 1.6);                                          // grace expired
  assert.deepEqual(r.commands, [{ type: "note_off" }]);
  assert.equal(g.current, null);
});

test("GestureLogic: left thumb-only flattens the right-hand note", () => {
  const g = new E.GestureLogic(100, 150);
  g.update([H("right", "11000"), H("left", "10000")], 1.0);
  assert.equal(g.current.midi, 61);
  assert.ok(g.minorActive);
});

// ---------------------------------------------------------------- ModeSwitch
test("ModeSwitch: double fist held 1.5 s fires once, and only re-arms after release", () => {
  const s = new E.ModeSwitch(1.5, 0.2);
  const fist = [0, 0, 0, 0, 0];
  let fired = 0;
  for (let t = 0; t <= 4; t += 0.05) if (s.update(fist, fist, t)) fired++;
  assert.equal(fired, 1);
  for (let t = 4.05; t <= 4.5; t += 0.05) s.update(null, null, t);
  for (let t = 4.5; t <= 6.5; t += 0.05) if (s.update(fist, fist, t)) fired++;
  assert.equal(fired, 2);
});

// ---------------------------------------------------------------- Synth
test("Synth stays silent until unlocked, then plays the held note at the right pitch", async () => {
  const Ctx = mockContext("suspended");
  const synth = new E.Synth({ AudioContext: Ctx });
  assert.equal(synth.status(), "locked");
  synth.noteOn(69);                                               // before any user gesture
  assert.equal(synth.voice, null);
  assert.equal(await synth.unlock(), true);
  assert.equal(synth.status(), "on");
  assert.ok(synth.voice, "held note starts once the context is running");
  const osc = Ctx.last.nodes.find((n) => n.kind === "osc");
  assert.equal(osc.frequency.value, 440);
  assert.ok(osc.wave, "piano uses a harmonic PeriodicWave");
});

test("Synth piano: noteOff releases and stops oscillators", async () => {
  const Ctx = mockContext("running");
  const synth = new E.Synth({ AudioContext: Ctx });
  await synth.unlock();
  synth.noteOn(60);
  const osc = Ctx.last.nodes.find((n) => n.kind === "osc");
  assert.ok(Math.abs(osc.frequency.value - 261.6256) < 0.01);
  synth.noteOff();
  assert.equal(synth.voice, null);
  assert.ok(osc.stopped > Ctx.last.currentTime);
});

test("Synth violin: two sawtooth voices + delayed vibrato from config", async () => {
  const Ctx = mockContext("running");
  const synth = new E.Synth({ AudioContext: Ctx });
  await synth.unlock();
  synth.setInstrument("violin");
  synth.noteOn(67);
  const oscs = Ctx.last.nodes.filter((n) => n.kind === "osc");
  assert.equal(oscs.length, 3);                                   // 2 saws + LFO
  const lfo = oscs.find((o) => o.frequency.value === E.settings.vibrato.rate_hz);
  assert.ok(lfo, "LFO runs at the configured vibrato rate");
  const lfoGain = Ctx.last.nodes.find((n) => n.kind === "gain" && n.gain.calls.some((c) => c[0] === "ramp" && c[1] === E.settings.vibrato.depth_cents));
  assert.ok(lfoGain, "vibrato depth ramps to the configured cents");
  const ramp = lfoGain.gain.calls.find((c) => c[0] === "ramp");
  assert.ok(Math.abs(ramp[2] - (1 + E.settings.vibrato.delay_s + E.settings.vibrato.ramp_s)) < 1e-9);
});

test("Synth mute stops sound and unmute resumes the held note", async () => {
  const Ctx = mockContext("running");
  const synth = new E.Synth({ AudioContext: Ctx });
  await synth.unlock();
  synth.noteOn(64);
  synth.setMuted(true);
  assert.equal(synth.voice, null);
  assert.equal(synth.status(), "muted");
  synth.setMuted(false);
  assert.ok(synth.voice);
});

// ---------------------------------------------------------------- Engine
function engineWithSynth() {
  const calls = [];
  const synth = {
    setInstrument: (k) => calls.push(["inst", k]), noteOn: (m) => calls.push(["on", m]),
    noteOff: () => calls.push(["off"]), latencyMs: () => 30
  };
  return { engine: new E.Engine({ synth }), calls };
}

test("Engine plays, retunes for minor, and silences when the camera turns off", () => {
  const { engine, calls } = engineWithSynth();
  let s = engine.step([H("right", "11100")], 10.0, 9.98);
  assert.deepEqual(s.note, { name: "E4", solfege: "E", midi: 64, minor: false, label: "E" });
  assert.ok(s.latency_ms >= 30 && s.client_camera === true);
  s = engine.step([H("right", "11100"), H("left", "10000")], 10.3, 10.3);
  assert.equal(s.note.midi, 63);
  assert.ok(s.minor_active);
  engine.setCameraEnabled(false);
  s = engine.step([H("right", "11100")], 10.5);
  assert.equal(s.note, null);
  assert.equal(s.hands.length, 0);
  assert.deepEqual(calls[calls.length - 1], ["off"]);
});

test("Engine switches instrument after a 1.5 s double fist, and the UI can set it directly", () => {
  const { engine, calls } = engineWithSynth();
  const fist = (side) => H(side, "00000");
  let s;
  for (let t = 0; t <= 1.7; t += 0.05) s = engine.step([fist("left"), fist("right")], 20 + t);
  assert.equal(s.instrument, "violin");
  assert.equal(s.mode_label, "VIOLIN");
  assert.ok(calls.some((c) => c[0] === "inst" && c[1] === "violin"));
  engine.setInstrument("piano");
  assert.equal(engine.snapshot().instrument, "piano");
  engine.setDebounce(5000);
  assert.equal(engine.snapshot().debounce_ms, 1000);
});

// ---------------------------------------------------------------- HandTracker (fake MediaPipe)
function fakeMediaPipe({ failGpu = false, results } = {}) {
  const log = { created: [], detects: [] };
  const mod = {
    FilesetResolver: { forVisionTasks: async (base) => { log.wasm = base; return { wasm: base }; } },
    HandLandmarker: {
      createFromOptions: async (fileset, opts) => {
        log.created.push(opts);
        if (failGpu && opts.baseOptions.delegate === "GPU") throw new Error("no webgl2");
        return { detectForVideo: (img, ts) => { log.detects.push([img, ts]); return results(); }, close() { log.closed = true; } };
      }
    }
  };
  return { mod, log };
}
const fakeCanvas = () => {
  const draws = [];
  const c2d = { save() {}, restore() {}, scale: (x, y) => draws.push(["scale", x, y]), drawImage: (...a) => draws.push(["draw", ...a]) };
  return { width: 0, height: 0, getContext: () => c2d, draws };
};
const pts = (code) => hand(code).map(([x, y]) => ({ x, y, z: 0 }));

test("HandTracker: GPU->CPU fallback, mirrored input, label swap, strictly increasing timestamps", async () => {
  const { mod, log } = fakeMediaPipe({
    failGpu: true,
    results: () => ({
      landmarks: [pts("11000"), pts("11111")],
      handedness: [[{ categoryName: "Left", score: 0.9 }], [{ categoryName: "Right", score: 0.8 }]]
    })
  });
  const canvas = fakeCanvas();
  const t = new E.HandTracker({ importer: async (u) => { log.imported = u; return mod; }, createCanvas: () => canvas, modelUrl: "/models/m.task" });
  await t.init();
  assert.equal(t.delegate, "CPU");
  assert.deepEqual(log.created.map((o) => o.baseOptions.delegate), ["GPU", "CPU"]);
  assert.match(log.imported, /tasks-vision@0\.10\.21\/vision_bundle\.mjs$/);
  assert.match(log.wasm, /tasks-vision@0\.10\.21\/wasm$/);
  assert.equal(log.created[0].numHands, 2);
  assert.equal(log.created[0].runningMode, "VIDEO");

  const video = { videoWidth: 640, videoHeight: 480 };
  const hands = t.detect(video, 1000.2);
  assert.deepEqual(canvas.draws[0], ["scale", -1, 1]);            // mirrored like cv2.flip(frame, 1)
  assert.deepEqual(canvas.draws[1], ["draw", video, -640, 0, 640, 480]);
  assert.equal(log.detects[0][0], canvas);
  assert.equal(hands.find((h) => h.side === "right").code, "11000");   // label "Left" -> player's right hand
  assert.equal(hands.find((h) => h.side === "left").code, "11111");
  t.detect(video, 1000.2);                                         // same timestamp must still advance
  t.detect(video, 999);                                            // going backwards must still advance
  const ts = log.detects.map((d) => d[1]);
  assert.ok(ts[0] < ts[1] && ts[1] < ts[2], ts.join(","));
});

test("HandTracker: detection errors return null and count; recover() switches to CPU", async () => {
  let boom = true;
  const { mod, log } = fakeMediaPipe({ results: () => { if (boom) throw new Error("gpu lost"); return { landmarks: [], handedness: [] }; } });
  const t = new E.HandTracker({ importer: async () => mod, createCanvas: fakeCanvas });
  await t.init();
  assert.equal(t.delegate, "GPU");
  const video = { videoWidth: 320, videoHeight: 240 };
  assert.equal(t.detect(video, 1), null);
  assert.equal(t.errors, 1);
  boom = false;
  await t.recover();
  assert.equal(t.delegate, "CPU");
  assert.equal(log.closed, true);
  assert.deepEqual(t.detect(video, 5), []);
  assert.equal(t.errors, 0);
});

test("HandTracker.init rejects when the MediaPipe bundle cannot be loaded", async () => {
  const t = new E.HandTracker({ importer: async () => { throw new Error("network down"); } });
  await assert.rejects(t.init(), /network down/);
  await assert.rejects(t.init(), /network down/);                 // can be retried
});