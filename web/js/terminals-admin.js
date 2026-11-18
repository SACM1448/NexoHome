"use strict";
const page = document.body.dataset.page;
const message = document.querySelector("#message");
const management = document.querySelector("#management");
const loginForm = document.querySelector("#login-form");
const logoutButton = document.querySelector("#logout");
const codeElement = document.querySelector("#pairing-code");
let csrf = null;
let codeId = null;
let codeTimer = null;
let refreshTimer = null;
let authenticated = false;
let loading = false;
const stateNames = {linked: "Vigente", expired: "Caducado", revoked: "Revocado", pending: "Pendiente", consumed: "Utilizado", locked: "Bloqueado"};
const metricNames = {cpu_percent: "Uso de CPU", ram_percent: "Uso de RAM", ram_used_bytes: "RAM usada", ram_total_bytes: "RAM total", storage_percent: "Almacenamiento usado", storage_free_bytes: "Almacenamiento libre", system_uptime_seconds: "Actividad del sistema visible", service_uptime_seconds: "Actividad de NEXO", process_rss_bytes: "RAM del proceso NEXO", cpu_temperature_celsius: "Temperatura de CPU"};
const eventNames = {admin_initialized: "Administrador creado", login_success: "Inicio de sesión", login_failure: "Intento de acceso fallido", login_limited: "Límite de acceso", logout: "Cierre de sesión", session_revoked: "Sesión revocada", admin_access_denied: "Acceso administrativo denegado", terminal_paired: "Terminal vinculado", terminal_revoked: "Terminal revocado", terminal_renamed: "Nombre actualizado", terminal_permissions_changed: "Permisos actualizados", pairing_code_created: "Código de vinculación creado", pairing_code_revoked: "Código de vinculación revocado"};
const resultNames = {success: "Correcto", failure: "Fallido", denied: "Denegado"};
Object.assign(eventNames, {terminal_linked: "Terminal vinculado", pairing_created: "Código de vinculación creado", pairing_revoked: "Código de vinculación revocado", pairing_limited: "Límite de vinculación", pairing_failed: "Vinculación rechazada", terminal_permissions: "Permisos actualizados", terminal_access_denied: "Acceso de terminal denegado", terminal_permission_denied: "Permiso de terminal denegado"});
const reasonNames = {new_login: "Nuevo inicio de sesión", invalid_session: "Sesión inválida", csrf: "Verificación CSRF", origin: "Origen no autorizado", authorization_header: "Credencial no administrativa", invalid_credential: "Credencial inválida", invalid_code: "Código inválido", "terminal.status": "Consultar estado", "terminal.chat": "Conversación"};

