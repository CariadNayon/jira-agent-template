/* Jira-Agent: Zahnrad oben rechts + Bestätigungs-Button für "ja <CODE>".
   Wird vom Backend in die HTML-Seite der Databricks-Chat-UI eingefügt (jira_agent/web.py). */
(function () {
  if (window.__jiraGear) return;
  window.__jiraGear = true;

  var style = document.createElement("style");
  style.textContent =
    "#jira-gear{position:fixed;top:10px;right:14px;z-index:2147483000;width:36px;height:36px;border-radius:50%;" +
    "border:1px solid rgba(128,128,128,.4);background:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;" +
    "box-shadow:0 1px 4px rgba(0,0,0,.15)}#jira-gear:hover{background:#f3f3f3}" +
    "#jira-overlay{position:fixed;inset:0;z-index:2147483001;background:rgba(0,0,0,.35);display:none;align-items:center;justify-content:center}" +
    "#jira-panel{width:min(760px,94vw);height:min(640px,90vh);background:#fff;border-radius:10px;overflow:hidden;position:relative;" +
    "box-shadow:0 8px 30px rgba(0,0,0,.25)}#jira-panel iframe{border:0;width:100%;height:100%}" +
    ".jira-confirm{margin:6px 0;padding:6px 12px;border-radius:6px;border:0;background:#1b5fd1;color:#fff;cursor:pointer;font-size:13px}" +
    ".jira-confirm:hover{background:#174fb0}";
  document.head.appendChild(style);

  var gear = document.createElement("button");
  gear.id = "jira-gear";
  gear.title = "Einstellungen (Jira, Modell, Datenquellen, Regeln)";
  gear.setAttribute("aria-label", "Einstellungen");
  gear.innerHTML =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 ' +
    '1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 ' +
    '1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 ' +
    '2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 ' +
    '2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>';

  var overlay = document.createElement("div");
  overlay.id = "jira-overlay";
  overlay.innerHTML = '<div id="jira-panel"><iframe title="Einstellungen"></iframe></div>';
  var frame = overlay.querySelector("iframe");

  function open() { frame.src = "/jira/settings?t=" + Date.now(); overlay.style.display = "flex"; }
  function close() { overlay.style.display = "none"; frame.src = "about:blank"; }
  gear.addEventListener("click", open);
  overlay.addEventListener("click", function (e) { if (e.target === overlay) close(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
  window.addEventListener("message", function (e) {
    if (e.origin === location.origin && e.data === "jira-settings-close") close();
  });

  function mount() {
    if (!document.body) return setTimeout(mount, 100);
    document.body.appendChild(gear);
    document.body.appendChild(overlay);
  }
  mount();

  /* ---------- Bestätigungs-Button ---------- */
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

  function scan() {
    var nodes = document.querySelectorAll("p, li, strong, code");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.closest("#jira-overlay, textarea, form") || el.dataset.jiraScanned) continue;
      var m = CODE_RE.exec(el.textContent || "");
      if (!m) continue;
      var code = m[1];
      el.dataset.jiraScanned = "1";
      // nur bei Vorschlägen des Agenten, nicht bei der kurzen Nutzer-Antwort "ja CODE"; je Code nur ein Button
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

  var pending = false;
  new MutationObserver(function () {
    if (pending) return;
    pending = true;
    setTimeout(function () { pending = false; scan(); }, 400);
  }).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
})();
