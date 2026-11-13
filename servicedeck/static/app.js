/* ServiceDeck dashboard. No build step: this file is served as-is. */

const app = document.getElementById("app");

const state = {
  view: "boot",
  page: "stream",
  settingsSection: "general",
  mixerBank: "",
  mixerView: "channels",
  dragKey: "",
  authed: false,
  organization: "PRBC",
  version: "",
  mustChange: false,
  dismissedPrompt: false,
  entered: "",
  lockError: "",
  lockoutUntil: 0,
  shake: false,
  status: null,
  structure: "",
  holding: false,
  pendingRender: false,
  speed: 10,
  cameraId: null,
  moveGen: 0,
  zoomGen: 0,
  moveTimer: null,
  zoomTimer: null,
  modal: null,
  busy: false,
  settings: null,
  catalog: [],
  settingsMessage: "",
  testResults: {},
};

app.addEventListener("click", onClick);
app.addEventListener("pointerdown", onPointerDown);
app.addEventListener("contextmenu", (event) => {
  if (event.target.closest(".pad, .keys")) event.preventDefault();
});
app.addEventListener("input", onInput);
app.addEventListener("change", onChange);
document.addEventListener("keydown", onKeyDown);

boot();
setInterval(tick, 1000);
setInterval(poll, 2000);

async function boot() {
  try {
    const session = await api("/api/auth/session", { quietAuth: true });
    state.organization = session.organization || "PRBC";
    state.version = session.version || "";
    state.mustChange = !!session.must_change_passcode;
    state.authed = !!session.authenticated;
    state.view = state.authed ? "dashboard" : "lock";
  } catch (error) {
    state.view = "lock";
    state.lockError = "Can't reach ServiceDeck. Is the booth computer running it?";
  }
  if (state.authed) await loadStatus(true);
  render();
  maybePromptPasscode();
}

async function poll() {
  if (!state.authed || document.hidden) return;
  if (state.view !== "dashboard") return;
  try {
    await loadStatus(false);
  } catch (error) {
    if (!error.silent) state.lockError = error.message;
  }
}

async function loadStatus(force) {
  const status = await api("/api/status");
  state.status = status;
  state.organization = status.organization || state.organization;
  state.mustChange = !!status.must_change_passcode;
  state.version = status.version || state.version;
  const cameras = status.ptz?.cameras || [];
  if (!state.cameraId || !cameras.some((camera) => camera.id === state.cameraId)) {
    state.cameraId = cameras[0]?.id || null;
  }
  const key = structureKey(status);
  const changed = key !== state.structure;
  state.structure = key;
  if (state.view === "settings") return;
  if (state.view !== "dashboard") return;
  if ((changed || force) && !state.holding) renderShell();
  else if (changed || force) state.pendingRender = true;
  else patch();
}

function structureKey(status) {
  const obs = status?.obs || {};
  const cameras = (status?.ptz?.cameras || []).map((camera) => ({
    id: camera.id,
    name: camera.name,
    protocol: camera.protocol,
    presets: camera.presets,
  }));
  return JSON.stringify({
    org: status?.organization,
    must: status?.must_change_passcode,
    tiles: status?.dashboard,
    scenes: obs.scenes,
    streaming: !!obs.streaming,
    recording: !!obs.recording,
    connected: !!obs.connected,
    cameras,
    cameraId: state.cameraId,
    plan: status?.planning_center?.plan?.id,
    planItems: (status?.planning_center?.plan?.items || []).map((item) => item.id + item.title),
    banks: (status?.mixer?.banks || []).map((bank) => bank.id + bank.name + JSON.stringify(bank.channels)),
    scenes: status?.mixer?.scenes,
    onAir: !!status?.proclaim?.on_air,
  });
}

function tick() {
  if (state.view === "lock" && state.lockoutUntil) {
    const left = Math.ceil((state.lockoutUntil - Date.now()) / 1000);
    const label = document.getElementById("lock-error");
    if (left > 0 && label) label.textContent = `Too many tries. Wait ${left} seconds.`;
    if (left <= 0) {
      state.lockoutUntil = 0;
      state.lockError = "";
      renderShell();
    }
  }
}

function render() {
  app.innerHTML = '<div id="shell"></div><div id="modal-root"></div><div id="toast" role="status"></div>';
  renderShell();
  renderModal();
}

function renderShell() {
  const shell = document.getElementById("shell");
  if (!shell) return render();
  if (state.view === "boot") {
    shell.innerHTML = '<div class="lock-screen"><p class="hint">Opening ServiceDeck…</p></div>';
    return;
  }
  if (state.view === "lock") {
    shell.innerHTML = lockHtml();
    return;
  }
  const body = state.view === "settings" ? settingsPage() : dashboardHtml();
  shell.innerHTML = `<div class="fit">${topbarHtml()}${tabBar()}${body}</div>`;
  state.pendingRender = false;
}

function topbarHtml() {
  return `
    <header class="topbar">
      <div class="brand">
        ${markSvg()}
        <div>
          <h1>ServiceDeck</h1>
          <p>${esc(state.organization)}</p>
        </div>
      </div>
      <div class="spacer"></div>
      <div class="top-actions">
        <button type="button" data-action="lock">Lock</button>
      </div>
    </header>`;
}

function lockHtml() {
  const digits = state.entered.length;
  const dots = Array.from({ length: Math.max(4, digits) }, (_, index) =>
    `<i class="${index < digits ? "filled" : ""}"></i>`
  ).join("");
  const hint = state.mustChange
    ? "First launch passcode is 0000. Change it after you unlock."
    : "Enter the booth passcode.";
  const locked = state.lockoutUntil > Date.now();
  return `
    <div class="lock-screen">
      <form class="lock-card" data-action="unlock-form">
        <p class="eyebrow">${esc(state.organization)}</p>
        <h1>ServiceDeck</h1>
        <p class="hint">${esc(hint)}</p>
        <div class="dots ${state.shake ? "shake" : ""}" id="dots">${dots}</div>
        <div class="keys">
          ${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => keyButton(n, locked)).join("")}
          ${keyButton("clear", locked, "Clear", "ghost")}
          ${keyButton(0, locked)}
          ${keyButton("back", locked, "Delete", "ghost")}
        </div>
        <button class="unlock" type="submit" ${digits < 4 || locked ? "disabled" : ""}>Unlock</button>
        <p class="error-text" id="lock-error">${esc(state.lockError)}</p>
      </form>
    </div>`;
}

function keyButton(value, locked, label, extra) {
  const text = label || value;
  return `<button type="button" data-key="${value}" class="${extra || ""}" ${locked ? "disabled" : ""}>${text}</button>`;
}

function tabBar() {
  const pages = [
    { id: "stream", label: "Stream" },
    { id: "cameras", label: "Cameras" },
    { id: "sound", label: "Sound" },
    { id: "service", label: "Service" },
    { id: "settings", label: "Settings" },
  ];
  return `<nav class="tabbar">${pages.map((page) =>
    `<button type="button" data-page="${page.id}" class="${state.page === page.id ? "active" : ""}">${page.label}</button>`
  ).join("")}</nav>`;
}

function dashboardHtml() {
  const status = state.status;
  if (!status) return '<div class="page-wrap"><p class="hint">Loading the booth…</p></div>';
  const tiles = (status.dashboard || [])
    .filter((tile) => tile.visible && (tile.page || "stream") === state.page)
    .sort((a, b) => a.order - b.order);
  const banner = state.mustChange
    ? '<div class="banner">The passcode is still the default 0000. Change it in Settings.</div>'
    : "";
  const count = Math.min(tiles.length, 2);
  const rendered = tiles.map(renderTile).join("");
  const empty = tiles.length
    ? ""
    : '<p class="empty">Nothing on this tab. Choose tiles in Settings.</p>';
  return `<div class="page-wrap">${banner}<div class="page-grid count-${count || 1}">${rendered}${empty}</div></div>`;
}

function renderTile(tile) {
  if (tile.id === "obs") return obsTile(state.status.obs || {});
  if (tile.id === "ptz") return ptzTile(state.status.ptz || {});
  if (tile.id === "planning_center") return planTile(state.status.planning_center || {});
  if (tile.id === "proclaim") return proclaimTile(state.status.proclaim || {});
  if (tile.id === "mixer") return mixerTile(state.status.mixer || {});
  return `<article class="tile"><h2>${esc(tile.id)}</h2><p>Not in this version.</p></article>`;
}