function element(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}
function display(id, ...children) { document.getElementById(id).replaceChildren(...children); }
function badge(text, tone = "neutral") { return element("span", text, `badge badge-${tone}`); }
function hideCode() { if (codeElement) codeElement.textContent = ""; clearTimeout(codeTimer); }
function signedIn(value) {
  authenticated = value;
  clearTimeout(refreshTimer);
  management.hidden = !value;
  loginForm.hidden = value;
  logoutButton.hidden = !value;
  if (!value) {
    csrf = null; codeId = null; hideCode();
    document.querySelectorAll("[data-private]").forEach(item => item.replaceChildren());
    for (const id of ["code-status", "code-revoke"]) {
      const control = document.getElementById(id); if (control) control.hidden = true;
    }
  }
}
async function api(path, method = "GET", payload) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const headers = {};
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    if (method !== "GET" && csrf) headers["X-CSRF-Token"] = csrf;
    const response = await fetch(`/api/v1/${path}`, {method, headers, credentials: "same-origin", cache: "no-store", body: payload === undefined ? undefined : JSON.stringify(payload), signal: controller.signal});
    const result = response.status === 204 ? null : await response.json();
    if (!response.ok) {
      if (response.status === 401) signedIn(false);
      throw new Error(result.detail || "No se pudo completar la solicitud");
    }
    return result;
  } finally { clearTimeout(timeout); }
}
async function act(callback) {
  try { await callback(); }
  catch (error) { message.textContent = error.name === "AbortError" ? "La consulta tardó demasiado. Puedes intentarlo de nuevo." : error.message; message.dataset.state = "error"; }
}
function button(label, callback, className) {
  const control = element("button", label, className); control.type = "button";
  control.addEventListener("click", () => act(async () => {
    control.disabled = true; try { await callback(); } finally { control.disabled = false; }
  }));
  return control;
}
function table(headers, rows, caption) {
  const wrapper = element("div", undefined, "table-scroll"); wrapper.tabIndex = 0;
  wrapper.setAttribute("role", "region"); wrapper.setAttribute("aria-label", caption);
  const view = element("table"); view.append(element("caption", caption, "sr-only"));
  const head = element("thead"); const heading = element("tr");
  for (const name of headers) { const cell = element("th", name); cell.scope = "col"; heading.append(cell); }
  head.append(heading); view.append(head);
  const body = element("tbody");
  for (const values of rows) {
    const row = element("tr");
    for (const value of values) { const cell = element("td"); cell.append(value instanceof Node ? value : document.createTextNode(String(value ?? "No disponible"))); row.append(cell); }
    body.append(row);
  }
  if (!rows.length) { const row = element("tr"); const cell = element("td", "No hay registros para mostrar.", "empty-state"); cell.colSpan = headers.length; row.append(cell); body.append(row); }
  view.append(body); wrapper.append(view); return wrapper;
}
function stat(label, value, note, tone = "neutral") {
  const card = element("article", undefined, "stat-card");
  card.append(element("p", label, "stat-label"), element("p", value, `stat-value tone-${tone}`), element("p", note, "muted"));
  return card;
}
function percentChart(label, value, note) {
  const chart = element("article", undefined, "chart-card");
  chart.append(element("h3", label), element("p", value === null ? "No disponible" : `${value.toLocaleString("es", {maximumFractionDigits: 1})} %`, "chart-value"));
  if (value !== null) {
    const meter = element("meter"); meter.min = 0; meter.max = 100; meter.value = value;
    meter.setAttribute("aria-label", label); meter.textContent = `${value} %`; chart.append(meter);
    const axis = element("div", undefined, "chart-axis"); axis.setAttribute("aria-hidden", "true");
    axis.append(element("span", "0 %"), element("span", "50 %"), element("span", "100 %")); chart.append(axis);
  } else chart.append(element("div", "Sin una lectura válida para graficar", "chart-unavailable"));
  chart.append(element("p", note, "muted")); return chart;
}
function formatted(metric) {
  if (metric.value === null) return "No disponible";
  if (metric.unit === "bytes") return `${(metric.value / 1048576).toLocaleString("es", {maximumFractionDigits: 1})} MiB`;
  if (metric.unit === "s") {
    const seconds = Math.floor(metric.value);
    return `${Math.floor(seconds / 86400)} d ${Math.floor(seconds % 86400 / 3600)} h ${Math.floor(seconds % 3600 / 60)} min`;
  }
  return `${metric.value.toLocaleString("es", {maximumFractionDigits: 1})} ${metric.unit}`;
}
async function loadSummary() {
  const summary = await api("admin/summary"); if (!authenticated) return;
  display("system-summary", stat("Backend", summary.service === "ok" ? "Disponible" : "No disponible", "Servicio NEXO Home", summary.service === "ok" ? "good" : "neutral"), stat("Persistencia", summary.persistence.status === "ok" ? "Disponible" : "No disponible", "Base de datos SQLite", summary.persistence.status === "ok" ? "good" : "neutral"), stat("Terminales", String(summary.terminals.total), `${summary.terminals.linked} con credencial vigente`), stat("Versión", summary.version, "NEXO Home instalado"));
  const terminal = summary.terminals;
  const percent = terminal.total ? terminal.linked / terminal.total * 100 : null;
  display("terminal-overview", percentChart("Credenciales vigentes", percent, terminal.total ? `${terminal.linked} de ${terminal.total} terminales registrados` : "Aún no hay terminales registrados."), element("p", "Una credencial vigente no confirma conexión en línea.", "muted"));
}
async function loadResources() {
  const result = await api("admin/metrics"); if (!authenticated) return;
  const values = result.metrics;
  display("sample-time", document.createTextNode(`Última muestra: ${new Date(result.sampled_at * 1000).toLocaleString("es")} · Cada ${result.refresh_seconds} s`));
  display("resource-charts", ...["cpu_percent", "ram_percent", "storage_percent"].map(key => percentChart(metricNames[key], values[key].value, values[key].value === null ? values[key].limitation : values[key].scope)));
  display("metrics", table(["Lectura", "Valor", "Ámbito / disponibilidad"], Object.entries(values).map(([key, metric]) => [metricNames[key] || key, formatted(metric), metric.value === null ? `${metric.scope}. ${metric.limitation}` : metric.scope]), "Lecturas actuales de recursos"));
  display("metrics-scope", document.createTextNode(`${result.execution === "container" ? "Ejecución en contenedor. CPU, RAM y actividad del sistema pueden pertenecer al anfitrión o a la VM de Docker. No indican los límites del contenedor ni acreditan métricas de la Raspberry." : "Ejecución local."} SO visible: ${result.os.system} ${result.os.release} (${result.os.machine}).`));
  return result.refresh_seconds;
}
async function loadAudit() {
  const events = await api("admin/audit?limit=20"); if (!authenticated) return;
  display("audit-events", table(["Fecha y hora", "Evento", "Resultado", "Motivo"], events.map(event => {
    const label = element("span", eventNames[event.event] || event.event); label.title = event.event;
    return [new Date(event.occurred_at * 1000).toLocaleString("es"), label, badge(resultNames[event.result] || event.result, event.result === "success" ? "good" : "warning"), reasonNames[event.reason] || event.reason || "—"];
  }), "Eventos recientes de auditoría"));
}
async function loadUpdates() {
  const result = await api("admin/updates"); if (!authenticated) return;
  display("update-notice", document.createTextNode(result.notice));
  display("version-inventory", table(["Componente", "Versión instalada"], Object.entries({"NEXO Home": result.nexo_home, Python: result.python, ...result.dependencies}), "Versiones locales de componentes"));
  display("deployment-info", table(["Información", "Estado"], [["Despliegue", result.deployment], ["Digest de imagen", result.image_digest || "No disponible"], ["Última comprobación", result.last_check_at ? new Date(result.last_check_at * 1000).toLocaleString("es") : "No realizada"], ["Resultado de vulnerabilidades", result.last_check_result || "No evaluado"], ["Comprobaciones automáticas", badge(result.checks_available ? "Disponibles" : "No disponibles", "warning")]], "Estado del despliegue y las comprobaciones"));
  if (!result.image_digest) { const details = element("details", undefined, "help"); details.append(element("summary", "Acerca del identificador de imagen"), element("p", result.image_limitation)); document.getElementById("deployment-info").append(details); }
}
async function loadTerminals() {
  display("terminals", element("p", "Actualizando terminales…", "muted"));
  const terminals = await api("admin/terminals"); if (!authenticated) return;
  const rows = terminals.filter(terminal => terminal.state === "linked" && terminal.revoked_at === null).map(terminal => {
    const identity = element("div", undefined, "terminal-name");
    const name = element("input"); name.value = terminal.name; name.maxLength = 80; name.setAttribute("aria-label", `Nombre de ${terminal.name}`);
    const rename = button("Guardar nombre", async () => { await api(`admin/terminals/${terminal.id}/name`, "PATCH", {name: name.value}); await refresh(); message.textContent = "Nombre actualizado."; });
    const id = element("small", `ID: ${terminal.id}`, "terminal-id"); identity.append(name, rename, id);
    const permissionsCell = element("div", undefined, "permission-list"); const permissions = [];
    for (const [permission, title] of [["terminal.status", "Consultar estado"], ["terminal.chat", "Conversación (próximamente)"]]) {
      const label = element("label"); const input = element("input"); input.type = "checkbox"; input.checked = terminal.permissions.includes(permission);
      permissions.push({permission, input}); label.append(input, document.createTextNode(title)); permissionsCell.append(label);
    }
    permissionsCell.append(button("Guardar permisos", async () => { await api(`admin/terminals/${terminal.id}/permissions`, "PUT", {permissions: permissions.filter(item => item.input.checked).map(item => item.permission)}); await refresh(); message.textContent = "Permisos actualizados."; }));
    const revoke = button("Revocar", async () => { await api(`admin/terminals/${terminal.id}`, "DELETE"); await refresh(); message.textContent = "Terminal revocado. Su credencial ya no permite nuevas solicitudes."; }, "button-danger");
    return [identity, badge(stateNames[terminal.state] || terminal.state, terminal.state === "linked" ? "good" : "warning"), permissionsCell, new Date(terminal.last_activity * 1000).toLocaleString("es"), revoke];
  });
  display("terminals", rows.length
    ? table(["Terminal", "Credencial", "Permisos", "Última actividad", "Acción"], rows, "Administración de terminales vinculados activos")
    : element("p", "No hay terminales vinculados activos", "empty-state"));
}
const loaders = {dashboard: loadSummary, terminals: loadTerminals, resources: loadResources, audit: loadAudit, updates: loadUpdates};
async function refresh() {
  if (loading || !authenticated) return;
  clearTimeout(refreshTimer); loading = true;
  const control = document.getElementById("refresh-page"); control.disabled = true;
  try {
    const interval = await loaders[page]();
    if (!authenticated) return;
    message.textContent = "Información actualizada."; message.dataset.state = "ok";
    if (page === "resources" && !document.hidden)
      refreshTimer = setTimeout(() => act(refresh), interval * 1000);
  } catch (error) {
    if (page === "terminals" && authenticated) {
      const text = "No se pudo actualizar la lista de terminales. Vuelve a intentarlo.";
      display("terminals", element("p", text, "empty-state"));
      throw new Error(text);
    }
    if (authenticated) throw new Error("No se pudo actualizar. Los datos visibles pueden estar desactualizados; vuelve a consultar con el botón de actualización.");
    throw error;
  } finally { loading = false; control.disabled = false; }
}
loginForm.addEventListener("submit", event => {
  event.preventDefault();
  act(async () => {
    const data = new FormData(loginForm); const submit = loginForm.querySelector("button"); submit.disabled = true;
    try {
      const result = await api("auth/login", "POST", {username: data.get("username"), password: data.get("password")});
      csrf = result.csrf_token; signedIn(true); await refresh();
    } finally { loginForm.elements.password.value = ""; submit.disabled = false; }
  });
});
logoutButton.addEventListener("click", () => act(async () => { await api("auth/logout", "POST"); signedIn(false); message.textContent = "Sesión cerrada."; message.dataset.state = "ok"; }));
document.getElementById("refresh-page").addEventListener("click", () => act(refresh));
document.addEventListener("visibilitychange", () => {
  clearTimeout(refreshTimer); if (page === "resources" && !document.hidden && authenticated) act(refresh);
});
document.querySelector(`[data-nav="${page}"]`).setAttribute("aria-current", "page");
if (page === "terminals") {
  document.getElementById("generate").addEventListener("click", event => act(async () => {
    const control = event.target; control.disabled = true;
    try {
      const result = await api("admin/pairing-codes", "POST", {permissions: ["terminal.status"]});
      if (!authenticated) return;
      hideCode(); codeId = result.id; codeElement.textContent = result.code;
      codeTimer = setTimeout(hideCode, Math.max(0, result.expires_at * 1000 - Date.now()));
      document.getElementById("code-status").hidden = false; document.getElementById("code-revoke").hidden = false;
      message.textContent = "Copia el código al terminal. Se ocultará al caducar y no se puede recuperar.";
    } finally { control.disabled = false; }
  }));
  document.getElementById("code-status").addEventListener("click", () => act(async () => {
    const result = await api(`admin/pairing-codes/${codeId}`);
    if (result.state !== "pending") hideCode(); await refresh();
    message.textContent = `Vinculación: ${stateNames[result.state]}. Intentos restantes: ${result.attempts_remaining}.`;
  }));
  document.getElementById("code-revoke").addEventListener("click", () => act(async () => { await api(`admin/pairing-codes/${codeId}`, "DELETE"); hideCode(); message.textContent = "Código revocado."; }));
}
act(async () => {
  try { const result = await api("auth/me"); csrf = result.csrf_token; signedIn(true); }
  catch { signedIn(false); message.textContent = "Accede con tu cuenta administrativa."; return; }
  await refresh();
});
