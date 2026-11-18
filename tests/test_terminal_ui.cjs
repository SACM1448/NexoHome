"use strict";
// DOM y transporte simulados: verifica comportamiento JS, no renderizado de navegador.
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function setup(stored = null) {
  const nodes = new Map();
  const writes = [];
  const requests = [];
  let pending, rejectPending;
  const timers = new Map(); let timerId = 0;
  function node(selector) {
    if (!nodes.has(selector)) nodes.set(selector, {
      textContent: "", disabled: false, dataset: {}, children: [], attributes: {}, hidden: false,
      setAttribute(key, value) { this.attributes[key] = value; },
      focus() { this.focused = true; },
      append(...items) { items.forEach(item => { item.parent = this; this.children.push(item); }); },
      replaceChildren() { this.children = []; },
      get firstElementChild() { return this.children[0]; },
      remove() { this.parent.children.shift(); }, listeners: {}, elements: {code: {value: ""}},
      addEventListener(event, listener) { this.listeners[event] = listener; },
      querySelector() { return node(selector + " button"); },
      reset() { this.resetCalled = true; },
      data: new Map([["text", "hola"]]),
    });
    return nodes.get(selector);
  }
  const context = vm.createContext({
    document: {querySelector: node, createElement: () => node(Symbol()), body: node("body"), hidden: false, addEventListener(event, listener) { node("document").listeners[event] = listener; }},
    sessionStorage: {getItem() { return stored; }, setItem(...args) { writes.push(args); }, removeItem() {}},
    AbortController, setTimeout(fn) { timers.set(++timerId, fn); return timerId; }, clearTimeout(id) { timers.delete(id); },
    FormData: class { constructor(form) { this.form = form; } get(key) { return this.form.data.get(key); } },
    fetch: async (url, options) => {
      requests.push({url, options});
      if (url.endsWith("/pair")) return {ok: true, json: async () => ({credential: "test-only", terminal: {id: "one"}})};
      return await new Promise((resolve, reject) => {pending = resolve; rejectPending = reject; options.signal.addEventListener("abort", () => reject(Object.assign(new Error("abort"), {name: "AbortError"})));});
    },
  });
  vm.runInContext(fs.readFileSync("web/js/terminal.js", "utf8"), context);
  return {node, writes, requests, context, timers, fail() { rejectPending(new TypeError("private-network-detail")); }, respond(status, data) { pending({ok: status < 400, status, json: async () => data}); },
    async pair() {
      const form = node("#pair-form");
      form.data = new Map([["name", "Prueba"], ["code", "code-test"]]);
      await form.listeners.submit({preventDefault() {}, currentTarget: form});
    },
    submit() {const form = node("#interact-form"); return form.listeners.submit({preventDefault() {}, currentTarget: form});},
  };
}

test("POST autenticado, estado visible y conversación solo en memoria", async () => {
  const ui = setup();
  await ui.pair();
  const request = ui.submit();
  assert.equal(ui.node("#interact-form button").disabled, true);
  assert.equal(ui.node("#processing").textContent, "Procesando…");
  const sent = ui.requests.at(-1);
  assert.equal(sent.url, "/api/v1/terminal/interact");
  assert.equal(sent.options.headers.Authorization, "Bearer test-only");
  assert.equal(sent.options.credentials, "omit");
  assert.equal(JSON.parse(sent.options.body).text, "hola");
  assert.equal(ui.node("#interact-form").resetCalled, true);
  ui.respond(200, {message: "<script>texto literal</script>"});
  await request;
  assert.equal(ui.node("#reply").textContent, "<script>texto literal</script>");
  assert.equal(ui.node("#interact-form button").disabled, false);
  assert.equal(ui.node("#processing").textContent, "");
  assert.deepEqual(ui.writes, [["nexo-terminal", "test-only"]]);
});

test("errores estructurados y ausencia de reintento", async () => {
  const ui = setup(); await ui.pair();
  const request = ui.submit();
  await ui.submit(); // Doble envío no crea otra solicitud.
  ui.respond(429, {message: "Espera 60 segundos"}); await request;
  assert.equal(ui.node("#reply").textContent, "Espera 60 segundos");
  assert.equal(ui.requests.length, 2);
});

test("revocación olvida credencial; respuesta tardía no cruza identidades", async () => {
  const ui = setup(); await ui.pair();
  let request = ui.submit();
  ui.respond(401, {message: "Credencial inválida"}); await request;
  assert.match(ui.node("#reply").textContent, /revocada/);
  await ui.pair();
  request = ui.submit();
  ui.node("#forget").listeners.click();
  ui.respond(200, {message: "privado-anterior"}); await request;
  assert.equal(ui.node("#reply").textContent, "");
});

