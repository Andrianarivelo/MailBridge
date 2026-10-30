/* =============================================================================
   MailBridge : logique de l'interface
   Les données viennent de Python (pywebview.api). Sans Python (navigateur) ou avec
   ?demo=1, un jeu de données fictif est utilisé (captures d'écran, aperçu).
   ============================================================================= */
"use strict";

// ---- Paramètres -------------------------------------------------------------
const REFRESH_MS = 4000;          // rafraîchissement de l'état
const RING_LENGTH = 2 * Math.PI * 34;
const GITHUB_URL = "https://github.com/Andrianarivelo/MailBridge";
const GOOGLE_GUIDE_URL = GITHUB_URL + "/blob/main/docs/GOOGLE_SETUP.md";
const APP_PASSWORD_URL = "https://myaccount.google.com/apppasswords";

// ---- Petits utilitaires -----------------------------------------------------
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const initials = (name) => (name || "?").replace(/\(.*?\)/g, "").trim().split(/\s+/)
  .filter((w) => w.length > 2 || /^[A-Z]/.test(w)).slice(0, 2).map((w) => w[0].toUpperCase()).join("") || "?";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Icônes (traits fins, style « Lucide »)
const svg = (d, w = 2) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const ICON = {
  gear: svg('<path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>', 1.7),
  sync: svg('<path d="M21 12a9 9 0 0 1-15.4 6.4L3 16"/><path d="M3 12a9 9 0 0 1 15.4-6.4L21 8"/><path d="M21 3v5h-5"/><path d="M3 21v-5h5"/>'),
  plus: svg('<path d="M12 5v14M5 12h14"/>', 2.4),
  ext: svg('<path d="M7 17 17 7M8 7h9v9"/>'),
  chev: svg('<path d="m9 18 6-6-6-6"/>'),
  back: svg('<path d="m15 18-6-6 6-6"/>'),
  mail: svg('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>'),
  cal: svg('<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>'),
  pulse: svg('<path d="M3 12h4l3-8 4 16 3-8h4"/>'),
  folder: svg('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>'),
  doc: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>'),
  code: svg('<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>'),
  okmark: '<svg class="okmark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
};

