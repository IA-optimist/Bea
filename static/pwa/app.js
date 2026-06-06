// Béa PWA — pilotage/monitoring minimal via l'API REST existante.
// Vanilla JS, aucun build. Stocke base URL + token en localStorage.
"use strict";

const $ = (id) => document.getElementById(id);
const store = {
  get base() { return localStorage.getItem("bea_base") || ""; },
  set base(v) { localStorage.setItem("bea_base", v); },
  get token() { return localStorage.getItem("bea_token") || ""; },
  set token(v) { localStorage.setItem("bea_token", v); },
};

function headers() {
  const h = { "Content-Type": "application/json" };
  if (store.token) h["Authorization"] = "Bearer " + store.token;
  return h;
}

async function api(path, method = "GET", body) {
  const res = await fetch(store.base.replace(/\/$/, "") + path, {
    method, headers: headers(), body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data; try { data = JSON.parse(text); } catch { data = text; }
  if (!res.ok) throw new Error("HTTP " + res.status + ": " + String(text).slice(0, 200));
  return data;
}

function setConn(ok, label) {
  const el = $("conn");
  el.textContent = label;
  el.className = "pill " + (ok ? "ok" : "err");
}

async function refresh() {
  if (!store.base) { $("status").textContent = "Renseigne l'URL puis Connecter."; return; }
  try {
    const health = await api("/health");
    setConn(true, "connecté");
    $("status").textContent = "Santé: " + JSON.stringify(health).slice(0, 120);
  } catch (e) {
    setConn(false, "erreur");
    $("status").textContent = "Connexion KO: " + e.message;
    return;
  }
  try {
    const data = await api("/api/v2/missions");
    const missions = Array.isArray(data) ? data : (data.missions || data.items || []);
    renderMissions(missions);
  } catch (e) {
    $("missions").innerHTML = '<p class="muted">Missions indisponibles: ' + e.message + "</p>";
  }
}

function renderMissions(missions) {
  const root = $("missions");
  if (!missions.length) { root.innerHTML = '<p class="muted">Aucune mission.</p>'; return; }
  root.innerHTML = "";
  missions.slice(0, 30).forEach((m) => {
    const id = m.id || m.mission_id || m.task_id || "";
    const status = m.status || m.state || "?";
    const goal = (m.goal || m.user_input || m.title || "").toString().slice(0, 100);
    const div = document.createElement("div");
    div.className = "mission";
    div.innerHTML =
      '<div><span class="pill">' + status + "</span> " + goal + "</div>" +
      '<div class="row" style="margin-top:6px">' +
      '<button data-act="approve" data-id="' + id + '">Approuver</button>' +
      '<button class="danger" data-act="abort" data-id="' + id + '">Abort</button>' +
      "</div>";
    root.appendChild(div);
  });
  root.querySelectorAll("button[data-act]").forEach((b) => {
    b.addEventListener("click", () => action(b.dataset.act, b.dataset.id));
  });
}

async function action(act, id) {
  if (!id) return;
  const path = act === "abort"
    ? "/api/v2/missions/" + id + "/abort"
    : "/api/v2/missions/" + id + "/approve";
  try { await api(path, "POST", {}); await refresh(); }
  catch (e) { alert(act + " échoué: " + e.message); }
}

$("connect").addEventListener("click", () => {
  store.base = $("base").value.trim();
  store.token = $("token").value.trim();
  refresh();
});
$("refresh").addEventListener("click", refresh);

// Pré-remplissage + auto-refresh
$("base").value = store.base;
if (store.base) refresh();
setInterval(() => { if (store.base) refresh(); }, 15000);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
