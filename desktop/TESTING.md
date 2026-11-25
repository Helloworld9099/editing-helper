# Testing Editing Coach

Three layers, from quick to real.

## 1. Automated, no display needed (30 seconds)

    npm test

Runs the logic and API-client tests (Node only): request shape, offline, timeout, HTTP errors, bad/odd replies,
redirects, oversized replies, config save/restore/corruption, URL validation, window-placement math.

## 2. Automated UI pages in a browser (optional, one-time setup)

    pip install playwright && playwright install chromium
    python3 test/ui/ui_check.py

Loads the real `renderer/*.html` pages in headless Chromium with a fake bridge. Checks Enter / Shift+Enter / Esc,
duplicate-submit blocking, waiting state, sanitized Markdown replies, no focus steal, click vs drag vs
right-click, setup/settings flows. Screenshots land in `test/ui/out/`.
This does **not** exercise real Electron windows. That's layer 3. (Playwright is test tooling only; the app itself is JS.)

## 3. The real app against a mock backend (no Ollama needed)

Terminal A:

    npm run mock            # fake coach on http://127.0.0.1:8001 (MOCK replies, clearly labeled)

Terminal B:

    npm start

First launch: choose DaVinci Resolve and click Start, then right-click the pet ->
Settings -> Server address `http://127.0.0.1:8001` -> Save. Open the panel and type:

| You type            | You should see                                                        |
|---------------------|-----------------------------------------------------------------------|
| `hello`             | a MOCK reply showing the selected editor and echoing your text                                        |
| `/slow`             | "Thinking..." for ~8s, pet's eyes glance, Send disabled, UI responsive |
| `/err`              | red message: HTTP 500 + "mock: ollama unavailable"; question restored |
| `/bad` `/noanswer`  | red "wasn't valid JSON" / "no text answer field"                      |
| `/html`             | unsafe HTML is sanitized; no script executes and no image is injected |
| `/long`             | long reply scrolls inside the panel                                   |
| `/hang`             | timeout message (first set `"timeoutSeconds": 5` in the config file)  |

Stop the mock and send a question: you should get "Can't reach the coach server".
Then point Settings back to `http://127.0.0.1:8000` and try your real FastAPI backend.

### Multi-editor smoke test

Choose a different editor in Settings and verify that the app remembers the choice after restarting. Repeat a short question with Kdenlive, Adobe Premiere Pro, and one web-based editor (Clipchamp or Canva). Verify that the selected name and optional version reach the mock backend in the returned message. The app provides AI guidance, not verified instructions or direct control of an editing program. The unit tests check all eleven editor names and verify that unsupported values are rejected before making a request.

### Connection Settings and public-release checks

- Launch `npm start` without `EDITING_HELPER_DEV_SETTINGS`: the ordinary Settings screen must not show Server address, Access token, or Forget saved token. Saving editor/window preferences must not change connection configuration.
- Launch the **unpackaged** app with `EDITING_HELPER_DEV_SETTINGS=1 npm start`: the developer-only connection controls should be visible. The shared token must never be returned by config:get, saved in config.json, or sent to a different overridden host.
- In an actual **packaged** build, the app must not read local developer tokens, environment token overrides or mutable saved API URLs. The blank default release-config.json intentionally fails closed; a configured release uses email OTP, per-user JWT verification on the backend and Redis quotas.
- Verify replies with no RAG references show exactly `AI guidance`; replies with references should retain source buttons.
- Public sign-in and shared-store quotas are implemented behind **COACH_AUTH_MODE=users**, but are not production-verified until Supabase + SMTP + Redis + Northflank are configured and tested. Do not distribute any shared service token.

### Judge Demo flow (no Supabase, configured backend required)