// ---- Données fictives (aperçu / captures d'écran) ---------------------------
const DEMO_PRESETS = {
  "u-paris": { name: "Université Paris Cité", type: "imap", label: "U-Paris", color: "#8B5CF6", hint: "Votre mot de passe ENT." },
  outlook: { name: "Compte Outlook (Inserm, Microsoft 365…)", type: "outlook", label: "Outlook", color: "#0EA5E9", hint: "Aucun mot de passe : lecture via Outlook ouvert sur ce PC." },
  yahoo: { name: "Yahoo Mail", type: "imap", label: "Yahoo", color: "#7C3AED", hint: "Mot de passe d'application Yahoo." },
  icloud: { name: "iCloud Mail", type: "imap", label: "iCloud", color: "#3B82F6", hint: "Mot de passe pour app Apple." },
  orange: { name: "Orange", type: "imap", label: "Orange", color: "#F97316", hint: "" },
  free: { name: "Free", type: "imap", label: "Free", color: "#EF4444", hint: "" },
  gmx: { name: "GMX", type: "imap", label: "GMX", color: "#1D4ED8", hint: "" },
  imap: { name: "Autre (IMAP)", type: "imap", label: "Mail", color: "#64748B", hint: "Serveur IMAP chiffré." },
};
const DEMO = {
  snapshot: () => ({
    status: { level: "ok", title: "Actif", detail: "Dernière passe à 11:58 · toutes les 5 min" },
    stats: { today: 23, total: 312 }, interval: 5, next_in: 197, version: "2.0.0",
    gmail: { address: "prenom.nom@gmail.com" },
    accounts: [
      { id: "u-paris", name: "Université Paris Cité", preset: "u-paris", type: "imap", label: "U-Paris", color: "#8B5CF6", enabled: true, user: "prenom.nom@u-paris.fr", level: "ok", sub: "prenom.nom@u-paris.fr", today: 14 },
      { id: "inserm", name: "Inserm", preset: "outlook", type: "outlook", label: "Inserm", color: "#0EA5E9", enabled: true, store: "prenom.nom@inserm.fr", level: "ok", sub: "Via Outlook · prenom.nom@inserm.fr", today: 6 },
      { id: "yahoo", name: "Yahoo Mail", preset: "yahoo", type: "imap", label: "Yahoo", color: "#7C3AED", enabled: true, user: "prenom@yahoo.fr", level: "ok", sub: "prenom@yahoo.fr", today: 3 },
    ],
    calendar: { level: "ok", text: "2 calendriers · 148 événements · 11:55", client: true, connected: true,
      email: "prenom.nom@gmail.com", sources: [
        { id: "cal-u-paris", store: "prenom.nom@u-paris.fr", label: "U-Paris", target_id: "x", target_name: "MailBridge · U-Paris", enabled: true, count: 112, changes: 2 },
        { id: "cal-inserm", store: "prenom.nom@inserm.fr", label: "Inserm", target_id: "y", target_name: "MailBridge · Inserm", enabled: true, count: 36, changes: 0 }] },
    recent: [
      { key: "1", time: "11:56", color: "#8B5CF6", sender: "Service Formation", subject: "Convocation : atelier Moodle, lundi 10 h", action: "copié" },
      { key: "2", time: "11:41", color: "#0EA5E9", sender: "Plateforme Imagerie", subject: "Réservation confirmée : confocal jeudi", action: "copié" },
      { key: "3", time: "11:20", color: "#7C3AED", sender: "Revue scientifique", subject: "Your manuscript has been received", action: "copié" },
    ],
    autostart: true,
  }),
  presets: () => DEMO_PRESETS,
  outlook_stores: () => ({ ok: true, stores: ["prenom.nom@inserm.fr", "prenom.nom@unige.ch"] }),
  save_account: async () => { await sleep(900); return { ok: true, message: "Connecté (1 234 messages)" }; },
  save_gmail: async () => { await sleep(900); return { ok: true, message: "Connecté à Gmail" }; },
  delete_account: () => ({ ok: true }), set_account_enabled: () => ({ ok: true }),
  sync_now: async () => { await sleep(2200); return { ok: true, message: "3 messages copiés" }; },
  check: async () => { await sleep(1200); return { ok: true, message: "[OK] Gmail\n[OK] Université Paris Cité\n[OK] Inserm" }; },
  set_autostart: () => ({ ok: true }),
  google_import_client: () => ({ ok: true, message: "Accès Google importé" }),
  google_save_client: () => ({ ok: true, message: "Accès Google enregistré" }),
  google_connect: async () => { await sleep(1500); return { ok: true, message: "Connecté : prenom.nom@gmail.com" }; },
  google_disconnect: () => ({ ok: true }),
  google_calendars: () => ({ ok: true, calendars: [{ id: "p", name: "prenom.nom@gmail.com", primary: true },
    { id: "x", name: "MailBridge · U-Paris" }, { id: "y", name: "MailBridge · Inserm" }] }),
  save_calendar: () => ({ ok: true, message: "Calendrier enregistré" }),
  delete_calendar: () => ({ ok: true }),
  sync_calendars_now: async () => { await sleep(1800); return { ok: true, message: "Agendas à jour · 4 ajoutés, 1 mis à jour" }; },
  open_journal: () => ({}), open_folder: () => ({}), open_url: (u) => window.open(u),
};

// ---- Pont vers Python --------------------------------------------------------
let demo = location.hash.startsWith("#demo") || new URLSearchParams(location.search).has("demo");
async function call(name, ...args) {
  if (demo || !window.pywebview?.api) return DEMO[name](...args);
  try { return await window.pywebview.api[name](...args); }
  catch (e) { return { ok: false, message: String(e) }; }
}

// ---- État de l'interface -----------------------------------------------------
let snap = null, presets = {}, busy = false, nextAt = 0, interval = 300;
const seen = { rows: new Set(), acts: new Set(), first: true };
const sig = {};   // signatures des sections déjà affichées (évite de redessiner pour rien)

// ---- Animations --------------------------------------------------------------
function countTo(el, to) {
  const from = Number(el.dataset.v || 0);
  if (from === to) return;
  el.dataset.v = to;
  const t0 = performance.now(), dur = 900;
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = Math.round(from + (to - from) * e).toLocaleString("fr-FR");
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function toast(text, level = "info", ms = 3200) {
  const t = document.createElement("div");
  t.className = `toast ${level}`;
  t.innerHTML = `<i></i><span>${esc(text)}</span>`;
  $("#toasts").appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 320); }, ms);
}

function tick() {
  if (busy || !nextAt) return;
  const left = Math.max(0, Math.round((nextAt - Date.now()) / 1000));
  $("#countdown").textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  $("#ringBar").style.strokeDashoffset = RING_LENGTH * (1 - left / interval);
}

