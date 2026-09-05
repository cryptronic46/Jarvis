"use strict";

const BRIDGE = "http://127.0.0.1:8765";
const stage = document.getElementById("stage");
const $ = (id) => document.getElementById(id);

const model = {
  state: "OFFLINE",
  bridgeOnline: false,
  lastSnapshot: null,
  fps: 30,
  audio: new Array(128).fill(0),
  smoothAudio: new Array(128).fill(0),
  audioLevel: 0,
  history: {
    cpu: new Array(50).fill(0),
    ram: new Array(50).fill(0),
    gpu: new Array(50).fill(0),
  },
};

window.wallpaperPropertyListener = {
  applyGeneralProperties: function(properties) {
    if (properties.fps) {
      model.fps = Number(properties.fps) || 30;
    }
  },
  applyUserProperties: function(properties) {
    // Prepared for Wallpaper Engine project properties later.
    if (properties && properties.coreglow) {
      const v = Number(properties.coreglow.value);
      if (Number.isFinite(v)) {
        document.documentElement.style.setProperty(
          "--core-base",
          Math.max(.15, Math.min(1, v / 100))
        );
      }
    }
  }
};

function setText(id, value, fallback="--") {
  const el = $(id);
  if (!el) return;
  const text = value === null || value === undefined || value === "" ? fallback : String(value);
  if (el.textContent !== text) el.textContent = text;
}

function num(v, digits=0, fallback="--") {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(digits) : fallback;
}

function gb(v) {
  return Number.isFinite(Number(v)) ? `${Number(v).toFixed(1)} GB` : "--";
}

function mbps(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "--";
  if (n < 1) return `${Math.round(n * 1000)} Kbps`;
  return `${n.toFixed(n >= 100 ? 0 : 1)} Mbps`;
}

function weatherGlyph(code) {
  code = Number(code);
  if (code === 0) return "☼";
  if ([1,2].includes(code)) return "◒";
  if (code === 3) return "☁";
  if ([45,48].includes(code)) return "≋";
  if ([51,53,55,61,63,65,80,81,82].includes(code)) return "☂";
  if ([71,73,75,77,85,86].includes(code)) return "❄";
  if ([95,96,99].includes(code)) return "ϟ";
  return "◌";
}

function greeting() {
  const h = new Date().getHours();
  return h >= 5 && h < 12 ? "BOM DIA, SENHOR"
       : h >= 12 && h < 20 ? "BOA TARDE, SENHOR"
       : "BOA NOITE, SENHOR";
}

function updateClock() {
  const d = new Date();
  setText("clock", d.toLocaleTimeString("pt-PT", {hour12:false}));
  setText(
    "date",
    d.toLocaleDateString("pt-PT", {day:"2-digit", month:"long", year:"numeric"}).toUpperCase()
  );
  setText(
    "weekday",
    d.toLocaleDateString("pt-PT", {weekday:"long"}).toUpperCase()
  );
  setText("greeting", greeting());
}

async function fetchJson(path, timeout=2200) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const started = performance.now();
  try {
    const res = await fetch(BRIDGE + path, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    data.__latency_ms = Math.round(performance.now() - started);
    return data;
  } finally {
    clearTimeout(timer);
  }
}

function setState(state, message) {
  state = String(state || "IDLE").toUpperCase();
  const allowed = ["IDLE","LISTENING","THINKING","SPEAKING","OFFLINE"];
  if (!allowed.includes(state)) state = "IDLE";

  model.state = state;
  stage.classList.remove(
    "state-idle","state-listening","state-thinking","state-speaking","state-offline"
  );
  stage.classList.add("state-" + state.toLowerCase());
  setText("coreState", state === "OFFLINE" ? "CORE OFFLINE" : state);
  setText(
    "coreMessage",
    message || ({
      IDLE: "Núcleo neural ativo",
      LISTENING: "Estou a ouvir, Senhor",
      THINKING: "A processar",
      SPEAKING: "A responder",
      OFFLINE: "A aguardar ligação ao JARVIS",
    }[state])
  );

  if (state === "LISTENING") setText("voicePrompt", "ESTOU A OUVIR...");
  else if (state === "THINKING") setText("voicePrompt", "A PROCESSAR...");
  else if (state === "SPEAKING") setText("voicePrompt", "A RESPONDER...");
  else setText("voicePrompt", "COMO POSSO AJUDAR?");
}

