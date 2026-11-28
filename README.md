# Editing Helper

**An AI-powered desktop companion for video editors.**

Editing Helper helps editors learn an effect, solve a workflow problem, or find a relevant resource without constantly switching between an editing program and tutorials. Its draggable floating mascot opens a small chat panel that stays accessible while you edit.

## Try the demo

Open the [latest GitHub Release](https://github.com/Helloworld9099/editing-helper/releases/latest) and download the installer for your operating system from the release assets (not the source-code ZIP). No account or API key is required for the limited public demo.

| Platform | Installer | Requirements |
| --- | --- | --- |
| Windows | `Editing.Helper.Setup.<version>.exe` | 64-bit Windows |
| Linux | `editing-coach_<version>_amd64.deb` | 64-bit Ubuntu or Debian-compatible distribution |

Each release includes `SHA256SUMS.txt` to verify downloads. These are unsigned evaluation builds. Windows may show an unknown-publisher or SmartScreen warning; investigate unexpected antivirus detections instead of bypassing them. Checksums verify file integrity, not whether a file is safe.

### Windows

Run the downloaded setup executable, follow the installation wizard, and launch Editing Helper from the Start menu.

### Linux

Open a terminal in the directory containing the downloaded package:

```bash
sudo apt install ./editing-coach_0.2.0_amd64.deb
```

Replace `0.2.0` with the version you downloaded. Launch **Editing Helper** from your application menu.

### First launch

1. Choose your video editor and optionally enter its version. Click **Start**.
2. Click the floating mascot to open the chat.
3. Type an editing question and send it. Follow the returned instructions in your own editor.
4. To recreate an effect, attach a 1–5 second MP4, MOV, or WebM (up to 10 MiB), then send it with an optional question. Editing Helper identifies likely effects and suggests recreation steps for your selected editor.
5. Drag the mascot to reposition it. Right-click it to access settings and chat size, or to **Quit Editing Coach** completely.

Closing the chat panel hides the chat; quitting the mascot closes the application. If floating windows do not behave correctly on your system, use **Normal window mode** in Settings and restart the app.

**Supported editors:** Adobe Premiere Pro, DaVinci Resolve, Kdenlive, Shotcut, CapCut, ACDSee Luxea, Lightworks, Clipchamp, OpenShot, Canva, and iMovie.

## Privacy, reliability and limitations

- Text requests send the question, selected editor, and optional version to the hosted backend and Google Gemini. If you attach and send a reference clip, the original clip is uploaded to the backend; a normalized video without audio or source metadata, together with visual analysis, is sent to Gemini. Uploads are not automatic. Do not submit private, confidential, or unauthorized footage.
- The backend uses temporary files for decoding and removes them when processing ends, including normal error paths. Google Gemini's handling and retention of submitted content are governed by the applicable [Gemini API terms](https://ai.google.dev/gemini-api/terms); the project does not promise provider-side deletion. Editing Helper does not capture the screen or control your editing program.
- Provider keys and Redis credentials stay on the server. The public installer contains the demo HTTPS address, not a shared access token.
- The public demo has finite per-IP and shared limits on AI calls, video analyses, and upload attempts. A video analysis reserves two AI calls. HTTP 429 indicates a usage or concurrency limit; retry later. HTTP 503 may indicate that the service, provider, or usage protection is unavailable. This is an account-free, limited-access demo, not an unlimited production service.
- AI answers can be incorrect or refer to features that vary by editor version or edition. Verify important steps in the editor.
- Windows and Linux installers are provided for evaluation; signing and full cross-platform acceptance testing are separate release tasks. The demo depends on the hosted backend remaining available.

**Maintainer resources:** [Full development guide](docs/DEVELOPMENT.md) · [Hosted demo setup and installer builds](desktop/JUDGE_DEMO.md) · [Knowledge source policy](knowledge/README.md)
