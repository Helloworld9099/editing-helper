# Editing Helper

**An AI-powered desktop companion for video editors.**

Editing Helper helps editors learn an effect, solve a workflow problem, or find a relevant resource without constantly switching between an editing program and tutorials. Its draggable floating mascot opens a small chat panel that stays accessible while you edit.

## Try the demo

Open the [GitHub Releases page](https://github.com/Helloworld9099/editing-helper/releases) and look for **v0.1.0 — Judge Demo** under Releases. Download the installer for your operating system from the release assets (not the source-code ZIP).

| Platform | Installer | Requirements |
| --- | --- | --- |
| Windows | `Editing Helper Setup 0.1.0.exe` | 64-bit Windows |
| Linux | `editing-coach_0.1.0_amd64.deb` | 64-bit Ubuntu or Debian-compatible distribution |

See [SHA-256 checksums](docs/releases/v0.1.0/SHA256SUMS.txt) to verify the downloaded files. These are unsigned hackathon test builds. Windows may show an unknown-publisher or SmartScreen warning; do not bypass an actual malware detection. If an installer is blocked, contact the project team or use the source preview below.

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

## What to test as a judge

Start with DaVinci Resolve, Kdenlive, or another editor you know. The app should give instructions appropriate to the selected editor and version.

| Example question | What to evaluate |
| --- | --- |
| How do I create a smooth zoom? | Clear, actionable steps and relevant controls |
| How can I create a camera shake and impact zoom? | Handling of a multi-step editing task |
| How do I create a crossfade transition? | Editor-specific guidance; change editors in Settings and repeat |
| How do I fix a clip with audio that is out of sync? | Useful troubleshooting suggestions |

Repeat a question to assess consistency. Follow the steps in an actual editor to assess accuracy. When related source links are returned, inspect the distinction between source-reviewed notes and further-reading links. The app provides guidance; it does not automatically edit footage.

## How it works

```text
Electron desktop companion
        │  Question + editor + optional version
        ▼
FastAPI backend (Northflank)
        │
        ├─ Redis guest request quotas
        ├─ SQLite FTS5 editor-specific knowledge retrieval
        └─ Google Gemini → generated instructions
        │
        ▼
Desktop chat: answer + relevant references when available
```

Gemini generates the answers. Retrieval supplies relevant, editor-specific context and reference links. The knowledge base contains **3,066 records across 11 editors**, as documented in the [coverage snapshot](knowledge/README.md): 55 source-reviewed summaries and 3,011 link-only references. A reference link does not prove that the model's instructions are correct, and the summaries have not all been physically tested in the editors.

**Supported editors:** Adobe Premiere Pro, DaVinci Resolve, Kdenlive, Shotcut, CapCut, ACDSee Luxea, Lightworks, Clipchamp, OpenShot, Canva, and iMovie.

## Privacy, reliability and limitations

- The hosted version sends the question, selected editor, and optional version to the backend and Gemini. It does not capture the screen, upload footage, or control the editing program. Avoid entering sensitive information.
- Provider keys and Redis credentials stay on the server. The public installer contains the demo HTTPS address, not a shared access token.
- The public demo has finite per-IP and shared quotas. HTTP 429 means the demo limit has been reached; retry later. HTTP 503 may indicate that the provider or usage-protection service is unavailable.
- AI answers can be incorrect or refer to features that vary by editor version or edition. Verify important steps in the editor.
- Windows and Linux installers are provided for evaluation; signing and full cross-platform acceptance testing are separate release tasks. The demo depends on the hosted backend remaining available.

## Run from source or inspect the implementation

The quickest source preview uses the same demo API. Requires Node.js 22.12+ and Python 3.11+:

```bash
git clone https://github.com/Helloworld9099/editing-helper.git
cd editing-helper
PUBLIC_API_URL=https://p01--demo-backend--fbvcc7mvswr6.code.run python3 .github/scripts/write_release_config.py
cd desktop
npm ci
EDITING_HELPER_PUBLIC_PREVIEW=1 npm start
```

The preview command is for Linux/macOS shells. See [desktop development](desktop/README.md) for other development modes and [deployment instructions](desktop/JUDGE_DEMO.md) to run your own backend. The source preview changes a local, nonsecret release configuration file.

| Repository area | Purpose |
| --- | --- |
| [desktop/](desktop/) | Electron UI, floating mascot, settings, HTTP client and packaging |
| [app.py](app.py) | FastAPI request validation and model-provider integration |
| [knowledge_rag.py](knowledge_rag.py) and [knowledge/](knowledge/) | Retrieval and attributed source records |
| [demo_access.py](demo_access.py) and [quota_limits.py](quota_limits.py) | Guest access protection using Redis |
| [tests/](tests/) and [desktop/test/](desktop/test/) | Backend and desktop automated tests |
| [training/](training/) | Earlier optional local-model experiments; not required for the Gemini-powered judge demo |

### Automated checks

From the repository root, using a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python knowledge_rag.py validate
.venv/bin/python knowledge_rag.py build
.venv/bin/python -m unittest discover -s tests -v
cd desktop
npm ci
npm test
```

These checks cover implementation behavior, mocked provider requests and retrieval; they do not establish real-world editing accuracy. See the [testing guide](desktop/TESTING.md) for additional renderer and manual desktop checks.

**Maintainer resources:** [Full development guide](docs/DEVELOPMENT.md) · [Hosted demo setup and installer builds](desktop/JUDGE_DEMO.md) · [Knowledge source policy](knowledge/README.md)
