/* Jira-Agent: Anpassung der Databricks-Chat-UI (e2e-chatbot-app-next), eingefügt von jira_agent/web.py.
   - blendet Seitenleiste (Chatverlauf) und die Hinweise "Ephemeral"/"Feedback disabled" aus
   - Kopfzeile: links der Name des Agenten, rechts "Anleitung", "Neuer Chat" und das Zahnrad
   - Banner "Jira verbinden", solange kein Jira-Token gesetzt ist
   - Dateien anhängen (Büroklammer, Strg+V, Drag & Drop) -> /jira/api/upload, Verweis "[Datei: name]" im Text
   - Skill-Vorschläge beim Tippen von "/" (aus /jira/api/skills)
   - Bestätigungs-Button für "ja <CODE>"
   Die UI wird beim App-Start geklont; falls sich ihr Markup ändert, erscheinen die Buttons fest oben rechts. */
(function () {
  if (window.__jiraUi) return;
  window.__jiraUi = true;

  var agentName = "Jira Agent";

  /* ---------- Stil ---------- */
  var style = document.createElement("style");
  style.textContent = [
    /* Seitenleiste (Desktop inkl. Platzhalter, mobil als Sheet) und mobiler Toggle ausblenden */
    '.peer:has([data-sidebar="sidebar"]){display:none!important}',
    '[data-sidebar="sidebar"][data-mobile="true"]{display:none!important}',
    'header [data-testid="sidebar-toggle-button"]{display:none!important}',
    /* Hinweise "Ephemeral" und "Feedback disabled" */
    'header a[href*="agent-framework/chat-app"]{display:none!important}',
    /* Neuer-Chat-Button der Vorlage auch am Desktop zeigen */
    'header .ml-auto > button.md\\:hidden{display:inline-flex!important;order:2;margin-left:0!important}',
    /* Inhalt ohne Seitenleiste links etwas einrücken */
    '@media (min-width:768px){main > div.md\\:mr-2{margin-left:.5rem}}',
    '#jira-agent-title{font-size:16px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:45vw}',
    '.jira-hdr-btn{height:32px;display:inline-flex;align-items:center;gap:6px;padding:0 10px;border-radius:8px;cursor:pointer;' +
      'border:1px solid rgba(128,128,128,.35);background:transparent;color:inherit;font-size:13px}',
    '.jira-hdr-btn:hover{background:rgba(128,128,128,.12)}',
    '#jira-guide-btn{order:1}#jira-gear{order:3;padding:0 8px}',
    '.jira-fixed{position:fixed;top:10px;z-index:2147483000;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.15)}',
    '#jira-gear.jira-fixed{right:14px}#jira-guide-btn.jira-fixed{right:60px}',
    '#jira-overlay{position:fixed;inset:0;z-index:2147483001;background:rgba(0,0,0,.35);display:none;align-items:center;justify-content:center}',
    '#jira-panel{width:min(820px,94vw);height:min(680px,90vh);background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.25)}',
    '#jira-panel iframe{border:0;width:100%;height:100%}',
    '.jira-confirm{margin:6px 0;padding:6px 12px;border-radius:6px;border:0;background:#1b5fd1;color:#fff;cursor:pointer;font-size:13px}',
    '.jira-confirm:hover{background:#174fb0}',
    /* Jira-Banner */
    '#jira-banner{position:fixed;top:64px;left:50%;transform:translateX(-50%);z-index:60;width:min(720px,92vw);box-sizing:border-box;' +
      'display:none;align-items:center;gap:8px;flex-wrap:wrap;padding:10px 12px;border-radius:10px;font-size:13px;' +
      'background:#fff8e1;color:#4a3800;border:1px solid #f0c36d;box-shadow:0 2px 8px rgba(0,0,0,.12)}',
    '#jira-banner.ok{background:#e8f5e9;color:#1b5e20;border-color:#a5d6a7}',
    '#jira-banner b{margin-right:4px}',
    '#jira-banner input{flex:1;min-width:200px;padding:6px 8px;border:1px solid #d9b45a;border-radius:6px;font:inherit;background:#fff;color:#222}',
    '#jira-banner button{padding:6px 12px;border-radius:6px;border:0;background:#1b5fd1;color:#fff;cursor:pointer;font:inherit}',
    '#jira-banner a{color:inherit;text-decoration:underline;cursor:pointer}',
    '#jira-banner .msg{width:100%;font-size:12px}',
    /* Upload */
    '#jira-attach{width:32px;height:32px;border-radius:999px;border:0;background:transparent;color:inherit;cursor:pointer;' +
      'display:inline-flex;align-items:center;justify-content:center;opacity:.75}',
    '#jira-attach:hover{opacity:1;background:rgba(128,128,128,.15)}',
    '#jira-toast{position:fixed;bottom:110px;left:50%;transform:translateX(-50%);z-index:2147483002;padding:8px 14px;border-radius:8px;' +
      'background:#222;color:#fff;font-size:13px;display:none;max-width:90vw}',
    'form.jira-drop{outline:2px dashed #1b5fd1;outline-offset:4px}',
    /* Skill-Vorschläge */
    '#jira-skills{position:fixed;z-index:2147483002;display:none;max-height:260px;overflow:auto;min-width:280px;max-width:520px;' +
      'background:#fff;color:#222;border:1px solid #ddd;border-radius:10px;box-shadow:0 6px 20px rgba(0,0,0,.18);font-size:13px;padding:4px}',
    '#jira-skills div{padding:6px 10px;border-radius:6px;cursor:pointer}',
    '#jira-skills div.active,#jira-skills div:hover{background:#eef3fd}',
    '#jira-skills small{color:#666;margin-left:6px}',
    '#jira-skills .team{font-size:10px;color:#1b5fd1;border:1px solid #1b5fd1;border-radius:4px;padding:0 4px;margin-left:6px}'
  ].join("\n");
  document.head.appendChild(style);

  /* ---------- Overlay für Einstellungen und Anleitung ---------- */
  var overlay = document.createElement("div");
  overlay.id = "jira-overlay";
  overlay.innerHTML = '<div id="jira-panel"><iframe title="Jira Agent"></iframe></div>';
  var frame = overlay.querySelector("iframe");
  function openPanel(url) {
    var parts = url.split("#");
    frame.src = parts[0] + "?t=" + Date.now() + (parts[1] ? "#" + parts[1] : "");
    overlay.style.display = "flex";
  }
  function closePanel() { overlay.style.display = "none"; frame.src = "about:blank"; }
  overlay.addEventListener("click", function (e) { if (e.target === overlay) closePanel(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closePanel(); });
  window.addEventListener("message", function (e) {
    if (e.origin !== location.origin) return;
    if (e.data === "jira-settings-close") { closePanel(); loadMe(); loadSkills(); }
    if (e.data === "jira-settings-saved") { loadMe(); loadSkills(); }
  });

  /* ---------- Buttons ---------- */
  var GEAR_SVG =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 ' +
    '1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 ' +
    '1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 ' +
    '2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 ' +
    '2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>';
  var HELP_SVG =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';

  function makeButton(id, html, title, onClick) {
    var b = document.createElement("button");
    b.id = id; b.type = "button"; b.className = "jira-hdr-btn"; b.title = title;
    b.setAttribute("aria-label", title); b.innerHTML = html;
    b.addEventListener("click", onClick);
    return b;
  }
  var guideBtn = makeButton("jira-guide-btn", HELP_SVG + "<span>Anleitung</span>", "Anleitung: Agent anpassen und erweitern",
    function () { openPanel("/jira/guide"); });
  var gearBtn = makeButton("jira-gear", GEAR_SVG, "Einstellungen (Name, Jira, Modell, Datenquellen, Regeln)",
    function () { openPanel("/jira/settings"); });
  var titleEl = document.createElement("span");
  titleEl.id = "jira-agent-title";

  /* ---------- Kopfzeile einrichten (idempotent, läuft nach jedem React-Neuaufbau) ---------- */
  function ensureLayout() {
    if (!document.body) return;
    if (!overlay.isConnected) document.body.appendChild(overlay);
    var header = document.querySelector("header.sticky") || document.querySelector("header");
    var right = header && header.querySelector(".ml-auto");
    if (right) {
      [guideBtn, gearBtn].forEach(function (b) {
        b.classList.remove("jira-fixed");
        if (b.parentNode !== right) right.appendChild(b);
      });
      if (titleEl.parentNode !== header) header.insertBefore(titleEl, header.firstChild);
      var newChat = right.querySelector("button.md\\:hidden span");
      if (newChat && newChat.textContent === "New Chat") newChat.textContent = "Neuer Chat";
    } else {
      [guideBtn, gearBtn].forEach(function (b) {
        b.classList.add("jira-fixed");
        if (b.parentNode !== document.body) document.body.appendChild(b);
      });
    }
    if (titleEl.textContent !== agentName) titleEl.textContent = agentName;
    if (document.title !== agentName) document.title = agentName;
  }

  function loadMe() {
    fetch("/jira/api/me", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        if (d.agent_name) { agentName = String(d.agent_name); ensureLayout(); }
        showBanner(!d.has_jira_token);
      })
      .catch(function () {});
  }

  /* ---------- Hilfen ---------- */
  var toast = document.createElement("div");
  toast.id = "jira-toast";
  var toastTimer = null;
  function showToast(text, ms) {
    if (!toast.isConnected) document.body.appendChild(toast);
    toast.textContent = text; toast.style.display = "block";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.style.display = "none"; }, ms || 3000);
  }
  function textarea() { return document.querySelector("form textarea") || document.querySelector("textarea"); }
  function setText(ta, text) {
    var setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    setter.call(ta, text);
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }

  /* ---------- Jira-Banner: solange kein Token gesetzt ist ---------- */
  var banner = document.createElement("div");
  banner.id = "jira-banner";
  banner.innerHTML =
    '<b>Jira verbinden:</b><span>Fügen Sie Ihren Jira Personal Access Token ein.</span>' +
    '<input type="password" autocomplete="off" placeholder="Jira-Token hier einfügen …" aria-label="Jira Personal Access Token">' +
    '<button type="button">Verbinden</button><a data-help>Wo finde ich den Token?</a><div class="msg"></div>';
  var bannerInput = banner.querySelector("input");
  var bannerMsg = banner.querySelector(".msg");
  var bannerWanted = false;
  function showBanner(show) {
    bannerWanted = show;
    if (!banner.isConnected && document.body) document.body.appendChild(banner);
    if (show) { banner.className = ""; banner.style.display = "flex"; }
    else if (!banner.classList.contains("ok")) banner.style.display = "none";
  }
  function connectJira() {
    var token = bannerInput.value.trim();
    if (!token) { bannerMsg.textContent = "Bitte zuerst den Token einfügen."; return; }
    bannerMsg.textContent = "Prüfe …";
    fetch("/jira/api/credentials", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jira_token: token })
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) { bannerMsg.textContent = (res.d && res.d.detail) || "Verbindung fehlgeschlagen."; return; }
        bannerInput.value = "";
        banner.className = "ok";
        banner.innerHTML = "<b>Jira verbunden</b><span></span>";
        banner.querySelector("span").textContent = "als " + res.d.jira_user;
        setTimeout(function () { banner.style.display = "none"; }, 3500);
        bannerWanted = false;
        loadMe();
      })
      .catch(function () { bannerMsg.textContent = "Verbindung fehlgeschlagen."; });
  }
  banner.querySelector("button").addEventListener("click", connectJira);
  bannerInput.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); connectJira(); } });
  banner.querySelector("[data-help]").addEventListener("click", function () { openPanel("/jira/guide#jira-token"); });

  /* ---------- Dateien hochladen: Büroklammer, Strg+V, Drag & Drop ---------- */
  var fileInput = document.createElement("input");
  fileInput.type = "file"; fileInput.multiple = true; fileInput.style.display = "none";
  fileInput.accept = ".png,.jpg,.jpeg,.webp,.csv,.tsv,.xlsx,.xlsm,.pdf,.txt,.md,.json,.xml,.yaml,.yml,.log,.html,.sql,.py";
  fileInput.addEventListener("change", function () { uploadFiles(fileInput.files); fileInput.value = ""; });
  var CLIP_SVG =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>';
  var attachBtn = document.createElement("button");
  attachBtn.id = "jira-attach"; attachBtn.type = "button"; attachBtn.innerHTML = CLIP_SVG;
  attachBtn.title = "Datei anhängen (Bilder, CSV, Excel, PDF, Text) – auch per Strg+V oder Ziehen";
  attachBtn.setAttribute("aria-label", "Datei anhängen");
  attachBtn.addEventListener("click", function () { fileInput.click(); });

  var uploadsInFlight = 0;
  document.addEventListener("submit", function (e) {
    if (uploadsInFlight && e.target && e.target.querySelector && e.target.querySelector("textarea")) {
      e.preventDefault(); e.stopImmediatePropagation(); showToast("Bitte warten, bis die Anhänge hochgeladen sind.", 5000);
    }
  }, true);
  function uploadFiles(files) {
    files = Array.prototype.slice.call(files || []).map(function (f) {
      if (f.name) return f;
      var ext = { "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp" }[f.type] || "bin";
      return new File([f], "eingefuegt-" + Date.now() + "." + ext, { type: f.type });
    });
    if (!files.length) return;
    var host = document.querySelector("[data-jira-chat-id]");
    var chatId = host && host.getAttribute("data-jira-chat-id");
    if (!chatId) { showToast("Der Chat ist noch nicht bereit. Bitte Seite neu laden.", 6000); return; }
    var allowed = /\.(png|jpe?g|webp|csv|tsv|xlsx|xlsm|pdf|txt|md|json|xml|ya?ml|log|html|sql|py)$/i;
    var invalid = files.find(function (f) { return !allowed.test(f.name || ""); });
    if (invalid) { showToast("Dateityp nicht unterstützt: " + invalid.name + ". Bilder bitte als PNG, JPEG oder WebP.", 7000); return; }
    var oversized = files.find(function (f) { return f.size > (/\.(png|jpe?g|webp)$/i.test(f.name) ? 5 : 20) * 1024 * 1024; });
    if (oversized) { showToast("Datei zu groß: " + oversized.name + ". Bilder maximal 5 MB, andere Dateien 20 MB.", 7000); return; }
    uploadsInFlight += 1;
    var pending = files.map(function (f) {
      return fetch("/jira/api/upload?name=" + encodeURIComponent(f.name) + "&chat_id=" + encodeURIComponent(chatId), {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": f.type || "application/octet-stream" }, body: f
      }).then(function (r) { return r.json().then(function (d) { return r.ok ? d : Promise.reject(d.detail || "Fehler"); }); });
    });
    showToast("Lade " + files.length + " Datei(en) hoch …", 10000);
    Promise.allSettled(pending).then(function (results) {
      var done = results.filter(function (r) { return r.status === "fulfilled"; }).map(function (r) { return r.value; });
      var failed = results.filter(function (r) { return r.status === "rejected"; });
      // Navigating during upload must never attach files to a different chat's composer.
      var current = document.querySelector("[data-jira-chat-id]");
      if (!current || current.getAttribute("data-jira-chat-id") !== chatId) {
        showToast("Die Dateien gehören zum vorherigen Chat. Bitte im aktuellen Chat erneut anhängen.", 7000); return;
      }
      var ta = textarea();
      if (ta && done.length) {
        var refs = done.map(function (d) { return d.reference; }).join(" ");
        setText(ta, (ta.value ? ta.value.replace(/\s*$/, " ") : "") + refs + " "); ta.focus();
      }
      var text = done.length ? "Hochgeladen: " + done.map(function (d) { return d.name; }).join(", ") : "";
      if (failed.length) text += (text ? " · " : "") + "Fehlgeschlagen: " + failed.map(function (r) { return String(r.reason); }).join("; ");
      showToast(text, failed.length ? 8000 : 3000);
    }).finally(function () { uploadsInFlight -= 1; });
  }
  /* Capture-Phase: die Chat-UI selbst hat keinen Upload-Endpunkt, daher Dateien vorher abfangen */
  document.addEventListener("paste", function (e) {
    var files = e.clipboardData && e.clipboardData.files;
    if (!files || !files.length || !(e.target && e.target.closest && e.target.closest("form"))) return;
    e.preventDefault(); e.stopImmediatePropagation();
    uploadFiles(files);
  }, true);
  document.addEventListener("dragover", function (e) {
    var form = e.target && e.target.closest && e.target.closest("form");
    if (!form || !e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types, "Files") < 0) return;
    e.preventDefault(); form.classList.add("jira-drop");
  }, true);
  document.addEventListener("dragleave", function (e) {
    var form = e.target && e.target.closest && e.target.closest("form");
    if (form) form.classList.remove("jira-drop");
  }, true);
  document.addEventListener("drop", function (e) {
    var form = e.target && e.target.closest && e.target.closest("form");
    if (!form || !e.dataTransfer || !e.dataTransfer.files.length) return;
    e.preventDefault(); e.stopImmediatePropagation(); form.classList.remove("jira-drop");
    uploadFiles(e.dataTransfer.files);
  }, true);
  function ensureAttach() {
    if (!fileInput.isConnected) document.body.appendChild(fileInput);
    var send = document.querySelector('[data-testid="send-button"], [data-testid="stop-button"]');
    if (send && send.parentNode && attachBtn.nextSibling !== send) send.parentNode.insertBefore(attachBtn, send);
  }

  /* ---------- Skills: Vorschläge beim Tippen von "/" ---------- */
  var skills = [];
  var popup = document.createElement("div");
  popup.id = "jira-skills";
  var matches = [], active = 0;
  function loadSkills() {
    fetch("/jira/api/skills", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (d) { skills = Array.isArray(d) ? d : []; })
      .catch(function () {});
  }
  function hidePopup() { popup.style.display = "none"; matches = []; }
  function choose(i) {
    var ta = textarea(), s = matches[i];
    if (!ta || !s) return;
    setText(ta, "/" + s.name + " ");
    hidePopup(); ta.focus();
  }
  function renderPopup(ta) {
    var m = /^\/([a-z0-9-]*)$/.exec(ta.value);
    if (!m || !skills.length) return hidePopup();
    matches = skills.filter(function (s) { return s.name.indexOf(m[1]) === 0; });
    if (!matches.length) return hidePopup();
    active = Math.min(active, matches.length - 1);
    popup.innerHTML = "";
    matches.forEach(function (s, i) {
      var row = document.createElement("div");
      if (i === active) row.className = "active";
      var b = document.createElement("b"); b.textContent = "/" + s.name; row.appendChild(b);
      if (s.quelle === "team") { var t = document.createElement("span"); t.className = "team"; t.textContent = "Team"; row.appendChild(t); }
      var d = document.createElement("small"); d.textContent = s.beschreibung; row.appendChild(d);
      row.addEventListener("mousedown", function (e) { e.preventDefault(); choose(i); });
      popup.appendChild(row);
    });
    if (!popup.isConnected) document.body.appendChild(popup);
    var r = ta.getBoundingClientRect();
    popup.style.left = r.left + "px";
    popup.style.bottom = (window.innerHeight - r.top + 8) + "px";
    popup.style.display = "block";
  }
  document.addEventListener("input", function (e) {
    if (e.target && e.target.tagName === "TEXTAREA" && e.target.closest("form")) { active = 0; renderPopup(e.target); }
  }, true);
  document.addEventListener("keydown", function (e) {
    if (popup.style.display !== "block" || !(e.target && e.target.tagName === "TEXTAREA")) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); e.stopImmediatePropagation();
      active = (active + (e.key === "ArrowDown" ? 1 : matches.length - 1)) % matches.length; renderPopup(e.target);
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault(); e.stopImmediatePropagation(); choose(active);
    } else if (e.key === "Escape") { e.stopImmediatePropagation(); hidePopup(); }
  }, true);
  document.addEventListener("click", function (e) { if (!popup.contains(e.target)) hidePopup(); }, true);

  /* ---------- Bestätigungs-Button für "ja <CODE>" ---------- */
  var CODE_RE = /\bja\s+([A-F0-9]{6})\b/;
  var used = {};
  function sendText(text) {
    var ta = document.querySelector("textarea");
    if (!ta) return;
    var setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    setter.call(ta, text);
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    setTimeout(function () {
      var form = ta.closest("form");
      var btn = (form && form.querySelector('button[type="submit"]')) ||
        document.querySelector('button[aria-label*="end" i], button[data-testid*="send" i]');
      if (btn && !btn.disabled) btn.click();
      else if (form && form.requestSubmit) form.requestSubmit();
      else ta.focus();
    }, 80);
  }
  function scanCodes() {
    var nodes = document.querySelectorAll("main p, main li, main strong, main code");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.closest("#jira-overlay, textarea, form") || el.dataset.jiraScanned) continue;
      var m = CODE_RE.exec(el.textContent || "");
      if (!m) continue;
      var code = m[1];
      el.dataset.jiraScanned = "1";
      /* nur bei Vorschlägen des Agenten, nicht bei der kurzen Nutzer-Antwort; je Code nur ein Button */
      if (used[code] || (el.textContent || "").trim().length < 15 ||
          document.querySelector('.jira-confirm[data-code="' + code + '"]')) continue;
      var b = document.createElement("button");
      b.className = "jira-confirm";
      b.dataset.code = code;
      b.textContent = "Aktion bestätigen (ja " + code + ")";
      b.addEventListener("click", function (ev) {
        var c = ev.currentTarget.dataset.code;
        used[c] = true;
        document.querySelectorAll('.jira-confirm[data-code="' + c + '"]').forEach(function (x) { x.remove(); });
        sendText("ja " + c);
      });
      el.insertAdjacentElement("afterend", b);
    }
  }

  /* ---------- Start und Beobachtung ---------- */
  var pending = false;
  function refresh() {
    pending = false; ensureLayout(); scanCodes(); ensureAttach();
    if (bannerWanted && !banner.isConnected) document.body.appendChild(banner);
  }
  new MutationObserver(function () {
    if (pending) return;
    pending = true;
    setTimeout(refresh, 300);
  }).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  function start() { if (!document.body) return setTimeout(start, 50); refresh(); loadMe(); loadSkills(); }
  start();
})();