function setBridgeOnline(online, latency) {
  model.bridgeOnline = !!online;
  const el = $("bridgeState");
  el.className = online ? "online" : "offline";
  setText("bridgeState", online ? "BRIDGE ONLINE" : "BRIDGE OFFLINE");
  setText("bridgeLatency", online ? `${latency ?? "--"} ms` : "--");
}

function updateTelemetry(t) {
  if (!t) return;

  setText("cpuName", t.cpu?.name || "CPU");
  setText("cpuUsage", num(t.cpu?.usage_percent));
  setText("cpuFreq", t.cpu?.frequency_mhz ? `${Math.round(t.cpu.frequency_mhz)} MHz` : "--");
  setText("cpuTemp", t.cpu?.temperature_c ? `${num(t.cpu.temperature_c)} °C` : "--");
  setText("cpuCores", t.cpu?.cores_logical || "--");

  setText("ramUsage", num(t.memory?.percent));
  setText("ramUsed", gb(t.memory?.used_gb));
  setText("ramFree", gb(t.memory?.available_gb));
  setText("ramTotal", gb(t.memory?.total_gb));
  setText("ramCapacity", t.memory?.total_gb ? `CAPACIDADE ${num(t.memory.total_gb,1)} GB` : "MEMÓRIA");

  setText("gpuName", t.gpu?.name || "GPU NÃO DETETADA");
  setText("gpuUsage", num(t.gpu?.utilization_percent));
  setText("gpuTemp", t.gpu?.temperature_c !== null ? `${num(t.gpu?.temperature_c)} °C` : "--");
  setText(
    "gpuVram",
    t.gpu?.memory_used_mb !== null && t.gpu?.memory_total_mb
      ? `${(t.gpu.memory_used_mb/1024).toFixed(1)} / ${(t.gpu.memory_total_mb/1024).toFixed(1)} GB`
      : "--"
  );
  setText("gpuClock", t.gpu?.clock_mhz ? `${Math.round(t.gpu.clock_mhz)} MHz` : "--");

  setText("download", mbps(t.network?.download_mbps));
  setText("upload", mbps(t.network?.upload_mbps));
  setText("localIp", t.network?.local_ip || "--");
  setText("networkType", t.network?.interface || "LAN");

  pushHistory(model.history.cpu, Number(t.cpu?.usage_percent || 0));
  pushHistory(model.history.ram, Number(t.memory?.percent || 0));
  pushHistory(model.history.gpu, Number(t.gpu?.utilization_percent || 0));
}

function updateEnvironment(env) {
  if (!env) return;
  const loc = env.location || {};
  const w = env.weather || {};
  const m = env.marine || {};

  setText("weatherLocation", (loc.label || "Furadouro, Ovar").toUpperCase());
  setText("temperature", num(w.temperature_c,1));
  setText("condition", w.condition || "--");
  setText("feelsLike", w.apparent_temperature_c !== undefined ? `${num(w.apparent_temperature_c,1)}°` : "--");
  setText("wind", w.wind_speed_kmh !== undefined ? `${num(w.wind_speed_kmh,0)} km/h` : "--");
  setText("weatherIcon", weatherGlyph(w.weather_code));

  setText("humidity", num(w.relative_humidity_percent));
  const h = Math.max(0, Math.min(100, Number(w.relative_humidity_percent || 0)));
  $("humidityGauge").style.width = `${h}%`;

  setText("waveHeight", num(m.wave_height_m,2));
  setText("seaState", m.state || "--");
  setText("wavePeriod", m.wave_period_s !== undefined ? `${num(m.wave_period_s,1)} s` : "--");
  setText("seaTemp", m.sea_surface_temperature_c !== undefined ? `${num(m.sea_surface_temperature_c,1)} °C` : "--");
}

function updateSecurity(sec) {
  sec = sec || {};
  const alerts = Array.isArray(sec.alerts) ? sec.alerts : [];
  const critical = alerts.filter(x => ["critical","attention"].includes(String(x.severity || "").toLowerCase()));
  const level = critical.some(x => String(x.severity).toLowerCase() === "critical")
    ? "CRÍTICO"
    : critical.length ? "ATENÇÃO" : "OK";

  setText("securityLevel", level);
  $("securityLevel").className =
    level === "CRÍTICO" ? "security-critical"
    : level === "ATENÇÃO" ? "security-attention"
    : "security-ok";

  setText(
    "securityTitle",
    level === "OK" ? "SISTEMA MONITORIZADO"
      : level === "ATENÇÃO" ? "VERIFICAR ALERTAS"
      : "ALERTA CRÍTICO"
  );
  setText(
    "securityDetail",
    sec.baseline_exists
      ? (alerts.length ? `${alerts.length} alteração(ões) detetada(s)` : "Sem alterações relevantes")
      : "Baseline ainda não criada"
  );
  setText("firewallState", sec.firewall_all_enabled === true ? "ATIVO" : sec.firewall_all_enabled === false ? "ATENÇÃO" : "--");
  setText("defenderState", sec.defender_realtime_enabled === true ? "ATIVO" : sec.defender_realtime_enabled === false ? "ATENÇÃO" : "--");
  setText("rdpState", sec.rdp_enabled === true ? "ATIVO" : sec.rdp_enabled === false ? "OFF" : "--");
  setText("securityAlerts", alerts.length);
}

