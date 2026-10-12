const $ = (id) => document.getElementById(id);
let meta = null;
let objects = [];
let ws = null;
let last = null;
const history = [];
const TRACK_COLORS = ["#0059ff", "#a4e3b8", "#ffeb00"];
const C = {
  blue: "#0059ff",
  dark: "#000a37",
  green: "#a4e3b8",
  yellow: "#ffeb00",
  grey: "#e5e2dd",
  muted: "#4a5168",
  white: "#ffffff",
};

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.style.display = "block";
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.style.display = "none"; }, 4200);
}

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, opt);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function hexIdx(n) { return "0x" + Number(n).toString(16).toUpperCase().padStart(4, "0"); }
function hexSub(n) { return "0x" + Number(n).toString(16).toUpperCase().padStart(2, "0"); }

async function init() {
  meta = await api("/api/meta");
  objects = meta.objects;
  for (const [k, v] of Object.entries(meta.variants)) {
    const o = document.createElement("option");
    o.value = k;
    o.textContent = `${k} (${v.range_mm} mm, ${v.elements} Hall)`;
    $("variant").appendChild(o);
  }
  $("variant").value = "MLSE-0400";
  meta.interfaces.forEach((n) => {
    const o = document.createElement("option");
    o.value = n; o.textContent = n;
    $("iface").appendChild(o);
  });
  meta.bitrates.forEach((n) => {
    const o = document.createElement("option");
    o.value = n; o.textContent = (n / 1000) + " kbit/s";
    $("bitrate").appendChild(o);
  });
  $("bitrate").value = "125000";
  const groups = [...new Set(objects.map((o) => o.group))];
  groups.forEach((g) => {
    const o = document.createElement("option");
    o.value = g; o.textContent = g;
    $("objGroup").appendChild(o);
  });
  renderObjectTables();
  $("mode").addEventListener("change", () => {
    $("hwFields").classList.toggle("hidden", $("mode").value !== "hardware");
  });
  $("btnConnect").onclick = connect;
  $("btnDisconnect").onclick = disconnect;
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll(".tabs button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      document.querySelectorAll(".tab").forEach((t) => t.classList.add("hidden"));
      $("tab-" + b.dataset.tab).classList.remove("hidden");
      resizeCanvases();
    };
  });
  document.querySelectorAll("[data-scen]").forEach((b) => {
    b.onclick = async () => {
      try { await api("/api/sim/scenario", { name: b.dataset.scen }); }
      catch (e) { toast(e.message); }
    };
  });
  document.querySelectorAll("[data-nmt]").forEach((b) => {
    b.onclick = async () => {
      try { await api("/api/nmt", { command: Number(b.dataset.nmt) }); toast("NMT gesendet"); }
      catch (e) { toast(e.message); }
    };
  });
  document.querySelectorAll(".quick [data-act]").forEach((b) => {
    b.onclick = () => quickAct(b.dataset.act);
  });
  $("btnRefreshProc").onclick = () => refreshGroup("Prozessdaten");
  $("btnReadAll").onclick = () => refreshGroup($("objGroup").value || null);
  $("objFilter").oninput = renderObjectTables;
  $("objGroup").onchange = renderObjectTables;
  $("btnReadPdo").onclick = readPdoParams;
  $("btnHall").onclick = async () => {
    try { await api("/api/hall", {}); toast("Hall-Rohdaten gelesen"); }
    catch (e) { toast(e.message); }
  };
  document.querySelectorAll("[data-pdo]").forEach((b) => {
    b.onclick = () => writePdo(Number(b.dataset.pdo));
  });
  window.addEventListener("resize", resizeCanvases);
  resizeCanvases();
  const st = await api("/api/status");
  applyLink(st);
  if (st.connected) openWs();
}

function filteredObjects(processOnly) {
  const q = ($("objFilter").value || "").toLowerCase();
  const g = $("objGroup").value;
  return objects.filter((o) => {
    if (processOnly && !o.process) return false;
    if (!processOnly && o.group === "Hall-Rohdaten") return false;
    if (g && o.group !== g) return false;
    if (!q) return true;
    return `${o.name} ${o.index_hex} ${o.group}`.toLowerCase().includes(q);
  });
}