// ---- Rendu -------------------------------------------------------------------
function setStatus(level, title, detail) {
  $("#statusPill").className = `pill lvl-${level}`;
  $("#statusTitle").textContent = title;
  if (detail !== undefined) $("#statusDetail").textContent = detail;
}

function changed(key, value) {
  const s = JSON.stringify(value);
  if (sig[key] === s) return false;
  sig[key] = s;
  return true;
}

function render(s) {
  snap = s;
  if (!busy) setStatus(s.status.level, s.status.title, s.status.detail);
  countTo($("#mToday"), s.stats.today);
  countTo($("#mTotal"), s.stats.total);
  interval = (s.interval || 5) * 60;
  if (s.next_in != null) nextAt = Date.now() + s.next_in * 1000;
  tick();

  if (changed("accounts", s.accounts)) {
    const list = $("#accounts");
    list.innerHTML = s.accounts.length ? s.accounts.map((a, i) => {
      const fresh = !seen.rows.has(a.id);
      seen.rows.add(a.id);
      return `<li class="row ${a.enabled ? "" : "off"}" data-id="${esc(a.id)}" style="${fresh ? `animation-delay:${i * 50}ms` : "animation:none"}">
        <div class="avatar" style="--c:${esc(a.color)}">${esc(initials(a.name))}</div>
        <div class="row-main"><b>${esc(a.name)}</b><small>${esc(a.sub)}</small></div>
        <div class="row-end"><span class="badge ${a.today ? "plus" : ""}">${a.today ? "+" + a.today : ""}</span>
          <span class="lvl-${esc(a.level)}"><i class="dot"></i></span><span class="chev">${ICON.chev}</span></div></li>`;
    }).join("") : `<li class="empty">Aucun compte : cliquez sur « Ajouter ».</li>`;
    list.querySelectorAll(".row").forEach((r) => r.onclick = () => sheetAccount(s.accounts.find((a) => a.id === r.dataset.id)));
  }

  const targets = [
    { k: "gmail", icon: ICON.mail, c: "#EA4335", name: "Gmail (destination)", sub: s.gmail.address || "À configurer : mot de passe d'application", level: s.gmail.address ? (s.gmail.level || "ok") : "warn" },
    { k: "cal", icon: ICON.cal, c: "#10B981", name: "Google Agenda", sub: s.calendar.text, level: s.calendar.level },
  ];
  if (changed("targets", targets)) {
    $("#targets").innerHTML = targets.map((t) => `<li class="row" data-k="${t.k}" style="animation:none">
      <div class="avatar" style="--c:${t.c}">${t.icon}</div>
      <div class="row-main"><b>${esc(t.name)}</b><small>${esc(t.sub)}</small></div>
      <div class="row-end"><span class="lvl-${esc(t.level)}"><i class="dot"></i></span><span class="chev">${ICON.chev}</span></div></li>`).join("");
    $("#targets [data-k=gmail]").onclick = sheetGmail;
    $("#targets [data-k=cal]").onclick = sheetCalendar;
  }

  if (changed("recent", s.recent)) {
    $("#recent").innerHTML = s.recent.length ? s.recent.map((r, i) => {
      const isNew = !seen.acts.has(r.key);
      seen.acts.add(r.key);
      const cls = r.action === "copié" ? "ok" : r.action === "erreur" || r.action === "abandonné" ? "err" : "muted";
      const style = seen.first ? `animation-delay:${200 + i * 60}ms` : isNew ? "" : "animation:none";
      return `<li class="act ${isNew && !seen.first ? "fresh" : ""}" style="--c:${esc(r.color)};${style}">
        <span class="bar"></span><div class="what"><b>${esc(r.sender)}</b><small>${esc(r.subject)}</small></div>
        <div class="when">${esc(r.time)}<i class="${cls}">${esc(r.action)}</i></div></li>`;
    }).join("") : `<li class="empty">Aucune copie pour l'instant.</li>`;
    seen.first = false;
  }

  const sw = $("#autoSwitch");   // présent seulement quand les réglages sont ouverts
  if (sw) sw.setAttribute("aria-checked", s.autostart ? "true" : "false");
}

async function refresh() {
  const s = await call("snapshot");
  if (s && s.status) render(s);
}

// ---- Panneau glissant --------------------------------------------------------
function openSheet(html, mount) {
  const sheet = $("#sheet");
  sheet.innerHTML = html;
  $("#backdrop").classList.add("show");
  requestAnimationFrame(() => sheet.classList.add("show"));
  mount?.(sheet);
  const first = sheet.querySelector("input:not([type=checkbox]):not([readonly])");
  if (first) setTimeout(() => first.focus(), 350);
}
function closeSheet() {
  $("#sheet").classList.remove("show");
  $("#backdrop").classList.remove("show");
}

