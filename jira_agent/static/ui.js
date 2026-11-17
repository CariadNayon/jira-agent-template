/* Jira-Agent: Anpassung der Databricks-Chat-UI (e2e-chatbot-app-next), eingefügt von jira_agent/web.py.
   - blendet Seitenleiste (Chatverlauf) und die Hinweise "Ephemeral"/"Feedback disabled" aus
   - Kopfzeile: links der Agent name, rechts "Guide", "New Chat" und das Zahnrad
   - Banner "Connect Jira", solange kein Jira-Token gesetzt ist
   - Dateien anhängen (Büroklammer, Strg+V, Drag & Drop) -> /jira/api/upload, Verweis "[Datei: name]" im Text
   - Skill-Vorschläge beim Tippen von "/" (aus /jira/api/skills)
   - Bestätigungs-Button für "ja <CODE>"
   Die UI wird beim App-Start geklont; falls sich ihr Markup ändert, erscheinen die Buttons fest oben rechts. */
(function () {
  if (window.__jiraUi) return;
  window.__jiraUi = true;

  var agentName = "Jira Agent";
  var appVersion = String(window.__jiraAppVersion || "");

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
    '#jira-agent-brand{display:inline-flex;align-items:baseline;gap:7px;min-width:0;max-width:45vw}',
    '#jira-agent-title{font-size:16px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}',
    '#jira-app-version{font-size:11px;font-weight:400;opacity:.65;white-space:nowrap;flex-shrink:0;font-variant-numeric:tabular-nums}',
    '#jira-app-version[hidden]{display:none}',
    '.jira-hdr-btn{height:32px;display:inline-flex;align-items:center;gap:6px;padding:0 10px;border-radius:8px;cursor:pointer;' +
      'border:1px solid rgba(128,128,128,.35);background:transparent;color:inherit;font-size:13px}',
    '.jira-hdr-btn:hover{background:rgba(128,128,128,.12)}',
    '#jira-auto-btn{order:0}#jira-guide-btn{order:1}#jira-gear{order:3;padding:0 8px}',
    '.jira-hdr-btn.on{background:#fff3cd;border-color:#d9b45a}',
    '.jira-fixed{position:fixed;top:10px;z-index:2147483000;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.15)}',
    '#jira-gear.jira-fixed{right:14px}#jira-guide-btn.jira-fixed{right:60px}#jira-auto-btn.jira-fixed{right:150px}',
    '#jira-overlay{position:fixed;inset:0;z-index:2147483001;background:rgba(0,0,0,.35);display:none;align-items:center;justify-content:center}',
    '#jira-panel{width:min(820px,94vw);height:min(680px,90vh);background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.25)}',
    '#jira-panel iframe{border:0;width:100%;height:100%}',
    '.jira-confirm-row{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0}',
    '.jira-confirm{margin:0;padding:6px 12px;border-radius:6px;border:0;background:#1b5fd1;color:#fff;cursor:pointer;font-size:13px}',
    '.jira-confirm:hover{background:#174fb0}',
    '.jira-confirm.jira-decline{background:transparent;color:inherit;border:1px solid rgba(128,128,128,.5)}',
    '.jira-confirm.jira-decline:hover{background:rgba(128,128,128,.15)}',
    /* Jira-Banner */
    '#jira-banner{position:fixed;top:64px;left:50%;transform:translateX(-50%);z-index:60;width:min(720px,92vw);box-sizing:border-box;' +
      'display:none;align-items:center;gap:8px;flex-wrap:wrap;padding:10px 12px;border-radius:10px;font-size:13px;' +
      'background:#fff8e1;color:#4a3800;border:1px solid #f0c36d;box-shadow:0 2px 8px rgba(0,0,0,.12)}',
    '#jira-banner.ok{background:#e8f5e9;color:#1b5e20;border-color:#a5d6a7}',
    '#jira-banner b{margin-right:4px}',
    '#jira-banner form{display:contents}',
    '#jira-banner input.jira-user{position:absolute;width:1px;height:1px;min-width:0;padding:0;border:0;opacity:0;overflow:hidden}',
    '#jira-banner input{flex:1;min-width:200px;padding:6px 8px;border:1px solid #d9b45a;border-radius:6px;font:inherit;background:#fff;color:#222}',
    '#jira-banner input[type="checkbox"]{flex:none;min-width:0;width:auto;margin-right:4px;padding:0}',
    '#jira-banner label{font-size:12px;display:flex;align-items:center}',
    '#jira-banner .remember-help{width:100%;font-size:12px}',
    '#jira-banner .remember-help[hidden]{display:none}',
    '#jira-banner.ok input,#jira-banner.ok button,#jira-banner.ok a,#jira-banner.ok label,#jira-banner.ok>span{display:none}',
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

  /* ---------- Overlay für Settings und Guide ---------- */
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
  var guideBtn = makeButton("jira-guide-btn", HELP_SVG + "<span>Guide</span>", "Guide: customize and extend your agent",
    function () { openPanel("/jira/guide"); });
  var gearBtn = makeButton("jira-gear", GEAR_SVG, "Settings (name, Jira, model, data sources, rules)",
    function () { openPanel("/jira/settings"); });
  var autoBtn = makeButton("jira-auto-btn", "<span>Auto-approve: off</span>",
    "Approve the agent's proposed Jira changes automatically (limited, off by default)", function () {});
  var titleEl = document.createElement("span");
  titleEl.id = "jira-agent-title";
  var versionEl = document.createElement("span");
  versionEl.id = "jira-app-version";
  var brandEl = document.createElement("span");
  brandEl.id = "jira-agent-brand";
  brandEl.appendChild(titleEl);
  brandEl.appendChild(versionEl);

  /* ---------- Kopfzeile einrichten (idempotent, läuft nach jedem React-Neuaufbau) ---------- */
  function ensureLayout() {
    if (!document.body) return;
    if (!overlay.isConnected) document.body.appendChild(overlay);
    var header = document.querySelector("header.sticky") || document.querySelector("header");
    var right = header && header.querySelector(".ml-auto");
    if (right) {
      [autoBtn, guideBtn, gearBtn].forEach(function (b) {
        b.classList.remove("jira-fixed");
        if (b.parentNode !== right) right.appendChild(b);
      });
      if (brandEl.parentNode !== header) header.insertBefore(brandEl, header.firstChild);
    } else {
      [autoBtn, guideBtn, gearBtn].forEach(function (b) {
        b.classList.add("jira-fixed");
        if (b.parentNode !== document.body) document.body.appendChild(b);
      });
    }
    if (titleEl.textContent !== agentName) titleEl.textContent = agentName;
    var label = appVersion ? "v" + appVersion : "";
    if (versionEl.textContent !== label) {
      versionEl.textContent = label;
      versionEl.title = "App version " + appVersion;
      versionEl.setAttribute("aria-label", "App version " + appVersion);
    }
    versionEl.hidden = !appVersion;
    if (document.title !== agentName) document.title = agentName;
  }

  function loadMe() {
    fetch("/jira/api/me", { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("Status unavailable"); return r.json(); })
      .then(function (d) {
        if (!d) return;
        if (d.agent_name) agentName = String(d.agent_name);
        if (d.app_version) appVersion = String(d.app_version);
        ensureLayout();
        bannerRemember.disabled = !d.remember_jira_available;
        bannerRemember.checked = !!d.has_saved_jira_token;
        bannerRemember.parentNode.title = d.remember_jira_available
          ? "Reconnect automatically for up to " + (d.remember_jira_days || 30) + " days after signing in."
          : (d.remember_jira_message || "Remember is not set up yet.");
        bannerRememberReason.textContent = d.remember_jira_message || "Remember is not set up yet. ";
        bannerRememberHelp.hidden = !!d.remember_jira_available;
        if (d.jira_connection_message && !d.has_jira_token) bannerMsg.textContent = d.jira_connection_message;
        showBanner(!d.has_jira_token);
      })
      .catch(function () {
        bannerRemember.disabled = true;
        bannerRememberReason.textContent = "Unable to check Remember availability. Reload the app or sign in again. ";
        bannerRememberHelp.hidden = false;
        showBanner(true);
      });
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
    '<b>Connect Jira:</b><span>Enter your Jira Personal Access Token.</span>' +
    '<form data-token-form method="post" novalidate>' +
    '<input class="jira-user" type="text" name="username" value="jira-token" autocomplete="username" readonly tabindex="-1" aria-hidden="true">' +
    '<input type="password" name="password" autocomplete="current-password" placeholder="Paste your Jira token here …" aria-label="Jira Personal Access Token">' +
    '<button type="submit">Connect</button></form><a data-help>Where can I find my token?</a>' +
    '<label><input type="checkbox" data-remember disabled>Remember for my account</label>' +
    '<div class="remember-help"><span data-remember-reason role="status">Checking whether Remember is available … </span> ' +
    '<a data-remember-setup href="/jira/guide#remember-tokens-setup">Setup help</a></div><div class="msg"></div>';
  var bannerInput = banner.querySelector('input[type="password"]');
  var bannerRemember = banner.querySelector("[data-remember]");
  var bannerRememberHelp = banner.querySelector(".remember-help");
  var bannerRememberReason = banner.querySelector("[data-remember-reason]");
  var bannerMsg = banner.querySelector(".msg");
  var bannerWanted = false;
  function showBanner(show) {
    bannerWanted = show;
    if (!banner.isConnected && document.body) document.body.appendChild(banner);
    if (show) { banner.className = ""; banner.querySelector("b").textContent = "Connect Jira:"; banner.style.display = "flex"; }
    else if (!banner.classList.contains("ok")) banner.style.display = "none";
  }
  /* Ohne Seitenwechsel erkennen Browser das Absenden oft nicht; deshalb das Speichern im Passwortmanager (mit Rückfrage des Browsers) ausdrücklich anbieten. */
  function offerPasswordSave(token) {
    try {
      if (window.PasswordCredential && navigator.credentials && navigator.credentials.store) {
        navigator.credentials.store(new PasswordCredential({ id: "jira-token", name: "Jira token", password: token })).catch(function () {});
      }
    } catch (e) { /* optional */ }
  }
  function connectJira() {
    var token = bannerInput.value.trim();
    if (!token) { bannerMsg.textContent = "Please enter your token first."; return; }
    bannerMsg.textContent = "Checking …";
    fetch("/jira/api/credentials", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jira_token: token, remember_jira: bannerRemember.checked && !bannerRemember.disabled })
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) { bannerMsg.textContent = (res.d && res.d.detail) || "Connection failed."; return; }
        offerPasswordSave(token);
        bannerInput.value = "";
        banner.className = "ok";
        banner.querySelector("b").textContent = "Jira connected";
        bannerMsg.textContent = "Connected as " + res.d.jira_user + (res.d.jira_remembered ? ". Remembered for your account." : ". Session only.");
        setTimeout(function () { banner.style.display = "none"; }, 3500);
        bannerWanted = false;
        loadMe();
      })
      .catch(function () { bannerMsg.textContent = "Connection failed."; });
  }
  // Echtes Formular, damit der Passwortmanager des Browsers das Speichern des Tokens anbietet.
  banner.querySelector("form").addEventListener("submit", function (e) { e.preventDefault(); connectJira(); });
  banner.querySelector("[data-help]").addEventListener("click", function () { openPanel("/jira/guide#jira-token"); });
  banner.querySelector("[data-remember-setup]").addEventListener("click", function (event) {
    event.preventDefault(); openPanel("/jira/guide#remember-tokens-setup");
  });

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
  attachBtn.title = "Attach a file (images, CSV, Excel, PDF, text), paste with Ctrl+V or drag and drop";
  attachBtn.setAttribute("aria-label", "Attach a file");
  attachBtn.addEventListener("click", function () { fileInput.click(); });

  var uploadsInFlight = 0;
  document.addEventListener("submit", function (e) {
    if (uploadsInFlight && e.target && e.target.querySelector && e.target.querySelector("textarea")) {
      e.preventDefault(); e.stopImmediatePropagation(); showToast("Please wait until the attachments have finished uploading.", 5000);
    }
  }, true);
  function uploadFiles(files) {
    files = Array.prototype.slice.call(files || []).map(function (f) {
      if (f.name) return f;
      var ext = { "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp" }[f.type] || "bin";
      return new File([f], "pasted-" + Date.now() + "." + ext, { type: f.type });
    });
    if (!files.length) return;
    var host = document.querySelector("[data-jira-chat-id]");
    var chatId = host && host.getAttribute("data-jira-chat-id");
    if (!chatId) { showToast("The chat is not ready yet. Please reload the page.", 6000); return; }
    var allowed = /\.(png|jpe?g|webp|csv|tsv|xlsx|xlsm|pdf|txt|md|json|xml|ya?ml|log|html|sql|py)$/i;
    var invalid = files.find(function (f) { return !allowed.test(f.name || ""); });
    if (invalid) { showToast("Unsupported file type: " + invalid.name + ". Please use PNG, JPEG or WebP for images.", 7000); return; }
    var oversized = files.find(function (f) { return f.size > (/\.(png|jpe?g|webp)$/i.test(f.name) ? 5 : 20) * 1024 * 1024; });
    if (oversized) { showToast("File too large: " + oversized.name + ". Images: maximum 5 MB; other files: 20 MB.", 7000); return; }
    uploadsInFlight += 1;
    var pending = files.map(function (f) {
      return fetch("/jira/api/upload?name=" + encodeURIComponent(f.name) + "&chat_id=" + encodeURIComponent(chatId), {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": f.type || "application/octet-stream" }, body: f
      }).then(function (r) { return r.json().then(function (d) { return r.ok ? d : Promise.reject(d.detail || "Error"); }); });
    });
    showToast("Uploading " + files.length + " file(s) …", 10000);
    Promise.allSettled(pending).then(function (results) {
      var done = results.filter(function (r) { return r.status === "fulfilled"; }).map(function (r) { return r.value; });
      var failed = results.filter(function (r) { return r.status === "rejected"; });
      // Navigating during upload must never attach files to a different chat's composer.
      var current = document.querySelector("[data-jira-chat-id]");
      if (!current || current.getAttribute("data-jira-chat-id") !== chatId) {
        showToast("These files belong to the previous chat. Please attach them again in the current chat.", 7000); return;
      }
      var ta = textarea();
      if (ta && done.length) {
        var refs = done.map(function (d) { return d.reference; }).join(" ");
        setText(ta, (ta.value ? ta.value.replace(/\s*$/, " ") : "") + refs + " "); ta.focus();
      }
      var text = done.length ? "Uploaded: " + done.map(function (d) { return d.name; }).join(", ") : "";
      if (failed.length) text += (text ? " · " : "") + "Failed: " + failed.map(function (r) { return String(r.reason); }).join("; ");
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
      if (s.quelle === "team" || s.quelle === "katalog") { var t = document.createElement("span"); t.className = "team"; t.textContent = s.quelle === "team" ? "Team" : "Catalog"; row.appendChild(t); }
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
  var CODE_RE = /\b(?:yes|ja)\s+([A-F0-9]{6})\b/g;
  var used = {}, autoPending = {};
  var AUTO_LIMIT = 5;
  var autoLeft = 0;
  try { autoLeft = Math.max(0, parseInt(sessionStorage.getItem("jiraAutoApprove") || "0", 10) || 0); } catch (e) { autoLeft = 0; }
  function setAuto(n) {
    autoLeft = Math.max(0, n);
    try { sessionStorage.setItem("jiraAutoApprove", String(autoLeft)); } catch (e) { /* optional */ }
    autoBtn.classList.toggle("on", autoLeft > 0);
    autoBtn.querySelector("span").textContent = autoLeft > 0 ? "Auto-approve: " + autoLeft + " left" : "Auto-approve: off";
  }
  autoBtn.addEventListener("click", function () {
    if (autoLeft > 0) { setAuto(0); showToast("Auto-approve turned off.", 3000); return; }
    if (confirm("Turn on auto-approve for the next " + AUTO_LIMIT + " actions in this browser tab?\n\n" +
        "The agent will then change Jira without asking you each time. Text in Jira tickets or files could trick the agent " +
        "into proposing unwanted changes. It turns off by itself afterwards, and when you close the tab.")) {
      setAuto(AUTO_LIMIT); showToast("Auto-approve is on for the next " + AUTO_LIMIT + " actions.", 4000);
    }
  });
  setAuto(autoLeft);
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
  /* Nur die letzte Antwort des Agenten kann einen gültigen Vorschlag enthalten (Codes sind einmalig, 10 Minuten gültig). */
  function latestAssistant() {
    var list = document.querySelectorAll('[data-testid="message-user"],[data-testid="message-assistant"]');
    var last = list[list.length - 1];
    return last && last.getAttribute("data-testid") === "message-assistant" ? last : null;
  }
  function approve(code) {
    used[code] = true;
    document.querySelectorAll(".jira-confirm-row").forEach(function (x) { x.remove(); });
    sendText("yes " + code);
  }
  function autoApprove(code) {
    if (used[code] || autoPending[code] || autoLeft <= 0) return;
    autoPending[code] = true;
    showToast("Auto-approving yes " + code + " …", 2500);
    setTimeout(function () {
      if (autoLeft <= 0 || used[code] || !latestAssistant()) { delete autoPending[code]; return; }
      setAuto(autoLeft - 1);
      approve(code);
      if (autoLeft === 0) showToast("Auto-approve limit reached and turned off.", 5000);
    }, 800);
  }
  function scanCodes() {
    var msg = latestAssistant();
    document.querySelectorAll(".jira-confirm-row").forEach(function (row) { if (!msg || !msg.contains(row)) row.remove(); });
    if (!msg || document.querySelector('[data-testid="stop-button"]')) return;
    var contents = msg.querySelectorAll('[data-testid="message-content"]');
    if (!contents.length) return;
    /* Textknoten einzeln lesen: textContent klebt benachbarte Absätze ohne Trennzeichen zusammen ("…FBB98AThis…"). */
    var pieces = [];
    Array.prototype.forEach.call(contents, function (c) {
      var walker = document.createTreeWalker(c, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) pieces.push(walker.currentNode.nodeValue);
    });
    var text = pieces.join("\n");
    var codes = [], m;
    CODE_RE.lastIndex = 0;
    while ((m = CODE_RE.exec(text))) if (codes.indexOf(m[1]) < 0 && !used[m[1]]) codes.push(m[1]);
    var row = msg.querySelector(".jira-confirm-row");
    if (!codes.length) { if (row) row.remove(); return; }
    if (autoLeft > 0) { autoApprove(codes[0]); return; }
    if (!row) {
      row = document.createElement("div");
      row.className = "jira-confirm-row";
      contents[contents.length - 1].parentNode.insertAdjacentElement("afterend", row);
    }
    if (row.dataset.codes === codes.join(",")) return;
    row.dataset.codes = codes.join(",");
    row.textContent = "";
    codes.forEach(function (code) {
      var b = document.createElement("button");
      b.className = "jira-confirm";
      b.dataset.code = code;
      b.textContent = "Approve action (yes " + code + ")";
      b.addEventListener("click", function () { approve(code); });
      row.appendChild(b);
    });
    var decline = document.createElement("button");
    decline.className = "jira-confirm jira-decline";
    decline.textContent = "Decline";
    decline.addEventListener("click", function () {
      codes.forEach(function (c) { used[c] = true; });
      row.remove();
      sendText("No, do not make this change.");
    });
    row.appendChild(decline);
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