- Create a separate `COACH_AUTH_MODE=demo` FastAPI deployment with Redis and `COACH_DEMO_GLOBAL_PER_DAY=100` (or a smaller test value).
- Test unauthenticated `POST /v1/coach` returns 200 and never requires a bearer token.
- Verify Redis quota exhaustion returns 429; Redis outage returns 503; **neither** should contact Gemini.
- For local preview, run `PUBLIC_RELEASE_MODE=demo PUBLIC_API_URL=https://YOUR-DEMO-HOST python3 .github/scripts/write_release_config.py`, then `EDITING_HELPER_PUBLIC_PREVIEW=1 npm start` from `desktop/`.
- Confirm no sign-in button, no access-token field, no server URL field, and no saved developer token sent; restore the checked-in release config after the preview.
- In GitHub Actions, choose `release_mode=demo` to build unsigned OS installer candidates without Supabase variables.
- Install and test the candidate on a clean device, then inspect the installer for embedded private secrets.

### Public user flow (requires configured services)

- Run `python3 .github/scripts/write_release_config.py` from the repository root with valid `PUBLIC_API_URL`, `PUBLIC_SUPABASE_URL`, and `PUBLIC_SUPABASE_PUBLISHABLE_KEY` environment variables.
- Start `EDITING_HELPER_PUBLIC_PREVIEW=1 npm start` from `desktop/`. Select an editor, request an email OTP, and verify it. No shared service token should be shown, required or sent.
- Sign in, ask an editing question, quit, relaunch, confirm session refresh when a secure keyring is available, then sign out.
- Verify missing/expired/fabricated/unconfirmed tokens fail with 401; user daily quota returns 429; Redis outage returns 503 without calling Gemini.
- With no secure keyring (Linux `basic_text`), sign-in should still work for the current session, but not persist an unencrypted refresh token.
- Build candidate installers via GitHub Actions and test `.AppImage`, `.deb`, `.exe`, `.dmg` on their native operating systems. Review signing/notarization requirements.

### RAG reference check

With the RAG-enabled Northflank backend, select Kdenlive and optionally version 26.08, then ask about the Broken TV glitch. A related Kdenlive manual reference button should appear; clicking it should open the original HTTPS documentation in the browser only after you click. Test DaVinci Resolve 20 with Dynamic Zoom. An unrelated editor should not show the Kdenlive or Resolve documentation as its own source.

### Window behavior checklist (what only your laptop can answer)

Open any other app (a text editor, browser, your video editor, anything) and verify:

- [ ] Pet stays 80x80 while dragging, including over another app or across displays; position survives quit + relaunch.
- [ ] With chat open, dragging the pet moves the chat alongside it without resizing either. The triangle tail points at the pet on both sides.
- [ ] The speech bubble's top is never higher than the pet's top, including when opening the chat near the bottom of the screen.
- [ ] With chat open, dragging toward the bottom stops the pet high enough for the whole bubble to remain on screen; closing chat restores unrestricted pet movement.
- [ ] Chat stays on screen and flips sides only when needed.
- [ ] Drag the pet repeatedly left/right/up/down, including after resizing the chat manually: neither window grows. The editor keeps keyboard focus during pet dragging.
- [ ] Right-click the pet > Chat size > Compact resizes deliberately to 320x400; Default restores 380x520. Neither changes the mascot size or steals focus while dragging.
- [ ] Click the other app while the panel is open: panel stays visible, the other app keeps keyboard focus.
- [ ] Send a question, immediately click the other app and keep typing there. When the reply lands, your typing
      is not interrupted (a yellow dot may appear on the pet if the panel was collapsed).
- [ ] Drag the chat corner outward and inward; a click alone does not resize.
      Dragging the pet still moves it without resizing it. The chat size persists on relaunch.
- [ ] Esc collapses; clicking the pet toggles; dragging doesn't open the panel; right-click menu works.
- [ ] Hide 10 min, then launch `npm start` again: pet returns.
- [ ] Works the same over a non-editing app, since the widget never reads or controls other apps.
- [ ] If any of this fails: `npm run start:normal` and note what broke (compositor, GNOME/KDE/etc.).
