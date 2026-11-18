"use strict";
const message = document.querySelector("#message");
const identity = document.querySelector("#identity");
const robot = document.querySelector("#robot");
const history = document.querySelector("#history");
const pairing = document.querySelector("#pairing");
const reply = document.querySelector("#reply");
const stateLabels = Object.freeze({idle: "Listo para conversar", listening: "Escuchando", processing: "Procesando…", speaking: "Hablando", success: "Respuesta recibida", error: "No se pudo completar", resource_busy: "Recurso ocupado", disconnected: "Sin conexión con NEXO", unpaired: "Sin vincular"});
let credential = null;
let generation = 0;
let interacting = false;
let pairingPending = false;
let stateTimer;
try { credential = sessionStorage.getItem("nexo-terminal"); } catch { /* Puede estar bloqueado. */ }

// Punto de integración visual para 2.4. No captura ni reproduce audio.
function setRobotState(state) {
  if (!Object.hasOwn(stateLabels, state)) throw new Error("Estado visual inválido");
  clearTimeout(stateTimer);
  robot.dataset.state = state;
  document.querySelector("#robot-status").textContent = stateLabels[state];
  if (state === "success") stateTimer = setTimeout(() => setRobotState(credential ? "idle" : "unpaired"), 1800);
}
function controls() {
  document.querySelector("#interact-form button").disabled = interacting;
  document.querySelector("#interact-form").setAttribute("aria-busy", String(interacting));
  document.querySelector("#pair-form button").disabled = pairingPending || Boolean(credential);
  document.querySelector("#pairing-status").textContent = credential ? "Vinculado" : "Sin vincular";
}
function clearConversation() {
  history.replaceChildren();
  reply.textContent = "";
  reply.dataset.inHistory = "false";
  document.querySelector("#welcome").hidden = false;
  document.querySelector("#interact-form").reset();
}
function forget() {
  generation += 1;
  credential = null;
  try { sessionStorage.removeItem("nexo-terminal"); } catch { /* Solo memoria. */ }
  identity.textContent = "";
  clearConversation();
  pairing.open = true;
  setRobotState("unpaired");
  controls();
}
function appendMessage(role, text) {
  const item = document.createElement("li");
  item.dataset.role = role;
  const label = document.createElement("strong");
  label.textContent = role === "user" ? "TÚ" : "NEXO";
  const content = document.createElement("span");
  content.textContent = text;
  item.append(label, content);
  history.append(item);
  while (history.children.length > 20) history.firstElementChild.remove();
  document.querySelector("#welcome").hidden = true;
  const body = document.querySelector(".conversation-body");
  body.scrollTop = body.scrollHeight;
}
class ApiError extends Error {
  constructor(text, status = 0, code = "") { super(text); this.status = status; this.code = code; }
}
async function api(path, payload) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const headers = {};
    if (payload) headers["Content-Type"] = "application/json";
    if (credential && path !== "pair") headers.Authorization = `Bearer ${credential}`;
    const response = await fetch(`/api/v1/terminal/${path}`, {
      method: payload ? "POST" : "GET", headers, credentials: "omit", cache: "no-store",
      body: payload ? JSON.stringify(payload) : undefined, signal: controller.signal,
    });
    let result;
    try { result = await response.json(); } catch {
      throw new ApiError("Respuesta no válida del servicio.", response.status || 502);
    }
    if (!response.ok || result.status === "failed") {
      const text = typeof result.message === "string" ? result.message : (typeof result.detail === "string" ? result.detail : "No se pudo completar la solicitud");
      throw new ApiError(text, response.status, result.error?.code);
    }
    return result;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(error.name === "AbortError" ? "Tiempo de espera agotado. El resultado puede ser desconocido; consulta el estado antes de intentarlo manualmente." : "No se pudo conectar con NEXO. Comprueba tu conexión e inténtalo manualmente.");
  } finally { clearTimeout(timeout); }
}
function handleError(error, path) {
  if (error.status === 401 && path !== "pair") {
    forget();
    return "Credencial ausente, expirada o revocada. Solicita una nueva vinculación.";
  }
  setRobotState(!credential ? "unpaired" : !error.status ? "disconnected" : error.code === "resource_busy" ? "resource_busy" : "error");
  return error.message;
}
function showIdentity(result) {
  // Solo campos públicos conocidos; nunca volcar respuestas que puedan contener secretos.
  identity.textContent = [result.name, result.id, result.state].filter(value => typeof value === "string").join(" · ");
}
async function show(path) {
  const activeGeneration = generation;
  if (!credential) { message.textContent = "Esta pestaña no tiene una credencial de terminal."; setRobotState("unpaired"); return; }
  try {
    const result = await api(path);
    if (activeGeneration !== generation) return;
    if (path === "me") showIdentity(result);
    message.textContent = path === "me" ? "Terminal vinculado. Identidad verificada." : "Estado autorizado consultado correctamente.";
    if (!interacting) setRobotState("idle");
  } catch (error) {
    if (activeGeneration !== generation) return;
    message.textContent = handleError(error, path);
  }
}
document.querySelector("#pair-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (pairingPending) return;
  const form = event.currentTarget;
  const activeGeneration = generation;
  pairingPending = true;
  controls();
  try {
    if (credential) throw new ApiError("Olvida la credencial actual antes de vincular otra identidad.", 409);
    const data = new FormData(form);
    const result = await api("pair", {name: data.get("name"), code: data.get("code").trim()});
    if (activeGeneration !== generation) return;
    if (typeof result.credential !== "string" || !result.credential || !result.terminal || typeof result.terminal.id !== "string") throw new ApiError("Respuesta de vinculación no válida.", 502);
    generation += 1;
    clearConversation();
    credential = result.credential;
    let stored = true;
    try { sessionStorage.setItem("nexo-terminal", credential); } catch { stored = false; }
    form.reset();
    showIdentity(result.terminal);
    message.textContent = stored ? "Terminal vinculado." : "Terminal vinculado solo en memoria; recargar perderá el acceso.";
    pairing.open = false;
    setRobotState("idle");
    document.querySelector("#text").focus();
  } catch (error) { if (activeGeneration === generation) message.textContent = handleError(error, "pair"); }
  finally { form.elements.code.value = ""; pairingPending = false; controls(); }
});
document.querySelector("#identity-refresh").addEventListener("click", () => show("me"));
document.querySelector("#status-refresh").addEventListener("click", () => show("status"));
document.querySelector("#forget").addEventListener("click", () => {
  forget(); message.textContent = "Credencial olvidada localmente. Para invalidar cualquier copia, pide revocación al administrador.";
});
document.querySelector("#interact-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (interacting) return;
  const form = event.currentTarget;
  const processing = document.querySelector("#processing");
  const activeGeneration = generation;
  if (!credential) { reply.textContent = "Vincula este terminal antes de enviar texto."; pairing.open = true; setRobotState("unpaired"); return; }
  const text = new FormData(form).get("text").trim();
  if (!text) return;
  interacting = true;
  controls();
  reply.textContent = "";
  reply.dataset.inHistory = "false";
  processing.textContent = "Procesando…";
  setRobotState("processing");
  appendMessage("user", text);
  form.reset();
  try {
    const result = await api("interact", {text});
    if (activeGeneration !== generation) return;
    if (typeof result.message !== "string") throw new ApiError("Respuesta no válida del servicio.", 502);
    appendMessage("assistant", result.message);
    // El historial evita anuncios repetidos; la última respuesta tiene aria-live.
    reply.textContent = result.message;
    reply.dataset.inHistory = "true";
    setRobotState("success");
  } catch (error) {
    if (activeGeneration !== generation) return;
    const text = handleError(error, "interact");
    reply.textContent = text;
    if (credential) { appendMessage("assistant", text); reply.dataset.inHistory = "true"; }
  } finally {
    processing.textContent = "";
    interacting = false;
    controls();
  }
});
document.addEventListener("visibilitychange", () => { document.body.dataset.hidden = String(document.hidden); });
document.body.dataset.hidden = String(document.hidden);
setRobotState(credential ? "idle" : "unpaired");
controls();
if (credential) { pairing.open = false; show("me"); }