function passwordField(id, label, extra = "") {
  return `<div class="field"><label for="${id}"><span>${label}</span>${extra}</label>
    <div class="pw"><input id="${id}" type="password" autocomplete="off" spellcheck="false">
    <button type="button" data-eye="${id}">Afficher</button></div></div>`;
}
function bindEyes(root) {
  root.querySelectorAll("[data-eye]").forEach((b) => b.onclick = () => {
    const inp = root.querySelector("#" + b.dataset.eye);
    const hidden = inp.type === "password";
    inp.type = hidden ? "text" : "password";
    b.textContent = hidden ? "Masquer" : "Afficher";
  });
}
function setResult(el, ok, text) {
  el.className = `result ${ok ? "ok" : "err"}`;
  el.innerHTML = ok ? `${ICON.okmark}<span>${esc(text)}</span>` : `<span>${esc(text)}</span>`;
}
function setBusyButton(btn, on, label) {
  btn.disabled = on;
  btn.innerHTML = on ? `<span class="ico spinning">${ICON.sync}</span>${esc(label)}` : esc(label);
}

// Choix du fournisseur
function sheetPresets() {
  const tiles = Object.entries(presets).map(([k, p], i) =>
    `<button class="tile" data-k="${k}" style="--c:${p.color};animation-delay:${i * 35}ms">
      <span class="avatar" style="--c:${p.color}">${esc(initials(p.name))}</span><b>${esc(p.name)}</b></button>`).join("");
  openSheet(`<div class="sheet-head"><h3>Ajouter un compte</h3></div>
    <p class="lead">Choisissez votre messagerie. Ses mails arriveront dans Gmail avec leur propre libellé.</p>
    <div class="grid">${tiles}</div>`,
  (el) => el.querySelectorAll(".tile").forEach((t) => t.onclick = () => sheetAccount(null, t.dataset.k)));
}

// Ajout ou modification d'un compte
async function sheetAccount(acc, presetKey) {
  const edit = !!acc;
  const key = acc?.preset || presetKey;
  const p = presets[key] || presets.imap;
  const type = acc?.type || p.type;
  const custom = key === "imap";
  const v = { name: acc?.name || p.name, label: acc?.label || p.label, host: acc?.host || p.host || "",
    port: acc?.port || p.port || 993, user: acc?.user || "", store: acc?.store || "", redirect: !!acc?.expects_redirect };

  const imapFields = `
    ${custom ? `<div class="two"><div class="field"><label>Serveur IMAP</label><input id="fHost" value="${esc(v.host)}" placeholder="imap.exemple.fr"></div>
      <div class="field"><label>Port</label><input id="fPort" value="${esc(v.port)}"></div></div>` : ""}
    <div class="field"><label>Identifiant</label><input id="fUser" value="${esc(v.user)}" placeholder="adresse@exemple.fr" spellcheck="false"></div>
    ${passwordField("fPass", edit ? "Mot de passe <small>(vide = inchangé)</small>" : "Mot de passe")}`;
  const outlookFields = `<div class="field"><label>Compte dans Outlook</label>
      <select id="fStore"><option>Recherche des comptes Outlook…</option></select></div>`;

  openSheet(`<div class="sheet-head">${edit ? "" : `<button class="back" id="bBack">${ICON.back}</button>`}
      <span class="avatar" style="--c:${p.color}">${esc(initials(v.name))}</span><h3>${esc(edit ? v.name : p.name)}</h3></div>
    <p class="lead">${edit ? "Modifier ce compte." : "Renseignez le compte à rassembler dans Gmail."}</p>
    ${p.hint ? `<div class="hint">${esc(p.hint)}</div>` : ""}
    <div class="two"><div class="field"><label>Nom affiché</label><input id="fName" value="${esc(v.name)}"></div>
      <div class="field"><label>Libellé Gmail</label><input id="fLabel" value="${esc(v.label)}"></div></div>
    ${type === "outlook" ? outlookFields : imapFields}
    <label class="check-line"><input type="checkbox" id="fRedirect" ${v.redirect ? "checked" : ""}>
      <span>Ce compte transfère déjà une partie de ses mails vers Gmail (contrôle anti-doublons renforcé).</span></label>
    <div class="result" id="fResult"></div>
    <div class="actions">${edit ? `<button class="btn danger" id="bDel">Supprimer</button>
      <button class="btn ghost" id="bPause">${acc.enabled ? "Mettre en pause" : "Réactiver"}</button>` : ""}
      <span class="grow"></span><button class="btn primary" id="bSave">Enregistrer</button></div>`,
  async (el) => {
    bindEyes(el);
    $("#bBack", el)?.addEventListener("click", sheetPresets);
    if (type === "outlook") {
      const res = await call("outlook_stores");
      const sel = $("#fStore", el);
      sel.innerHTML = res.ok && res.stores.length
        ? res.stores.map((s) => `<option ${s === v.store ? "selected" : ""}>${esc(s)}</option>`).join("")
        : `<option value="">Ouvrez Outlook puis rouvrez ce panneau</option>`;
    }
    $("#bSave", el).onclick = async () => {
      const btn = $("#bSave", el);
      const data = { id: acc?.id || "", preset: key, type, name: $("#fName", el).value.trim(),
        label: $("#fLabel", el).value.trim(), expects_redirect: $("#fRedirect", el).checked };
      if (type === "outlook") data.store = $("#fStore", el).value;
      else Object.assign(data, { host: custom ? $("#fHost", el).value.trim() : v.host,
        port: Number(custom ? $("#fPort", el).value : v.port) || 993,
        user: $("#fUser", el).value.trim(), password: $("#fPass", el).value });
      setBusyButton(btn, true, "Test de connexion…");
      const res = await call("save_account", data);
      setBusyButton(btn, false, "Enregistrer");
      setResult($("#fResult", el), res.ok, res.message);
      if (res.ok) { toast(`${data.name} : compte enregistré`, "ok"); await sleep(1000); closeSheet(); refresh(); }
      else if (res.saved) refresh();
    };
    $("#bDel", el)?.addEventListener("click", async () => {
      const b = $("#bDel", el);
      if (b.dataset.confirm !== "1") { b.dataset.confirm = "1"; b.textContent = "Confirmer ?"; return; }
      await call("delete_account", acc.id); closeSheet(); toast(`${acc.name} supprimé`); refresh();
    });
    $("#bPause", el)?.addEventListener("click", async () => {
      await call("set_account_enabled", acc.id, !acc.enabled); closeSheet();
      toast(acc.enabled ? `${acc.name} en pause` : `${acc.name} réactivé`, "ok"); refresh();
    });
  });
}

