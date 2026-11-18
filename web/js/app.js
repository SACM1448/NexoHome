"use strict";

const statusElement = document.querySelector("#service-status");
const refreshButton = document.querySelector("#refresh");

async function checkHealth() {
  refreshButton.disabled = true;
  statusElement.dataset.state = "pending";
  statusElement.textContent = "Comprobando conexión…";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch("/api/v1/health", {
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) throw new Error("Respuesta HTTP no válida");
    const health = await response.json();
    if (health.status !== "ok" || health.service !== "nexo-home") {
      throw new Error("Respuesta de salud no válida");
    }
    statusElement.dataset.state = "ok";
    statusElement.textContent = "Servicio operativo";
  } catch {
    statusElement.dataset.state = "error";
    statusElement.textContent = "No se pudo verificar el servicio. Inténtalo nuevamente.";
  } finally {
    clearTimeout(timeout);
    refreshButton.disabled = false;
  }
}

refreshButton.addEventListener("click", checkHealth);
checkHealth();
