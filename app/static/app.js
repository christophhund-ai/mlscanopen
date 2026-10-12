const state = {
  meta: null,
  connected: false,
  process: null,
  objects: [],
  values: new Map(),
  history: [],
};

const $ = (id) => document.getElementById(id);

function hexIndex(n) {
  return "0x" + Number(n).toString(16).toUpperCase().padStart(4, "0");
}

async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  return res.json();
}

function setActiveTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
}

function fillMeta(meta) {
  state.meta = meta;
  state.objects = meta.objects;
  const iface = $("iface");
  iface.innerHTML = meta.interfaces.map((i) => `<option value="${i.id}">${i.label}</option>`).join("");
  $("bitrate").innerHTML = meta.bitrates.map((b) => `<option value="${b}" ${b === 125000 ? "selected" : ""}>${b / 1000} kbit/s</option>`).join("");
  $("variant").innerHTML = Object.keys(meta.variants).map((v) => `<option>${v}</option>`).join("");
  $("variant").value = "MLSE-0300";
  renderOd();
}

function renderOd() {
  const q = ($("odFilter").value || "").toLowerCase();
  const body = $("odBody");
  body.innerHTML = "";
  for (const obj of state.objects) {
    const blob = `${obj.indexHex} ${obj.name} ${obj.description}`.toLowerCase();
    if (q && !blob.includes(q)) continue;
    const key = `${obj.index}.${obj.sub}`;
    const stored = state.values.get(key);
    const tr = document.createElement("tr");
    const writable = obj.access !== "RO";
    const choice = (obj.choices || []).map((c) => `<option value="${c.value}">${c.value}: ${c.label}</option>`).join("");
    tr.innerHTML = `
      <td>${obj.indexHex}</td>
      <td>${obj.subHex}</td>
      <td class="rw ${obj.access}">${obj.access}</td>
      <td>${obj.dataType}</td>
      <td>${obj.name}${obj.fw5 ? " <span class='hint'>FW5</span>" : ""}</td>
      <td class="val">${stored === undefined ? "—" : stored}</td>
      <td>
        ${writable ? `<div class="od-write">
          ${choice ? `<select data-choices>${choice}</select>` : `<input data-val placeholder="Wert">`}
          <button data-write>Schreiben</button>
        </div>` : `<button data-read>Lesen</button>`}
      </td>
      <td>${obj.description}${obj.unit ? " [" + obj.unit + "]" : ""}</td>`;
    const read = async () => {
      const r = await api("/api/sdo/read", { index: obj.index, sub: obj.sub });
      if (!r.ok) { tr.querySelector(".val").textContent = r.error || r.abortHex || "Fehler"; return; }
      const v = r.value !== undefined ? r.value : r.raw;
      state.values.set(key, v);
      tr.querySelector(".val").textContent = v;
    };
    tr.querySelector("[data-read]")?.addEventListener("click", read);
    tr.querySelector("[data-write]")?.addEventListener("click", async () => {
      const input = tr.querySelector("[data-val], [data-choices]");
      const r = await api("/api/sdo/write", { index: obj.index, sub: obj.sub, value: input.value });
      tr.querySelector(".val").textContent = r.ok ? input.value : (r.error || r.abortHex || "Fehler");
    });
    if (obj.access === "RO") {
      tr.querySelector("td.val").style.cursor = "pointer";
      tr.querySelector("td.val").title = "Klicken zum Lesen";
      tr.querySelector("td.val").addEventListener("click", read);
    }
    body.appendChild(tr);
  }
}

async function connect() {
  const body = {
    interface: $("iface").value,
    channel: $("channel").value,
    bitrate: Number($("bitrate").value),
    nodeId: Number($("nodeId").value),
    variant: $("variant").value,
  };
  const r = await api("/api/connect", body);
  if (!r.ok && r.error) { alert(r.error); return; }
  setConnected(true, r.mode);
  if (body.interface !== "simulator") {
    await api("/api/nmt", { command: 1 });
  }
}

async function disconnect() {
  await api("/api/disconnect", {});
  setConnected(false, "idle");
}

function setConnected(on, mode) {
  state.connected = on;
  $("connBadge").textContent = on ? (mode === "simulator" ? "Simulator" : "CAN verbunden") : "offline";
  $("connBadge").classList.toggle("on", on);
  $("connBadge").classList.toggle("off", !on);
  $("simCard").style.opacity = mode === "simulator" || !on ? "1" : "0.45";
}