function obsTile(obs) {
  const live = !!obs.streaming;
  const scenes = (obs.scenes || []).map((name) => `
    <button type="button" data-action="scene" data-scene="${esc(name)}" ${obs.connected ? "" : "disabled"}
      class="${name === obs.current_scene ? "active" : ""}">${esc(name)}</button>`).join("");
  const sceneBlock = scenes || '<p class="empty">No scenes yet. Connect OBS to load them.</p>';
  const timer = live ? (obs.stream_timecode || "00:00:00") : "Off air";
  const go = live
    ? `<button type="button" class="end-stream" data-action="end-stream" ${obs.connected ? "" : "disabled"}>End Stream</button>`
    : `<button type="button" class="go-live" data-action="go-live" ${obs.connected ? "" : "disabled"}>Go Live</button>`;
  const note = live
    ? "The stream is using the Facebook key saved in OBS."
    : obs.use_start_scene && obs.start_scene
      ? `Go Live switches to “${obs.start_scene}”, then starts the stream.`
      : "Go Live starts the stream with the Facebook key saved in OBS.";
  const recordLabel = obs.recording ? (obs.recording_paused ? "Recording paused" : "Stop recording") : "Start recording";
  return `
    <article class="tile ${live ? "live" : ""}" id="obs-tile">
      <div class="tile-head">
        <h2>OBS</h2>
        <div class="pills" data-bind="obs-pills">${obsPills(obs)}</div>
      </div>
      <div class="timer" data-bind="obs-timer">${esc(timer)}</div>
      <div class="scenes" data-bind="scenes">${sceneBlock}</div>
      ${go}
      <p class="sub" data-bind="obs-note">${esc(note)}</p>
      <p class="sub" data-bind="obs-message">${esc(obs.message || "")}</p>
      <div class="row-2">
        <button type="button" data-action="record" ${obs.connected ? "" : "disabled"}>${esc(recordLabel)}</button>
        <button type="button" data-action="refresh-status">Refresh</button>
      </div>
    </article>`;
}

function obsPills(obs) {
  const pills = [];
  if (obs.connected) pills.push(pill("Connected", "ok"));
  else if (obs.state === "not_configured") pills.push(pill("Not set up", "bad"));
  else pills.push(pill("Disconnected", "bad"));
  if (obs.reconnecting) pills.push(pill("Reconnecting", "bad"));
  if (obs.streaming) pills.push(pill("Live", "live"));
  if (obs.recording) pills.push(pill(obs.recording_paused ? "Rec paused" : "Recording", "rec"));
  return pills.join("");
}

function pill(text, kind) {
  return `<span class="pill ${kind}"><span class="dot"></span>${esc(text)}</span>`;
}

function ptzTile(ptz) {
  const cameras = ptz.cameras || [];
  if (!cameras.length) {
    return `
      <article class="tile">
        <div class="tile-head"><h2>PTZ cameras</h2></div>
        <p class="empty">No cameras yet. Add one in Settings. VISCA over IP, usually port 52381.</p>
      </article>`;
  }
  const current = cameras.find((camera) => camera.id === state.cameraId) || cameras[0];
  const tabs = cameras.map((camera) => `
    <button type="button" data-action="camera" data-camera="${esc(camera.id)}"
      class="${camera.id === current.id ? "active" : ""}">${esc(camera.name)}</button>`).join("");
  const unavailable = current.protocol !== "visca_ip";
  const presets = (current.presets || []).map((preset) => `
    <button type="button" data-action="preset" data-number="${preset.number}" ${unavailable ? "disabled" : ""}>
      ${esc(preset.label)}
    </button>`).join("");
  const disabled = unavailable ? "disabled" : "";
  return `
    <article class="tile" id="ptz-tile">
      <div class="tile-head">
        <h2>PTZ</h2>
        <div class="pills" data-cam-state="${esc(current.id)}">${cameraPill(current)}</div>
      </div>
      <div class="cameras">${tabs}</div>
      <p class="sub" data-bind="cam-message">${esc(current.message || "")}</p>
      <div class="presets">${presets || '<p class="empty">No preset buttons yet. Add some in Settings.</p>'}</div>
      <div class="pad">
        ${holdButton("Up", "stop", "up", "up", disabled)}
        ${holdButton("Left", "left", "stop", "left", disabled)}
        <button type="button" class="stop" data-action="stop-all" ${disabled}>Stop</button>
        ${holdButton("Right", "right", "stop", "right", disabled)}
        ${holdButton("Down", "stop", "down", "down", disabled)}
      </div>
      <div class="row-2">
        ${zoomButton("Zoom out", "out", disabled)}
        ${zoomButton("Zoom in", "in", disabled)}
      </div>
      <div class="row-2">
        <button type="button" data-action="home" ${disabled}>Home</button>
        <button type="button" data-action="save-preset" ${disabled || !(current.presets || []).length ? "disabled" : ""}>Save preset…</button>
      </div>
      <label class="field speed">
        <span>Speed <strong id="speed-readout">${state.speed}</strong></span>
        <input type="range" min="1" max="24" value="${state.speed}" data-action="speed" aria-label="Camera speed">
      </label>
    </article>`;
}

function cameraPill(camera) {
  if (camera.state === "connected") return pill("Connected", "ok");
  if (camera.state === "disconnected") return pill("No reply", "bad");
  if (camera.state === "unavailable") return pill("Not available", "bad");
  return pill("Not checked", "");
}

function holdButton(label, pan, tilt, place, disabled) {
  return `<button type="button" class="${place}" data-hold="move" data-pan="${pan}" data-tilt="${tilt}" ${disabled}>${label}</button>`;
}

function zoomButton(label, direction, disabled) {
  return `<button type="button" data-hold="zoom" data-direction="${direction}" ${disabled}>${label}</button>`;
}

function settingsPage() {
  const draft = state.settings || blankSettings();
  const sections = [
    ["general", "General"],
    ["obs", "OBS"],
    ["cameras", "Cameras"],
    ["sound", "Sound"],
    ["service", "Service"],
    ["layout", "Tabs"],
  ];
  const nav = sections.map(([id, label]) =>
    `<button type="button" data-section="${id}" class="${state.settingsSection === id ? "active" : ""}">${label}</button>`
  ).join("");
  return `
    <div class="page-wrap settings-fit">
      <div class="section-nav">${nav}</div>
      <div class="section-body" id="settings">
        ${settingsSection(draft)}
        <p class="sub">${esc(state.settingsMessage)}</p>
      </div>
    </div>`;
}

function settingsSection(draft) {
  if (state.settingsSection === "general") return generalCard(draft);
  if (state.settingsSection === "obs") return obsCard(draft);
  if (state.settingsSection === "cameras") return cameraCard(draft);
  if (state.settingsSection === "sound") return soundCard(draft);
  if (state.settingsSection === "service") return serviceCard(draft);
  return layoutCard();
}

function generalCard(draft) {
  return `
    <section class="card">
      <h2>General</h2>
      <div class="fields two">
        <label class="field"><span>Name on the dashboard</span><input name="organization" value="${esc(draft.organization)}" maxlength="40"></label>
        <label class="field"><span>Dashboard port</span><input name="server-port" inputmode="numeric" value="${esc(draft.server.port)}"></label>
      </div>
      <p class="sub">${serverNote(draft)}</p>
      <div class="actions"><button type="button" class="primary" data-action="save-settings">Save</button></div>
      ${passcodeCard()}
    </section>`;
}

function passcodeCard() {
  return `
    <section class="card">
      <h2>Passcode</h2>
      <p class="lead">4 to 8 digits. The default 0000 cannot be kept.</p>
      <div class="fields">
        <label class="field"><span>Current</span><input name="current-passcode" inputmode="numeric" autocomplete="off" maxlength="8"></label>
        <label class="field"><span>New</span><input name="new-passcode" inputmode="numeric" autocomplete="off" maxlength="8"></label>
        <label class="field"><span>New again</span><input name="confirm-passcode" inputmode="numeric" autocomplete="off" maxlength="8"></label>
      </div>
      <div class="actions">
        <button type="button" class="primary" data-action="change-passcode">Change passcode</button>
      </div>
    </section>`;
}

