"""UI checks: loads the real renderer pages in headless Chromium with a stubbed Electron bridge.
Setup (once):  pip install playwright && playwright install chromium
Run:           python3 test/ui/ui_check.py
Screenshots go to test/ui/out/. This does NOT test Electron windows (drag, always-on-top, focus)."""
import json, os, pathlib, sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
R = (ROOT / "renderer").as_uri() + "/"
OUT = pathlib.Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
STUB = """
(() => {
  const cfg = Object.assign({setupDone:true, editor:'DaVinci Resolve', editorVersion:'20.1', apiBaseUrl:'http://127.0.0.1:8000',
    keepOnTop:true, windowMode:'floating', normal:false, supportedApps:['DaVinci Resolve'], upcomingApps:['Kdenlive','Shotcut']}, %s);
  const calls = []; const listeners = {}; let pending = null;
  window.__calls = calls; window.__closed = false;
  window.close = () => { window.__closed = true; };
  window.__emit = (ch, p) => (listeners[ch] || []).forEach(f => f(p));
  window.__resolveAsk = (r) => pending && pending(r);
  window.__saveResult = {ok:true, restartNeeded:false};
  window.coach = {
    getConfig: async () => cfg,
    saveConfig: async (c) => { calls.push(['save', c]); return window.__saveResult; },
    ask: (q) => { calls.push(['ask', q]); return new Promise(r => { pending = r; }); },
    resizePanel: (...args) => calls.push(['resizePanel', ...args]),
    closePanel: () => calls.push(['closePanel']),
    openSettings: () => calls.push(['openSettings']),
    quit: () => calls.push(['quit']),
    mascot: { dragStart: () => calls.push(['dragStart']), dragMove: () => calls.push(['dragMove']),
              dragEnd: (moved) => calls.push(['dragEnd', moved]), click: () => calls.push(['click']), menu: () => calls.push(['menu']) },
    on: (ch, cb) => { (listeners[ch] = listeners[ch] || []).push(cb); return () => {}; },
  };
})();
"""
fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond: fails.append(name)

def names(page): return [c[0] for c in page.evaluate("window.__calls")]