function applyProcess(p) {
  if (!p) return;
  state.process = p;
  state.history.push({ t: performance.now(), lcp1: p.lcp1, lcp2: p.lcp2, lcp3: p.lcp3, nlcp: p.nlcp });
  if (state.history.length > 240) state.history.shift();
  $("nmtBadge").textContent = "NMT " + (p.nmt || "—");
  $("rangeHint").textContent = `${p.variant || ""} · Messbereich ±${(p.rangeMm || 0) / 2} mm · ${p.elements || "?"} Hall`;
  const st = p.status || {};
  const nl = p.nlcp || {};
  $("ledY").className = "led" + (st.lineGood ? " on-y" : "");
  $("ledR").className = "led" + (st.eventFlag ? " on-r" : "");
  const pos = Number(p.lcp2 || 0);
  $("ledG").className = "led" + (nl.lcp2 && pos <= 0 ? " on-g" : "");
  $("ledB").className = "led" + (nl.lcp2 && pos >= 0 ? " on-b" : "");
  if (!nl.lcp2 || (nl.lcp1 || nl.lcp3)) {
    $("ledG").className = "led";
    $("ledB").className = "led";
  }
  const cards = $("trackCards");
  cards.innerHTML = "";
  const tracks = p.tracks || [];
  if (!tracks.length) {
    cards.innerHTML = "<div class='hint'>Keine Spur erkannt</div>";
  } else {
    for (const t of tracks) {
      const el = document.createElement("div");
      el.className = "track-pill";
      const w = t.widthMm != null ? ` · ${t.widthMm} mm breit` : "";
      el.innerHTML = `<strong>LCP${t.id}</strong><span>${t.positionMm} mm${w}</span>`;
      cards.appendChild(el);
    }
  }
  if (nl.markerIntro || (p.marker && p.marker.visible)) {
    const el = document.createElement("div");
    el.className = "track-pill marker";
    el.innerHTML = `<strong>Marker</strong><span>Code ${nl.markerCode || p.marker?.code || "—"} · Offset ${p.marker?.offsetMm ?? "?"} mm</span>`;
    cards.appendChild(el);
  }
  $("nlcpMeta").textContent = nl.trackLabel || "";
  $("statusDl").innerHTML = [
    ["Line good", st.lineGood ? "ja" : "nein"],
    ["Track Level", `${st.trackLevel ?? "—"} (${st.trackQuality || "—"})`],
    ["Polarität", st.polarity || "—"],
    ["Sensor flipped", st.sensorFlipped ? "ja" : "nein"],
    ["Code wird gelesen", st.readingCode ? "ja" : "nein"],
    ["Event-Flag", st.eventFlag ? "aktiv" : "nein"],
    ["Field Level", p.fieldLevel ?? "—"],
    ["#LCP", nl.trackCode ?? "—"],
  ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  const imu = p.imu || {};
  $("imuDl").innerHTML = [
    ["Roll", imu.rollRad != null ? (imu.rollRad * 180 / Math.PI).toFixed(2) + " °" : "—"],
    ["Pitch", imu.pitchRad != null ? (imu.pitchRad * 180 / Math.PI).toFixed(2) + " °" : "—"],
    ["Yaw", imu.yawRad != null ? (imu.yawRad * 180 / Math.PI).toFixed(2) + " °" : "—"],
    ["Zeitstempel", imu.timestampMs != null ? imu.timestampMs + " ms" : "—"],
  ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  renderPdoTable(p);
  drawAll(p);
}

function renderPdoTable(p) {
  const rows = [
    ["LCP1", p.lcp1, "Spurmitte 1 [mm]"],
    ["LCP2", p.lcp2, "Spurmitte 2 [mm] (bei einer Spur hier)"],
    ["LCP3", p.lcp3, "Spurmitte 3 [mm]"],
    ["Breite 1/2/3", [p.width1, p.width2, p.width3].join(" / "), "mm"],
    ["Line Level 1/2/3", [p.level1, p.level2, p.level3].join(" / "), "LSB ≈ 0,048 mT"],
    ["#LCP", p.nlcp?.trackLabel, "Spurkombination"],
    ["Marker-Code", p.nlcp?.markerCode, "Bit0 = Start, Bit1–4 = Code"],
    ["Status", p.status?.raw, JSON.stringify(p.status || {})],
    ["TPDO1 raw", (p.raw || []).map((b) => b.toString(16).padStart(2, "0")).join(" "), "Little Endian"],
    ["Combi-Modus", p.combi ? "ja" : "nein", "Index 0x2006:1"],
  ];
  $("pdoBody").innerHTML = rows.map(([a, b, c]) => `<tr><td>${a}</td><td>${b ?? "—"}</td><td>${c}</td></tr>`).join("");
}

function mmToX(mm, w, range) {
  const half = range / 2;
  return ((Number(mm) + half) / Math.max(range, 1)) * w;
}

function drawScene(p) {
  const c = $("scene");
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height;
  ctx.clearRect(0, 0, w, h);
  const range = p.rangeMm || 300;
  const pad = 36;
  const usable = w - pad * 2;
  const y = h * 0.55;
  ctx.fillStyle = "#0e141b";
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "#2c3644";
  ctx.beginPath();
  ctx.moveTo(pad, y);
  ctx.lineTo(w - pad, y);
  ctx.stroke();
  ctx.fillStyle = "#93a0b5";
  ctx.font = "12px Segoe UI";
  for (let mm = -range / 2; mm <= range / 2; mm += range / 8) {
    const x = pad + mmToX(mm, usable, range);
    ctx.fillText(String(Math.round(mm)), x - 10, y + 28);
    ctx.fillStyle = "#2c3644";
    ctx.fillRect(x, y - 6, 1, 12);
    ctx.fillStyle = "#93a0b5";
  }
  ctx.fillStyle = "#f5c400";
  const z = pad + mmToX(0, usable, range);
  ctx.fillRect(z, y - 18, 2, 36);
  ctx.fillText("0", z - 4, y - 24);
  ctx.fillStyle = "#3d4a5c";
  ctx.fillRect(pad, 28, usable, 36);
  ctx.fillStyle = "#93a0b5";
  ctx.fillText("Sensor " + (p.variant || ""), pad, 22);
  ctx.fillText("Kabelabgang −", pad, h - 12);
  ctx.fillText("+", w - pad - 8, h - 12);
  const tracks = p.tracks || [];
  tracks.forEach((t, i) => {
    const width = Math.max(12, t.widthMm || 25);
    const x = pad + mmToX(t.positionMm, usable, range);
    const bw = (width / range) * usable;
    ctx.fillStyle = "rgba(245,196,0,0.85)";
    ctx.fillRect(x - bw / 2, y - 48, bw, 18);
    ctx.fillStyle = "#111";
    ctx.fillText("LCP" + t.id, x - 16, y - 52);
    ctx.strokeStyle = "#f5c400";
    ctx.beginPath();
    ctx.moveTo(x, 70);
    ctx.lineTo(x, y + 8);
    ctx.stroke();
  });
  if (p.marker && p.marker.visible && tracks.length) {
    const main = tracks.find((t) => t.id === 2) || tracks[0];
    const mx = pad + mmToX(main.positionMm + (p.marker.offsetMm || 30), usable, range);
    ctx.fillStyle = "#ff6b4a";
    ctx.fillRect(mx - 8, y - 72, 16, 14);
    ctx.fillText("M" + (p.nlcp?.markerCode || ""), mx - 10, y - 78);
  }
}

function drawHall(p) {
  const c = $("hall");
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#0e141b";
  ctx.fillRect(0, 0, w, h);
  const hall = p.hall || [];
  const pos = p.positionsMm || [];
  if (!hall.length) {
    ctx.fillStyle = "#93a0b5";
    ctx.fillText("Keine Hall-Daten", 20, h / 2);
    return;
  }
  const maxAbs = Math.max(400, ...hall.map((v) => Math.abs(v)));
  const range = p.rangeMm || 300;
  const pad = 36;
  const usable = w - pad * 2;
  const mid = h / 2;
  ctx.strokeStyle = "#2c3644";
  ctx.beginPath();
  ctx.moveTo(pad, mid);
  ctx.lineTo(w - pad, mid);
  ctx.stroke();
  ctx.strokeStyle = "#f5c400";
  ctx.beginPath();
  hall.forEach((v, i) => {
    const mm = pos[i] ?? (-range / 2 + (i / Math.max(hall.length - 1, 1)) * range);
    const x = pad + mmToX(mm, usable, range);
    const y = mid - (v / maxAbs) * (h * 0.42);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  hall.forEach((v, i) => {
    const mm = pos[i] ?? (-range / 2 + (i / Math.max(hall.length - 1, 1)) * range);
    const x = pad + mmToX(mm, usable, range);
    ctx.fillStyle = v > 0 ? "#4aa3ff" : "#ff6b4a";
    ctx.globalAlpha = Math.min(1, Math.abs(v) / maxAbs);
    ctx.fillRect(x - 1, h - 18, 3, 10);
    ctx.globalAlpha = 1;
  });
}

function drawTrend() {
  const c = $("trend");
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#0e141b";
  ctx.fillRect(0, 0, w, h);
  const hist = state.history;
  if (hist.length < 2) return;
  const range = state.process?.rangeMm || 300;
  const colors = { lcp1: "#4aa3ff", lcp2: "#f5c400", lcp3: "#3dcc8a" };
  Object.keys(colors).forEach((key) => {
    ctx.strokeStyle = colors[key];
    ctx.beginPath();
    hist.forEach((s, i) => {
      const x = (i / (hist.length - 1)) * w;
      const y = h / 2 - (Number(s[key] || 0) / range) * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
}

function drawAll(p) {
  drawScene(p);
  drawHall(p);
  drawTrend();
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "process") applyProcess(msg.process);
    if (msg.type === "connection") setConnected(!!msg.connected, msg.mode);
  };
  ws.onclose = () => setTimeout(connectWs, 1500);
}

async function init() {
  const meta = await api("/api/meta");
  fillMeta(meta);
  const st = await api("/api/status");
  setConnected(st.connected, st.mode);
  if (st.process) applyProcess(st.process);
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => setActiveTab(t.dataset.tab)));
  $("btnConnect").addEventListener("click", connect);
  $("btnDisconnect").addEventListener("click", disconnect);
  $("odFilter").addEventListener("input", renderOd);
  $("btnReadVisible").addEventListener("click", async () => {
    const q = ($("odFilter").value || "").toLowerCase();
    const list = state.objects.filter((o) => `${o.indexHex} ${o.name} ${o.description}`.toLowerCase().includes(q)).slice(0, 40);
    const r = await api("/api/sdo/read-many", list.map((o) => ({ index: o.index, sub: o.sub })));
    for (const item of r.results || []) {
      if (item.ok && item.value !== undefined) state.values.set(`${item.index}.${item.sub}`, item.value);
    }
    renderOd();
  });
  $("btnSave").addEventListener("click", () => api("/api/sdo/write", { index: 0x1010, sub: 1, value: 0x65766173 }));
  $("btnDefaults").addEventListener("click", () => api("/api/sdo/write", { index: 0x202A, sub: 0, value: 1 }));
  $("btnCalib").addEventListener("click", () => api("/api/sdo/write", { index: 0x202B, sub: 0, value: 1 }));
  $("btnZero").addEventListener("click", () => api("/api/sdo/write", { index: 0x202C, sub: 0, value: 1 }));
  $("btnYaw").addEventListener("click", () => api("/api/sdo/write", { index: 0x2032, sub: 1, value: 1 }));
  $("btnEvent").addEventListener("click", () => api("/api/sdo/write", { index: 0x2080, sub: 1, value: 1 }));
  document.querySelectorAll("[data-nmt]").forEach((b) => b.addEventListener("click", () => api("/api/nmt", { command: Number(b.dataset.nmt) })));
  $("enableTpdo2").addEventListener("click", () => api("/api/tpdo", { pdo: 2, enabled: true, eventTimerMs: 20 }));
  $("enableTpdo3").addEventListener("click", () => api("/api/tpdo", { pdo: 3, enabled: true, eventTimerMs: 20 }));
  $("enableTpdo4").addEventListener("click", () => api("/api/tpdo", { pdo: 4, enabled: true, eventTimerMs: 20 }));
  const pushSim = () => api("/api/sim", {
    variant: $("variant").value,
    autoMove: $("simAuto").checked,
    trackCount: Number($("simTracks").value),
    useMarkers: $("simMarker").checked,
    marker: { visible: $("simMarker").checked, offsetMm: Number($("simMarkerOff").value) },
  });
  $("simTracks").addEventListener("input", () => { $("simTrackLabel").textContent = $("simTracks").value + " Spuren"; pushSim(); });
  $("simAuto").addEventListener("change", pushSim);
  $("simMarker").addEventListener("change", pushSim);
  $("simMarkerOff").addEventListener("change", pushSim);
  $("variant").addEventListener("change", pushSim);
  $("iface").addEventListener("change", async () => {
    if ($("iface").value === "slcan") {
      const ports = await api("/api/ports");
      if (ports.ports?.[0]) $("channel").placeholder = ports.ports.map((p) => p.device).join(", ");
    }
  });
  setInterval(async () => {
    if (state.connected && $("pollHall").checked && $("iface").value !== "simulator") {
      const h = await api("/api/hall");
      if (h.ok && state.process) {
        state.process.hall = h.hall;
        state.process.positionsMm = h.positionsMm;
        drawHall(state.process);
      }
    }
  }, 250);
  connectWs();
}

init().catch((err) => console.error(err));
