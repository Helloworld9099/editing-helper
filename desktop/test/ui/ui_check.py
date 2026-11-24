"""UI checks: loads the real renderer pages in headless Chromium with a stubbed Electron bridge.
Setup (once):  pip install playwright && playwright install chromium
Run:           python3 test/ui/ui_check.py
Screenshots go to test/ui/out/. This does NOT test Electron windows (drag, always-on-top, focus)."""
import base64, json, os, pathlib, sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
R = (ROOT / "renderer").as_uri() + "/"
OUT = pathlib.Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
STUB = """
(() => {
  const cfg = Object.assign({setupDone:true, editor:'DaVinci Resolve', editorVersion:'20.1', apiBaseUrl:'http://127.0.0.1:8000',
    keepOnTop:true, windowMode:'floating', normal:false, accessTokenSaved:false, canSaveAccessToken:true, environmentTokenActive:false, supportedApps:['Adobe Premiere Pro','DaVinci Resolve','Kdenlive','Shotcut','CapCut','ACDSee Luxea','Lightworks','Clipchamp','OpenShot','Canva','iMovie'], upcomingApps:['Final Cut Pro']}, %s);
  const calls = []; const listeners = {}; let pending = null;
  window.__calls = calls; window.__closed = false;
  window.close = () => { window.__closed = true; };
  window.__emit = (ch, p) => (listeners[ch] || []).forEach(f => f(p));
  window.__selectEditor = (name, version = '') => { cfg.editor = name; cfg.editorVersion = version; window.__emit('panel:config-changed'); };
  window.__resolveAsk = (r) => pending && pending(r);
  window.__saveResult = {ok:true, restartNeeded:false};
  window.coach = {
    getConfig: async () => cfg,
    saveConfig: async (c) => { calls.push(['save', c]); return window.__saveResult; },
    ask: (q) => { calls.push(['ask', q]); return new Promise(r => { pending = r; }); },
    openScreenAnalysis: async () => { calls.push(['openScreenAnalysis']); return {ok:true}; },
    openSource: async (url) => { calls.push(['openSource', url]); return true; },
    clearSources: () => calls.push(['clearSources']),
    resizePanel: (...args) => calls.push(['resizePanel', ...args]),
    closePanel: () => calls.push(['closePanel']),
    openSettings: () => calls.push(['openSettings']),
    quit: () => calls.push(['quit']),
    mascot: { dragStart: () => calls.push(['dragStart']), dragMove: () => calls.push(['dragMove']),
              dragEnd: (moved) => calls.push(['dragEnd', moved]), click: () => calls.push(['click']), menu: () => calls.push(['menu']) },
    on: (ch, cb) => { (listeners[ch] = listeners[ch] || []).push(cb); return () => {}; },
  };
  window.capture = {
    destination: async () => ({destination:cfg.apiBaseUrl, editor:cfg.editor, version:cfg.editorVersion}),
    onUploaded: (cb) => { window.__upload = cb; },
    send: (...args) => {
      calls.push(['analyze', ...args]);
      return new Promise(r => { window.__resolveAnalysis = r; });
    },
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
    check("panel: speech-bubble tail visible on the left by default",
          p.evaluate("(() => {const x=getComputedStyle(document.body,'::before'); return document.body.dataset.panelSide==='right' && x.content!=='none' && x.left==='0px';})()"))
    p.evaluate("window.__emit('panel:side', 'left')")
    check("panel: tail points right when bubble is to the left of pet",
          p.evaluate("(() => {const x=getComputedStyle(document.body,'::before');return document.body.dataset.panelSide==='left' && x.right==='0px';})()"))
    p.evaluate("window.__emit('panel:side', 'right')")
    check("panel: bubble controls fit within the panel window",
          p.evaluate("(() => {const b=document.querySelector('.panel').getBoundingClientRect();const s=document.querySelector('#send').getBoundingClientRect();return b.left>=15 && b.right<=innerWidth && s.bottom<=innerHeight;})()"))
    check("panel: studio header is present", p.locator(".brand-symbol .slate").count() == 1 and "Your creative sidekick" in p.inner_text(".brand"))
    check("panel: no horizontal overflow", p.evaluate("document.documentElement.scrollWidth <= innerWidth"))
    compact, _ = open_page("panel.html", size=(320, 400))
    check("panel: compact remains fully usable",
          compact.evaluate("(() => { const s=document.querySelector('#send').getBoundingClientRect(); const v=document.documentElement; return v.scrollWidth <= innerWidth && s.right <= innerWidth && s.bottom <= innerHeight && document.querySelector('#input').getBoundingClientRect().bottom < innerHeight; })()"))
    compact.screenshot(path=str(OUT / "panel_compact.png"))
    minimum, _ = open_page("panel.html", size=(300, 300))
    check("panel: minimum window keeps Send visible",
          minimum.evaluate("(() => {const s=document.querySelector('#send').getBoundingClientRect(); return document.documentElement.scrollWidth <= innerWidth && s.bottom <= innerHeight;})()"))
    minimum.get_by_role("button", name="Analyze Screen").click()
    check("panel: Analyze Screen is accessible at the minimum size", names(minimum) == ["openScreenAnalysis"])
    minimum.fill("#input", "Draft question")
    minimum.focus("#analyze-screen")
    minimum.evaluate("""window.__emit('panel:screen-analysis', {answer:'**Review** <img src=x onerror="alert(1)">'})""")
    check("panel: screenshot reply is labeled, sanitized, and keeps the draft and focus",
          minimum.locator(".msg.coach strong").inner_text() == "Review"
          and "Screenshot analysis" in minimum.locator(".msg.coach .who").text_content()
          and minimum.locator(".msg.coach img").count() == 0
          and minimum.input_value("#input") == "Draft question"
          and minimum.evaluate("document.activeElement.id") == "analyze-screen")
    check("panel: welcome note mentions app and says not verified",
          "DaVinci Resolve 20.1" in p.inner_text("#log") and "Related references" in p.inner_text("#log"))
    p.evaluate("window.__selectEditor('Kdenlive', '26.08')")
    p.wait_for_timeout(50)
    check("panel: editor label refreshes after Settings change without reopening",
          "Kdenlive 26.08" in p.inner_text("#log") and "DaVinci Resolve 20.1" not in p.inner_text("#log"))
    p.evaluate("window.__selectEditor('DaVinci Resolve', '20.1')")
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
    check("panel: untrusted HTML cannot insert images, scripts, or event handlers",
          p.locator("#log img, #log script").count() == 0 and p.evaluate("window.__pwned") is None and "Press C." in p.inner_text("#log"))
    check("panel: coach reply uses Markdown layout",
          p.evaluate("getComputedStyle(document.querySelector('.msg.coach .body')).whiteSpace") == "normal")
    check("panel: reply does not steal focus", p.evaluate("document.activeElement.id") != "input")
    check("panel: draft typed during wait is preserved and Send re-enabled",
          not p.is_disabled("#send") and p.input_value("#input") == "second question" and p.inner_text("#status") == "")
    p.fill("#input", "show formatting"); p.press("#input", "Enter")
    p.evaluate("window.__resolveAsk({ok:true, answer:'## Method 1\\n\\n**Bold instruction**\\n\\n1. First step\\n2. Second step\\n\\n`code`'})")
    p.wait_for_timeout(150)
    check("panel: Markdown headings, bold, lists, and inline code are rendered",
          p.locator(".msg.coach .body h2").count() >= 1
          and p.locator(".msg.coach .body strong").count() >= 1
          and p.locator(".msg.coach .body ol li").count() >= 2
          and p.locator(".msg.coach .body code").count() >= 1)
    check("panel: no visible Markdown syntax tokens",
          "**Bold instruction**" not in p.inner_text(".msg.coach:last-of-type"))

    p.fill("#input", "how do I use Transform?"); p.press("#input", "Enter")
    p.evaluate("""window.__resolveAsk({ok:true,answer:'Use Transform [1].',sources:[{
      title:'Kdenlive Transform Manual', url:'https://docs.kdenlive.org/en/transform.html',
      source_kind:'official', version:'26.08', review_status:'source_checked'
    }]})""")
    p.wait_for_timeout(100)
    check("panel: source information appears as a button",
          p.locator(".msg.coach .source-link").count() == 1
          and "Source-reviewed notes" in p.locator(".msg.coach .source-label").last.text_content())
    p.click(".msg.coach .source-link")
    check("panel: source opens through the restricted native bridge",
          ['openSource', 'https://docs.kdenlive.org/en/transform.html'] in p.evaluate("window.__calls"))

    p.fill("#input", "line1"); p.press("#input", "Shift+Enter")
    check("panel: Shift+Enter makes a newline, doesn't send", "\n" in p.input_value("#input") and names(p).count("ask") == 3)
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

    # ---------------- screen analysis ----------------
    p, errs = open_page("capture.html", size=(360, 400))
    fixture = p.evaluate("document.createElement('canvas').toDataURL('image/png').split(',')[1]")
    p.locator("#file").set_input_files({"name": "fixture.png", "mimeType": "image/png",
                                       "buffer": base64.b64decode(fixture)})
    p.get_by_role("button", name="Analyze Screenshot").wait_for()
    check("analysis: review and privacy precede all uploads",
          not names(p) and p.is_visible("#preview") and "Google Gemini" in p.inner_text("#privacy")
          and "DaVinci Resolve 20.1" in p.inner_text("#editor"))
    p.select_option("#mode", "effect")
    p.select_option("#content-type", "gaming")
    p.fill("#context", "Minecraft montage")
    p.fill("#question", "How do I add an impact zoom?")
    p.screenshot(path=str(OUT / "capture_compact.png"))
    p.click("#send")
    check("analysis: confirmation sends preview and selected options exactly once",
          p.evaluate("window.__calls") == [["analyze", "image/png", p.get_attribute("#preview", "src").split(",")[1],
                                           "effect", "gaming", "Minecraft montage", "How do I add an impact zoom?"]]
          and p.is_disabled("#send") and "Uploading" in p.inner_text("#status"))
    p.evaluate("window.__upload()")
    check("analysis: shows the waiting state after upload", "Waiting" in p.inner_text("#status"))
    p.evaluate("window.__resolveAnalysis({error:'Gemini rate limit reached.'})")
    check("analysis: failure preserves preview and form for retry",
          "rate limit" in p.inner_text("#status") and not p.is_disabled("#send")
          and p.is_visible("#preview") and p.input_value("#context") == "Minecraft montage")
    p.click("#send")
    p.evaluate("window.__resolveAnalysis({ok:true})")
    check("analysis: success clears the image and directs the user to chat",
          names(p) == ["analyze", "analyze"] and not p.locator("#preview").get_attribute("src")
          and "added to chat" in p.inner_text("#status") and not errs, errs)
    p.press("#cancel", "Escape")
    check("analysis: Escape closes the review window", p.evaluate("window.__closed"))

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
    check("mascot: fixed 80px artwork even after hover",
          p.locator("#pet svg").evaluate("(svg) => svg.getBoundingClientRect().width === 80 && svg.getBoundingClientRect().height === 80"))
    p.emulate_media(reduced_motion="reduce")
    p.evaluate("window.__emit('mascot:busy', true)")
    check("mascot: reduce-motion disables thinking animation",
          p.locator("#pet .eyes").evaluate("(eyes) => getComputedStyle(eyes).animationName === 'none'"))
    p.evaluate("window.__emit('mascot:busy', false)")
    p.screenshot(path=str(OUT / "mascot.png"), omit_background=True)

    p, _ = open_page("mascot.html", cfg={"normal": True, "windowMode": "normal"}, size=(96, 96))
    p.mouse.move(48, 48); p.mouse.down(); p.mouse.move(80, 80, steps=4); p.mouse.up()
    check("mascot (normal-window mode): never asks the app to drag; WM does", "dragStart" not in names(p) and "dragMove" not in names(p))
    p.evaluate("window.__calls.length = 0"); p.mouse.click(48, 48)
    check("mascot (normal-window mode): click still toggles panel", names(p) == ["click"])

    # ---------------- setup / settings ----------------
    p, errs = open_page("settings.html", cfg={"setupDone": False, "editor": "", "editorVersion": ""}, query="?mode=setup", size=(460, 380))
    check("setup: loads with no errors", not errs, errs)
    check("setup: primary Start action fits inside native window",
          p.evaluate("(() => {const s=document.querySelector('#save').getBoundingClientRect();return s.bottom <= innerHeight && document.documentElement.scrollWidth <= innerWidth;})()"))
    check("setup: no editor preselected", p.input_value("#editor") == "")
    check("setup: editor/version visible, no server or edition field", p.is_visible("#editor") and p.is_visible("#version") and not p.is_visible("#url") and "Studio" not in p.inner_text("body"))
    check("setup: shows all eleven available editors",
          p.locator("#editor option:not([disabled])").count() == 11
          and not p.locator("#editor option[value=Kdenlive]").is_disabled()
          and not p.locator("#editor option[value=iMovie]").is_disabled())
    check("setup: future editor stays disabled", p.locator("#editor option[value='Final Cut Pro']").is_disabled())
    p.click("#save")
    check("setup: cannot skip the editor", not names(p) and "Choose a supported" in p.inner_text("#error"))
    p.select_option("#editor", "Kdenlive")
    p.click("#save")
    p.wait_for_timeout(100)
    saves = p.evaluate("window.__calls.filter(c=>c[0]==='save')")
    check("setup: saves explicit editor with optional version", len(saves) == 1 and saves[0][1] == {"editor": "Kdenlive", "editorVersion": "", "finishSetup": True}, saves)
    check("setup: window closes after saving", p.evaluate("window.__closed"))
    p.screenshot(path=str(OUT / "setup.png"))

    p, errs = open_page("settings.html", query="?mode=settings", size=(460, 650))
    check("settings: shows server address, prefilled", p.input_value("#url") == "http://127.0.0.1:8000" and p.is_visible("#url"))
    check("settings: access token is not prefilled or exposed", p.is_visible("#accessToken") and p.input_value("#accessToken") == ""
          and not p.is_disabled("#accessToken"))
    p.fill("#accessToken", "secret-test-token")

    check("settings: no warning for loopback http", p.inner_text("#urlWarn") == "")
    p.fill("#url", "http://coach.example.com")
    check("settings: warns about plain http to remote host", "unencrypted" in p.inner_text("#urlWarn"))
    p.fill("#url", "http://127.attacker.example:8000")
    check("settings: lookalike 127 hostname warns as remote", "unencrypted" in p.inner_text("#urlWarn"))
    p.evaluate("window.__saveResult = {ok:false, errors:{apiBaseUrl:'The address must start with http:// or https://'}}")
    p.fill("#url", "ftp://x"); p.click("#save"); p.wait_for_timeout(100)
    check("settings: validation error shown, window stays open", "must start with http" in p.inner_text("#error") and not p.evaluate("window.__closed"))
    p.evaluate("window.__saveResult = {ok:true, restartNeeded:true}")
    p.fill("#url", "https://coach.example.com"); p.select_option("#editor", "ACDSee Luxea"); p.check("#normalMode"); p.click("#save"); p.wait_for_timeout(100)
    last = p.evaluate("window.__calls.filter(c=>c[0]==='save').slice(-1)[0][1]")
    check("settings: sends URL, access token, keepOnTop, windowMode",
          last["apiBaseUrl"] == "https://coach.example.com" and last["accessToken"] == "secret-test-token"
          and last["forgetAccessToken"] is False and last["windowMode"] == "normal"
          and last["keepOnTop"] is True and last["finishSetup"] is False
          and last["editor"] == "ACDSee Luxea", last)
    check("settings: restart notice shown when mode changes", "next time you start" in p.inner_text("#info"))
    p.screenshot(path=str(OUT / "settings.png"))

    p, errs = open_page("settings.html", cfg={"accessTokenSaved": True}, query="?mode=settings", size=(460, 650))
    check("settings: saved credential is never returned to UI",
          "encrypted access token is saved" in p.inner_text("#tokenHint") and p.input_value("#accessToken") == "")
    p.check("#forgetToken")
    check("settings: removing token disables replacement field", p.is_disabled("#accessToken"))
    p.click("#save"); p.wait_for_timeout(80)
    payload = p.evaluate("window.__calls.filter(c=>c[0]==='save').slice(-1)[0][1]")
    check("settings: forget token sends clear intent", payload["forgetAccessToken"] is True and payload["accessToken"] == "")

    p, errs = open_page("settings.html", cfg={"canSaveAccessToken": False},
                        query="?mode=settings", size=(460, 650))
    check("settings: unsafe Linux fallback cannot save a token",
          p.is_disabled("#accessToken") and "keyring unavailable" in p.inner_text("#tokenHint").lower())
    b.close()

print("\nFAILED:" if fails else "\nALL UI CHECKS PASSED", fails if fails else "")
sys.exit(1 if fails else 0)