test("renderizado inicial, sin vincular y envío sin credencial", async () => {
  const ui = setup();
  assert.equal(ui.node("#robot").dataset.state, "unpaired");
  await ui.submit();
  assert.equal(ui.requests.length, 0);
  assert.match(ui.node("#reply").textContent, /Vincula/);
  assert.equal(ui.node("#pairing").open, true);
});
test("vinculación, idle, processing, success y vuelta a reposo", async () => {
  const ui = setup(); await ui.pair();
  assert.equal(ui.node("#robot").dataset.state, "idle");
  assert.equal(ui.node("#pairing").open, false);
  assert.equal(ui.node("#text").focused, true);
  const request = ui.submit();
  assert.equal(ui.node("#robot").dataset.state, "processing");
  assert.equal(ui.node("#interact-form").attributes["aria-busy"], "true");
  ui.respond(200, {message: "Hola"}); await request;
  assert.equal(ui.node("#robot").dataset.state, "success");
  for (const callback of [...ui.timers.values()]) callback();
  assert.equal(ui.node("#robot").dataset.state, "idle");
  assert.equal(ui.node("#reply").textContent, "Hola");
});
for (const [status, code, state, text] of [
  [500, "processing_error", "error", "No se pudo procesar"],
  [409, "resource_busy", "resource_busy", "Recurso ocupado"],
  [409, "terminal_busy", "error", "Este terminal ya está procesando una solicitud"],
  [403, "forbidden", "error", "Permiso requerido"],
  [504, "execution_timeout", "error", "Operación agotada"],
]) test(`resultado ${code}, error permanece visible`, async () => {
  const ui = setup(); await ui.pair(); const request = ui.submit();
  ui.respond(status, {status: "failed", message: text, error: {code}}); await request;
  assert.equal(ui.node("#robot").dataset.state, state);
  assert.equal(ui.node("#reply").textContent, text);
  assert.equal(ui.timers.size, 0);
  assert.equal(ui.node("#interact-form button").disabled, false);
  assert.equal(ui.requests.length, 2);
});
test("red fallida: disconnected, mensaje seguro y recuperación manual", async () => {
  const ui = setup(); await ui.pair(); let request = ui.submit();
  ui.fail(); await request;
  assert.equal(ui.node("#robot").dataset.state, "disconnected");
  assert.match(ui.node("#reply").textContent, /conexión/);
  assert.doesNotMatch(ui.node("#reply").textContent, /private-network/);
  request = ui.submit(); ui.respond(200, {message: "Recuperado"}); await request;
  assert.equal(ui.node("#robot").dataset.state, "success");
});
test("revocación elimina historial y credencial, no confunde 403 con revocación", async () => {
  const ui = setup(); await ui.pair(); const request = ui.submit();
  ui.respond(401, {error: {code: "invalid_credential"}}); await request;
  assert.equal(ui.node("#robot").dataset.state, "unpaired");
  assert.equal(ui.node("#history").children.length, 0);
  assert.equal(ui.node("#pairing").open, true);
  assert.match(ui.node("#reply").textContent, /revocada/);
});
test("historial limitado, HTML literal, sin almacenamiento y recarga vacía", async () => {
  const ui = setup(); await ui.pair();
  for (let i = 0; i < 13; i++) {
    ui.node("#interact-form").data.set("text", "<img src=x onerror=alert(1)>");
    const request = ui.submit(); ui.respond(200, {message: `<script>${i}</script>`}); await request;
  }
  const items = ui.node("#history").children;
  assert.equal(items.length, 20);
  assert.equal(items[0].children[1].textContent, "<img src=x onerror=alert(1)>");
  assert.equal(items.at(-1).children[1].textContent, "<script>12</script>");
  assert.deepEqual(ui.writes, [["nexo-terminal", "test-only"]]);
  assert.equal(setup().node("#history").children.length, 0);
  ui.node("#forget").listeners.click();
  assert.equal(ui.node("#history").children.length, 0);
});
test("credencial restaurada se verifica y errores de identidad son visibles", async () => {
  const ui = setup("stored-test-only");
  assert.equal(ui.requests[0].options.headers.Authorization, "Bearer stored-test-only");
  ui.respond(401, {detail: "Credencial inválida"});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.node("#robot").dataset.state, "unpaired");
});
test("máquina explícita, voz reservada y pausa al ocultar pestaña", () => {
  const ui = setup();
  for (const state of ["idle", "listening", "processing", "speaking", "success", "error", "resource_busy", "disconnected", "unpaired"]) {
    vm.runInContext(`setRobotState("${state}")`, ui.context);
    assert.equal(ui.node("#robot").dataset.state, state);
  }
  assert.throws(() => vm.runInContext('setRobotState("inventado")', ui.context));
  vm.runInContext('document.hidden = true', ui.context);
  ui.node("document").listeners.visibilitychange();
  assert.equal(ui.node("body").dataset.hidden, "true");
});
test("estructura accesible, teclado nativo, movimiento reducido y ausencia de código inseguro", () => {
  const html = fs.readFileSync("web/terminal.html", "utf8");
  const css = fs.readFileSync("web/css/terminal.css", "utf8");
  const js = fs.readFileSync("web/js/terminal.js", "utf8");
  assert.match(html, /lang="es"/);
  assert.match(html, /class="skip-link" href="#text"/);
  assert.match(html, /for="text"/);
  assert.match(html, /type="submit" aria-label="Enviar mensaje"/);
  assert.match(html, /<summary>/);
  assert.match(html, /aria-live="polite"/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /prefers-reduced-motion:reduce/);
  assert.match(css, /animation:none!important/);
  assert.match(css, /animation-play-state:paused/);
  assert.doesNotMatch(js, /innerHTML|localStorage|console\.|setInterval|speechSynthesis|getUserMedia|new Audio/);
  assert.doesNotMatch(html, /https?:\/\/|<canvas|<video/);
});

test("timeout libera envío sin reintento y advierte resultado desconocido", async () => {
  const ui = setup(); await ui.pair(); const request = ui.submit();
  for (const callback of [...ui.timers.values()]) callback();
  await request;
  assert.equal(ui.node("#robot").dataset.state, "disconnected");
  assert.match(ui.node("#reply").textContent, /desconocido/);
  assert.equal(ui.node("#interact-form button").disabled, false);
  assert.equal(ui.requests.length, 2);
});
test("respuesta inválida no confirma éxito y permite envío manual posterior", async () => {
  const ui = setup(); await ui.pair(); const request = ui.submit();
  ui.respond(200, {status: "completed"}); await request;
  assert.equal(ui.node("#robot").dataset.state, "error");
  assert.match(ui.node("#reply").textContent, /no válida/);
});
