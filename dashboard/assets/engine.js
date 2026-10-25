/*
 * Musicozie browser engine: hand tracking -> finger states -> notes -> WebAudio sound.
 *
 * This is a JavaScript port of the Python modules gesture_matrix.py, instrument_modes.py, the finger
 * detection in vision_processor.py and GestureLogic in pipeline.py, so the instrument works for every visitor
 * of a cloud deployment (no server camera, no server sound card). Everything runs in the browser:
 * camera frames never leave the device.
 *
 * The file is a UMD module: `window.MusicozieEngine` in the browser, `require()` in Node (used by the tests).
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MusicozieEngine = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ------------------------------------------------------------------ settings (mirror of config.py)
  var settings = {
    solfege: {
      "10000": ["C", 60], "11000": ["D", 62], "11100": ["E", 64], "11110": ["F", 65],
      "11111": ["G", 67], "01111": ["A", 69], "01110": ["B", 71], "01100": ["C High", 72]
    },
    minorShift: -1,
    minorTrigger: "10000",
    melodyHand: "right",
    modifierHand: "left",
    holdS: 1.5,
    dropoutS: 0.2,
    openRatio: 1.25,
    thumbTuckRatio: 0.95,
    minHandScore: 0.5,
    debounceMs: 100,
    lostGraceMs: 150,
    melodyVelocity: 105,
    defaultInstrument: "piano",
    vibrato: { rate_hz: 5.5, depth_cents: 20, delay_s: 0.15, ramp_s: 0.25 },
    instruments: {
      piano: { key: "piano", label: "PIANO", program: 0, sustained: false, vibrato: false },
      violin: { key: "violin", label: "VIOLIN", program: 40, sustained: true, vibrato: true }
    }
  };
  var ORDER = ["piano", "violin"];

  // Apply the payload of GET /api/config (and its optional "vision" block) so the browser follows config.py.
  function configure(cfg) {
    if (!cfg) return;
    if (typeof cfg.minor_shift === "number") settings.minorShift = cfg.minor_shift;
    if (cfg.minor_trigger) settings.minorTrigger = String(cfg.minor_trigger);
    if (cfg.melody_hand) { settings.melodyHand = cfg.melody_hand; settings.modifierHand = cfg.modifier_hand; }
    if (typeof cfg.mode_switch_hold_s === "number") settings.holdS = cfg.mode_switch_hold_s;
    if (cfg.vibrato) {
      settings.vibrato.rate_hz = cfg.vibrato.rate_hz;
      settings.vibrato.depth_cents = cfg.vibrato.depth_cents;
      settings.vibrato.delay_s = cfg.vibrato.delay_s;
      if (typeof cfg.vibrato.ramp_s === "number") settings.vibrato.ramp_s = cfg.vibrato.ramp_s;
    }
    if (cfg.solfege && cfg.solfege.length) {
      settings.solfege = {};
      cfg.solfege.forEach(function (r) { settings.solfege[r.code] = [r.name, r.midi]; });
    }
    if (cfg.instruments && cfg.instruments.length) {
      settings.instruments = {};
      cfg.instruments.forEach(function (m) { settings.instruments[m.key] = m; });
      ORDER = cfg.instruments.map(function (m) { return m.key; });
    }
    if (cfg.default_instrument) settings.defaultInstrument = cfg.default_instrument;
    var v = cfg.vision;
    if (v) {
      if (typeof v.open_ratio === "number") settings.openRatio = v.open_ratio;
      if (typeof v.thumb_tuck_ratio === "number") settings.thumbTuckRatio = v.thumb_tuck_ratio;
      if (typeof v.min_hand_score === "number") settings.minHandScore = v.min_hand_score;
      if (typeof v.debounce_ms === "number") settings.debounceMs = v.debounce_ms;
      if (typeof v.lost_grace_ms === "number") settings.lostGraceMs = v.lost_grace_ms;
      if (typeof v.melody_velocity === "number") settings.melodyVelocity = v.melody_velocity;
    }
  }

  // ------------------------------------------------------------------ finger detection (vision_processor.py)
  var WRIST = 0;
  var FINGER_IDS = [[8, 5], [12, 9], [16, 13], [20, 17]];   // [tip, mcp]: index, middle, ring, pinky

  function dist(a, b) { return Math.hypot(a[0] - b[0], a[1] - b[1]); }

  function isFingerOpen(lm, tipId, mcpId, ratio) {
    ratio = ratio == null ? settings.openRatio : ratio;
    return dist(lm[tipId], lm[WRIST]) > ratio * dist(lm[mcpId], lm[WRIST]);
  }

  function fingerStates(lm) {
    return FINGER_IDS.map(function (p) { return isFingerOpen(lm, p[0], p[1]) ? 1 : 0; });
  }

  function thumbRatio(lm) {
    var base = dist(lm[2], lm[17]);
    return base > 1e-6 ? dist(lm[4], lm[17]) / base : 1.0;
  }

  function isThumbOpen(lm, ratio) {
    ratio = ratio == null ? settings.thumbTuckRatio : ratio;
    return thumbRatio(lm) >= ratio;
  }

  function fingerStates5(lm) {
    return [isThumbOpen(lm) ? 1 : 0].concat(fingerStates(lm));
  }

  function buildHandState(side, lm) {
    var pts = lm.map(function (p) { return [Number(p[0]), Number(p[1])]; });
    var fingers = fingerStates5(pts);
    return { side: side, fingers: fingers, code: fingers.join(""), landmarks: pts };
  }

  // MediaPipe label -> the player's physical hand. Measured on the real webcam pipeline (selfie-flipped frame):
  // the label is from the camera's point of view, so it is swapped here. Same rule as side_from_label() in Python.
  function sideFromLabel(label, swap) {
    var side = String(label).toLowerCase();
    if (swap === undefined || swap) side = side === "left" ? "right" : "left";
    return side;
  }

  // candidates: [[score, handState], ...]. Keep the best score per side (avoids two "left" detections).
  function pickBestPerSide(candidates) {
    var best = {}, order = [];
    candidates.forEach(function (c) {
      var side = c[1].side;
      if (!(side in best)) order.push(side);
      if (!(side in best) || c[0] > best[side][0]) best[side] = c;
    });
    return order.map(function (s) { return best[s][1]; });
  }

  // ------------------------------------------------------------------ notes (gesture_matrix.py)
  var NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  function midiName(m) { return NOTE_NAMES[m % 12] + (Math.floor(m / 12) - 1); }

  function makeNote(solfege, midi, minor) {
    return {
      solfege: solfege, midi: midi, minor: !!minor, name: midiName(midi),
      label: minor ? solfege + "\u266d (Minor)" : solfege
    };
  }

  function bits(f) { return Array.prototype.map.call(f, function (x) { return x ? 1 : 0; }).join(""); }

  function resolveSolfege(fingers) {
    var hit = settings.solfege[bits(fingers)];
    return hit ? makeNote(hit[0], hit[1], false) : null;
  }

  function isMinorActive(modifier) {
    return !!modifier && bits(modifier) === settings.minorTrigger;
  }

  function resolvePair(melody, modifier) {
    if (!melody) return null;
    var note = resolveSolfege(melody);
    if (!note) return null;
    if (isMinorActive(modifier)) return makeNote(note.solfege, note.midi + settings.minorShift, true);
    return note;
  }

  function sameNote(a, b) {
    if (a === null || b === null) return a === b;
    return a.solfege === b.solfege && a.midi === b.midi && a.minor === b.minor;
  }

  function nextMode(key) { return ORDER[(ORDER.indexOf(key) + 1) % ORDER.length]; }

  // ------------------------------------------------------------------ GestureLogic (pipeline.py)
  function GestureLogic(debounceMs, lostGraceMs) {
    this.debounceMs = debounceMs == null ? settings.debounceMs : debounceMs;
    this.lostGraceMs = lostGraceMs == null ? settings.lostGraceMs : lostGraceMs;
    this.current = null;
    this.minorActive = false;
    this._changedAt = -1e9;
    this._seen = {};
  }
  GestureLogic.prototype.reset = function () {
    var cmds = this.current !== null ? [{ type: "note_off" }] : [];
    this.current = null;
    this.minorActive = false;
    this._seen = {};
    return cmds;
  };
  GestureLogic.prototype._effective = function (side, bySide, now) {
    var h = bySide[side];
    if (h) {
      this._seen[side] = { fingers: h.fingers.slice(), t: now };
      return h.fingers.slice();
    }
    var s = this._seen[side];
    return s && (now - s.t) * 1000 < this.lostGraceMs ? s.fingers : null;
  };
  // hands: [{side, fingers}], now: seconds. Returns { commands, events }.
  GestureLogic.prototype.update = function (hands, now) {
    var bySide = {};
    hands.forEach(function (h) { bySide[h.side] = h; });
    var melody = this._effective(settings.melodyHand, bySide, now);
    var modifier = this._effective(settings.modifierHand, bySide, now);
    this.minorActive = isMinorActive(modifier);
    var desired = resolvePair(melody, modifier);
    var commands = [], events = [];
    if (!sameNote(desired, this.current) && (now - this._changedAt) * 1000 >= this.debounceMs) {
      this._changedAt = now;
      if (this.current !== null) commands.push({ type: "note_off" });
      this.current = desired;
      if (desired === null) {
        events.push({ kind: "note_off" });
      } else {
        commands.push({ type: "note_on", midi: desired.midi });
        events.push({ kind: "note_on", name: desired.name, solfege: desired.solfege, midi: desired.midi,
                      minor: desired.minor, label: desired.label });
      }
    }
    return { commands: commands, events: events };
  };

  // ------------------------------------------------------------------ ModeSwitch (instrument_modes.py)
  function ModeSwitch(holdS, dropoutS) {
    this.holdS = holdS == null ? settings.holdS : holdS;
    this.dropoutS = dropoutS == null ? settings.dropoutS : dropoutS;
    this._start = null;
    this._lastOk = -1e9;
    this._armed = true;
    this._now = 0;
  }
  ModeSwitch.isDoubleFist = function (left, right) {
    return !!left && !!right && !Array.prototype.some.call(left, Boolean) && !Array.prototype.some.call(right, Boolean);
  };
  Object.defineProperty(ModeSwitch.prototype, "progress", {
    get: function () {
      if (this._start === null) return 0;
      return Math.max(0, Math.min(1, (this._now - this._start) / this.holdS));
    }
  });
  ModeSwitch.prototype.update = function (left, right, now) {
    this._now = now;
    if (ModeSwitch.isDoubleFist(left, right)) {
      this._lastOk = now;
      if (this._armed && this._start === null) this._start = now;
    } else if (now - this._lastOk > this.dropoutS) {
      this._start = null;
      this._armed = true;
    }
    if (this._armed && this._start !== null && now - this._start >= this.holdS) {
      this._armed = false;
      this._start = null;
      return true;
    }
    return false;
  };

  // ------------------------------------------------------------------ WebAudio synth
  function midiToHz(m) { return 440 * Math.pow(2, (m - 69) / 12); }

  // Monophonic synth with two voices that stand in for the SoundFont programs:
  //   piano  : percussive harmonic tone that decays by itself while the gesture is held
  //   violin : bowed sawtooth pair, sustained while held, with delayed vibrato (rate/depth/delay from config.py)
  function Synth(opts) {
    opts = opts || {};
    this.AudioCtx = opts.AudioContext || (typeof window !== "undefined" ? (window.AudioContext || window.webkitAudioContext) : null);
    this.ctx = null;
    this.master = null;
    this.pianoWave = null;
    this.muted = false;
    this.instrument = settings.defaultInstrument;
    this.heldMidi = null;
    this.voice = null;
    this.volume = opts.volume == null ? 0.5 : opts.volume;
  }
  Synth.prototype.supported = function () { return !!this.AudioCtx; };
  Synth.prototype._build = function () {
    if (this.ctx || !this.AudioCtx) return;
    var ctx = this.ctx = new this.AudioCtx({ latencyHint: "interactive" });
    var comp = ctx.createDynamicsCompressor();
    this.master = ctx.createGain();
    this.master.gain.value = this.volume;
    this.master.connect(comp);
    comp.connect(ctx.destination);
    // piano timbre: fundamental plus decaying harmonics
    var amps = [0, 1, 0.55, 0.32, 0.2, 0.12, 0.08, 0.05, 0.03];
    var real = new Float32Array(amps.length), imag = new Float32Array(amps.length);
    for (var i = 0; i < amps.length; i++) imag[i] = amps[i];
    this.pianoWave = ctx.createPeriodicWave(real, imag);
  };
  // Must be called from a user gesture (browsers keep the context suspended until then).
  Synth.prototype.unlock = function () {
    var self = this;
    this._build();
    if (!this.ctx) return Promise.resolve(false);
    var p = this.ctx.state === "running" ? Promise.resolve() : this.ctx.resume();
    return Promise.resolve(p).then(function () {
      var ok = self.ctx.state === "running";
      if (ok) self._resumeHeld();
      return ok;
    }, function () { return false; });
  };
  Synth.prototype.status = function () {
    if (!this.AudioCtx) return "unsupported";
    if (!this.ctx || this.ctx.state !== "running") return "locked";
    return this.muted ? "muted" : "on";
  };
  Synth.prototype.latencyMs = function () {
    if (!this.ctx) return 0;
    return ((this.ctx.baseLatency || 0) + (this.ctx.outputLatency || 0)) * 1000;
  };
  Synth.prototype.setMuted = function (m) {
    this.muted = !!m;
    if (this.muted) this._stopVoice(0.03); else this._resumeHeld();
  };
  Synth.prototype.setInstrument = function (key) {
    this.instrument = key;
    this.noteOff();
  };
  Synth.prototype.noteOn = function (midi) {
    this._stopVoice(0.02);
    this.heldMidi = midi;
    this._resumeHeld();
  };
  Synth.prototype.noteOff = function () {
    this.heldMidi = null;
    this._stopVoice(this.instrument === "violin" ? 0.05 : 0.08);
  };
  Synth.prototype.allOff = function () { this.noteOff(); };
  Synth.prototype._resumeHeld = function () {
    if (this.heldMidi === null || this.voice || this.muted) return;
    if (!this.ctx || this.ctx.state !== "running") return;
    this.voice = this._startVoice(this.heldMidi);
  };
  Synth.prototype._stopVoice = function (tau) {
    var v = this.voice;
    if (!v) return;
    this.voice = null;
    var t = this.ctx.currentTime;
    v.release.gain.cancelScheduledValues(t);
    v.release.gain.setTargetAtTime(0, t, tau);
    var stopAt = t + tau * 8 + 0.05;
    v.sources.forEach(function (s) { try { s.stop(stopAt); } catch (e) { /* already stopped */ } });
    if (v.sources[0]) {
      v.sources[0].onended = function () {
        v.nodes.forEach(function (n) { try { n.disconnect(); } catch (e) { /* ignore */ } });
      };
    }
  };
  Synth.prototype._startVoice = function (midi) {
    var ctx = this.ctx, t = ctx.currentTime, hz = midiToHz(midi);
    var vel = Math.max(0.05, Math.min(1, settings.melodyVelocity / 127));
    var release = ctx.createGain();
    release.gain.value = 1;
    release.connect(this.master);
    var env = ctx.createGain();
    env.connect(release);
    var filt = ctx.createBiquadFilter();
    filt.type = "lowpass";
    filt.connect(env);
    var sources = [], nodes = [release, env, filt];

    if (this.instrument === "violin") {
      var vib = settings.vibrato;
      filt.Q.value = 0.9;
      filt.frequency.value = Math.min(hz * 6, 5000);
      env.gain.setValueAtTime(0, t);
      env.gain.linearRampToValueAtTime(vel * 0.55, t + 0.09);     // bow attack
      var lfo = ctx.createOscillator(), lfoGain = ctx.createGain();
      lfo.type = "sine";
      lfo.frequency.value = vib.rate_hz;
      lfoGain.gain.setValueAtTime(0, t);
      lfoGain.gain.setValueAtTime(0, t + vib.delay_s);            // clean tone first, then vibrato fades in
      lfoGain.gain.linearRampToValueAtTime(vib.depth_cents, t + vib.delay_s + (vib.ramp_s || 0.25));
      lfo.connect(lfoGain);
      [0, 7].forEach(function (detune) {
        var o = ctx.createOscillator();
        o.type = "sawtooth";
        o.frequency.value = hz;
        o.detune.value = detune;
        lfoGain.connect(o.detune);
        o.connect(filt);
        o.start(t);
        sources.push(o);
      });
      lfo.start(t);
      sources.push(lfo);
      nodes.push(lfo, lfoGain);
    } else {
      filt.Q.value = 0.7;
      filt.frequency.setValueAtTime(Math.min(hz * 10, 9000), t);
      filt.frequency.setTargetAtTime(Math.max(hz * 2.5, 900), t + 0.02, 0.6);   // tone darkens as it decays
      env.gain.setValueAtTime(0, t);
      env.gain.linearRampToValueAtTime(vel * 0.8, t + 0.006);                   // hammer attack
      env.gain.setTargetAtTime(0.0001, t + 0.006, 1.1);                         // percussive decay
      var po = ctx.createOscillator();
      po.setPeriodicWave(this.pianoWave);
      po.frequency.value = hz;
      po.connect(filt);
      po.start(t);
      sources.push(po);
    }
    // sources[0] must be an oscillator that ends last-ish: used for cleanup
    nodes = nodes.concat(sources);
    return { release: release, sources: sources, nodes: nodes };
  };

  // ------------------------------------------------------------------ Engine (LogicThread.step + SharedState)
  function Engine(opts) {
    opts = opts || {};
    this.synth = opts.synth || new Synth();
    this.instrument = settings.defaultInstrument;
    this.debounceMs = settings.debounceMs;
    this.cameraEnabled = true;
    this.logic = new GestureLogic(this.debounceMs);
    this.switcher = new ModeSwitch();
    this.hands = [];
    this.note = null;
    this.switchProgress = 0;
    this.minorActive = false;
    this.latencyMs = 0;
    this.fps = 0;
    this._tPrev = null;
    this.synth.setInstrument(this.instrument);
  }
  Engine.prototype._run = function (commands) {
    var s = this.synth;
    commands.forEach(function (c) {
      if (c.type === "note_off") s.noteOff();
      else if (c.type === "note_on") s.noteOn(c.midi);
    });
  };
  Engine.prototype._applyInstrument = function (key) {
    this.instrument = key;
    this.synth.setInstrument(key);
    this._run(this.logic.reset());
    this.note = null;
  };
  Engine.prototype.setInstrument = function (key) {
    if (settings.instruments[key] && key !== this.instrument) this._applyInstrument(key);
  };
  Engine.prototype.setDebounce = function (ms) {
    var v = Number(ms);
    if (isFinite(v)) this.debounceMs = Math.max(0, Math.min(1000, v));
  };
  Engine.prototype.setCameraEnabled = function (on) {
    on = !!on;
    if (on === this.cameraEnabled) return;
    this.cameraEnabled = on;
    if (!on) this.silence();
  };
  // Silence everything and clear hand/HUD state (camera off, tab hidden, tracker stopped).
  Engine.prototype.silence = function () {
    this._run(this.logic.reset());
    this.switcher = new ModeSwitch();     // drop any half-finished double-fist hold
    this.hands = [];
    this.note = null;
    this.switchProgress = 0;
    this.minorActive = false;
    this.fps = 0;
    this._tPrev = null;
  };
  // hands: [{side, fingers, ...}] detected in one frame; now: seconds (monotonic); tCapture: seconds (optional).
  Engine.prototype.step = function (hands, now, tCapture) {
    if (!this.cameraEnabled) { this.silence(); return this.snapshot(); }
    var bySide = {};
    hands.forEach(function (h) { bySide[h.side] = h; });
    var left = bySide.left, right = bySide.right;
    if (this.switcher.update(left ? left.fingers : null, right ? right.fingers : null, now)) {
      this._applyInstrument(nextMode(this.instrument));
    }
    this.switchProgress = this.switcher.progress;

    this.logic.debounceMs = this.debounceMs;
    var out = this.logic.update(hands, now);
    this._run(out.commands);
    this.hands = hands;
    this.note = this.logic.current;
    this.minorActive = this.logic.minorActive;

    var noteOn = out.events.some(function (e) { return e.kind === "note_on"; });
    if (noteOn) {
      var lat = (now - (tCapture == null ? now : tCapture)) * 1000 + this.synth.latencyMs();
      this.latencyMs = this.latencyMs === 0 ? lat : 0.8 * this.latencyMs + 0.2 * lat;
    }
    if (this._tPrev !== null) {
      var inst = 1 / Math.max(now - this._tPrev, 1e-6);
      this.fps = this.fps ? 0.9 * this.fps + 0.1 * inst : inst;
    }
    this._tPrev = now;
    return this.snapshot();
  };
  // Same shape as the server's WebSocket "state" message, so the dashboard renders it unchanged.
  Engine.prototype.snapshot = function () {
    var n = this.note;
    return {
      status: "ok", message: "", camera_enabled: this.cameraEnabled, client_camera: true, has_video: false,
      fps: Math.round(this.fps * 10) / 10, latency_ms: Math.round(this.latencyMs * 10) / 10,
      debounce_ms: this.debounceMs, hands: this.hands,
      instrument: this.instrument, mode_label: (settings.instruments[this.instrument] || {}).label || this.instrument.toUpperCase(),
      switch_progress: Math.round(this.switchProgress * 1000) / 1000, minor_active: this.minorActive,
      note: n ? { name: n.name, solfege: n.solfege, midi: n.midi, minor: n.minor, label: n.label } : null
    };
  };

  // ------------------------------------------------------------------ HandTracker (MediaPipe Tasks Vision, browser)
  var MP_VERSION = "0.10.21";
  var MP_CDN = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@" + MP_VERSION;

  function HandTracker(opts) {
    opts = opts || {};
    this.baseUrl = (opts.baseUrl || (typeof window !== "undefined" && window.MUSICOZIE_MEDIAPIPE_BASE) || MP_CDN).replace(/\/+$/, "");
    this.modelUrl = opts.modelUrl || "/models/hand_landmarker.task";
    this.importer = opts.importer || function (url) { return import(url); };
    this.createCanvas = opts.createCanvas || function () { return document.createElement("canvas"); };
    this.mod = null;
    this.fileset = null;
    this.landmarker = null;
    this.delegate = null;
    this.canvas = null;
    this.c2d = null;
    this._lastTs = -1;
    this.errors = 0;
    this._loading = null;
  }
  HandTracker.prototype._create = function (delegate) {
    var self = this, mod = this.mod, s = settings.minHandScore;
    return mod.HandLandmarker.createFromOptions(this.fileset, {
      baseOptions: { modelAssetPath: this.modelUrl, delegate: delegate },
      runningMode: "VIDEO",
      numHands: 2,
      minHandDetectionConfidence: s,
      minHandPresenceConfidence: s,
      minTrackingConfidence: s
    }).then(function (lm) { self.landmarker = lm; self.delegate = delegate; self.errors = 0; return lm; });
  };
  // Load the MediaPipe bundle + model once. Tries the GPU delegate first, then CPU.
  HandTracker.prototype.init = function () {
    var self = this;
    if (this.landmarker) return Promise.resolve(this);
    if (this._loading) return this._loading;
    this._loading = Promise.resolve(this.importer(this.baseUrl + "/vision_bundle.mjs")).then(function (mod) {
      self.mod = mod;
      return mod.FilesetResolver.forVisionTasks(self.baseUrl + "/wasm");
    }).then(function (fileset) {
      self.fileset = fileset;
      return self._create("GPU").catch(function () { return self._create("CPU"); });
    }).then(function () { self._loading = null; return self; }, function (err) { self._loading = null; throw err; });
    return this._loading;
  };
  // Rebuild the landmarker on the CPU delegate (used when the GPU path throws while detecting).
  HandTracker.prototype.recover = function () {
    var self = this, old = this.landmarker;
    this.landmarker = null;
    try { if (old && old.close) old.close(); } catch (e) { /* ignore */ }
    return this._create("CPU").then(function () { return self; });
  };
  HandTracker.prototype.close = function () {
    try { if (this.landmarker && this.landmarker.close) this.landmarker.close(); } catch (e) { /* ignore */ }
    this.landmarker = null;
  };
  // Draw the frame mirrored (selfie view), exactly like cv2.flip(frame, 1) in vision_processor.py.
  HandTracker.prototype._flip = function (video) {
    var w = video.videoWidth, h = video.videoHeight;
    if (!this.canvas) { this.canvas = this.createCanvas(); this.c2d = this.canvas.getContext("2d"); }
    if (this.canvas.width !== w || this.canvas.height !== h) { this.canvas.width = w; this.canvas.height = h; }
    var c = this.c2d;
    c.save();
    c.scale(-1, 1);
    c.drawImage(video, -w, 0, w, h);
    c.restore();
    return this.canvas;
  };
  // Returns [{side, fingers, code, landmarks}] in mirrored (selfie) coordinates, or null on a detection error.
  HandTracker.prototype.detect = function (video, tsMs) {
    if (!this.landmarker) return null;
    var ts = Math.max(Math.round(tsMs), this._lastTs + 1);   // timestamps must increase strictly
    this._lastTs = ts;
    var res;
    try {
      res = this.landmarker.detectForVideo(this._flip(video), ts);
      this.errors = 0;
    } catch (e) {
      this.errors++;
      return null;
    }
    var cats = res.handedness || res.handednesses || [];
    var cands = [];
    for (var i = 0; i < res.landmarks.length; i++) {
      var cat = cats[i] && cats[i][0];
      if (!cat) continue;
      var side = sideFromLabel(cat.categoryName);
      var lm = res.landmarks[i].map(function (p) { return [p.x, p.y]; });
      cands.push([cat.score, buildHandState(side, lm)]);
    }
    return pickBestPerSide(cands);
  };

  return {
    settings: settings, configure: configure,
    isFingerOpen: isFingerOpen, fingerStates: fingerStates, thumbRatio: thumbRatio, isThumbOpen: isThumbOpen,
    fingerStates5: fingerStates5, buildHandState: buildHandState, sideFromLabel: sideFromLabel,
    pickBestPerSide: pickBestPerSide, midiName: midiName, midiToHz: midiToHz,
    resolveSolfege: resolveSolfege, isMinorActive: isMinorActive, resolvePair: resolvePair, nextMode: nextMode,
    GestureLogic: GestureLogic, ModeSwitch: ModeSwitch, Synth: Synth, Engine: Engine, HandTracker: HandTracker,
    MP_VERSION: MP_VERSION, MP_CDN: MP_CDN
  };
});