// Destination Gmail
function sheetGmail() {
  openSheet(`<div class="sheet-head"><span class="avatar" style="--c:#EA4335">${ICON.mail}</span><h3>Gmail (destination)</h3></div>
    <p class="lead">Tous les comptes arrivent ici, chacun avec son libellé.</p>
    <div class="hint">Google exige un <b>mot de passe d'application</b> (16 lettres), pas votre mot de passe habituel.</div>
    <div class="field"><label>Adresse Gmail</label><input id="gAddr" value="${esc(snap?.gmail.address || "")}" placeholder="prenom.nom@gmail.com" spellcheck="false"></div>
    ${passwordField("gPass", "Mot de passe d'application", `<span class="counter" id="gCount">0/16</span>`)}
    <p class="lead"><a class="link" id="gLink">Créer un mot de passe d'application ${ICON.ext}</a></p>
    <div class="result" id="gResult"></div>
    <div class="actions"><span class="grow"></span><button class="btn primary" id="gSave">Enregistrer et tester</button></div>`,
  (el) => {
    bindEyes(el);
    const pass = $("#gPass", el), counter = $("#gCount", el);
    pass.oninput = () => {
      const n = pass.value.replace(/\s/g, "").length;
      counter.textContent = `${n}/16${n === 16 ? " ✓" : ""}`;
      counter.classList.toggle("good", n === 16);
    };
    $("#gLink", el).onclick = () => call("open_url", APP_PASSWORD_URL);
    $("#gSave", el).onclick = async () => {
      const btn = $("#gSave", el);
      setBusyButton(btn, true, "Test de connexion…");
      const res = await call("save_gmail", $("#gAddr", el).value.trim(), pass.value);
      setBusyButton(btn, false, "Enregistrer et tester");
      setResult($("#gResult", el), res.ok, res.message);
      if (res.ok) { toast("Gmail connecté", "ok"); await sleep(1000); closeSheet(); refresh(); }
    };
  });
}

