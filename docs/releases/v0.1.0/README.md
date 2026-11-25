# Editing Helper v0.1.0 — Judge Demo

The demo installer artifacts are intended for direct evaluation on Windows x64 and Debian/Ubuntu amd64. They connect to the hosted Gemini-backed demo automatically; no login, key, server address or development environment is required.

| Release asset | Bytes |
| --- | ---: |
| `Editing Helper Setup 0.1.0.exe` | 121,581,794 |
| `editing-coach_0.1.0_amd64.deb` | 100,777,444 |
| `SHA256SUMS.txt` | Checksums for both installers |

See the [judge installation and evaluation guide](../../../README.md). The supplied Linux archive was inspected against source commit `39bc9650d407ad3f25b32cd85313bed5404cc77e`: the 15 packaged renderer and application source files matched that commit, and the embedded public demo URL was confirmed. The supplied Windows file was identified as an unsigned NSIS installer; its embedded app payload and installation behavior were not independently verified. These are inspection results, not runtime acceptance or malware-scan results. Both artifacts need clean-machine testing.

The `.exe.blockmap` is not required for manual distribution. Upload the two installers and checksum file as assets on the GitHub Release tagged `v0.1.0` rather than committing binaries to the repository. Verify the release from an unauthenticated browser before sharing it with judges.