function renderObjectTables() {
  fillTable($("procBody"), objects.filter((o) => o.process && o.group !== "Hall-Rohdaten"));
  fillTable($("svcBody"), filteredObjects(false));
}

function fillTable(tbody, rows) {
  tbody.innerHTML = "";
  for (const o of rows) {
    const tr = document.createElement("tr");
    const canWrite = o.access === "rw" || o.access === "wo";
    tr.innerHTML = `
      <td>${o.index_hex}</td>
      <td>${o.sub_hex}</td>
      ${tbody.id === "svcBody" ? `<td>${o.group}</td>` : ""}
      <td>${o.name}${o.fw5 ? " <span class='hint'>FW5</span>" : ""}</td>
      <td>${o.dtype}</td>
      <td>${o.access}</td>
      <td><input class="val-in" data-k="${o.index}:${o.sub}" placeholder="${o.default ?? ""}" ${canWrite ? "" : "readonly"} /></td>
      <td>
        <button data-r="${o.index}:${o.sub}">Lesen</button>
        ${canWrite ? `<button data-w="${o.index}:${o.sub}">Schreiben</button>` : ""}
      </td>`;
    tbody.appendChild(tr);
  }
  tbody.querySelectorAll("[data-r]").forEach((b) => b.onclick = () => rw(b.dataset.r, false));
  tbody.querySelectorAll("[data-w]").forEach((b) => b.onclick = () => rw(b.dataset.w, true));
}

async function rw(key, write) {
  const [index, sub] = key.split(":").map(Number);
  const input = document.querySelector(`input[data-k="${key}"]`);
  try {
    if (write) {
      const raw = input.value.trim();
      const num = raw.startsWith("0x") || raw.startsWith("0X") ? parseInt(raw, 16) : Number(raw);
      const value = Number.isFinite(num) && raw !== "" ? num : raw;
      const r = await api("/api/sdo/write", { index, sub, value });
      if (r.display) input.value = r.display;
      toast("Geschrieben: " + (r.name || key));
    } else {
      const r = await api("/api/sdo/read", { index, sub });
      input.value = r.display;
    }
  } catch (e) { toast(e.message); }
}

async function refreshGroup(group) {
  const list = objects.filter((o) => o.access !== "wo" && (!group || o.group === group) && o.group !== "Hall-Rohdaten");
  for (const o of list) {
    try {
      const r = await api("/api/sdo/read", { index: o.index, sub: o.sub });
      const input = document.querySelector(`input[data-k="${o.index}:${o.sub}"]`);
      if (input) input.value = r.display;
    } catch { /* skip missing subs on older FW */ }
  }
  toast("SDO-Lesen abgeschlossen");
}

async function quickAct(name) {
  const map = {
    save: { index: 0x1010, sub: 1, value: 0x65766173 },
    default: { index: 0x202A, sub: 0, value: 1 },
    offset: { index: 0x202B, sub: 0, value: 1 },
    zero: { index: 0x202C, sub: 0, value: 1 },
    yaw: { index: 0x2032, sub: 1, value: 1 },
    event: { index: 0x2080, sub: 1, value: 1 },
  };
  try {
    await api("/api/sdo/write", map[name]);
    toast("Aktion ausgeführt");
  } catch (e) { toast(e.message); }
}

function cobDefault(pdo, node) {
  return [0, 0x180, 0x280, 0x380, 0x480][pdo] + node;
}

async function readPdoParams() {
  const node = Number($("nodeId").value);
  for (let i = 1; i <= 4; i++) {
    const idx = 0x17FF + i;
    try {
      const cob = await api("/api/sdo/read", { index: idx, sub: 1 });
      const tmr = await api("/api/sdo/read", { index: idx, sub: 5 });
      $("cob" + i).value = "0x" + Number(cob.value).toString(16);
      $("tmr" + i).value = tmr.value;
    } catch {
      $("cob" + i).value = "0x" + cobDefault(i, node).toString(16);
      $("tmr" + i).value = i === 1 ? 10 : 10;
    }
  }
}