function obsCard(draft) {
  const obs = draft.obs;
  return `
    <section class="card">
      <h2>OBS</h2>
      <p class="lead">The Facebook stream key stays in OBS.</p>
      <div class="fields two">
        <label class="field"><span>OBS computer IP</span><input name="obs-host" value="${esc(obs.host)}" autocomplete="off"></label>
        <label class="field"><span>WebSocket port</span><input name="obs-port" inputmode="numeric" value="${esc(obs.port)}"></label>
        <label class="field"><span>WebSocket password</span><input name="obs-password" type="password" autocomplete="new-password" placeholder="${obs.password_set ? "Saved — leave blank to keep" : "Password from OBS"}"></label>
        <label class="field"><span>Start scene</span><input name="obs-start-scene" value="${esc(obs.start_scene)}" placeholder="Exact OBS scene name"></label>
      </div>
      <label class="check"><input type="checkbox" name="obs-use-start" ${obs.use_start_scene ? "checked" : ""}> Switch to the start scene when going live</label>
      <label class="check"><input type="checkbox" name="obs-clear-password"> Remove the saved OBS password</label>
      <div class="actions">
        <button type="button" class="primary" data-action="save-settings">Save devices</button>
        <button type="button" data-action="test-obs">Test OBS</button>
      </div>
      <p class="sub" data-test="obs">${esc(state.testResults.obs || "")}</p>
    </section>`;
}

function cameraCard(draft) {
  const cameras = (draft.cameras || []).map((camera, index) => cameraEditor(camera, index)).join("");
  return `
    <section class="card">
      <h2>Cameras</h2>
      <p class="lead">VISCA over IP uses UDP port 52381. Preset 1 is the camera's first memory.</p>
      ${cameras || '<p class="empty">No cameras yet.</p>'}
      <div class="actions">
        <button type="button" data-action="add-camera">Add camera</button>
        <button type="button" class="primary" data-action="save-settings">Save</button>
      </div>
    </section>`;
}

function serverNote(draft) {
  const running = draft.running;
  if (!running) return "Port changes apply after you close ServiceDeck and open it again.";
  if (draft.restart_required) {
    return `This window is on port ${running.port}. Saved settings say port ${draft.server.port}. Restart ServiceDeck to use the saved port.`;
  }
  return `Listening on port ${running.port}. A new port applies after you restart ServiceDeck.`;
}

function cameraEditor(camera, index) {
  const presets = (camera.presets || []).map((preset, presetIndex) => `
    <div class="fields two">
      <label class="field"><span>Button</span><input data-preset="${presetIndex}" data-part="number" inputmode="numeric" value="${esc(preset.number)}"></label>
      <label class="field"><span>Label</span><input data-preset="${presetIndex}" data-part="label" value="${esc(preset.label)}" maxlength="24"></label>
    </div>
    <button type="button" data-action="remove-preset" data-camera-index="${index}" data-preset="${presetIndex}">Remove ${esc(preset.label || "preset")}</button>
  `).join("");
  return `
    <div class="camera" data-camera-index="${index}">
      <div class="fields two">
        <label class="field"><span>Name</span><input data-cam="name" value="${esc(camera.name)}" maxlength="40"></label>
        <label class="field"><span>IP address</span><input data-cam="host" value="${esc(camera.host)}" autocomplete="off"></label>
        <label class="field"><span>Port</span><input data-cam="port" inputmode="numeric" value="${esc(camera.port)}"></label>
        <label class="field"><span>Protocol</span>
          <select data-cam="protocol">
            <option value="visca_ip" ${camera.protocol === "visca_ip" ? "selected" : ""}>VISCA over IP</option>
            <option value="http_cgi" ${camera.protocol === "http_cgi" ? "selected" : ""} disabled>HTTP/CGI (not available yet)</option>
          </select>
        </label>
      </div>
      ${presets}
      <div class="actions">
        <button type="button" data-action="add-preset" data-camera-index="${index}">Add preset</button>
        <button type="button" data-action="test-camera" data-camera-index="${index}">Test connection</button>
        <button type="button" class="danger" data-action="remove-camera" data-camera-index="${index}">Remove camera</button>
      </div>
      <p class="sub">${esc(state.testResults[camera.id] || "")}</p>
    </div>`;
}

function layoutCard() {
  const tiles = (state.status?.dashboard || []).slice().sort((a, b) => a.order - b.order);
  const items = tiles.map((tile) => {
    const info = tileInfo(tile.id);
    return `
      <li>
        <label class="check"><input type="checkbox" data-tile-visible="${esc(tile.id)}" ${tile.visible ? "checked" : ""}> ${esc(info.name)}</label>
        <select data-tile-page="${esc(tile.id)}" aria-label="Tab for ${esc(info.name)}">
          ${[["stream", "Stream"], ["cameras", "Cameras"], ["sound", "Sound"], ["service", "Service"]].map(([page, label]) => `<option value="${page}" ${(tile.page || "stream") === page ? "selected" : ""}>${label}</option>`).join("")}
        </select>
        <button type="button" data-action="tile-up" data-tile="${esc(tile.id)}">Up</button>
        <button type="button" data-action="tile-down" data-tile="${esc(tile.id)}">Down</button>
      </li>`;
  }).join("");
  return `
    <section class="card">
      <h2>Tabs</h2>
      <p class="lead">Each tile lives on one tab. The same layout opens on every device.</p>
      <ul class="tile-order">${items}</ul>
    </section>`;
}

function tileInfo(id) {
  const fromStatus = (state.status?.placeholders || {})[id];
  if (fromStatus) return { name: fromStatus.name, implemented: false, description: fromStatus.description };
  if (id === "obs") return { name: "OBS", implemented: true };
  if (id === "ptz") return { name: "PTZ cameras", implemented: true };
  if (id === "planning_center") return { name: "Planning Center", implemented: true };
  if (id === "proclaim") return { name: "Proclaim", implemented: true };
  if (id === "mixer") return { name: "Yamaha TF3", implemented: true };
  const found = state.catalog.find((item) => item.id === id);
  return found || { name: id, implemented: false };
}

function blankSettings() {
  return {
    organization: state.organization,
    server: { host: "0.0.0.0", port: 8080 },
    obs: { host: "", port: 4455, password_set: false, use_start_scene: false, start_scene: "" },
    cameras: [],
    planning_center: { application_id: "", service_type_id: "", secret_set: false },
    proclaim: { host: "", port: 52195, password_set: false },
    mixer: { host: "", port: 49280, banks: [], dca_labels: [], scenes: [] },
    running: null,
    restart_required: false,
  };
}

function onClick(event) {
  const key = event.target.closest("[data-key]");
  if (key && state.view === "lock") {
    event.preventDefault();
    pressKey(key.dataset.key);
    return;
  }
  const pageButton = event.target.closest("[data-page]");
  if (pageButton) return showPage(pageButton.dataset.page);
  const sectionButton = event.target.closest("[data-section]");
  if (sectionButton) return showSection(sectionButton.dataset.section);
  const button = event.target.closest("[data-action]");
  if (!button || button.disabled) return;
  const action = button.dataset.action;
  if (action === "unlock-form") return;
  if (action === "lock") return lock();
  if (action === "settings") return openSettings();
  if (action === "scene") return run("obs", "set_scene", { name: button.dataset.scene });
  if (action === "go-live") return askGoLive();
  if (action === "end-stream") return askEndStream();
  if (action === "record") return toggleRecord();
  if (action === "refresh-status") return loadStatus(true).catch(toastError);
  if (action === "camera") {
    state.cameraId = button.dataset.camera;
    state.structure = "";
    renderShell();
    return;
  }
  if (action === "preset") return recallPreset(Number(button.dataset.number));
  if (action === "home") return run("ptz", "home", { camera_id: state.cameraId });
  if (action === "stop-all") return stopAll();
  if (action === "save-preset") return openSavePreset();
  if (action === "modal-confirm") return confirmModal();
  if (action === "modal-cancel") return closeModal();
  if (action === "modal-settings") {
    closeModal();
    return openSettings();
  }
  if (action === "choose-preset-save") return confirmSavePreset(Number(button.dataset.number), button.dataset.label);
  if (action === "change-passcode") return changePasscode();
  if (action === "save-settings") return saveSettings();
  if (action === "test-obs") return testObs();
  if (action === "add-camera") return addCamera();
  if (action === "add-preset") return addPreset(Number(button.dataset.cameraIndex));
  if (action === "remove-preset") return removePreset(Number(button.dataset.cameraIndex), Number(button.dataset.preset));
  if (action === "remove-camera") return removeCamera(Number(button.dataset.cameraIndex));
  if (action === "test-camera") return testCamera(Number(button.dataset.cameraIndex));
  if (action === "tile-up") return moveTile(button.dataset.tile, -1);
  if (action === "tile-down") return moveTile(button.dataset.tile, 1);
  if (action === "plan-step") return run("planning_center", "step", { delta: Number(button.dataset.delta) });
  if (action === "plan-refresh") return run("planning_center", "refresh", {});
  if (action === "proclaim") return run("proclaim", button.dataset.command, {});
  if (action === "mixer-on") return toggleMixerOn(button.dataset.target, Number(button.dataset.index));
  if (action === "mixer-bank") {
    state.mixerView = "channels";
    state.mixerBank = button.dataset.bank;
    renderShell();
    return;
  }
  if (action === "mixer-dca") {
    state.mixerView = "dca";
    renderShell();
    return;
  }
  if (action === "recall-scene") return askRecall(button.dataset.bank, Number(button.dataset.number), button.dataset.label);
  if (action === "load-service-types") return loadServiceTypes();
  if (action === "add-bank") return addBank();
  if (action === "add-scene") return addScene();
  if (action === "test-proclaim") return testIntegration("proclaim");
  if (action === "test-mixer") return testIntegration("mixer");
  if (action === "test-planning") return testIntegration("planning_center");
}

