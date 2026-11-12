/* Jira-Agent: Anpassung der Databricks-Chat-UI (e2e-chatbot-app-next), eingefügt von jira_agent/web.py.
   - blendet Seitenleiste (Chatverlauf) und die Hinweise "Ephemeral"/"Feedback disabled" aus
   - Kopfzeile: links der Name des Agenten, rechts "Anleitung", "Neuer Chat" und das Zahnrad
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
    '.jira-confirm:hover{background:#174fb0}'
  ].join("\n");
  document.head.appendChild(style);

  /* ---------- Overlay für Einstellungen und Anleitung ---------- */
  var overlay = document.createElement("div");
  overlay.id = "jira-overlay";
  overlay.innerHTML = '<div id="jira-panel"><iframe title="Jira Agent"></iframe></div>';
  var frame = overlay.querySelector("iframe");
  function openPanel(url) { frame.src = url + "?t=" + Date.now(); overlay.style.display = "flex"; }
  function closePanel() { overlay.style.display = "none"; frame.src = "about:blank"; }
  overlay.addEventListener("click", function (e) { if (e.target === overlay) closePanel(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closePanel(); });
  window.addEventListener("message", function (e) {
    if (e.origin !== location.origin) return;
    if (e.data === "jira-settings-close") closePanel();
    if (e.data === "jira-settings-saved") loadName();
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

  function loadName() {
    fetch("/jira/api/me", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && d.agent_name) { agentName = String(d.agent_name); ensureLayout(); } })
      .catch(function () {});
  }

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
  function refresh() { pending = false; ensureLayout(); scanCodes(); }
  new MutationObserver(function () {
    if (pending) return;
    pending = true;
    setTimeout(refresh, 300);
  }).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  function start() { if (!document.body) return setTimeout(start, 50); refresh(); loadName(); }
  start();
})();
