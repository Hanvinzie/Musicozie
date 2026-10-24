(function () {  
 "use strict";

 var $ = function (id) { return document.getElementById(id); };  
 var FLAT = "\u266d";

 // ------------------------------------------------------------------ defaults
 var NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];  
 function midiName(m) { return NOTE_NAMES[m % 12] + (Math.floor(m / 12) - 1); }

 var MINOR_SHIFT = -1, HOLD_S = 1.5, MINOR_TRIGGER = "10000";  
 var MELODY_HAND = "right", MODIFIER_HAND = "left";  
 var VIBRATO = { rate_hz: 5.5, depth_cents: 20, delay_s: 0.15 };  
 var INSTR = {  
   piano: { label: "PIANO", program: 0, sustained: false, vibrato: false },  
   violin: { label: "VIOLIN", program: 40, sustained: true, vibrato: true }  
 };  
 var NOTES = [  
   { n: "C", midi: 60, code: "10000", d: "Thumb only" },  
   { n: "D", midi: 62, code: "11000", d: "Thumb + index" },  
   { n: "E", midi: 64, code: "11100", d: "Thumb + index + middle" },  
   { n: "F", midi: 65, code: "11110", d: "Thumb + index + middle + ring" },  
   { n: "G", midi: 67, code: "11111", d: "All 5 fingers open (open palm)" },  
   { n: "A", midi: 69, code: "01111", d: "Index + middle + ring + pinky (thumb closed)" },  
   { n: "B", midi: 71, code: "01110", d: "Index + middle + ring (thumb closed)" },  
   { n: "C High", midi: 72, code: "01100", d: "Index + middle (thumb closed)" }  
 ];  
 var BIT_LABELS = ["T", "I", "M", "R", "P"];  
 var CONNECTIONS = [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],  
                    [9,13],[13,14],[14,15],[15,16],[13,17],[0,17],[17,18],[18,19],[19,20]];

 var instrument = "piano";  
 var online = false, lastState = null, ws = null, retryTimer = null, retryDelay = 1000;  
 var videoOn = false;  
 var wantInst = null, wantInstTimer = null, wantCam = null, wantCamTimer = null;

 // ------------------------------------------------------------------ helper DOM
 function el(tag, text, cls) {  
   var e = document.createElement(tag);  
   if (text) e.textContent = text;  
   if (cls) e.className = cls;  
   return e;  
 }  
 function secs(x) { return String(x); }  
 function cap(w) { return w.charAt(0).toUpperCase() + w.slice(1); }

 function diagram(code, inline) {  
   var box = el("div", "", "diagram" + (inline ? " inline" : ""));  
   BIT_LABELS.forEach(function (l, i) {  
     box.appendChild(el("span", l, code.charAt(i) === "1" ? "open" : ""));  
   });  
   return box;  
 }

 // ------------------------------------------------------------------ guide (data from Python)
 function buildGuide() {  
   var host = $("guideNotes");  
   if (!host) return;
   host.textContent = "";  
   NOTES.forEach(function (g) {  
     var row = el("div", "", "g-row");  
     row.dataset.key = g.n;  
     var n = el("div", g.n, "g-note");  
     var sm = el("small");  
     sm.appendChild(document.createTextNode(midiName(g.midi) + " \u00b7 " + g.midi + "  "));  
     sm.appendChild(el("b", "\u2192 " + midiName(g.midi + MINOR_SHIFT) + " \u00b7 " + (g.midi + MINOR_SHIFT)));  
     n.appendChild(sm);  
     row.appendChild(n);  
     row.appendChild(el("div", g.d + "  (" + g.code + ")", "g-desc"));  
     row.appendChild(diagram(g.code, false));  
     host.appendChild(row);  
   });  
   fillTexts();  
 }

 function fillTexts() {  
   var hold = secs(HOLD_S), ex = NOTES[1] || NOTES[0], i, nodes;  
   nodes = document.querySelectorAll('[data-cfg="hold"]');  
   for (i = 0; i < nodes.length; i++) nodes[i].textContent = hold;  
   nodes = document.querySelectorAll('[data-cfg="trigger"]');  
   for (i = 0; i < nodes.length; i++) nodes[i].textContent = MINOR_TRIGGER;  
   var texts = { "melody": cap(MELODY_HAND), "melody-l": MELODY_HAND, "modifier": cap(MODIFIER_HAND), "modifier-l": MODIFIER_HAND };  
   Object.keys(texts).forEach(function (k) {  
     var ns = document.querySelectorAll('[data-cfg="' + k + '"]');  
     for (var n = 0; n < ns.length; n++) ns[n].textContent = texts[k];  
   });  
   if ($("leftTitle")) $("leftTitle").textContent = "LEFT HAND \u00b7 " + (MELODY_HAND === "left" ? "MELODY" : "MINOR");  
   if ($("rightTitle")) $("rightTitle").textContent = "RIGHT HAND \u00b7 " + (MELODY_HAND === "right" ? "MELODY" : "MINOR");

   var mb = $("minorBox");  
   if (mb) {
     mb.textContent = "";  
     var shiftTxt = Math.abs(MINOR_SHIFT) + " semitone" + (MINOR_SHIFT < 0 ? " lower" : " higher");  
     mb.appendChild(el("b", "Minor Toggle"));  
     mb.appendChild(document.createTextNode(" \u2014 example: " + MELODY_HAND + " hand " + ex.code + " + " + MODIFIER_HAND + " hand "));  
     mb.appendChild(diagram(MINOR_TRIGGER, true));  
     mb.appendChild(document.createTextNode(" (" + MINOR_TRIGGER + ", thumb only) = "));  
     mb.appendChild(el("span", ex.n + FLAT + " (Minor)", "amber"));  
     mb.appendChild(document.createTextNode(", note " + midiName(ex.midi + MINOR_SHIFT) + " (MIDI " + (ex.midi + MINOR_SHIFT) +  
       ") replaces " + midiName(ex.midi) + " (" + ex.midi + "): " + shiftTxt +  
       ". The small line under each note name shows its minor result."));
   }

   var md = $("modeBox");  
   if (md) {
     md.textContent = "";  
     var keys = ["piano", "violin"].filter(function (k) { return INSTR[k]; });  
     keys.forEach(function (k) {  
       var m = INSTR[k];  
       md.appendChild(el("b", m.label + " mode"));  
       md.appendChild(document.createTextNode(" (program " + m.program + "): " + (m.sustained  
         ? "the note is sustained while the gesture is held, with gentle vibrato (pitch bend \u00b1" + VIBRATO.depth_cents + " cents, " +  
           VIBRATO.rate_hz + " Hz, starting after " + secs(VIBRATO.delay_s) + " s)."  
         : "percussive \u2014 the note sounds when the gesture forms and decays by itself.")));  
       md.appendChild(document.createElement("br"));  
     });  
     md.appendChild(document.createTextNode("The gesture mapping is identical in every mode. "));  
     md.appendChild(el("b", "Double fist "));  
     md.appendChild(diagram("00000", true));  
     md.appendChild(document.createTextNode(" + "));  
     md.appendChild(diagram("00000", true));  
     md.appendChild(document.createTextNode(" held for " + hold + " seconds switches the mode (a progress bar appears in the main panel)."));
   }

   if ($("instPiano")) $("instPiano").textContent = (INSTR.piano || {}).label || "PIANO";  
   if ($("instViolin")) $("instViolin").textContent = (INSTR.violin || {}).label || "VIOLIN";  
 }

 function highlightGuide(note) {  
   var rows = document.querySelectorAll("#guideNotes .g-row");  
   for (var i = 0; i < rows.length; i++) {  
     var on = !!note && rows[i].dataset.key === note.solfege;  
     rows[i].classList.toggle("live", on);  
     rows[i].classList.toggle("minor", on && note.minor);  
   }  
 }

 function applyConfig(cfg) {  
   if (!cfg || !cfg.solfege) return;  
   MINOR_SHIFT = cfg.minor_shift;  
   MINOR_TRIGGER = cfg.minor_trigger;  
   if (cfg.melody_hand) { MELODY_HAND = cfg.melody_hand; MODIFIER_HAND = cfg.modifier_hand; }  
   HOLD_S = cfg.mode_switch_hold_s;  
   VIBRATO = cfg.vibrato;  
   INSTR = {};  
   cfg.instruments.forEach(function (m) { INSTR[m.key] = m; });  
   NOTES = cfg.solfege.map(function (r) { return { n: r.name, midi: r.midi, code: r.code, d: r.description }; });  
   if (cfg.app && $("appVersion")) $("appVersion").textContent = "v" + cfg.app.version;  
   if (!(instrument in INSTR)) instrument = cfg.default_instrument;  
   buildGuide();  
   refreshInstrument();  
 }

 function loadConfig() {  
   fetch("/api/config", { cache: "no-store" })  
     .then(function (r) { return r.json(); })  
     .then(applyConfig)  
     .catch(function () { /* server not ready */ });  
 }

 // ------------------------------------------------------------------ finger bits
 function makeBits(container) {  
   if (!container) return [];
   return BIT_LABELS.map(function (l) {  
     var d = el("div", l, "bit");  
     container.appendChild(d);  
     return d;  
   });  
 }  
 var lhBits = makeBits($("lhBits")), rhBits = makeBits($("rhBits"));  
 function setBits(els, hand) {  
   els.forEach(function (e, i) { e.classList.toggle("on", !!(hand && hand.fingers[i])); });  
 }

 function setHud(note, progress, minor) {  
   var n = $("hudNote");  
   if (!n) return;
   n.textContent = "";  
   n.classList.toggle("idle", !note);  
   n.classList.toggle("minor", !!(note && note.minor));  
   if (!note) {  
     n.textContent = "-";  
   } else {  
     n.appendChild(document.createTextNode(note.label));  
     n.appendChild(el("small", note.name + " \u00b7 MIDI " + note.midi));  
   }  
   var st = $("hudStatus");  
   if (st) {
     st.textContent = minor ? "[MODE: MINOR TOGGLE ACTIVE]" : "[MODE: MAJOR]";  
     st.classList.toggle("minor", !!minor);  
   }
   if ($("switchFill")) $("switchFill").style.width = Math.round(Math.max(0, Math.min(1, progress || 0)) * 100) + "%";  
   if ($("switchTxt")) $("switchTxt").textContent = progress > 0 ? "Switching mode... keep both fists closed" : "";  
 }

 function setBadge(cls, text) {  
   if ($("badge")) $("badge").className = "badge " + cls;  
   if ($("badgeText")) $("badgeText").textContent = text;  
 }

 // ------------------------------------------------------------------ video + pesan
 function setVideo(on) {  
   if (on === videoOn) return;  
   videoOn = on;  
   var img = $("cam");  
   if (!img) return;
   if (on) img.src = "/video?t=" + Date.now();  
   else img.removeAttribute("src");  
 }

 function showMessage(text, withButton, buttonText) {  
   var stage = $("stage");  
   if (!stage) return;
   stage.classList.toggle("msg-on", !!text);  
   if ($("stageMsgText")) $("stageMsgText").textContent = text || "";  
   var b = $("camOnBtn");  
   if (b) {
     b.hidden = !withButton;  
     if (withButton) b.textContent = buttonText;  
   }
 }

 // ------------------------------------------------------------------ WebSocket (SSL Fix)
 function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

 function connect() {  
   clearTimeout(retryTimer);  
   // Otomatis memilih wss:// jika di Render (HTTPS)
   var proto = window.location.protocol === "https:" ? "wss://" : "ws://";  
   var wsUrl = proto + window.location.host + "/ws";
   
   try {
     ws = new WebSocket(wsUrl);  
   } catch(e) {
     retryTimer = setTimeout(connect, 2000);
     return;
   }

   ws.onopen = function () {  
     online = true;  
     retryDelay = 1000;  
     loadConfig();  
     render(lastState);  
   };  
   ws.onmessage = function (ev) {  
     var m;  
     try { m = JSON.parse(ev.data); } catch (e) { return; }  
     if (m.type === "state") { lastState = m; render(m); }  
     else if (m.type === "error") { console.warn("server:", m.message); }  
   };  
   ws.onclose = function () {  
     online = false;  
     render(lastState);  
     retryTimer = setTimeout(connect, retryDelay);  
     retryDelay = Math.min(retryDelay * 2, 5000);  
   };  
   ws.onerror = function () { try { ws.close(); } catch (e) { /* ignore */ } };  
 }

 // ------------------------------------------------------------------ render
 function render(s) {  
   if (!online) {  
     setBadge("err", "OFFLINE");  
     if ($("stFps")) $("stFps").textContent = "FPS -";  
     if ($("stLat")) $("stLat").textContent = "LATENCY -";  
     setVideo(false);  
     showMessage("Server not reachable. Reconnecting...", false);  
     clearHands();  
     return;  
   }  
   if (!s) return;

   var camOn = s.camera_enabled;  
   if (wantCam !== null && s.camera_enabled === wantCam) wantCam = null;  
   if (wantCam !== null) camOn = wantCam;  
   var sw = $("camSwitch");  
   if (sw) {
     sw.setAttribute("aria-checked", String(camOn));  
     if ($("camSwitchText")) $("camSwitchText").textContent = camOn ? "ON" : "OFF";
   }

   var camErr = s.status === "error" && camOn;  
   if (!camOn) {  
     setBadge("off", "CAMERA OFF");  
     showMessage("Camera is off. Nothing is captured and no notes are played.", true, "Turn camera on");  
   } else if (camErr) {  
     setBadge("err", "CAMERA ERROR");  
     showMessage(s.message + " \u2014 check the camera permission, then try again.", true, "Try again");  
   } else if (s.status === "starting") {  
     setBadge("warn", "STARTING");  
     showMessage("", false);  
   } else {  
     setBadge("ok", "ONLINE");  
     showMessage("", false);  
   }  
   setVideo(camOn && !camErr);

   if ($("stFps")) $("stFps").textContent = camOn ? "FPS " + s.fps : "FPS -";  
   if ($("stLat")) $("stLat").textContent = camOn && s.latency_ms ? "LATENCY ~" + s.latency_ms + " ms" : "LATENCY -";

   var left = null, right = null;  
   if (s.hands) s.hands.forEach(function (h) { if (h.side === "left") left = h; else right = h; });  
   setBits(lhBits, left);  
   setBits(rhBits, right);  
   if ($("lhState")) $("lhState").textContent = left ? left.code : "";  
   if ($("rhState")) $("rhState").textContent = right ? right.code : "";

   var minor = !!s.minor_active;  
   setMinorFlag(minor);  
   setHud(s.note, s.switch_progress, minor);  
   highlightGuide(s.note);

   if (wantInst && s.instrument === wantInst) wantInst = null;  
   if (!wantInst) instrument = s.instrument;  
   refreshInstrument();

   if ($("debounce") && document.activeElement !== $("debounce")) $("debounce").value = s.debounce_ms;  
   if ($("resSelect") && document.activeElement !== $("resSelect")) $("resSelect").value = s.resolution;  
   drawOverlay(camOn && !camErr ? s.hands : []);  
 }

 function setMinorFlag(minor) {  
   var onLeft = MODIFIER_HAND === "left";  
   var text = minor ? MODIFIER_HAND.toUpperCase() + " THUMB ACTIVE: " + MELODY_HAND + "-hand note " + Math.abs(MINOR_SHIFT) + " semitone lower" : "";  
   [["flagLeft", onLeft], ["flagRight", !onLeft]].forEach(function (p) {  
     var f = $(p[0]);  
     if (f) {
       f.textContent = p[1] ? text : "";  
       f.classList.toggle("on", p[1] && minor);  
     }
   });  
 }

 function clearHands() {  
   setBits(lhBits, null);  
   setBits(rhBits, null);  
   if ($("lhState")) $("lhState").textContent = "";  
   if ($("rhState")) $("rhState").textContent = "";  
   setMinorFlag(false);  
   setHud(null, 0, false);  
   highlightGuide(null);  
   drawOverlay([]);  
 }

 function refreshInstrument() {  
   if ($("instPiano")) $("instPiano").setAttribute("aria-pressed", String(instrument === "piano"));  
   if ($("instViolin")) $("instViolin").setAttribute("aria-pressed", String(instrument === "violin"));  
   if ($("hudMode")) $("hudMode").textContent = (INSTR[instrument] || {}).label || "-";  
 }

 // ------------------------------------------------------------------ overlay skeleton
 var canvas = $("overlay"), ctx = canvas ? canvas.getContext("2d") : null;  
 function fitCanvas() {  
   if (!canvas) return;
   var dpr = window.devicePixelRatio || 1, r = canvas.getBoundingClientRect();  
   var w = Math.round(r.width * dpr), h = Math.round(r.height * dpr);  
   if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }  
 }  
 function videoRect() {  
   if (!canvas) return { x: 0, y: 0, w: 0, h: 0 };
   var cw = canvas.width, ch = canvas.height, img = $("cam");  
   var iw = (img && img.naturalWidth) || 4, ih = (img && img.naturalHeight) || 3, k = Math.min(cw / iw, ch / ih);  
   var w = iw * k, h = ih * k;  
   return { x: (cw - w) / 2, y: (ch - h) / 2, w: w, h: h };  
 }  
 function drawOverlay(hands) {  
   if (!ctx) return;
   fitCanvas();  
   ctx.clearRect(0, 0, canvas.width, canvas.height);  
   var r = videoRect(), dpr = window.devicePixelRatio || 1;  
   if (!hands) return;
   hands.forEach(function (h) {  
     if (!h.landmarks || !h.landmarks.length) return;  
     var pts = h.landmarks.map(function (p) { return [r.x + p[0] * r.w, r.y + p[1] * r.h]; });  
     ctx.strokeStyle = "rgba(255,255,255,0.85)";  
     ctx.lineWidth = 2 * dpr;  
     CONNECTIONS.forEach(function (c) {  
       ctx.beginPath(); ctx.moveTo(pts[c[0]][0], pts[c[0]][1]); ctx.lineTo(pts[c[1]][0], pts[c[1]][1]); ctx.stroke();  
     });  
     ctx.fillStyle = "#00ff66";  
     pts.forEach(function (p) { ctx.beginPath(); ctx.arc(p[0], p[1], 3 * dpr, 0, 6.2832); ctx.fill(); });  
     ctx.fillStyle = "#ffffff";  
     ctx.font = "bold " + (11 * dpr) + "px ui-monospace, Menlo, monospace";  
     ctx.fillText((h.side === "left" ? "L " : "R ") + h.code, pts[0][0] - 24 * dpr, Math.min(pts[0][1] + 20 * dpr, canvas.height - 6));  
   });  
 }  
 window.addEventListener("resize", function () { drawOverlay(lastState && online && lastState.camera_enabled ? lastState.hands : []); });

 // ------------------------------------------------------------------ kontrol
 function setCamera(on) {  
   wantCam = on;  
   clearTimeout(wantCamTimer);  
   wantCamTimer = setTimeout(function () { wantCam = null; }, 2500);  
   send({ type: "config", camera: on });  
   render(lastState);  
 }  
 function setInstrument(name) {  
   if (name === instrument) return;  
   instrument = name;  
   wantInst = name;  
   clearTimeout(wantInstTimer);  
   wantInstTimer = setTimeout(function () { wantInst = null; }, 2000);  
   send({ type: "config", instrument: name });  
   refreshInstrument();  
 }  
 function retryCamera() {  
   setCamera(false);  
   setTimeout(function () { setCamera(true); }, 500);  
 }

 if ($("camSwitch")) {
   $("camSwitch").addEventListener("click", function () {  
     setCamera($("camSwitch").getAttribute("aria-checked") !== "true");  
   });  
 }
 if ($("camOnBtn")) {
   $("camOnBtn").addEventListener("click", function () {  
     if (lastState && lastState.camera_enabled) retryCamera(); else setCamera(true);  
   });  
 }
 if ($("instPiano")) $("instPiano").addEventListener("click", function () { setInstrument("piano"); });  
 if ($("instViolin")) $("instViolin").addEventListener("click", function () { setInstrument("violin"); });  
 if ($("resSelect")) $("resSelect").addEventListener("change", function () { send({ type: "config", resolution: $("resSelect").value }); });  
 if ($("debounce")) {
   $("debounce").addEventListener("change", function () {  
     var v = Number($("debounce").value);  
     if (isFinite(v)) send({ type: "config", debounce_ms: Math.max(0, Math.min(1000, v)) });  
   });  
 }
 if ($("cam")) {
   $("cam").addEventListener("error", function () {  
     if (!videoOn) return;  
     videoOn = false;  
     setTimeout(function () { if (online && lastState) render(lastState); }, 1500);  
   });  
   $("cam").addEventListener("load", function () {  
     drawOverlay(lastState && online && lastState.camera_enabled ? lastState.hands : []);  
   });  
 }

 // shortcut: "?" opens / closes the guide  
 document.addEventListener("keydown", function (ev) {  
   var t = ev.target && ev.target.tagName;  
   if (t === "INPUT" || t === "SELECT" || t === "TEXTAREA" || ev.ctrlKey || ev.metaKey || ev.altKey) return;  
   if (ev.key === "?") {  
     ev.preventDefault();  
     var g = $("guide");  
     if (g) {
       g.open = !g.open;  
       if (g.open) g.scrollIntoView({ block: "nearest", behavior: "smooth" });  
     }
   }  
 });

 // ------------------------------------------------------------------ tema terang / gelap  
 var THEME_COLORS = { dark: "#0d0d0d", light: "#f3f3f5" };  
 function applyTheme(theme, persist) {  
   document.documentElement.setAttribute("data-theme", theme);  
   var dark = theme === "dark";  
   if ($("themeIcon")) $("themeIcon").textContent = dark ? "\u263e" : "\u2600";  
   if ($("themeText")) $("themeText").textContent = dark ? "Dark" : "Light";  
   if ($("themeToggle")) $("themeToggle").setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");  
   var meta = document.querySelector('meta[name="theme-color"]');  
   if (meta) meta.setAttribute("content", THEME_COLORS[theme]);  
   if (persist) { try { localStorage.setItem("musicozie-theme", theme); } catch (e) { /* ignore */ } }  
 }  
 if ($("themeToggle")) {
   $("themeToggle").addEventListener("click", function () {  
     applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light", true);  
   });  
 }

 applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark", false);  
 if (location.hash === "#guide" && $("guide")) $("guide").open = true;  
 buildGuide();  
 refreshInstrument();  
 render(null);  
 loadConfig();  
 connect();  
})();