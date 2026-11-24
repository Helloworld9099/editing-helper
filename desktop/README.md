# Editing Coach desktop frontend

This Electron app is a floating desktop companion. It sends a question and the
selected editor (plus the optional version) to the Editing Helper API. It does
not read, upload, or control your editor, clips, or screen.

## Test the frontend without a model

From the repository root, on Ubuntu with Node.js 22.12+ and npm:

```bash
cd desktop
npm ci
npm run mock
```

Leave that terminal open. In a second terminal, from the repository root:

```bash
cd desktop
npm start
```

1. Choose an editor (for example, **Kdenlive** or **DaVinci Resolve**) and click **Start**. All 11 requested editors are selectable; none is preselected. The version is optional.
2. Click the floating pet, open **Settings**, and set **Server address** to
   `http://127.0.0.1:8001`. Save.
3. Ask **How do I make a camera shake?** The mock should echo the question and
   show **Editor: DaVinci Resolve**. It does not generate real instructions.
4. Drag the pet to move it without scaling: the chat is a speech bubble with
   a triangle pointing toward the pet's face. Its top always starts below the
   visible clapperboard cap, and it switches sides near screen edges. With the chat open the pet
   stays high enough for the full bubble to fit on screen. Neither window
   changes size or grabs keyboard focus during pet dragging. Drag the bottom-right
   corner of the chat window only when you actually want to resize it. The chat remembers
   its size. For a smaller, less intrusive chat, right-click the pet and choose
   **Chat size → Compact**. Choose **Chat size → Default** to restore its original size.
5. Try `/long` for scrolling, `/slow` for a delayed reply, and `/err` for retry.
   Stop the mock server with Ctrl+C when finished.

## Visual and motion behavior

The studio-style UI uses layered surfaces and a small set of teal tones. The
mascot now has highlights and a brief hover expression, but **no continuous idle
movement**. The pet and chat window dimensions remain fixed while dragging;
only the chat resize grip or the explicit size presets change chat dimensions.
The model's thinking indicator is the only repeating status animation, and it
stops when the request finishes. The OS `prefers-reduced-motion` setting
disables nonessential animations. No sounds, automatic messages, or focus changes
are introduced by the redesign.

Try `npm run start:normal` if the floating overlay doesn't behave on your
desktop. On Linux the floating mode defaults to X11/XWayland. The normal
mode uses regular framed windows. Windows and macOS are not verified.

## Connect to the real backend

Set **Server address** back to `http://127.0.0.1:8000`. See the
[root README](../README.md) to start the local API and a runner. The desktop
makes requests in Electron's main process, so no CORS change is needed.
AI responses are rendered as sanitized Markdown in the chat bubble. Headings, lists, bold text, and code blocks display normally; potentially unsafe HTML and images are discarded. User messages and error messages are kept as literal text.

## Supported editing software

The editor selector offers AI guidance for **Adobe Premiere Pro, DaVinci Resolve, Kdenlive, Shotcut, CapCut, ACDSee Luxea, Lightworks, Clipchamp, OpenShot, Canva, and iMovie**. The choice and optional version are sent to the same FastAPI endpoint. The app is **not** integrated with the editor's controls or files, and answers are not verified against documentation for every editor/version; check menu names and edition limitations before following advanced instructions.

The request shape is `{"question":"...", "editor":"DaVinci Resolve", "version":"20.1"}`
(version optional); the response is `{"answer":"..."}`.

The existing launcher can start the local GGUF runner, API and desktop
together. From the repository root, after `npm ci` in `desktop/`:

```bash
python launch.py --runner /path/to/llama-server --model /path/to/model.gguf -- \
  "$PWD/desktop/node_modules/.bin/electron" "$PWD/desktop"
```

## Connect to a hosted backend

**One-time setup (recommended):**

1. Launch the app normally with `cd desktop && npm start`.
2. Right-click the pet and open **Settings**.
3. Enter the **Server address** (the HTTPS URL for your Northflank FastAPI service).
4. Enter the **Access token** once (the same value configured as `COACH_ACCESS_TOKEN` on Northflank). Click **Save**.
5. On later launches, simply run `npm start`. The server URL is already saved in `config.json`, while the access token is encrypted separately using Electron's OS keyring support.

You can replace a token by entering a new value in Settings, or select **Forget saved access token** to remove it. The token is **never returned to the HTML renderer, written to config.json, or committed to GitHub**. Electron's main process uses it only as an HTTPS bearer token (or to a loopback localhost server).

On Ubuntu, secure saving requires an unlocked GNOME Keyring or KWallet. If Electron selects its insecure Linux `basic_text` backend, the app **refuses to store** the token and Settings explains that the secure keyring is unavailable. If necessary, continue with the previous environment-variable launch method; avoid plaintext token files in the repository.

**Optional environment overrides (development / insecure keyring fallback):**

```bash
read -rsp 'Coach access token: ' EDITING_HELPER_ACCESS_TOKEN
printf '\n'
EDITING_HELPER_API=https://coach.example.com \
  EDITING_HELPER_ACCESS_TOKEN="$EDITING_HELPER_ACCESS_TOKEN" npm start
unset EDITING_HELPER_ACCESS_TOKEN
```

`EDITING_HELPER_API` overrides the saved URL for a single launch. `EDITING_HELPER_ACCESS_TOKEN` independently overrides the saved token for that process. The Gemini API key remains on the FastAPI backend, not the desktop.

## Verification and scope

Run `npm test` for the client tests. See [TESTING.md](TESTING.md)
for renderer tests and the manual desktop checklist. Desktop rendering and
mock replies do not establish model accuracy. Related source references appear when the backend retrieves reviewed knowledge notes; they do not guarantee that every generated step is correct. A fully verified tutorial library, screen capture, installers, and packaged weights are not implemented by this integration. For adding documentation notes, see [knowledge/README.md](../knowledge/README.md).