// Google Agenda : connexion puis calendriers Outlook synchronisés
async function sheetCalendar() {
  await refresh();
  const c = snap.calendar;
  const head = `<div class="sheet-head"><span class="avatar" style="--c:#10B981">${ICON.cal}</span><h3>Google Agenda</h3></div>`;

  if (!c.client) {   // étape 1 : créer et importer l'accès Google
    openSheet(`${head}
      <p class="lead">Copie automatique de vos calendriers Outlook (université, Inserm…) dans Google Agenda.</p>
      <ol class="steps">
        <li class="now"><b>Créer votre accès Google</b><small>5 minutes, une seule fois. Google l'exige pour l'agenda.</small>
          <button class="btn ghost" id="cGuide">Ouvrir le guide pas à pas ${ICON.ext}</button></li>
        <li class="now"><b>Importer le fichier téléchargé</b><small>client_secret_….json</small>
          <button class="btn primary" id="cImport">Importer le fichier</button></li>
        <li><b>Se connecter à Google</b><small>Dans le navigateur, en un clic.</small></li>
      </ol>
      <details class="manual"><summary>Ou coller l'identifiant et le secret</summary>
        <div class="field"><label>ID client</label><input id="cId" placeholder="….apps.googleusercontent.com" spellcheck="false"></div>
        ${passwordField("cSecret", "Code secret du client")}
        <div class="actions"><span class="grow"></span><button class="btn ghost" id="cSave">Enregistrer</button></div>
      </details>
      <div class="result" id="cResult"></div>`,
    (el) => {
      bindEyes(el);
      $("#cGuide", el).onclick = () => call("open_url", GOOGLE_GUIDE_URL);
      const done = async (res) => {
        setResult($("#cResult", el), res.ok, res.message);
        if (res.ok) { toast(res.message, "ok"); await sleep(700); sheetCalendar(); }
      };
      $("#cImport", el).onclick = async () => { const r = await call("google_import_client"); if (r.message) done(r); };
      $("#cSave", el).onclick = async () => done(await call("google_save_client", $("#cId", el).value, $("#cSecret", el).value));
    });
    return;
  }

  if (!c.connected) {   // étape 2 : connexion dans le navigateur
    openSheet(`${head}
      <p class="lead">Dernière étape : autorisez MailBridge à écrire dans votre agenda.</p>
      <ol class="steps"><li class="ok"><b>Accès Google importé</b></li>
        <li class="now"><b>Se connecter à Google</b><small>Une page Google s'ouvre dans votre navigateur. Si Google
        affiche « application non validée », cliquez sur « Paramètres avancés » puis « Accéder à MailBridge » : c'est
        votre propre accès.</small></li></ol>
      <div class="result" id="cResult"></div>
      <div class="actions"><span class="grow"></span><button class="btn primary" id="cConnect">Se connecter à Google</button></div>`,
    (el) => {
      $("#cConnect", el).onclick = async () => {
        const btn = $("#cConnect", el);
        setBusyButton(btn, true, "Validez dans le navigateur…");
        const res = await call("google_connect");
        setBusyButton(btn, false, "Se connecter à Google");
        setResult($("#cResult", el), res.ok, res.message);
        if (res.ok) { toast("Google Agenda connecté", "ok"); await sleep(800); sheetCalendar(); }
      };
    });
    return;
  }

  // Connecté : liste des calendriers synchronisés
  const rows = c.sources.map((s, i) => `<li class="row" data-id="${esc(s.id)}" style="animation-delay:${i * 50}ms">
      <div class="avatar" style="--c:#10B981">${esc(initials(s.label))}</div>
      <div class="row-main"><b>${esc(s.label)}</b><small>${esc(s.error ? s.error : `${s.store} → ${s.target_name || "nouvel agenda"}`)}</small></div>
      <div class="row-end"><span class="badge">${s.count != null ? s.count + " év." : ""}</span>
      <span class="lvl-${s.error ? "err" : s.count != null ? "ok" : "muted"}"><i class="dot"></i></span><span class="chev">${ICON.chev}</span></div></li>`).join("");
  openSheet(`${head}
    <p class="lead">Connecté : <b>${esc(c.email)}</b> · <a class="link" id="cOut">Déconnecter</a></p>
    <ul class="rows">${rows || `<li class="empty">Aucun calendrier : ajoutez celui d'un compte Outlook.</li>`}</ul>
    <div class="result" id="cResult"></div>
    <div class="actions"><button class="chip" id="cAdd"><span class="ico">${ICON.plus}</span>Ajouter un calendrier</button>
      <span class="grow"></span><button class="btn primary" id="cSync">Synchroniser</button></div>`,
  (el) => {
    el.querySelectorAll(".row").forEach((r) => r.onclick = () => sheetCalendarSource(c.sources.find((s) => s.id === r.dataset.id)));
    $("#cAdd", el).onclick = () => sheetCalendarSource(null);
    $("#cOut", el).onclick = async () => { await call("google_disconnect"); toast("Google Agenda déconnecté"); sheetCalendar(); };
    $("#cSync", el).onclick = async () => {
      const btn = $("#cSync", el);
      setBusyButton(btn, true, "Synchronisation…");
      const res = await call("sync_calendars_now");
      setBusyButton(btn, false, "Synchroniser");
      setResult($("#cResult", el), res.ok, res.message);
      refresh();
    };
  });
}

// Ajout / modification d'un calendrier synchronisé
async function sheetCalendarSource(src) {
  const edit = !!src;
  openSheet(`<div class="sheet-head"><button class="back" id="bBack">${ICON.back}</button>
      <span class="avatar" style="--c:#10B981">${ICON.cal}</span><h3>${edit ? esc(src.label) : "Ajouter un calendrier"}</h3></div>
    <p class="lead">Le calendrier principal d'un compte Outlook est copié dans un agenda Google (sens Outlook → Google).</p>
    <div class="field"><label>Compte Outlook</label><select id="kStore"><option>Recherche des comptes Outlook…</option></select></div>
    <div class="field"><label>Nom affiché</label><input id="kLabel" value="${esc(src?.label || "")}" placeholder="U-Paris"></div>
    <div class="field"><label>Agenda Google de destination</label><select id="kTarget"><option>Chargement…</option></select></div>
    <div class="hint">Conseil : un agenda dédié (« MailBridge · … ») se masque ou se supprime d'un clic dans Google Agenda.</div>
    <div class="result" id="kResult"></div>
    <div class="actions">${edit ? `<button class="btn danger" id="kDel">Supprimer</button>` : ""}
      <span class="grow"></span><button class="btn primary" id="kSave">Enregistrer</button></div>`,
  async (el) => {
    $("#bBack", el).onclick = sheetCalendar;
    const [stores, cals] = await Promise.all([call("outlook_stores"), call("google_calendars")]);
    const storeSel = $("#kStore", el), targetSel = $("#kTarget", el), label = $("#kLabel", el);
    storeSel.innerHTML = stores.ok && stores.stores.length
      ? stores.stores.map((s) => `<option ${s === src?.store ? "selected" : ""}>${esc(s)}</option>`).join("")
      : `<option value="">Ouvrez Outlook puis rouvrez ce panneau</option>`;
    const fillTargets = () => {
      const name = `MailBridge · ${label.value.trim() || "Agenda"}`;
      const current = targetSel.value || src?.target_id || "";
      targetSel.innerHTML = `<option value="">＋ Nouvel agenda « ${esc(name)} »</option>` +
        (cals.calendars || []).map((k) => `<option value="${esc(k.id)}" ${k.id === current ? "selected" : ""}>${esc(k.name)}${k.primary ? " (principal)" : ""}</option>`).join("");
    };
    fillTargets();
    label.oninput = fillTargets;
    if (!label.value && storeSel.value) label.value = storeSel.value.split("@")[1]?.split(".")[0]?.toUpperCase() || "";
    storeSel.onchange = () => { if (!edit) { label.value = storeSel.value.split("@")[1]?.split(".")[0]?.toUpperCase() || ""; fillTargets(); } };
    fillTargets();
    $("#kSave", el).onclick = async () => {
      const btn = $("#kSave", el);
      const opt = targetSel.selectedOptions[0];
      const data = { id: src?.id || "", store: storeSel.value, label: label.value.trim(),
        target_id: targetSel.value, target_name: targetSel.value ? opt.textContent.replace(" (principal)", "") : "" };
      setBusyButton(btn, true, "Enregistrement…");
      const res = await call("save_calendar", data);
      if (!res.ok) { setBusyButton(btn, false, "Enregistrer"); return setResult($("#kResult", el), false, res.message); }
      setBusyButton(btn, true, "Première synchronisation…");
      const sync = await call("sync_calendars_now");
      setBusyButton(btn, false, "Enregistrer");
      setResult($("#kResult", el), sync.ok, sync.message);
      if (sync.ok) { toast(sync.message, "ok"); await sleep(900); sheetCalendar(); }
    };
    $("#kDel", el)?.addEventListener("click", async () => {
      const b = $("#kDel", el);
      if (b.dataset.confirm !== "1") { b.dataset.confirm = "1"; b.textContent = "Confirmer ?"; return; }
      await call("delete_calendar", src.id); toast(`${src.label} retiré (l'agenda Google est conservé)`); sheetCalendar();
    });
  });
}