with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH'))
    def open_page(file, cfg=None, query="", size=(380, 520)):
        ctx = b.new_context(viewport={"width": size[0], "height": size[1]})
        page = ctx.new_page()
        errs = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.add_init_script(STUB % json.dumps(cfg or {}))
        page.goto(R + file + query)
        page.wait_for_timeout(150)
        return page, errs

    # ---------------- panel ----------------
    p, errs = open_page("panel.html")
    check("panel: loads with no console/CSP errors", not errs, errs)
    check("panel: welcome note mentions app and says not verified",
          "DaVinci Resolve 20.1" in p.inner_text("#log") and "aren't checked against sources" in p.inner_text("#log"))
    pb, _ = open_page("panel.html", cfg={"editor": "", "editorVersion": ""})
    check("panel: works with no editing app set (generic welcome)",
          "DaVinci Resolve" not in pb.inner_text("#log") and "Choose your editor" in pb.inner_text("#log"))
    check("panel: empty question disables Send", p.is_disabled("#send"))
    check("panel: shows suggested questions", p.locator("#examples button").count() == 2)
    p.fill("#input", "how do I cut a clip?")
    check("panel: typed question enables Send and counter updates", not p.is_disabled("#send") and p.inner_text("#count").startswith("20 /"))
    p.press("#input", "Enter")
    check("panel: Enter sends the question", p.evaluate("window.__calls.filter(c=>c[0]==='ask')") == [["ask", "how do I cut a clip?"]])
    check("panel: waiting state shown, send disabled", p.is_disabled("#send") and p.inner_text("#status") == "Thinking")
    p.fill("#input", "second question"); p.press("#input", "Enter"); p.click("#send", force=True)
    check("panel: duplicate submits blocked while waiting", names(p).count("ask") == 1)
    p.evaluate("document.activeElement && document.activeElement.blur()")
    p.evaluate("window.__resolveAsk({ok:true, answer:'<img src=x onerror=\"window.__pwned=1\">Press C.\\nThen click.'})")
    p.wait_for_timeout(150)
    check("panel: reply rendered as literal text, no element injected",
          p.locator("#log img").count() == 0 and p.evaluate("window.__pwned") is None and "<img src=x" in p.inner_text("#log"))
    check("panel: newlines preserved", p.evaluate("getComputedStyle(document.querySelector('.msg.coach .body')).whiteSpace") == "pre-wrap")
    check("panel: reply does not steal focus", p.evaluate("document.activeElement.id") != "input")
    check("panel: blank Send stays disabled, waiting cleared", p.is_disabled("#send") and p.inner_text("#status") == "")
    p.fill("#input", "line1"); p.press("#input", "Shift+Enter")
    check("panel: Shift+Enter makes a newline, doesn't send", "\n" in p.input_value("#input") and names(p).count("ask") == 1)
    p.fill("#input", "next"); p.press("#input", "Enter")
    p.evaluate("window.__resolveAsk({ok:false, kind:'offline', message:\"Can't reach the coach server at http://127.0.0.1:8000.\"})")
    p.wait_for_timeout(150)
    check("panel: error shown as alert", p.locator(".msg.error[role=alert]").count() == 1 and "Can't reach" in p.inner_text(".msg.error"))
    check("panel: question restored after error", p.input_value("#input") == "next")
    p.press("#input", "Escape")
    check("panel: Escape collapses", "closePanel" in names(p))
    p.evaluate("window.__emit('panel:shown')"); p.wait_for_timeout(50)
    check("panel: focuses input only when shown by user", p.evaluate("document.activeElement.id") == "input")
    p.click("#settings"); p.click("#collapse")
    check("panel: Settings and Collapse buttons wired", "openSettings" in names(p) and names(p).count("closePanel") == 2)
    p.screenshot(path=str(OUT / "panel.png"))
    # scrolling with a very long answer
    p.fill("#input", "long"); p.press("#input", "Enter")
    p.evaluate("window.__resolveAsk({ok:true, answer:Array.from({length:80},(_, i)=>'Line '+i).join('\\n')})"); p.wait_for_timeout(150)
    check("panel: long answers scroll inside the log",
          p.evaluate("(() => {const l=document.getElementById('log'); return l.scrollHeight > l.clientHeight && getComputedStyle(l).overflowY === 'auto'})()"))
    p.screenshot(path=str(OUT / "panel_long.png"))
    p.click("#clear")
    check("panel: Clear chat restores empty state", p.locator(".msg.user, .msg.coach, .msg.error").count() == 0
          and p.is_visible("#examples") and p.is_disabled("#send"))
    p.click("#examples button:first-child")
    check("panel: example fills the draft without sending", p.input_value("#input") == "How do I make a camera shake?"
          and not p.is_disabled("#send"))

    box = p.locator("#resize").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    p.evaluate("window.__calls.length = 0")
    p.mouse.click(x, y)
    check("panel: grip click alone doesn't resize", p.evaluate("window.__calls") == [["resizePanel", "start"], ["resizePanel", "end"]])
    p.evaluate("window.__calls.length = 0")
    p.mouse.move(x, y); p.mouse.down(); p.mouse.move(x + 40, y + 30); p.mouse.move(x - 40, y - 25); p.mouse.up()
    resize_calls = p.evaluate("window.__calls")
    check("panel: grip captures outward and inward movement", resize_calls == [
        ["resizePanel", "start"], ["resizePanel", "move", 40, 30],
        ["resizePanel", "move", -40, -25], ["resizePanel", "end"]], resize_calls)

    # ---------------- mascot ----------------
    p, errs = open_page("mascot.html", size=(96, 96))
    check("mascot: loads with no console/CSP errors", not errs, errs)
    p.mouse.move(48, 48); p.mouse.down(); p.mouse.up()
    n = names(p)
    check("mascot: plain click -> click only (no drag)", "click" in n and "dragMove" not in n and ["dragEnd", False] in p.evaluate("window.__calls"), n)
    p.evaluate("window.__calls.length = 0")
    p.mouse.move(48, 48); p.mouse.down(); p.mouse.move(70, 60, steps=6); p.mouse.up()
    n = names(p)
    check("mascot: drag -> dragStart/dragMove/dragEnd and NO click", n[0] == "dragStart" and "dragMove" in n and n[-1] == "dragEnd" and "click" not in n and "zoom" not in n, n)
    p.evaluate("window.__calls.length = 0")
    p.mouse.move(48, 48); p.mouse.down(); p.mouse.move(51, 49); p.mouse.up()
    check("mascot: tiny jitter (<5px) still counts as a click", "click" in names(p) and "dragMove" not in names(p))
    p.evaluate("window.__calls.length = 0")
    p.mouse.click(48, 48, button="right")
    check("mascot: right-click opens menu, not the panel", names(p) == ["menu"], names(p))
    p.evaluate("window.__emit('mascot:busy', true); window.__emit('mascot:badge', true)")
    cls = p.evaluate("document.getElementById('pet').className")
    check("mascot: busy animation + badge classes toggle", "busy" in cls and "badge-on" in cls)
    p.evaluate("window.__emit('mascot:busy', false); window.__emit('mascot:badge', false)")
    check("mascot: classes clear", p.evaluate("document.getElementById('pet').className") == "")
    p.evaluate("window.__calls.length = 0"); p.focus("#pet"); p.keyboard.press("Enter")
    check("mascot: keyboard Enter opens panel (accessibility)", names(p) == ["click"])
    check("mascot: hovering does not scale the artwork", p.locator("#pet svg").evaluate("(svg) => getComputedStyle(svg).transform") == "none")
    check("mascot: no resize grip", p.locator("#zoom, #resize").count() == 0)
    p.screenshot(path=str(OUT / "mascot.png"), omit_background=True)

    p, _ = open_page("mascot.html", cfg={"normal": True, "windowMode": "normal"}, size=(96, 96))
    p.mouse.move(48, 48); p.mouse.down(); p.mouse.move(80, 80, steps=4); p.mouse.up()
    check("mascot (normal-window mode): never asks the app to drag; WM does", "dragStart" not in names(p) and "dragMove" not in names(p))
    p.evaluate("window.__calls.length = 0"); p.mouse.click(48, 48)
    check("mascot (normal-window mode): click still toggles panel", names(p) == ["click"])

    # ---------------- setup / settings ----------------
    p, errs = open_page("settings.html", cfg={"setupDone": False, "editor": "", "editorVersion": ""}, query="?mode=setup", size=(460, 380))
    check("setup: loads with no errors", not errs, errs)
    check("setup: no editor preselected", p.input_value("#editor") == "")
    check("setup: editor/version visible, no server or edition field", p.is_visible("#editor") and p.is_visible("#version") and not p.is_visible("#url") and "Studio" not in p.inner_text("body"))
    check("setup: upcoming editor disabled", p.locator("#editor option[value=Kdenlive]").is_disabled())
    p.click("#save")
    check("setup: cannot skip the editor", not names(p) and "Choose a supported" in p.inner_text("#error"))
    p.select_option("#editor", "DaVinci Resolve")
    p.click("#save")
    p.wait_for_timeout(100)
    saves = p.evaluate("window.__calls.filter(c=>c[0]==='save')")
    check("setup: saves explicit editor with optional version", len(saves) == 1 and saves[0][1] == {"editor": "DaVinci Resolve", "editorVersion": "", "finishSetup": True}, saves)
    check("setup: window closes after saving", p.evaluate("window.__closed"))
    p.screenshot(path=str(OUT / "setup.png"))

    p, errs = open_page("settings.html", query="?mode=settings", size=(460, 580))
    check("settings: shows server address, prefilled", p.input_value("#url") == "http://127.0.0.1:8000" and p.is_visible("#url"))
    check("settings: no warning for loopback http", p.inner_text("#urlWarn") == "")
    p.fill("#url", "http://coach.example.com")
    check("settings: warns about plain http to remote host", "unencrypted" in p.inner_text("#urlWarn"))
    p.fill("#url", "http://127.attacker.example:8000")
    check("settings: lookalike 127 hostname warns as remote", "unencrypted" in p.inner_text("#urlWarn"))
    p.evaluate("window.__saveResult = {ok:false, errors:{apiBaseUrl:'The address must start with http:// or https://'}}")
    p.fill("#url", "ftp://x"); p.click("#save"); p.wait_for_timeout(100)
    check("settings: validation error shown, window stays open", "must start with http" in p.inner_text("#error") and not p.evaluate("window.__closed"))
    p.evaluate("window.__saveResult = {ok:true, restartNeeded:true}")
    p.fill("#url", "https://coach.example.com"); p.check("#normalMode"); p.click("#save"); p.wait_for_timeout(100)
    last = p.evaluate("window.__calls.filter(c=>c[0]==='save').slice(-1)[0][1]")
    check("settings: sends URL, keepOnTop, windowMode", last["apiBaseUrl"] == "https://coach.example.com" and last["windowMode"] == "normal" and last["keepOnTop"] is True and last["finishSetup"] is False, last)
    check("settings: restart notice shown when mode changes", "next time you start" in p.inner_text("#info"))
    p.screenshot(path=str(OUT / "settings.png"))
    b.close()

print("\nFAILED:" if fails else "\nALL UI CHECKS PASSED", fails if fails else "")
sys.exit(1 if fails else 0)
