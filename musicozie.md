Berikut adalah penyatuan \*\*Product Requirement Document (PRD)\*\* lengkap untuk proyek \*\*Musicozie\*\* yang mencakup arsitektur sistem, skema gestur biner ergonomis, manajemen latensi rendah, serta kode interface dashboard web (HTML \+ CSS \+ JS) dalam satu dokumen utuh.

\---

\# 🎼 Musicozie — Unified Product Requirement Document (PRD)

\#\# 1\. Executive Summary & Vision

\* \*\*Project Name\*\*: Musicozie (Gesture-Driven Neural Synthesizer)  
\* \*\*Concept\*\*: Instrumen virtual \*real-time\* berbasis \*computer vision\* yang memungkinkan pengguna memainkan Piano dan Biola/Synth menggunakan gestur biner jari tangan (Buka \`1\` / Tutup \`0\`) melalui webcam standar.  
\* \*\*Core Value\*\*: Mengeliminasi ketergantungan area layar virtual atau estimasi kedalaman ($Z$\-axis) yang sering meleset dengan menggantinya menggunakan kalkulasi posisi relatif antar-sendi jari yang ramah anatomi tangan.

\---

\#\# 2\. Tech Stack & System Architecture

\| Layer \| Teknologi / Library \| Fungsi Utama \|  
\| \--- \| \--- \| \--- \|  
\| \*\*Language\*\* \| Python 3.10+ \| Bahasa pemrograman utama backend \|  
\| \*\*Vision Engine\*\* \| OpenCV (\`cv2\`), MediaPipe Hands (\`mediapipe\`) \| Tangkap frame & deteksi 21 koordinat \*landmark\* tangan \|  
\| \*\*Audio Engine\*\* \| \`pyfluidsynth\` \+ SoundFont (\`GeneralMidi.sf2\`) \| Synthesizer MIDI \*real-time\* untuk suara Piano & Biola \|  
\| \*\*Concurrency\*\* \| \`threading\` \+ \`queue.Queue\` \| Pemisahan thread \*Vision\* dan \*Audio\* (Anti-delay) \|  
\| \*\*Dashboard UI\*\* \| HTML5, CSS3, JavaScript (Web Audio API, Canvas) \| Interface antarmuka lokal dengan style monokrom \*clean\* \|

\---

\#\# 3\. Gestur Biner & Pemetaan Musik Ergonomis

\#\#\# 3.1 Logika Kalkulasi Jari Terbuka/Tutup

Status jari (Buka \= \`1\`, Tutup \= \`0\`) dihitung berdasarkan perbandingan jarak Euclidean dari \*\*Wrist (Landmark 0)\*\* ke \*\*Fingertip\*\* dan \*\*MCP Joint (Pangkal Jari)\*\*:

\`\`\`python  
def is\_finger\_open(hand\_landmarks, tip\_id, mcp\_id):  
    wrist \= hand\_landmarks.landmark\[0\]  
    tip \= hand\_landmarks.landmark\[tip\_id\]  
    mcp \= hand\_landmarks.landmark\[mcp\_id\]  
      
    dist\_tip\_to\_wrist \= ((tip.x \- wrist.x)\*\*2 \+ (tip.y \- wrist.y)\*\*2)\*\*0.5  
    dist\_mcp\_to\_wrist \= ((mcp.x \- wrist.x)\*\*2 \+ (mcp.y \- wrist.y)\*\*2)\*\*0.5  
      
    return dist\_tip\_to\_wrist \> dist\_mcp\_to\_wrist

\`\`\`

\---

\#\#\# 3.2 Tangan Kiri: Biola / Synth Auto-Chord Matrix

\#\#\#\# A. Root Note Selection (Kombinasi Telunjuk & Tengah)

\* \*\*C\*\*: Telunjuk BUKA (\`1000\`)  
\* \*\*D\*\*: Jari Tengah BUKA (\`0100\`)  
\* \*\*E\*\*: Telunjuk \+ Tengah BUKA (\`1100\`)  
\* \*\*F\*\*: Kepalan Tangan / Semua Tutup (\`0000\`)  
\* \*\*G\*\*: Telapak Terbuka Santai (\`1110\`)  
\* \*\*A\*\*: Telunjuk \+ Kelingking BUKA (\`1001\`)  
\* \*\*B\*\*: Pinch (Ujung Ibu Jari & Telunjuk Menempel)

\#\#\#\# B. Chord Quality Modifiers (Ibu Jari & Kelingking)

\* \*\*Major Chord\*\* \*(Default)\*: Tanpa modifier.  
\* \*\*Minor Chord\*\*: Ditekuknya Ibu Jari ke dalam.  
\* \*\*Diminished (dim)\*\*: Kelingking dibuka lebar.  
\* \*\*Diminished 7th (dim7)\*\*: Ibu Jari \+ Kelingking dibuka bersamaan.

\---

\#\#\# 3.3 Tangan Kanan: Solo Piano Melody (Pinch & Tap)

\* \*\*C4\*\*: Telunjuk BUKA  
\* \*\*D4\*\*: Jari Tengah BUKA  
\* \*\*E4\*\*: Telunjuk \+ Tengah BUKA  
\* \*\*F4\*\*: Pinch (Ibu Jari \+ Telunjuk)  
\* \*\*G4\*\*: Pinch (Ibu Jari \+ Tengah)  
\* \*\*A4\*\*: Pinch (Ibu Jari \+ Manis)  
\* \*\*B4\*\*: Kelingking BUKA

\---

\#\# 4\. Persyaratan Non-Fungsional & Manajemen Latensi

1\. \*\*Multi-threading Architecture\*\*:  
\* \*\*Thread 1 (Vision)\*\*: Mengambil frame webcam pada resolusi $640\times 480$ dengan MediaPipe \`model\_complexity=0\`.  
\* \*\*Thread 2 (Logic)\*\*: Kalkulasi status biner jari dan \*debouncing\* ($100ms$ cooldown).  
\* \*\*Thread 3 (Audio)\*\*: Pemicu nada \`pyfluidsynth\` tanpa memblokir pergerakan video.

2\. \*\*Buffer Management\*\*: Set ukuran buffer audio FluidSynth sebesar \*\*512 bytes\*\* untuk mempertahankan total latensi $<30ms$.

\---

\#\# 5\. Struktur Folder Proyek

\`\`\`text  
musicozie/  
├── main.py               \# Entry point aplikasi & multi-threading manager  
├── config.py             \# Konstanta global, MIDI mappings, & threshold  
├── vision\_processor.py   \# Pipeline MediaPipe & logika is\_finger\_open()  
├── audio\_engine.py       \# Wrapper FluidSynth SoundFont  
├── gesture\_matrix.py     \# Penerjemah kombinasi biner ke Chord/MIDI Note  
├── dashboard/  
│   └── index.html        \# Web Dashboard UI & Web Audio Simulator  
└── soundfont/  
    └── GeneralMidi.sf2   \# SoundFont instrument bank

\`\`\`

\---

\#\# 6\. Dashboard Web Interface (\`dashboard/index.html\`)

Berikut adalah file tunggal dashboard web lokal dengan style monokrom khas Musicozie yang siap digunakan:

\`\`\`html  
\<\!DOCTYPE html\>  
\<html lang="id"\>  
\<head\>  
  \<meta charset="UTF-8"\>  
  \<meta name="viewport" content="width=device-width, initial-scale=1.0"\>  
  \<title\>Musicozie \- Dashboard Control\</title\>  
  \<style\>  
    :root {  
      \--bg-color: \#0d0d0d;  
      \--card-bg: \#141414;  
      \--border-color: \#262626;  
      \--text-main: \#ffffff;  
      \--text-muted: \#8c8c8c;  
      \--active-green: \#00ff66;  
      \--font-family: \-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;  
    }  
    \* { box-sizing: border-box; margin: 0; padding: 0; }  
    body { background-color: var(--bg-color); color: var(--text-main); font-family: var(--font-family); padding: 24px; }  
    header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid var(--border-color); margin-bottom: 24px; }  
    .brand-title { font-size: 20px; font-weight: 800; text-transform: uppercase; letter-spacing: \-0.5px; }  
    .brand-title span { color: var(--text-muted); font-weight: 400; font-size: 13px; margin-left: 8px; }  
    .status-badge { display: inline-flex; align-items: center; gap: 8px; background: \#1f1f1f; border: 1px solid var(--border-color); padding: 6px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; }  
    .dot { width: 8px; height: 8px; background-color: var(--active-green); border-radius: 50%; box-shadow: 0 0 8px var(--active-green); }  
    .dashboard-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 24px; }  
    @media (max-width: 992px) { .dashboard-grid { grid-template-columns: 1fr; } }  
    .card { background-color: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 20px; }  
    .card-title { font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 16px; }  
    .canvas-container { width: 100%; background: \#000000; border: 1px solid var(--border-color); border-radius: 6px; overflow: hidden; }  
    canvas { display: block; width: 100%; height: 260px; }  
    .hands-control { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }  
    .hand-box { background: \#1a1a1a; border: 1px solid var(--border-color); padding: 12px; border-radius: 6px; }  
    .hand-box-header { font-size: 11px; font-weight: 700; color: var(--text-muted); margin-bottom: 8px; }  
    .finger-btn-group { display: flex; gap: 6px; }  
    .finger-btn { flex: 1; background: \#0d0d0d; border: 1px solid var(--border-color); color: var(--text-main); padding: 8px 0; font-size: 11px; font-weight: 600; border-radius: 4px; cursor: pointer; text-align: center; }  
    .finger-btn.active { background: var(--text-main); color: \#000000; border-color: var(--text-main); }  
    .config-group { margin-bottom: 16px; }  
    .config-label { display: block; font-size: 12px; color: var(--text-muted); margin-bottom: 6px; }  
    select, input { width: 100%; background: \#0d0d0d; border: 1px solid var(--border-color); color: var(--text-main); padding: 8px 12px; border-radius: 4px; font-size: 13px; outline: none; }  
    textarea { width: 100%; height: 160px; background: \#080808; border: 1px solid var(--border-color); color: \#00ff66; font-family: monospace; font-size: 11px; padding: 12px; border-radius: 4px; resize: none; outline: none; }  
    .btn-copy { margin-top: 8px; width: 100%; background: var(--text-main); color: \#000000; border: none; padding: 10px; font-weight: 700; font-size: 12px; text-transform: uppercase; border-radius: 4px; cursor: pointer; }  
  \</style\>  
\</head\>  
\<body\>  
  \<header\>  
    \<div class="brand-title"\>Musicozie \<span\>/ Gesture-Driven Neural Synthesizer\</span\>\</div\>  
    \<div class="status-badge"\>\<div class="dot"\>\</div\>\<span\>SYSTEM READY\</span\>\</div\>  
  \</header\>

  \<div class="dashboard-grid"\>  
    \<div class="card"\>  
      \<div class="card-title"\>Real-Time Gesture Simulator (Binary Open/Closed)\</div\>  
      \<div class="canvas-container"\>\<canvas id="visualizerCanvas"\>\</canvas\>\</div\>  
      \<div class="hands-control"\>  
        \<div class="hand-box"\>  
          \<div class="hand-box-header"\>LEFT HAND: VIOLIN CHORD\</div\>  
          \<div class="finger-btn-group"\>  
            \<button class="finger-btn" id="lh-thumb" onclick="toggleFinger('lh', 'thumb')"\>THUMB\</button\>  
            \<button class="finger-btn" id="lh-index" onclick="toggleFinger('lh', 'index')"\>INDEX\</button\>  
            \<button class="finger-btn" id="lh-middle" onclick="toggleFinger('lh', 'middle')"\>MID\</button\>  
            \<button class="finger-btn" id="lh-pinky" onclick="toggleFinger('lh', 'pinky')"\>PINKY\</button\>  
          \</div\>  
        \</div\>  
        \<div class="hand-box"\>  
          \<div class="hand-box-header"\>RIGHT HAND: PIANO MELODY\</div\>  
          \<div class="finger-btn-group"\>  
            \<button class="finger-btn" id="rh-index" onclick="triggerPianoNote(60, 'rh-index')"\>C4\</button\>  
            \<button class="finger-btn" id="rh-middle" onclick="triggerPianoNote(62, 'rh-middle')"\>D4\</button\>  
            \<button class="finger-btn" id="rh-ring" onclick="triggerPianoNote(64, 'rh-ring')"\>E4\</button\>  
            \<button class="finger-btn" id="rh-pinky" onclick="triggerPianoNote(67, 'rh-pinky')"\>G4\</button\>  
          \</div\>  
        \</div\>  
      \</div\>  
    \</div\>

    \<div\>  
      \<div class="card" style="margin-bottom: 24px;"\>  
        \<div class="card-title"\>Engine Configuration\</div\>  
        \<div class="config-group"\>  
          \<label class="config-label"\>Camera Resolution\</label\>  
          \<select id="resSelect"\>  
            \<option value="640x480"\>640 x 480 (Recommended)\</option\>  
            \<option value="320x240"\>320 x 240 (Ultra Low Latency)\</option\>  
          \</select\>  
        \</div\>  
        \<div class="config-group"\>  
          \<label class="config-label"\>Debounce Delay (ms)\</label\>  
          \<input type="number" value="100" min="50" max="300"\>  
        \</div\>  
      \</div\>

      \<div class="card"\>  
        \<div class="card-title"\>Master Agent Prompt Export\</div\>  
        \<textarea readonly id="promptText"\>\# MUSICOZIE AI AGENT MASTER PROMPT  
Build a low-latency Python AI virtual instrument using OpenCV, MediaPipe Hands (complexity=0), and pyfluidsynth (GeneralMidi.sf2).

Left Hand: Violin Auto-Chord Matrix  
\- Index (1000): C \| Middle (0100): D \| Index+Middle (1100): E  
\- Closed Fist (0000): F \| Open Palm (1110): G \| Index+Pinky (1001): A  
\- Thumb Curled \= Minor \| Pinky Wide \= Diminished (dim) \| Thumb+Pinky \= Dim7

Right Hand: Solo Piano Melody (Pinch/Tap triggers)  
\- Index: C4 \| Middle: D4 \| Index+Middle: E4 \| Pinky: G4

Run Vision, Logic, and Audio on decoupled threads for ultra-low latency.\</textarea\>  
        \<button class="btn-copy" onclick="copyPrompt()"\>Copy Master Prompt\</button\>  
      \</div\>  
    \</div\>  
  \</div\>

  \<script\>  
    const audioCtx \= new (window.AudioContext \|\| window.webkitAudioContext)();  
    const fingerState \= { lh: { thumb: false, index: false, middle: false, pinky: false } };

    function toggleFinger(hand, finger) {  
      fingerState\[hand\]\[finger\] \= \!fingerState\[hand\]\[finger\];  
      document.getElementById(\`$hand-${finger}\`).classList.toggle('active');  
      evalChord();  
      drawVisualizer();  
    }

    function evalChord() {  
      const lh \= fingerState.lh;  
      let root \= "NO CHORD", quality \= "Major", freq \= 261.63;  
      if (lh.index && \!lh.middle) { root \= "C"; freq \= 261.63; }  
      else if (\!lh.index && lh.middle) { root \= "D"; freq \= 293.66; }  
      else if (lh.index && lh.middle) { root \= "E"; freq \= 329.63; }  
      else if (\!lh.index && \!lh.middle && \!lh.pinky) { root \= "F"; freq \= 349.23; }  
      if (lh.thumb) quality \= "Minor";  
      if (lh.pinky) quality \= "Diminished";  
      if (root \!== "NO CHORD") playSynthTone(freq, quality);  
    }

    function playSynthTone(freq, quality) {  
      const osc \= audioCtx.createOscillator();  
      const gain \= audioCtx.createGain();  
      osc.type \= quality \=== "Diminished" ? 'sawtooth' : 'sine';  
      osc.frequency.setValueAtTime(freq, audioCtx.currentTime);  
      gain.gain.setValueAtTime(0.1, audioCtx.currentTime);  
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime \+ 0.8);  
      osc.connect(gain); gain.connect(audioCtx.destination);  
      osc.start(); osc.stop(audioCtx.currentTime \+ 0.8);  
    }

    function triggerPianoNote(midiNote, btnId) {  
      const btn \= document.getElementById(btnId);  
      btn.classList.add('active');  
      setTimeout(() \=\> btn.classList.remove('active'), 200);  
      const freq \= 440 \* Math.pow(2, (midiNote \- 69\) / 12);  
      playSynthTone(freq, "Major");  
    }

    const canvas \= document.getElementById('visualizerCanvas');  
    const ctx \= canvas.getContext('2d');  
    function drawVisualizer() {  
      canvas.width \= canvas.clientWidth; canvas.height \= canvas.clientHeight;  
      ctx.fillStyle \= "\#0d0d0d"; ctx.fillRect(0, 0, canvas.width, canvas.height);  
      ctx.fillStyle \= "\#ffffff"; ctx.font \= "bold 14px sans-serif";  
      ctx.fillText("MUSICOZIE CANVAS SIMULATOR", 20, 35);  
      ctx.fillStyle \= "\#8c8c8c"; ctx.font \= "12px monospace";  
      ctx.fillText(\`LH STATE: T:$fingerState.lh.thumb?1:0I:${fingerState.lh.index?1:0} M:$fingerState.lh.middle?1:0P:${fingerState.lh.pinky?1:0}\`, 20, 60);  
    }  
    function copyPrompt() {  
      const copyText \= document.getElementById("promptText");  
      copyText.select(); navigator.clipboard.writeText(copyText.value);  
      alert("Master Prompt berhasil disalin\!");  
    }  
    drawVisualizer();  
  \</script\>  
\</body\>  
\</html\>

\`\`\`  
