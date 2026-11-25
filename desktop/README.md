# Editing Coach desktop frontend

This Electron app is a floating desktop companion for editing questions and
screenshot-guided suggestions. It sends the selected editor and optional version
to the Editing Helper API.

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
EDITING_HELPER_DEV_SETTINGS=1 npm start
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

## Analyze a screenshot

Use a backend with Screen Analysis enabled and choose your editor and optional
version in **Settings**. In a configured public build, sign in with your email
before opening Screen Analysis. [Backend setup](../README.md#enable-screen-analysis)

1. Click **Analyze Screen** next to the chat composer, or choose it from the pet’s right-click menu.
2. Choose **Choose display**, **Choose window**, or **Open screenshot…** for a PNG or JPEG. If a source list appears, select the source and click **Capture**. On Wayland, the system may open its own screen-sharing picker.
3. Check the preview. To share a smaller area, open **Crop to a region**, enter the rectangle in image pixels, and click **Apply crop**. Use **Retake** for a different image or **Cancel** to close the window.
4. Pick an **Analysis mode**. Leave **Content type** set to **Auto-detect** or choose a category such as **Minecraft / Gaming**. Add creative context or a specific question if it will help.
5. Click **Analyze Screenshot** to send the reviewed preview. The answer appears in chat under **Screenshot analysis**. If the request fails, the review window keeps the preview and options so you can retry.

| Mode | When to use it |
| --- | --- |
| **Improve This Scene** | Ask for the most useful visible changes to framing, readability, color, or composition. |
| **How Do I Create This Effect?** | Name or describe the effect in **Question** to get an editor-specific workflow and suggested starting settings. |
| **Fix What I’m Doing** | Describe the symptom and capture the relevant controls or preview so the coach can suggest checks. |

A screenshot is a single still. Capture the relevant controls at a readable
size, and describe any motion, timing, or audio issue in the question.

### Screenshot privacy

Screen Analysis takes a single capture when you pick a source. The app sends
the reviewed preview, editor details, and any context or question only after
you click **Analyze Screenshot**. The review window names the backend
destination. The backend forwards the image to Google Gemini even if you run
FastAPI locally. Editing Helper keeps working images in memory and clears the
preview when you close it or the analysis succeeds. Closing the window after
submission cancels the desktop request. The backend or Gemini may already have
received the image. [Gemini API terms](https://ai.google.dev/gemini-api/terms)

### Capture permissions and troubleshooting

| Platform or symptom | What to try |
| --- | --- |
| **Ubuntu on X11 or XWayland** | The app defaults to X11/XWayland. Bring the target window onscreen and retry. Some native Wayland windows may be absent from the XWayland list. If the mascot positioning interferes, try `npm run start:normal`. |
| **Ubuntu on native Wayland** | For a source launch, try `EDITING_COACH_NATIVE_WAYLAND=1 npm start` from `desktop/`. Choose a source in the system picker and allow sharing. If the picker is missing, check that PipeWire and the XDG Desktop Portal backend for your GNOME or KDE session are running. The compositor can restrict which sources are available. |
| **macOS** | Allow Editing Helper under **System Settings → Privacy & Security → Screen & System Audio Recording**, then relaunch. [Apple’s permission guide](https://support.apple.com/guide/mac-help/control-access-to-screen-and-system-audio-recording-mchld6aa7d23/mac) |
| **Windows, or an empty or black preview** | Protected or minimized content may be unavailable. Restore the target window and retry. If native capture is unavailable, use the system screenshot tool and select **Open screenshot…** in Editing Helper. |
| **Upload or service error** | Select a valid PNG or JPEG under 24 MiB. The app reduces the reviewed image to fit the analysis limits. For connection, model, or sign-in errors, check the backend URL, HTTPS, Gemini settings, and account or access token. |

Native capture was verified on Linux X11. Native Wayland, Windows, macOS, and
multi-monitor behavior still need platform verification.

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

## Connection modes

**For your own developer checkout**: `cd desktop && npm start` uses your previously saved private Northflank connection. To edit its HTTPS URL or shared developer token, use `EDITING_HELPER_DEV_SETTINGS=1 npm start` (unpackaged only).

**For a packaged public build**: users do not enter an API URL, shared access token or Gemini key. The app uses the publisher-configured HTTPS service, opens an email-code sign-in window, refreshes each user's session, and sends that user's token to FastAPI. Only the refresh token is persisted using the OS keyring when available. Public FastAPI verifies the account against Supabase and enforces Redis usage quotas before contacting Gemini.

A public installer requires configuration of Supabase Auth, email delivery, Redis and Northflank. The default release-config.json contains placeholders and intentionally blocks connections. For instructions, see [PUBLIC_RELEASE.md](PUBLIC_RELEASE.md). The GitHub Actions build workflow generates candidate .AppImage/.deb/.exe/.dmg installers; unsigned macOS/Windows builds are not yet trusted by their platforms.

## Verification and scope

Run `npm test` for the client tests. See [TESTING.md](TESTING.md)
for renderer tests and the manual desktop checklist. Desktop rendering and
mock replies do not establish model accuracy. Related source references appear when the backend retrieves reviewed knowledge notes; they do not guarantee that every generated step is correct. See the [public release guide](PUBLIC_RELEASE.md) for installer builds. For adding documentation notes, see [knowledge/README.md](../knowledge/README.md).