// Réglages
function sheetSettings() {
  const item = (id, icon, title, sub) => `<li><button id="${id}"><span class="ico">${icon}</span><span><b>${title}</b><small>${sub}</small></span></button></li>`;
  openSheet(`<div class="sheet-head"><h3>Réglages</h3></div>
    <label class="switch-line" style="margin-top:8px">
      <span><b>Démarrage automatique</b><small>Au démarrage du PC, puis toutes les ${esc(snap?.interval || 5)} min</small></span>
      <button class="switch" id="autoSwitch" role="switch" aria-checked="${snap?.autostart ? "true" : "false"}"><i></i></button>
    </label>
    <ul class="menu">
      ${item("sGmail", ICON.mail, "Destination Gmail", esc(snap?.gmail.address || "À configurer"))}
      ${item("sTest", ICON.pulse, "Tester toutes les connexions", "Gmail et chaque compte")}
      ${item("sJournal", ICON.doc, "Journal des copies", "Chaque message examiné, au format Excel")}
      ${item("sCal", ICON.cal, "Google Agenda", "Connexion et calendriers synchronisés")}
      ${item("sFolder", ICON.folder, "Dossier de MailBridge", "Configuration et journaux")}
      ${item("sAbout", ICON.code, "À propos", `Version ${esc(snap?.version || "")} · code source sur GitHub`)}
    </ul><div id="sOut"></div>`,
  (el) => {
    $("#autoSwitch", el).onclick = (e) => { e.preventDefault(); toggleAutostart(); };
    $("#sGmail", el).onclick = sheetGmail;
    $("#sJournal", el).onclick = () => call("open_journal");
    $("#sCal", el).onclick = sheetCalendar;
    $("#sFolder", el).onclick = () => call("open_folder");
    $("#sAbout", el).onclick = () => call("open_url", GITHUB_URL);
    $("#sTest", el).onclick = async () => {
      $("#sOut", el).innerHTML = `<div class="result"><span class="ico spinning">${ICON.sync}</span>Test en cours…</div>`;
      const res = await call("check");
      $("#sOut", el).innerHTML = `<div class="mono">${esc(res.message)}</div>`;
    };
  });
}

