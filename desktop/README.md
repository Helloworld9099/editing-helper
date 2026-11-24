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

## Connection modes

### Normal desktop UI

Ordinary users see only editor, version and window preferences. **Server address and the shared access token are not shown in normal Settings.** Responses without a retrieved source now display only `AI guidance`; existing document links still appear when retrieval finds them.

For local development, existing saved URL/token settings continue to work when you launch from an existing checkout with `npm start`, even with the connection fields hidden.

### Your local development connection

Only an **unpackaged** Electron development app can show connection controls. Launch with:

```bash
cd desktop
EDITING_HELPER_DEV_SETTINGS=1 npm start
```

Open the pet's **Settings** and enter your Northflank HTTPS URL and your developer access token. The URL is saved in the local Electron config; the token remains encrypted separately with Electron safeStorage when GNOME Keyring/KWallet is available. Developer mode does not weaken the backend's authentication: it just restores the controls for your own testing.

Do not share your `COACH_ACCESS_TOKEN`. The optional environment variables `EDITING_HELPER_API` and `EDITING_HELPER_ACCESS_TOKEN` still work for unpackaged local development.

### Public/packaged releases

Packaged Electron applications ignore saved developer URLs, saved developer tokens and developer environment-variable overrides. They read the **nonsecret** publisher API URL from `src/release-config.json`; the shared access token is never bundled in the app.

`src/release-config.json` intentionally has an empty URL and `authentication: "not-configured"`. Until you implement *individual user authentication* on the desktop and enforce it in FastAPI, packaged public releases display a connection/setup error rather than trying to use the private shared-token server.

**Do not set `authentication: "user-accounts"` just to bypass the startup warning.** Doing so does not implement sign-in or backend authorization. Do not disable `COACH_REQUIRE_AUTH` or distribute the server's shared token to make a public build work. Follow [PUBLIC_RELEASE.md](PUBLIC_RELEASE.md) first.

## Verification and scope

Run `npm test` for the client tests. See [TESTING.md](TESTING.md)
for renderer tests and the manual desktop checklist. Desktop rendering and
mock replies do not establish model accuracy. Related source references appear when the backend retrieves reviewed knowledge notes; they do not guarantee that every generated step is correct. A fully verified tutorial library, screen capture, installers, and packaged weights are not implemented by this integration. For adding documentation notes, see [knowledge/README.md](../knowledge/README.md).