function showPage(page) {
  if (state.view === "settings") readSettingsFromDom();
  state.page = page;
  state.view = page === "settings" ? "settings" : "dashboard";
  state.structure = "";
  if (page === "settings" && !state.settings) return openSettings();
  renderShell();
}

function showSection(section) {
  readSettingsFromDom();
  state.settingsSection = section;
  renderShell();
}

function onPointerDown(event) {
  const fader = event.target.closest("[data-fader]");
  if (fader) return startFader(event, fader);
  const el = event.target.closest("[data-hold]");
  if (!el || el.disabled || (event.button !== undefined && event.button !== 0)) return;
  event.preventDefault();
  state.holding = true;
  try { el.setPointerCapture(event.pointerId); } catch (error) { /* older browsers */ }
  const stop = () => finishHold(el);
  el.addEventListener("pointerup", stop, { once: true });
  el.addEventListener("pointercancel", stop, { once: true });
  if (el.dataset.hold === "move") beginMove(el.dataset.pan, el.dataset.tilt);
  if (el.dataset.hold === "zoom") beginZoom(el.dataset.direction);
}

function finishHold(el) {
  state.holding = false;
  if (el.dataset.hold === "move") endMove();
  if (el.dataset.hold === "zoom") endZoom();
  if (state.pendingRender) renderShell();
}

function onInput(event) {
  if (event.target.dataset.action === "speed") {
    state.speed = Number(event.target.value);
    const readout = document.getElementById("speed-readout");
    if (readout) readout.textContent = String(state.speed);
  }
}

function onChange(event) {
  const pageId = event.target.dataset.tilePage;
  if (pageId && state.status) {
    const tiles = state.status.dashboard.map((tile) => ({ ...tile, page: tile.id === pageId ? event.target.value : tile.page }));
    saveTiles(tiles);
    return;
  }
  const id = event.target.dataset.tileVisible;
  if (!id || !state.status) return;
  if (state.view === "settings") readSettingsFromDom();
  const tiles = state.status.dashboard.map((tile) => ({ ...tile, visible: tile.id === id ? event.target.checked : tile.visible }));
  saveTiles(tiles);
}

function onKeyDown(event) {
  if (state.view !== "lock") {
    if (event.key === "Escape" && state.modal) closeModal();
    return;
  }
  if (/^\d$/.test(event.key)) pressKey(event.key);
  else if (event.key === "Backspace") pressKey("back");
  else if (event.key === "Escape") pressKey("clear");
  else if (event.key === "Enter") {
    event.preventDefault();
    submitPasscode();
  }
}

function pressKey(value) {
  if (state.lockoutUntil > Date.now()) return;
  if (value === "clear") state.entered = "";
  else if (value === "back") state.entered = state.entered.slice(0, -1);
  else if (state.entered.length < 8) state.entered += String(value);
  state.lockError = "";
  renderShell();
}

async function submitPasscode() {
  if (state.unlocking || state.entered.length < 4 || state.lockoutUntil > Date.now()) return;
  state.unlocking = true;
  const passcode = state.entered;
  try {
    const result = await api("/api/auth/unlock", {
      method: "POST",
      body: JSON.stringify({ passcode }),
      quietAuth: true,
    });
    state.entered = "";
    state.authed = true;
    state.mustChange = !!result.must_change_passcode;
    state.view = "dashboard";
    state.lockError = "";
    await loadStatus(true);
    render();
    maybePromptPasscode();
  } catch (error) {
    state.entered = "";
    state.shake = true;
    const retry = error.body?.retry_after || 0;
    if (error.status === 429 && retry) state.lockoutUntil = Date.now() + retry * 1000;
    const left = error.body?.attempts_remaining;
    state.lockError = left ? `${error.message} ${left} tries left.` : error.message;
    renderShell();
    setTimeout(() => { state.shake = false; }, 400);
  } finally {
    state.unlocking = false;
  }
}

function maybePromptPasscode() {
  if (!state.mustChange || state.dismissedPrompt || state.view !== "dashboard") return;
  state.modal = {
    title: "Change the default passcode",
    body: "ServiceDeck is still using 0000. Anyone on the church Wi-Fi who can open this page could control the stream until you change it.",
    confirmLabel: "Change passcode",
    cancelLabel: "Not now",
    confirmAction: "modal-settings",
  };
  renderModal();
}

async function lock() {
  try { await api("/api/auth/lock", { method: "POST", body: "{}" }); } catch (error) { /* already locked */ }
  state.authed = false;
  state.view = "lock";
  state.entered = "";
  state.modal = null;
  state.status = null;
  render();
}

async function toggleSettings() {
  if (state.view === "settings") {
    state.view = "dashboard";
    await loadStatus(true);
    render();
    return;
  }
  return openSettings();
}

async function openSettings() {
  try {
    const [config, catalog] = await Promise.all([
      api("/api/config"),
      api("/api/integrations"),
    ]);
    state.catalog = catalog.integrations || [];
    state.settings = {
      organization: config.organization,
      server: config.server,
      obs: config.obs,
      cameras: config.cameras || [],
      planning_center: config.planning_center,
      proclaim: config.proclaim,
      mixer: config.mixer,
      running: config.running,
      restart_required: config.restart_required,
    };
    state.page = "settings";
    state.view = "settings";
    state.settingsMessage = "";
    renderShell();
  } catch (error) {
    toastError(error);
  }
}

function askGoLive() {
  const obs = state.status?.obs || {};
  const scene = obs.use_start_scene && obs.start_scene
    ? `The program scene will switch to “${obs.start_scene}”, then the stream will start. `
    : "";
  state.modal = {
    title: "Go Live?",
    body: `${scene}OBS will use the Facebook stream key already saved in OBS. ServiceDeck never sees that key.`,
    confirmLabel: "Go Live",
    danger: true,
    onConfirm: () => run("obs", "go_live", { confirm: true }),
  };
  renderModal();
}

function askEndStream() {
  state.modal = {
    title: "End the stream?",
    body: "This stops the Facebook stream. Recording, if it is running, keeps going.",
    confirmLabel: "End Stream",
    danger: true,
    onConfirm: () => run("obs", "end_stream", { confirm: true }),
  };
  renderModal();
}

function toggleRecord() {
  const recording = !!state.status?.obs?.recording;
  return run("obs", recording ? "stop_record" : "start_record", {});
}

function recallPreset(number) {
  return run("ptz", "recall_preset", { camera_id: state.cameraId, number });
}

function openSavePreset() {
  const camera = currentCamera();
  if (!camera) return;
  const buttons = (camera.presets || []).map((preset) =>
    `<button type="button" data-action="choose-preset-save" data-number="${preset.number}" data-label="${esc(preset.label)}">${esc(preset.label)}</button>`
  ).join("");
  state.modal = {
    title: "Save into which preset?",
    body: "You will be asked to confirm before the camera memory is overwritten.",
    extra: `<div class="presets">${buttons}</div>`,
    cancelLabel: "Cancel",
  };
  renderModal();
}