async function writePdo(n) {
  const idx = 0x17FF + n;
  let cob = $("cob" + n).value.trim();
  cob = cob.startsWith("0x") ? parseInt(cob, 16) : Number(cob);
  const tmr = Number($("tmr" + n).value);
  try {
    await api("/api/sdo/write", { index: idx, sub: 1, value: cob });
    await api("/api/sdo/write", { index: idx, sub: 2, value: 255 });
    await api("/api/sdo/write", { index: idx, sub: 5, value: tmr });
    toast(`TPDO${n} geschrieben`);
  } catch (e) { toast(e.message); }
}

async function connect() {
  try {
    const body = {
      mode: $("mode").value,
      variant: $("variant").value,
      node_id: Number($("nodeId").value),
      bitrate: Number($("bitrate").value),
      interface: $("iface").value,
      channel: $("channel").value,
    };
    const st = await api("/api/connect", body);
    applyLink(st);
    openWs();
    await readPdoParams();
    toast(st.mode === "simulation" ? "Simulation verbunden" : "CAN verbunden");
  } catch (e) { toast(e.message); }
}

async function disconnect() {
  await api("/api/disconnect", {});
  if (ws) { ws.close(); ws = null; }
  applyLink({ connected: false });
}

function applyLink(st) {
  const on = !!st.connected;
  $("btnConnect").disabled = on;
  $("btnDisconnect").disabled = !on;
  $("linkState").textContent = on ? (st.mode + " · NMT " + (st.nmt || "?")) : "getrennt";
  $("linkState").className = "pill " + (on ? "on" : "off");
  $("simPanel").classList.toggle("hidden", st.mode !== "simulation");
}