// ---- Actions principales -----------------------------------------------------
async function syncNow() {
  if (busy) return;
  busy = true;
  $(".hero").classList.add("syncing");
  $("#btnSync").disabled = true;
  $("#syncIco").classList.add("spinning");
  $("#syncTxt").textContent = "Synchronisation…";
  $("#countdown").textContent = "···";
  setStatus("busy", "En cours", "Lecture des comptes et copie vers Gmail…");
  const res = await call("sync_now");
  busy = false;
  $(".hero").classList.remove("syncing");
  $("#btnSync").disabled = false;
  $("#syncIco").classList.remove("spinning");
  $("#syncTxt").textContent = "Synchroniser";
  toast(res.message || (res.ok ? "Terminé" : "Échec"), res.ok ? "ok" : "err", 4500);
  refresh();
}

async function toggleAutostart() {
  const sw = $("#autoSwitch");
  const want = sw.getAttribute("aria-checked") !== "true";
  sw.setAttribute("aria-checked", want ? "true" : "false");
  const res = await call("set_autostart", want);
  toast(res.ok ? (want ? "Démarrage automatique activé" : "MailBridge en pause") : "Modification impossible",
    res.ok ? "ok" : "err");
  refresh();
}

// ---- Démarrage ---------------------------------------------------------------
let started = false;
async function start() {
  if (started) return;
  started = true;
  $("#btnSettings").innerHTML = ICON.gear;
  $("#syncIco").innerHTML = ICON.sync;
  $("#addIco").innerHTML = ICON.plus;
  $("#extIco").innerHTML = ICON.ext;
  $("#btnSettings").onclick = sheetSettings;
  $("#btnSync").onclick = syncNow;
  $("#btnAdd").onclick = sheetPresets;
  $("#btnJournal").onclick = () => call("open_journal");
  $("#backdrop").onclick = closeSheet;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });
  presets = await call("presets");
  await refresh();
  setInterval(refresh, REFRESH_MS);
  setInterval(tick, 1000);
  // Captures d'écran de la documentation : #demo-add, #demo-form
  if (location.hash === "#demo-add") setTimeout(sheetPresets, 900);
  if (location.hash === "#demo-form") setTimeout(() => sheetAccount(null, "yahoo"), 900);
  if (location.hash === "#demo-cal") setTimeout(sheetCalendar, 900);
}
window.addEventListener("pywebviewready", start);
setTimeout(() => { if (!window.pywebview) { demo = true; start(); } }, 700);
if (demo) start();