function confirmSavePreset(number, label) {
  const camera = currentCamera();
  state.modal = {
    title: `Save over “${label}”?`,
    body: `This replaces preset ${number} on ${camera ? camera.name : "the camera"} with where it is pointing right now.`,
    confirmLabel: "Save preset",
    danger: true,
    onConfirm: () => run("ptz", "save_preset", { confirm: true, camera_id: state.cameraId, number }),
  };
  renderModal();
}

function beginMove(pan, tilt) {
  clearTimeout(state.moveTimer);
  const generation = ++state.moveGen;
  postQuiet("/api/integrations/ptz/actions/move", {
    camera_id: state.cameraId,
    pan,
    tilt,
    speed: state.speed,
    generation,
  });
}

function endMove() {
  const generation = ++state.moveGen;
  const cameraId = state.cameraId;
  postQuiet("/api/integrations/ptz/actions/stop", { camera_id: cameraId, target: "move", generation });
  const scheduled = generation;
  state.moveTimer = setTimeout(() => {
    if (state.moveGen === scheduled) {
      postQuiet("/api/integrations/ptz/actions/stop", {
        camera_id: cameraId,
        target: "move",
        generation: ++state.moveGen,
      });
    }
  }, 150);
}

function beginZoom(direction) {
  clearTimeout(state.zoomTimer);
  const generation = ++state.zoomGen;
  postQuiet("/api/integrations/ptz/actions/zoom", {
    camera_id: state.cameraId,
    direction,
    speed: state.speed,
    generation,
  });
}

function endZoom() {
  const generation = ++state.zoomGen;
  const cameraId = state.cameraId;
  postQuiet("/api/integrations/ptz/actions/stop", { camera_id: cameraId, target: "zoom", generation });
  const scheduled = generation;
  state.zoomTimer = setTimeout(() => {
    if (state.zoomGen === scheduled) {
      postQuiet("/api/integrations/ptz/actions/stop", {
        camera_id: cameraId,
        target: "zoom",
        generation: ++state.zoomGen,
      });
    }
  }, 150);
}

function stopAll() {
  clearTimeout(state.moveTimer);
  clearTimeout(state.zoomTimer);
  const generation = ++state.moveGen;
  const zoomGeneration = ++state.zoomGen;
  postQuiet("/api/integrations/ptz/actions/stop", {
    camera_id: state.cameraId,
    target: "all",
    generation,
    zoom_generation: zoomGeneration,
  });
}