function updateNetwork(net) {
  net = net || {};
  const devices = Array.isArray(net.active_devices) ? net.active_devices : [];
  setText("activeDevices", devices.length);
}

function updateAgenda(agenda) {
  const el = $("agendaList");
  const items = Array.isArray(agenda?.upcoming) ? agenda.upcoming : [];
  if (!items.length) {
    el.innerHTML = '<div class="empty">Sem compromissos próximos.</div>';
    return;
  }
  el.innerHTML = items.slice(0,5).map(item => {
    const when = item.when ? new Date(item.when) : null;
    const t = when && !Number.isNaN(when.getTime())
      ? when.toLocaleTimeString("pt-PT",{hour:"2-digit",minute:"2-digit"})
      : "•";
    return `<div class="agenda-item">
      <span class="agenda-time">${escapeHtml(t)}</span>
      <span class="agenda-title">${escapeHtml(item.title || "Sem título")}</span>
    </div>`;
  }).join("");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll('"',"&quot;");
}

function updateSnapshot(data) {
  model.lastSnapshot = data;
  setBridgeOnline(true, data.__latency_ms);
  setText("coreVersion", data.bridge?.core_version || "0.12.0");
  updateTelemetry(data.telemetry);
  updateEnvironment(data.environment);
  updateSecurity(data.security);
  updateNetwork(data.network);
  updateAgenda(data.agenda);

  if (data.state) {
    setState(data.state.name, data.state.message);
  }
}

async function pollSnapshot() {
  try {
    const data = await fetchJson("/api/snapshot", 3500);
    updateSnapshot(data);
  } catch (err) {
    setBridgeOnline(false);
    setState("OFFLINE");
  }
}

async function pollState() {
  try {
    const data = await fetchJson("/api/state", 1200);
    setBridgeOnline(true, data.__latency_ms);
    setState(data.name, data.message);
  } catch (err) {
    if (!model.bridgeOnline) setState("OFFLINE");
  }
}

function pushHistory(arr, value) {
  arr.push(Math.max(0, Math.min(100, Number(value) || 0)));
  while (arr.length > 50) arr.shift();
}

function resizeCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
  const w = Math.max(1, Math.round(rect.width * dpr));
  const h = Math.max(1, Math.round(rect.height * dpr));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  return {w,h,dpr};
}

