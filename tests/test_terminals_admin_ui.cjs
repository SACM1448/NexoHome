"use strict";
// DOM/transporte simulados; ejecuta el script completo y su botón real existente.
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

async function setup(initial) {
  const nodes = new Map(), requests = [], changes = [];
  let response = () => ({ok: true, status: 200, json: async () => initial});
  class Node {
    constructor(tag = "div") { this.tag = tag; this.children = []; this.listeners = {}; this.dataset = {}; this.attributes = {}; this._text = ""; }
    set textContent(value) { this._text = value; this.children = []; for (const notify of changes) notify(); }
    get textContent() { return this._text + this.children.map(item => item.textContent).join(""); }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this._text = ""; this.children = children; }
    addEventListener(event, callback) { this.listeners[event] = callback; }
    setAttribute(key, value) { this.attributes[key] = value; }
    querySelector() { return node("submit"); }
  }
  function node(id) { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); }
  const document = {
    body: {dataset: {page: "terminals"}},
    querySelector: selector => node(selector.startsWith("#") ? selector.slice(1) : selector),
    getElementById: node,
    querySelectorAll: () => [node("terminals"), node("pairing-code")],
    createElement: tag => new Node(tag),
    createTextNode: text => { const item = new Node("text"); item.textContent = text; return item; },
    addEventListener() {},
  };
  const ready = new Promise(resolve => changes.push(() => {
    if (node("message").textContent === "Información actualizada.") resolve();
  }));
  const context = vm.createContext({document, Node, AbortController, setTimeout, clearTimeout,
    fetch: async (url, options) => {
      requests.push({url, options});
      if (url === "/api/v1/auth/me") return {ok: true, status: 200, json: async () => ({csrf_token: "test-only"})};
      assert.equal(url, "/api/v1/admin/terminals");
      return response();
    },
  });
  vm.runInContext(fs.readFileSync("web/js/terminals-admin.js", "utf8"), context);
  await ready;
  return {node, requests, setResponse(callback) { response = callback; },
    refresh() { return node("refresh-page").listeners.click(); },
    rows() { // Nombres y permisos de los inputs que se muestran en el DOM.
      const inputs = [];
      function visit(item) { if (item.tag === "input") inputs.push(item); item.children.forEach(visit); }
      visit(node("terminals")); return inputs;
    },
  };
}

function terminal(id, state = "linked", revoked_at = null) {
  return {id, name: id, state, revoked_at, last_activity: 1000, permissions: ["terminal.chat"]};
}
const ok = rows => ({ok: true, status: 200, json: async () => rows});

test("Actualizar terminales consulta backend y oculta revocados y caducados", {timeout: 5000}, async () => {
  const ui = await setup([terminal("uno"), terminal("dos")]);
  assert.deepEqual(ui.rows().filter(n => n.maxLength === 80).map(n => n.value), ["uno", "dos"]);
  ui.setResponse(() => ok([terminal("uno"), terminal("dos", "revoked", 123), terminal("caducado", "expired"), terminal("inconsistente", "linked", 456)]));
  await ui.refresh();
  assert.deepEqual(ui.rows().filter(n => n.maxLength === 80).map(n => n.value), ["uno"]);
  assert.deepEqual(ui.rows().filter(n => n.type === "checkbox").map(n => n.checked), [false, true]);
  assert.equal(ui.requests.filter(r => r.url === "/api/v1/admin/terminals").length, 2);
  for (const {options} of ui.requests) {
    assert.equal(options.method, "GET");
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.cache, "no-store");
    assert.equal(options.body, undefined);
  }
  assert.equal(ui.node("management").hidden, false);
  assert.equal(ui.node("logout").hidden, false);
  assert.equal(ui.node("refresh-page").disabled, false);
});

test("listado vacío muestra el mensaje de terminales activos", {timeout: 5000}, async () => {
  const ui = await setup([]);
  assert.equal(ui.node("terminals").textContent, "No hay terminales vinculados activos");
  ui.setResponse(() => ok([terminal("revocado", "revoked", 123), terminal("caducado", "expired")]));
  await ui.refresh();
  assert.equal(ui.node("terminals").textContent, "No hay terminales vinculados activos");
});

test("fallo o desconexión vacía datos antiguos, muestra error y permite recuperación", {timeout: 5000}, async () => {
  const ui = await setup([terminal("anterior")]);
  let resolve;
  ui.setResponse(() => new Promise(done => { resolve = done; }));
  const pending = ui.refresh();
  assert.equal(ui.node("terminals").textContent, "Actualizando terminales…");
  assert.equal(ui.rows().length, 0);
  assert.equal(ui.node("refresh-page").disabled, true);
  resolve({ok: false, status: 503, json: async () => ({detail: "Temporalmente no disponible"})});
  await pending;
  assert.match(ui.node("terminals").textContent, /No se pudo actualizar/);
  assert.match(ui.node("message").textContent, /No se pudo actualizar/);
  assert.equal(ui.node("message").dataset.state, "error");
  assert.equal(ui.rows().length, 0);
  assert.equal(ui.node("refresh-page").disabled, false);
  ui.setResponse(() => { throw new TypeError("Network error"); });
  await ui.refresh();
  assert.match(ui.node("terminals").textContent, /No se pudo actualizar/);
  ui.setResponse(() => ok([terminal("actual")]));
  await ui.refresh();
  assert.equal(ui.rows()[0].value, "actual");
  assert.equal(ui.node("message").dataset.state, "ok");
});

test("sesión inválida oculta el listado y exige autenticación", {timeout: 5000}, async () => {
  const ui = await setup([terminal("privado")]);
  ui.setResponse(() => ({ok: false, status: 401, json: async () => ({detail: "Sesión inválida"})}));
  await ui.refresh();
  assert.equal(ui.node("terminals").textContent, "");
  assert.equal(ui.node("management").hidden, true);
  assert.equal(ui.node("login-form").hidden, false);
  assert.equal(ui.node("message").dataset.state, "error");
});
