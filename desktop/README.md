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

1. Choose **DaVinci Resolve** and click **Start**. No editor is preselected;
   other listed editors are coming soon. The version is optional.
2. Click the floating pet, open **Settings**, and set **Server address** to
   `http://127.0.0.1:8001`. Save.
3. Ask **How do I make a camera shake?** The mock should echo the question and
   show **Editor: DaVinci Resolve**. It does not generate real instructions.
4. Drag the pet to move it without scaling: when chat is open, it follows the pet
   and keeps its size. Drag the **bottom-right corner of the chat window** outward
   or inward to resize the chat. The chat remembers
   its size. You can also focus the grip and use the arrow keys.
5. Try `/long` for scrolling, `/slow` for a delayed reply, and `/err` for retry.
   Stop the mock server with Ctrl+C when finished.

Try `npm run start:normal` if the floating overlay doesn't behave on your
desktop. On Linux the floating mode defaults to X11/XWayland. The normal
mode uses regular framed windows. Windows and macOS are not verified.

## Connect to the real backend

Set **Server address** back to `http://127.0.0.1:8000`. See the
[root README](../README.md) to start the local API and a runner. The desktop
makes requests in Electron's main process, so no CORS change is needed.
The request shape is `{"question":"...", "editor":"DaVinci Resolve", "version":"20.1"}`
(version optional); the response is `{"answer":"..."}`.

The existing launcher can start the local GGUF runner, API and desktop
together. From the repository root, after `npm ci` in `desktop/`:

```bash
python launch.py --runner /path/to/llama-server --model /path/to/model.gguf -- \
  "$PWD/desktop/node_modules/.bin/electron" "$PWD/desktop"
```

## Verification and scope

Run `npm test` for the client tests. See [TESTING.md](TESTING.md)
for renderer tests and the manual desktop checklist. Desktop rendering and
mock replies do not establish model accuracy. Source retrieval, verified
tutorials with a Sources footer, installers, and packaged weights are not
implemented by this integration.
