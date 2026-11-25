# Editing Helper

**An AI-powered desktop companion for video editors.**

Editing Helper helps editors learn an effect, solve a workflow problem, or find a relevant resource without constantly switching between an editing program and tutorials. Its draggable floating mascot opens a small chat panel that stays accessible while you edit.

## Try the demo

Open the [GitHub Releases page](https://github.com/Helloworld9099/editing-helper/releases) and look for **v0.1.0 — Judge Demo** under Releases. Download the installer for your operating system from the release assets (not the source-code ZIP).

| Platform | Installer | Requirements |
| --- | --- | --- |
| Windows | `Editing Helper Setup 0.1.0.exe` | 64-bit Windows |
| Linux | `editing-coach_0.1.0_amd64.deb` | 64-bit Ubuntu or Debian-compatible distribution |

See [SHA-256 checksums](docs/releases/v0.1.0/SHA256SUMS.txt) to verify the downloaded files. These are unsigned hackathon test builds. Windows may show an unknown-publisher or SmartScreen warning; don't worry, this isn't a virus. If an installer is blocked, contact the project team or use the source preview below.

### Windows

Run the downloaded setup executable, follow the installation wizard, and launch Editing Helper from the Start menu.

### Linux

Open a terminal in the directory containing the downloaded package:

```bash
sudo apt install ./editing-coach_0.1.0_amd64.deb
```

Launch **Editing Helper** from your application menu.

### First launch

1. Choose your video editor and optionally enter its version. Click **Start**.
2. Click the floating mascot to open the chat.
3. Type an editing question and send it. Follow the returned instructions in your own editor.
4. Drag the mascot to reposition it. Right-click it to access settings and chat size, or to **Quit Editing Coach** completely.

Closing the chat panel hides the chat; quitting the mascot closes the application. If floating windows do not behave correctly on your system, use **Normal window mode** in Settings and restart the app.

**Supported editors:** Adobe Premiere Pro, DaVinci Resolve, Kdenlive, Shotcut, CapCut, ACDSee Luxea, Lightworks, Clipchamp, OpenShot, Canva, and iMovie.

## Privacy, reliability and limitations

- The hosted version sends the question, selected editor, and optional version to the backend and Gemini. It does not capture the screen, upload footage, or control the editing program. Avoid entering sensitive information.
- Provider keys and Redis credentials stay on the server. The public installer contains the demo HTTPS address, not a shared access token.
- The public demo has finite per-IP and shared quotas. HTTP 429 means the demo limit has been reached; retry later. HTTP 503 may indicate that the provider or usage-protection service is unavailable.
- AI answers can be incorrect or refer to features that vary by editor version or edition. Verify important steps in the editor.
- Windows and Linux installers are provided for evaluation; signing and full cross-platform acceptance testing are separate release tasks. The demo depends on the hosted backend remaining available.

**Maintainer resources:** [Full development guide](docs/DEVELOPMENT.md) · [Hosted demo setup and installer builds](desktop/JUDGE_DEMO.md) · [Knowledge source policy](knowledge/README.md)