async function run(integration, action, payload) {
  closeModal();
  if (state.busy) return;
  state.busy = true;
  try {
    const result = await api(`/api/integrations/${integration}/actions/${action}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (result?.message) showToast(result.message);
    await loadStatus(true);
  } catch (error) {
    toastError(error);
  } finally {
    state.busy = false;
  }
}

function postQuiet(path, payload) {
  api(path, { method: "POST", body: JSON.stringify(payload) }).catch((error) => {
    if (!error.silent) showToast(error.message);
  });
}

async function changePasscode() {
  const root = document.getElementById("shell");
  const current = root.querySelector('[name="current-passcode"]').value;
  const next = root.querySelector('[name="new-passcode"]').value;
  const again = root.querySelector('[name="confirm-passcode"]').value;
  if (next !== again) {
    state.settingsMessage = "The new passcode and the repeat do not match.";
    renderShell();
    return;
  }
  try {
    await api("/api/auth/passcode", { method: "POST", body: JSON.stringify({ current, new: next }) });
    state.mustChange = false;
    state.settingsMessage = "Passcode changed.";
    showToast("Passcode changed.");
    renderShell();
  } catch (error) {
    state.settingsMessage = error.message;
    renderShell();
  }
}

function readSettingsFromDom() {
  const root = document.getElementById("settings");
  if (!root || !state.settings) return state.settings;
  const draft = state.settings;
  const organization = root.querySelector('[name="organization"]');
  if (organization) draft.organization = organization.value;
  const serverPort = root.querySelector('[name="server-port"]');
  if (serverPort) draft.server.port = Number(serverPort.value) || draft.server.port;
  const obsHost = root.querySelector('[name="obs-host"]');
  if (obsHost) {
    draft.obs.host = obsHost.value.trim();
    draft.obs.port = Number(value(root, "obs-port")) || 4455;
    draft.obs.start_scene = value(root, "obs-start-scene").trim();
    draft.obs.use_start_scene = root.querySelector('[name="obs-use-start"]').checked;
    draft.obs._password = value(root, "obs-password");
    draft.obs._clearPassword = root.querySelector('[name="obs-clear-password"]').checked;
  }
  const planApp = root.querySelector('[name="pco-app"]');
  if (planApp) {
    draft.planning_center = draft.planning_center || {};
    draft.planning_center.application_id = planApp.value.trim();
    draft.planning_center.service_type_id = value(root, "pco-type").trim();
    draft.planning_center._secret = value(root, "pco-secret");
    draft.planning_center._clearSecret = root.querySelector('[name="pco-clear"]').checked;
  }
  const proclaimHost = root.querySelector('[name="proclaim-host"]');
  if (proclaimHost) {
    draft.proclaim = draft.proclaim || { port: 52195 };
    draft.proclaim.host = proclaimHost.value.trim();
    draft.proclaim._password = value(root, "proclaim-password");
    draft.proclaim._clearPassword = root.querySelector('[name="proclaim-clear"]').checked;
  }
  const mixerHost = root.querySelector('[name="mixer-host"]');
  if (mixerHost) readMixerFromDom(root, draft);
  root.querySelectorAll(".camera").forEach((block) => {
    const index = Number(block.dataset.cameraIndex);
    const camera = draft.cameras[index];
    if (!camera) return;
    camera.name = block.querySelector('[data-cam="name"]').value.trim();
    camera.host = block.querySelector('[data-cam="host"]').value.trim();
    camera.port = Number(block.querySelector('[data-cam="port"]').value) || 52381;
    camera.protocol = block.querySelector('[data-cam="protocol"]').value;
    block.querySelectorAll("[data-preset][data-part]").forEach((input) => {
      const preset = camera.presets[Number(input.dataset.preset)];
      if (!preset) return;
      if (input.dataset.part === "number") preset.number = Number(input.value);
      if (input.dataset.part === "label") preset.label = input.value.trim();
    });
  });
  return draft;
}

function settingsPayload(draft) {
  const obs = {
    host: draft.obs.host,
    port: Number(draft.obs.port) || 4455,
    use_start_scene: !!draft.obs.use_start_scene,
    start_scene: draft.obs.start_scene || "",
  };
  if (draft.obs._clearPassword) obs.password = "";
  else if (draft.obs._password) obs.password = draft.obs._password;
  const planning = {
    application_id: draft.planning_center?.application_id || "",
    service_type_id: draft.planning_center?.service_type_id || "",
  };
  if (draft.planning_center?._clearSecret) planning.secret = "";
  else if (draft.planning_center?._secret) planning.secret = draft.planning_center._secret;
  const proclaim = { host: draft.proclaim?.host || "", port: 52195 };
  if (draft.proclaim?._clearPassword) proclaim.password = "";
  else if (draft.proclaim?._password) proclaim.password = draft.proclaim._password;
  return {
    organization: draft.organization,
    server: { host: draft.server.host || "0.0.0.0", port: Number(draft.server.port) || 8080 },
    obs,
    planning_center: planning,
    proclaim,
    mixer: draft.mixer,
    cameras: draft.cameras.map((camera) => ({
      id: camera.id || "",
      name: camera.name,
      host: camera.host,
      port: Number(camera.port) || 52381,
      protocol: camera.protocol || "visca_ip",
      presets: (camera.presets || []).map((preset) => ({
        number: Number(preset.number),
        label: preset.label,
      })),
    })),
  };
}

async function saveSettings() {
  const payload = settingsPayload(readSettingsFromDom());
  try {
    const saved = await api("/api/config", { method: "PUT", body: JSON.stringify(payload) });
    state.settings = {
      organization: saved.organization,
      server: saved.server,
      obs: saved.obs,
      cameras: saved.cameras || [],
      planning_center: saved.planning_center,
      proclaim: saved.proclaim,
      mixer: saved.mixer,
      running: saved.running,
      restart_required: saved.restart_required,
    };
    state.organization = saved.organization;
    state.settingsMessage = saved.restart_required
      ? "Saved. Restart ServiceDeck to use the new port."
      : "Saved.";
    showToast("Devices saved.");
    renderShell();
    return true;
  } catch (error) {
    state.settingsMessage = error.message;
    renderShell();
    return false;
  }
}

async function testObs() {
  if (!(await saveSettings())) return;
  try {
    const result = await api("/api/integrations/obs/test", { method: "POST", body: "{}" });
    state.testResults.obs = result.message;
  } catch (error) {
    state.testResults.obs = error.message;
  }
  renderShell();
}

function addCamera() {
  readSettingsFromDom();
  state.settings.cameras.push({
    id: "",
    name: "Camera",
    host: "",
    port: 52381,
    protocol: "visca_ip",
    presets: [
      { number: 1, label: "Wide" },
      { number: 2, label: "Pulpit" },
      { number: 3, label: "Piano" },
    ],
  });
  renderShell();
}

function addPreset(index) {
  readSettingsFromDom();
  const camera = state.settings.cameras[index];
  const used = new Set(camera.presets.map((preset) => Number(preset.number)));
  let number = 1;
  while (used.has(number) && number < 64) number += 1;
  camera.presets.push({ number, label: "Preset" });
  renderShell();
}

function removePreset(cameraIndex, presetIndex) {
  readSettingsFromDom();
  state.settings.cameras[cameraIndex].presets.splice(presetIndex, 1);
  renderShell();
}

function removeCamera(index) {
  readSettingsFromDom();
  const camera = state.settings.cameras[index];
  state.modal = {
    title: `Remove ${camera.name}?`,
    body: "The camera stays on the network. It only disappears from this dashboard.",
    confirmLabel: "Remove",
    danger: true,
    onConfirm: () => {
      state.settings.cameras.splice(index, 1);
      closeModal();
      renderShell();
    },
  };
  renderModal();
}

async function testCamera(index) {
  if (!(await saveSettings())) return;
  const camera = state.settings?.cameras?.[index];
  if (!camera?.id) return;
  try {
    const result = await api("/api/integrations/ptz/test", {
      method: "POST",
      body: JSON.stringify({ camera_id: camera.id }),
    });
    state.testResults[camera.id] = result.message;
  } catch (error) {
    state.testResults[camera.id] = error.message;
  }
  renderShell();
}

async function saveTiles(tiles) {
  try {
    const saved = await api("/api/dashboard", { method: "PUT", body: JSON.stringify({ tiles }) });
    if (state.status) state.status.dashboard = saved.tiles;
    state.structure = "";
    showToast("Layout saved.");
    if (state.view === "settings") renderShell();
  } catch (error) {
    toastError(error);
    if (state.view === "settings") renderShell();
  }
}

function moveTile(id, direction) {
  if (state.view === "settings") readSettingsFromDom();
  const tiles = (state.status?.dashboard || []).slice().sort((a, b) => a.order - b.order);
  const index = tiles.findIndex((tile) => tile.id === id);
  const next = index + direction;
  if (index < 0 || next < 0 || next >= tiles.length) return;
  const swapped = tiles.slice();
  const [item] = swapped.splice(index, 1);
  swapped.splice(next, 0, item);
  saveTiles(swapped.map((tile, order) => ({ ...tile, order })));
}

function confirmModal() {
  const action = state.modal && state.modal.onConfirm;
  closeModal();
  if (action) action();
}

function closeModal() {
  if (state.modal && state.modal.confirmAction === "modal-settings") state.dismissedPrompt = true;
  state.modal = null;
  renderModal();
}

function renderModal() {
  const root = document.getElementById("modal-root");
  if (!root) return;
  const modal = state.modal;
  if (!modal) {
    root.innerHTML = "";
    return;
  }
  const confirm = modal.confirmLabel
    ? `<button type="button" class="${modal.danger ? "danger" : "primary"}" data-action="${modal.confirmAction || "modal-confirm"}">${esc(modal.confirmLabel)}</button>`
    : "";
  root.innerHTML = `
    <div class="modal-back">
      <div class="modal" role="dialog" aria-modal="true" aria-label="${esc(modal.title)}">
        <h2>${esc(modal.title)}</h2>
        <p>${esc(modal.body || "")}</p>
        ${modal.extra || ""}
        <div class="actions">
          <button type="button" data-action="modal-cancel">${esc(modal.cancelLabel || "Cancel")}</button>
          ${confirm}
        </div>
      </div>
    </div>`;
}

function patch() {
  const obs = state.status?.obs;
  if (!obs) return;
  const pills = document.querySelector("[data-bind='obs-pills']");
  if (pills) pills.innerHTML = obsPills(obs);
  const timer = document.querySelector("[data-bind='obs-timer']");
  if (timer) timer.textContent = obs.streaming ? (obs.stream_timecode || "00:00:00") : "Off air";
  document.querySelectorAll("[data-scene]").forEach((button) => {
    button.classList.toggle("active", button.dataset.scene === obs.current_scene);
  });
  const camera = currentCamera();
  if (camera) {
    const badge = document.querySelector(`[data-cam-state="${cssEscape(camera.id)}"]`);
    if (badge) badge.innerHTML = cameraPill(camera);
    const message = document.querySelector("[data-bind='cam-message']");
    if (message) message.textContent = camera.message || "";
  }
  patchPlan();
  patchMixer();
}

function patchPlan() {
  const plan = state.status?.planning_center;
  if (!plan) return;
  document.querySelectorAll("[data-item]").forEach((row) => {
    row.classList.toggle("current", row.dataset.item === plan.current_item_id);
  });
}

function patchMixer() {
  document.querySelectorAll("[data-fader]").forEach((el) => {
    const key = `${el.dataset.fader}:${el.dataset.index}`;
    if (state.dragKey === key) return;
    const strip = mixerStrip(el.dataset.fader, Number(el.dataset.index));
    if (!strip || strip.level == null) return;
    el.style.setProperty("--pos", String(levelToSlider(strip.level)));
    const label = el.closest(".strip")?.querySelector(".strip-level");
    if (label) label.textContent = formatLevel(strip.level);
    const button = el.closest(".strip")?.querySelector("[data-action='mixer-on']");
    if (button && strip.on != null) {
      button.classList.toggle("on", !!strip.on);
      button.textContent = strip.on ? "On" : "Off";
    }
  });
}

function currentCamera() {
  const cameras = state.status?.ptz?.cameras || [];
  return cameras.find((camera) => camera.id === state.cameraId) || cameras[0] || null;
}

async function api(path, options = {}) {
  const quietAuth = !!options.quietAuth;
  const response = await fetch(path, {
    method: options.method || "GET",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: options.body,
  });
  let body = null;
  try { body = await response.json(); } catch (error) { body = null; }
  if (response.status === 401 && !quietAuth) {
    if (state.authed) {
      state.authed = false;
      state.view = "lock";
      state.entered = "";
      state.modal = null;
      render();
    }
    const error = new Error(body?.message || "Unlock ServiceDeck first.");
    error.silent = true;
    error.status = 401;
    throw error;
  }
  if (!response.ok) {
    const error = new Error(body?.message || "Request failed.");
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

function showToast(text) {
  const toast = document.getElementById("toast");
  if (!toast || !text) return;
  toast.textContent = text;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2200);
}

function toastError(error) {
  if (error && !error.silent) showToast(error.message || "Something went wrong.");
}

function value(root, name) {
  const field = root.querySelector(`[name="${name}"]`);
  return field ? field.value : "";
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[character]));
}

function cssEscape(value) {
  if (window.CSS && CSS.escape) return CSS.escape(value);
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "");
}

function markSvg() {
  return `<svg class="mark" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="14" fill="#17161a"/><rect x="12" y="14" width="40" height="28" rx="4" fill="none" stroke="#e0a45a" stroke-width="3"/><circle cx="46" cy="46" r="6" fill="#e23b3b"/></svg>`;
}

document.addEventListener("submit", (event) => {
  if (event.target.matches("[data-action='unlock-form']")) {
    event.preventDefault();
    submitPasscode();
  }
});

function planTile(plan) {
  if (!plan || plan.state === "not_configured") {
    return `<article class="tile"><h2>Planning Center</h2><p class="empty">${esc(plan?.message || "Add a token in Settings.")}</p></article>`;
  }
  const body = plan.plan;
  if (!body) {
    return `<article class="tile"><h2>Planning Center</h2><p class="empty">${esc(plan.message || "No plan for this service type.")}</p></article>`;
  }
  const items = (body.items || []).map((item) => `
    <div class="order-item ${item.id === plan.current_item_id ? "current" : ""}" data-item="${esc(item.id)}">
      <span class="kind">${esc(item.item_type)}</span>
      <span class="title">${esc(item.title)}</span>
      <span class="kind">${esc(clock(item.length_seconds))}</span>
    </div>`).join("");
  const people = (body.people || []).map((person) => `
    <div class="person"><span class="team">${esc(person.team)} ${esc(person.position)}</span><span class="who">${esc(person.name)}</span><span class="kind">${esc(person.status)}</span></div>
  `).join("");
  const steps = plan.current_source === "live" ? "" : `
    <div class="row-2">
      <button type="button" data-action="plan-step" data-delta="-1">Previous</button>
      <button type="button" data-action="plan-step" data-delta="1">Next</button>
    </div>`;
  return `
    <article class="tile">
      <div class="tile-head">
        <h2>${esc(body.title)}</h2>
        <div class="pills">${plan.current_source === "live" ? pill("Live", "live") : pill("Manual", "")}${plan.stale ? pill("Saved", "bad") : pill("Online", "ok")}</div>
      </div>
      <p class="sub">${esc(body.dates)} ${esc(plan.service_type_name)} ${esc(plan.message)}</p>
      <div class="order-list">${items}</div>
      <div class="people-list">${people}</div>
      ${steps}
      <button type="button" data-action="plan-refresh">Refresh</button>
    </article>`;
}

function proclaimTile(proclaim) {
  const commands = proclaim.commands || [];
  const button = (id) => {
    const command = commands.find((item) => item.id === id);
    if (!command) return "";
    const disabled = proclaim.connected ? "" : "disabled";
    return `<button type="button" data-action="proclaim" data-command="${esc(id)}" class="${command.verified ? "" : "unverified"}" ${disabled}>${esc(command.label)}</button>`;
  };
  return `
    <article class="tile">
      <div class="tile-head">
        <h2>Proclaim</h2>
        <div class="pills">${proclaim.connected ? pill(proclaim.on_air ? "On air" : "Off air", proclaim.on_air ? "live" : "ok") : pill("No reply", "bad")}</div>
      </div>
      <p class="sub">${esc(proclaim.message || proclaim.note || "")}</p>
      <div class="proclaim-grid">
        ${button("previous_slide")}
        ${button("next_slide")}
        ${button("previous_item")}
        ${button("next_item")}
      </div>
      <div class="section-grid">
        ${button("start_pre_service")}
        ${button("start_warm_up")}
        ${button("start_service")}
        ${button("start_post_service")}
      </div>
      <p class="sub">Previous slide and the item buttons use command names that are not in the public Proclaim list we could confirm. On Air is the only status Proclaim documents.</p>
    </article>`;
}

function mixerTile(mixer) {
  const banks = mixer.banks || [];
  if (!state.mixerBank && banks[0]) state.mixerBank = banks[0].id;
  const bank = banks.find((item) => item.id === state.mixerBank) || banks[0];
  const bankButtons = banks.map((item) =>
    `<button type="button" data-action="mixer-bank" data-bank="${esc(item.id)}" class="${state.mixerView === "channels" && bank && item.id === bank.id ? "active" : ""}">${esc(item.name)}</button>`
  ).join("");
  const strips = state.mixerView === "dca"
    ? (mixer.dca_labels || []).map((label, index) => stripHtml("dca", index, label, mixer))
    : (bank?.channels || []).map((channel) => stripHtml("input", channel.index, channel.label, mixer));
  const scenes = (mixer.scenes || []).map((scene) =>
    `<button type="button" data-action="recall-scene" data-bank="${esc(scene.bank)}" data-number="${scene.number}" data-label="${esc(scene.label)}">${esc(scene.label)}</button>`
  ).join("");
  return `
    <article class="tile">
      <div class="mixer">
        <div class="tile-head">
          <h2>TF3</h2>
          <div class="pills">${mixer.connected ? pill("Connected", "ok") : pill(mixer.state === "not_configured" ? "Not set up" : "No reply", "bad")}</div>
        </div>
        <div class="bank-row">${bankButtons}<button type="button" data-action="mixer-dca" class="${state.mixerView === "dca" ? "active" : ""}">DCAs</button></div>
        <div class="strips">
          ${stripHtml("master", 0, "Master", mixer)}
          ${strips}
        </div>
        <div class="scene-row">${scenes}</div>
        <p class="sub">${esc(mixer.message || "")}</p>
      </div>
    </article>`;
}

function stripHtml(target, index, label, mixer) {
  const strip = mixerStrip(target, index) || {};
  const pos = strip.level == null ? 0.75 : levelToSlider(strip.level);
  const on = strip.on !== false;
  const consoleName = target === "input" ? `Ch ${index + 1}` : target === "dca" ? `DCA ${index + 1}` : "Master";
  return `
    <div class="strip ${target === "master" ? "master" : ""}">
      <span class="strip-name">${esc(label || consoleName)}</span>
      <span class="strip-level">${strip.level == null ? "—" : esc(formatLevel(strip.level))}</span>
      <div class="fader" data-fader="${target}" data-index="${index}" style="--pos: ${pos}">
        <div class="fader-track"><div class="fader-fill"></div></div>
      </div>
      <button type="button" data-action="mixer-on" data-target="${target}" data-index="${index}" class="${on ? "on" : ""}">${on ? "On" : "Off"}</button>
    </div>`;
}

function mixerStrip(target, index) {
  return (state.status?.mixer?.strips || {})[`${target}:${index}`];
}

function soundCard(draft) {
  const mixer = draft.mixer || { banks: [], dca_labels: [], scenes: [] };
  const bankId = state.soundBank || mixer.banks[0]?.id || "";
  state.soundBank = bankId;
  const bank = (mixer.banks || []).find((item) => item.id === bankId) || mixer.banks[0];
  const pills = (mixer.banks || []).map((item) =>
    `<button type="button" data-sound-bank="${esc(item.id)}" class="${item.id === bankId ? "active" : ""}">${esc(item.name)}</button>`
  ).join("");
  const slots = (bank?.channels || []).map((channel, index) => `
    <div class="compact-row" data-slot="${index}">
      <input data-slot-channel inputmode="numeric" aria-label="Channel ${index + 1}" value="${channel.index + 1}">
      <input data-slot-label aria-label="Label ${index + 1}" value="${esc(channel.label)}" maxlength="16">
    </div>`).join("");
  const dcas = (mixer.dca_labels || []).map((label, index) =>
    `<input data-dca-label aria-label="DCA ${index + 1}" value="${esc(label)}" maxlength="16">`
  ).join("");
  const scenes = (mixer.scenes || []).map((scene, index) => `
    <div class="scene-edit" data-scene-row="${index}">
      <select data-scene-bank aria-label="Scene bank"><option value="a" ${scene.bank === "a" ? "selected" : ""}>A</option><option value="b" ${scene.bank === "b" ? "selected" : ""}>B</option></select>
      <input data-scene-number inputmode="numeric" aria-label="Scene number" value="${scene.number}">
      <input data-scene-label aria-label="Scene label" value="${esc(scene.label)}" maxlength="24">
    </div>`).join("");
  return `
    <section class="card" data-editing-bank="${esc(bankId)}">
      <h2>Yamaha TF3</h2>
      <div class="fields two">
        <label class="field"><span>Mixer IP</span><input name="mixer-host" value="${esc(mixer.host || "")}" autocomplete="off"></label>
        <label class="field"><span>Port</span><input value="49280" disabled></label>
      </div>
      <div class="actions">
        <button type="button" class="primary" data-action="save-settings">Save</button>
        <button type="button" data-action="test-mixer">Test connection</button>
        <button type="button" data-action="add-bank">Add bank</button>
      </div>
      <p class="sub">${esc(state.testResults.mixer || "")}</p>
      <div class="bank-row">${pills}</div>
      <div class="slot-grid">${slots}</div>
      <p class="sub">DCAs</p>
      <div class="dca-grid">${dcas}</div>
      <p class="sub">Scenes</p>
      ${scenes}
      <button type="button" data-action="add-scene">Add scene</button>
    </section>`;
}

function serviceCard(draft) {
  const plan = draft.planning_center || {};
  const proclaim = draft.proclaim || {};
  const types = state.serviceTypes || plan.service_types || [];
  const typeField = types.length
    ? `<select name="pco-type">${types.map((row) => `<option value="${esc(row.id)}" ${row.id === plan.service_type_id ? "selected" : ""}>${esc(row.name)}</option>`).join("")}</select>`
    : `<input name="pco-type" value="${esc(plan.service_type_id || "")}" placeholder="Service type id">`;
  return `
    <section class="card">
      <h2>Planning Center</h2>
      <p class="lead">Personal access token from Planning Center developer settings. The secret stays on this computer.</p>
      <div class="fields two">
        <label class="field"><span>Application ID</span><input name="pco-app" value="${esc(plan.application_id || "")}" autocomplete="off"></label>
        <label class="field"><span>Secret</span><input name="pco-secret" type="password" placeholder="${plan.secret_set ? "Saved — leave blank to keep" : "Secret"}" autocomplete="new-password"></label>
        <label class="field"><span>Service type</span>${typeField}</label>
      </div>
      <label class="check"><input type="checkbox" name="pco-clear"> Remove the saved secret</label>
      <div class="actions">
        <button type="button" class="primary" data-action="save-settings">Save</button>
        <button type="button" data-action="test-planning">Test connection</button>
        <button type="button" data-action="load-service-types">Load service types</button>
      </div>
      <p class="sub">${esc(state.testResults.planning_center || "")}</p>
      <h2>Proclaim</h2>
      <p class="lead">Settings, Remote, Enable. Port 52195 cannot be changed in Proclaim.</p>
      <div class="fields two">
        <label class="field"><span>Proclaim computer IP</span><input name="proclaim-host" value="${esc(proclaim.host || "")}" autocomplete="off"></label>
        <label class="field"><span>Network password</span><input name="proclaim-password" type="password" placeholder="${proclaim.password_set ? "Saved — leave blank to keep" : "proclaim"}" autocomplete="new-password"></label>
      </div>
      <label class="check"><input type="checkbox" name="proclaim-clear"> Remove the saved password</label>
      <div class="actions">
        <button type="button" data-action="test-proclaim">Test Proclaim</button>
      </div>
      <p class="sub">${esc(state.testResults.proclaim || "")}</p>
    </section>`;
}

function readMixerFromDom(root, draft) {
  const mixer = draft.mixer || { banks: [], dca_labels: [], scenes: [] };
  mixer.host = value(root, "mixer-host").trim();
  mixer.port = 49280;
  const bankId = root.querySelector("[data-editing-bank]")?.dataset.editingBank;
  const channels = [];
  root.querySelectorAll("[data-slot]").forEach((row) => {
    const number = Number(row.querySelector("[data-slot-channel]").value);
    const label = row.querySelector("[data-slot-label]").value.trim();
    if (!number) return;
    channels.push({ index: number - 1, label: label || `Ch ${number}` });
  });
  mixer.banks = (mixer.banks || []).map((bank) => (bank.id === bankId ? { ...bank, channels: channels.slice(0, 8) } : bank));
  const labels = [];
  root.querySelectorAll("[data-dca-label]").forEach((input) => labels.push(input.value.trim() || "DCA"));
  if (labels.length === 8) mixer.dca_labels = labels;
  const scenes = [];
  root.querySelectorAll("[data-scene-row]").forEach((row) => {
    scenes.push({
      bank: row.querySelector("[data-scene-bank]").value,
      number: Number(row.querySelector("[data-scene-number]").value) || 0,
      label: row.querySelector("[data-scene-label]").value.trim() || "Scene",
    });
  });
  if (root.querySelector("[data-scene-row]")) mixer.scenes = scenes;
  draft.mixer = mixer;
}

function addBank() {
  readSettingsFromDom();
  const mixer = state.settings.mixer;
  const start = mixer.banks.reduce((max, bank) => Math.max(max, ...bank.channels.map((channel) => channel.index)), -1) + 1;
  const number = mixer.banks.length + 1;
  mixer.banks.push({
    id: `bank${number}`,
    name: `Bank ${number}`,
    channels: Array.from({ length: 8 }, (_, offset) => ({ index: Math.min(39, start + offset), label: `Ch ${Math.min(40, start + offset + 1)}` })),
  });
  state.soundBank = `bank${number}`;
  renderShell();
}

function addScene() {
  readSettingsFromDom();
  state.settings.mixer.scenes.push({ bank: "a", number: state.settings.mixer.scenes.length, label: `A${state.settings.mixer.scenes.length}` });
  renderShell();
}

function startFader(event, el) {
  if (event.button !== undefined && event.button !== 0) return;
  event.preventDefault();
  state.holding = true;
  state.dragKey = `${el.dataset.fader}:${el.dataset.index}`;
  const move = (ev) => moveFader(el, ev.clientY, false);
  const finish = (ev) => {
    moveFader(el, ev.clientY, true);
    state.holding = false;
    state.dragKey = "";
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", finish);
    if (state.pendingRender) renderShell();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", finish);
  moveFader(el, event.clientY, false);
}

function moveFader(el, clientY, immediate) {
  const rect = el.getBoundingClientRect();
  const fraction = rect.height ? Math.min(1, Math.max(0, (rect.bottom - clientY) / rect.height)) : 0;
  el.style.setProperty("--pos", String(fraction));
  const level = sliderToLevel(fraction);
  const label = el.closest(".strip")?.querySelector(".strip-level");
  if (label) label.textContent = formatLevel(level);
  state.pendingLevel = { target: el.dataset.fader, index: Number(el.dataset.index), level };
  if (immediate) {
    clearTimeout(moveFader.timer);
    postQuiet("/api/integrations/mixer/actions/set_level", state.pendingLevel);
    return;
  }
  if (moveFader.timer) return;
  moveFader.timer = setTimeout(() => {
    moveFader.timer = null;
    if (state.pendingLevel) postQuiet("/api/integrations/mixer/actions/set_level", state.pendingLevel);
  }, 80);
}

function toggleMixerOn(target, index) {
  const strip = mixerStrip(target, index) || {};
  const on = strip.on === false;
  postQuiet("/api/integrations/mixer/actions/set_on", { target, index, on });
  if (state.status?.mixer) {
    state.status.mixer.strips = state.status.mixer.strips || {};
    const key = `${target}:${index}`;
    state.status.mixer.strips[key] = { ...(state.status.mixer.strips[key] || {}), on };
  }
  patchMixer();
}

function askRecall(bank, number, label) {
  state.modal = {
    title: `Recall ${label}?`,
    body: "This recalls that scene on the Yamaha TF3.",
    confirmLabel: "Recall",
    danger: true,
    onConfirm: () => run("mixer", "recall_scene", { bank, number, confirm: true }),
  };
  renderModal();
}

async function loadServiceTypes() {
  await testIntegration("planning_center");
}

async function testIntegration(id) {
  if (!(await saveSettings())) return;
  try {
    const result = await api(`/api/integrations/${id}/test`, { method: "POST", body: "{}" });
    state.testResults[id] = result.message;
    if (result.service_types) state.serviceTypes = result.service_types;
  } catch (error) {
    state.testResults[id] = error.message;
  }
  renderShell();
}

function sliderToLevel(position) {
  if (position <= 0.005) return -32768;
  const db = -60 + Math.min(1, Math.max(0, position)) * 70;
  return Math.max(-32768, Math.min(1000, Math.round(db * 100)));
}

function levelToSlider(level) {
  if (level <= -6000) return 0;
  const db = Math.max(-60, Math.min(10, level / 100));
  return (db + 60) / 70;
}

function formatLevel(level) {
  if (level <= -32768) return "−∞";
  const text = (level / 100).toFixed(1);
  return text === "-0.0" ? "0.0" : text;
}

function clock(seconds) {
  const total = Number(seconds) || 0;
  if (!total) return "";
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

document.addEventListener("click", (event) => {
  const bank = event.target.closest("[data-sound-bank]");
  if (!bank) return;
  readSettingsFromDom();
  state.soundBank = bank.dataset.soundBank;
  renderShell();
});