function drawSparkline(id, values, bars=false) {
  const c = $(id);
  const {w,h} = resizeCanvas(c);
  const ctx = c.getContext("2d");
  ctx.clearRect(0,0,w,h);
  if (!values.length) return;

  ctx.strokeStyle = "rgba(39,221,255,.82)";
  ctx.fillStyle = "rgba(39,221,255,.7)";
  ctx.lineWidth = Math.max(1, w/350);

  if (bars) {
    const bw = w / values.length;
    values.forEach((v,i) => {
      const bh = Math.max(1, h * (v/100));
      ctx.fillRect(i*bw, h-bh, Math.max(1,bw*.45), bh);
    });
    return;
  }

  ctx.beginPath();
  values.forEach((v,i) => {
    const x = (i/(values.length-1))*w;
    const y = h - (v/100)*(h*.82) - h*.08;
    if (i === 0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
  });
  ctx.stroke();
}

function wallpaperAudioListener(audioArray) {
  if (!audioArray || audioArray.length < 128) return;
  for (let i=0;i<128;i++) {
    model.audio[i] = Math.min(1, Math.max(0, Number(audioArray[i]) || 0));
  }
}

function smoothAudio() {
  let sum = 0;
  for (let i=0;i<128;i++) {
    const target = model.audio[i];
    model.smoothAudio[i] += (target - model.smoothAudio[i]) * .32;
    sum += model.smoothAudio[i];
  }
  model.audioLevel = Math.min(1, (sum / 128) * 3.2);
  document.documentElement.style.setProperty("--audio", model.audioLevel.toFixed(3));

  let stateBoost =
    model.state === "THINKING" ? .68 :
    model.state === "LISTENING" ? .58 :
    model.state === "SPEAKING" ? .52 + model.audioLevel*.45 :
    model.state === "OFFLINE" ? .12 :
    .38 + model.audioLevel*.22;
  document.documentElement.style.setProperty(
    "--core-intensity",
    Math.min(1, stateBoost).toFixed(3)
  );
}

function drawAudio(id, reverse=false) {
  const c = $(id);
  const {w,h} = resizeCanvas(c);
  const ctx = c.getContext("2d");
  ctx.clearRect(0,0,w,h);

  const count = 42;
  const half = 64;
  const source = [];
  for (let i=0;i<count;i++) {
    const idx = Math.floor((i/(count-1))*(half-1));
    const left = model.smoothAudio[idx] || 0;
    const right = model.smoothAudio[64+idx] || 0;
    source.push(Math.min(1, (left+right)*.72));
  }
  if (reverse) source.reverse();

  const gap = Math.max(1,w*.006);
  const bw = Math.max(1,(w-gap*(count-1))/count);
  const mid = h/2;

  source.forEach((v,i) => {
    const idle = .04 + Math.sin((performance.now()/420)+(i*.55))*.018;
    const level = Math.max(idle, v);
    const barH = Math.max(1, level*h*.88);
    const x = i*(bw+gap);
    const grad = ctx.createLinearGradient(0,mid-barH/2,0,mid+barH/2);
    grad.addColorStop(0,"rgba(39,221,255,.72)");
    grad.addColorStop(.7,"rgba(39,221,255,.95)");
    grad.addColorStop(1,"rgba(255,86,216,.78)");
    ctx.fillStyle = grad;
    ctx.fillRect(x,mid-barH/2,bw,barH);
  });
}

const particleCanvas = $("particles");
let particles = [];
function initParticles() {
  particles = Array.from({length: 90}, () => ({
    x: Math.random(),
    y: Math.random(),
    z: .2 + Math.random()*.8,
    s: .2 + Math.random()*.8,
  }));
}
function drawParticles(dt) {
  const {w,h} = resizeCanvas(particleCanvas);
  const ctx = particleCanvas.getContext("2d");
  ctx.clearRect(0,0,w,h);
  const cx=w*.5, cy=h*.42;
  const intensity = model.state === "THINKING" ? 2.4 : model.state === "LISTENING" ? 1.7 : 1;
  particles.forEach(p => {
    p.y -= dt*.007*p.z*intensity;
    p.x += Math.sin((p.y+p.z)*12)*dt*.0015*intensity;
    if (p.y < -.02) { p.y=1.02; p.x=Math.random(); }
    const x=p.x*w, y=p.y*h;
    const dx=x-cx, dy=y-cy;
    const dist=Math.sqrt(dx*dx+dy*dy)/(Math.min(w,h)*.7);
    const alpha=Math.max(0,.34*(1-dist))*p.z;
    ctx.fillStyle=`rgba(39,221,255,${alpha})`;
    ctx.fillRect(x,y,Math.max(1,p.s*1.5),Math.max(1,p.s*1.5));
  });
}

let lastFrame = performance.now();
let fpsAccumulator = 0;
function animate(now) {
  window.requestAnimationFrame(animate);
  const dt = Math.min((now-lastFrame)/1000, .1);
  lastFrame = now;

  if (model.fps > 0) {
    fpsAccumulator += dt;
    const threshold = 1/model.fps;
    if (fpsAccumulator < threshold) return;
    fpsAccumulator %= threshold;
  }

  smoothAudio();
  drawAudio("audioLeft", false);
  drawAudio("audioRight", true);
  drawSparkline("cpuChart", model.history.cpu, false);
  drawSparkline("ramChart", model.history.ram, true);
  drawSparkline("gpuChart", model.history.gpu, false);
  drawParticles(dt);
}

updateClock();
setInterval(updateClock, 1000);
initParticles();
setState("OFFLINE");

pollSnapshot();
setInterval(pollSnapshot, 3000);
setInterval(pollState, 650);

window.addEventListener("resize", () => {
  initParticles();
});

if (typeof window.wallpaperRegisterAudioListener === "function") {
  window.wallpaperRegisterAudioListener(wallpaperAudioListener);
}
window.requestAnimationFrame(animate);