function openWs() {
  if (ws) ws.close();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/process`);
  ws.onmessage = (ev) => {
    last = JSON.parse(ev.data);
    drawAll(last);
    $("linkState").textContent = `${last.mode || ""} · NMT ${last.nmt || "?"}`.trim();
  };
}

function resizeCanvases() {
  ["view", "hall", "hist"].forEach((id) => {
    const c = $(id);
    const r = c.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.max(200, r.width) * dpr;
    const cssH = r.height || Number(c.getAttribute("height"));
    c.height = Math.max(Number(c.getAttribute("height")), cssH) * dpr;
    c._dpr = dpr;
  });
  if (last) drawAll(last);
}

function drawAll(p) {
  drawView(p);
  drawHall(p);
  drawHist(p);
  drawStatus(p);
  drawLeds(p);
}

function mmX(ctx, mm, range, pad) {
  const w = ctx.canvas.width;
  const span = range;
  return pad + ((mm + span / 2) / span) * (w - pad * 2);
}

function drawView(p) {
  const c = $("view");
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height, dpr = c._dpr || 1;
  ctx.clearRect(0, 0, w, h);
  const range = p.range_mm || 400;
  const pad = 48 * dpr;
  const y0 = h * 0.55;
  ctx.strokeStyle = C.grey;
  ctx.lineWidth = 2 * dpr;
  ctx.beginPath();
  ctx.moveTo(pad, y0);
  ctx.lineTo(w - pad, y0);
  ctx.stroke();
  ctx.fillStyle = C.muted;
  ctx.font = `${11 * dpr}px Segoe UI`;
  for (let mm = -range / 2; mm <= range / 2; mm += 50) {
    const x = mmX(ctx, mm, range, pad);
    ctx.fillRect(x, y0 - 6 * dpr, 1, 12 * dpr);
    ctx.fillText(String(mm), x - 10 * dpr, y0 + 22 * dpr);
  }
  ctx.fillStyle = C.yellow;
  const zx = mmX(ctx, 0, range, pad);
  ctx.fillRect(zx, y0 - 16 * dpr, 2 * dpr, 32 * dpr);
  ctx.fillStyle = C.dark;
  ctx.fillText("0", zx - 4 * dpr, y0 - 22 * dpr);

  ctx.fillStyle = C.dark;
  roundRect(ctx, pad, h * 0.18, w - pad * 2, 28 * dpr, 8 * dpr);
  ctx.fill();
  ctx.fillStyle = C.white;
  ctx.fillText("Sensor  " + (p.variant || ""), pad + 8 * dpr, h * 0.18 + 19 * dpr);

  const tracks = (p.tracks || []).filter((t) => t.detected);
  tracks.forEach((t, i) => {
    const width = t.width_mm || 25;
    const x1 = mmX(ctx, t.position_mm - width / 2, range, pad);
    const x2 = mmX(ctx, t.position_mm + width / 2, range, pad);
    ctx.fillStyle = TRACK_COLORS[i % 3];
    ctx.globalAlpha = 0.85;
    roundRect(ctx, x1, y0 - 38 * dpr, Math.max(4, x2 - x1), 22 * dpr, 4 * dpr);
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.fillStyle = C.dark;
    ctx.fillText(`LCP${t.index}  ${t.position_mm} mm`, x1, y0 - 44 * dpr);
  });

  const main = tracks.find((t) => t.index === 2) || tracks[0];
  if (p.reading_marker && main && (p.markers || []).length) {
    p.markers.forEach((m) => {
      const mx = mmX(ctx, main.position_mm + m.offset_mm, range, pad);
      ctx.fillStyle = C.yellow;
      ctx.strokeStyle = C.dark;
      ctx.lineWidth = dpr;
      ctx.fillRect(mx - 5 * dpr, y0 + 10 * dpr, 10 * dpr, 18 * dpr);
      ctx.strokeRect(mx - 5 * dpr, y0 + 10 * dpr, 10 * dpr, 18 * dpr);
      ctx.fillStyle = C.dark;
      ctx.fillText("M" + p.marker_code, mx - 8 * dpr, y0 + 44 * dpr);
    });
  } else if (p.reading_marker) {
    ctx.fillStyle = C.dark;
    ctx.fillText("Marker-Code " + p.marker_code + (p.marker_intro ? " (Intro)" : ""), pad, h - 16 * dpr);
  }

  ctx.fillStyle = C.muted;
  ctx.fillText("Kabelabgang −", pad, h - 16 * dpr);
  ctx.fillText("+", w - pad - 10 * dpr, h - 16 * dpr);
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function drawHall(p) {
  const c = $("hall");
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height, dpr = c._dpr || 1;
  ctx.clearRect(0, 0, w, h);
  const hall = p.hall || [];
  const bitmap = p.bitmap || [];
  if (!hall.length) {
    ctx.fillStyle = C.muted;
    ctx.font = `${12 * dpr}px Segoe UI`;
    ctx.fillText("Keine Hall-Daten – verbinden oder TPDO3/SDO 0x2000", 12 * dpr, h / 2);
    return;
  }
  const max = Math.max(400, ...hall.map((v) => Math.abs(v)));
  const mid = h * 0.62;
  const barW = w / hall.length;
  hall.forEach((v, i) => {
    const x = i * barW;
    const bh = (v / max) * (h * 0.45);
    ctx.fillStyle = v >= 0 ? C.green : C.blue;
    ctx.fillRect(x, mid - Math.max(0, bh), Math.max(1, barW - 1), Math.abs(bh));
    if (bitmap[i]) {
      ctx.fillStyle = C.yellow;
      ctx.fillRect(x, 8 * dpr, Math.max(1, barW - 1), 8 * dpr);
    }
  });
  ctx.strokeStyle = C.grey;
  ctx.beginPath();
  ctx.moveTo(0, mid);
  ctx.lineTo(w, mid);
  ctx.stroke();
  ctx.fillStyle = C.muted;
  ctx.font = `${11 * dpr}px Segoe UI`;
  ctx.fillText("Hall " + hall.length + " Elemente · gelb = Bitmap 1", 8 * dpr, h - 10 * dpr);
}

const HIST_LEN = 360;

function drawHist(p) {
  const c = $("hist");
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height, dpr = c._dpr || 1;
  const tracks = p.tracks || [];
  const sample = [1, 2, 3].map((idx) => {
    const t = tracks.find((x) => x.index === idx);
    return t && t.detected ? t.position_mm : null;
  });
  history.push({ t: Date.now(), lcp: sample });
  if (history.length > HIST_LEN) history.shift();

  ctx.clearRect(0, 0, w, h);
  const range = p.range_mm || 400;
  const padL = 52 * dpr;
  const padR = 18 * dpr;
  const padT = 28 * dpr;
  const padB = 28 * dpr;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  const xOf = (mm) => padL + ((mm + range / 2) / range) * plotW;
  const n = Math.max(history.length, 2);
  const yOf = (i) => padT + (i / (n - 1)) * plotH;

  ctx.strokeStyle = C.grey;
  ctx.lineWidth = dpr;
  ctx.beginPath();
  ctx.moveTo(xOf(0), padT);
  ctx.lineTo(xOf(0), padT + plotH);
  ctx.stroke();

  ctx.fillStyle = C.muted;
  ctx.font = `${11 * dpr}px Segoe UI`;
  ctx.textAlign = "center";
  for (let mm = -range / 2; mm <= range / 2; mm += 50) {
    const x = xOf(mm);
    ctx.fillStyle = "#e5e2dd";
    ctx.fillRect(x, padT, dpr, plotH);
    ctx.fillStyle = C.muted;
    ctx.fillText(String(mm), x, padT - 8 * dpr);
  }
  ctx.textAlign = "left";
  ctx.fillText("alt", 8 * dpr, padT + 10 * dpr);
  ctx.fillText("jetzt", 8 * dpr, padT + plotH);

  [1, 2, 3].forEach((idx) => {
    ctx.strokeStyle = TRACK_COLORS[idx - 1];
    ctx.lineWidth = 2.4 * dpr;
    ctx.beginPath();
    let started = false;
    history.forEach((s, i) => {
      const v = s.lcp ? s.lcp[idx - 1] : (idx === 2 ? s.v : null);
      if (v == null) {
        started = false;
        return;
      }
      const x = xOf(v);
      const y = yOf(i);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();
  });
}

function drawStatus(p) {
  const s = p.status || {};
  const tracks = (p.tracks || []).filter((t) => t.detected).map((t) => `LCP${t.index}: ${t.position_mm} mm` + (t.width_mm != null ? ` / ${t.width_mm} mm` : "")).join(" · ") || "—";
  const rows = [
    ["#LCP", `${p.nlcp} · ${p.nlcp_label || ""}`],
    ["Spuren", tracks],
    ["Marker", p.reading_marker ? `Code ${p.marker_code}${p.marker_intro ? " · Intro" : ""}` : "keiner"],
    ["Line good", s.line_good ? "ja" : "nein"],
    ["Track Level", `${s.track_level} (${s.track_level_class || ""})`],
    ["Field Level", p.field_level ?? "—"],
    ["Polarität", s.polarity || "—"],
    ["Flipped", s.sensor_flipped ? "ja" : "nein"],
    ["Event", s.event_flag ? "ja" : "nein"],
    ["IMU", p.imu ? `R ${p.imu.roll_deg}°  P ${p.imu.pitch_deg}°  Y ${p.imu.yaw_deg}°` : "—"],
    ["Temperatur", p.temperature_c != null ? p.temperature_c + " °C" : "—"],
  ];
  $("statusDl").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}

function drawLeds(p) {
  const s = p.status || {};
  const tracks = (p.tracks || []).filter((t) => t.detected);
  $("ledY").classList.toggle("on", !!s.line_good || (s.track_level || 0) >= 1);
  $("ledR").classList.toggle("on", !!s.event_flag);
  const pos = tracks.length === 1 ? tracks[0].position_mm : 0;
  $("ledG").classList.toggle("on", tracks.length === 1 && pos <= 0);
  $("ledB").classList.toggle("on", tracks.length === 1 && pos >= 0);
}

init().catch((e) => toast(e.message));
