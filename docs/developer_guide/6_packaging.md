# Packaging

## Building and verifying the bundles

```
just build-sidecar      # PyInstaller --onefile → src-tauri/binaries/agentspace-sidecar-<triple>
just build-installer    # setup + build-sidecar + tauri build --bundles <nsis|app>
just package-macos      # macOS only, AFTER a build: ditto archive preserving the .app and executable modes
just verify-build       # AFTER build/archive: launches binaries and checks bundle/archive contents
just verify-installed   # installs it on THIS machine and runs it with Python scrubbed from PATH (Windows only)
```

The sidecar filename carries the target triple: `x86_64-pc-windows-msvc` on
Windows, `aarch64-apple-darwin` (Apple Silicon) or `x86_64-apple-darwin`
(Intel) on macOS.

| | Windows | macOS |
|---|---|---|
| Bundle target | `nsis` | `app` |
| Bundle location | `apps/desktop/src-tauri/target/release/bundle/nsis/` | `apps/desktop/src-tauri/target/release/bundle/macos/` |
| Distribution file | `AgentSpace_0.2.0_x64-setup.exe` | `AgentSpace_0.2.0_<target-triple>.app.zip` |
| Silent install | `AgentSpace_0.2.0_x64-setup.exe /S` | N/A (extract and copy the `.app`) |
| `verify-installed` | Installs the NSIS `.exe` and runs it | Not applicable (no NSIS on macOS) |

Things that will bite:

- **The filename must carry the target triple** or Tauri never finds it, and
  Tauri then *strips* the triple when staging, so the shipped file is
  `agentspace-sidecar.exe` (Windows) or `agentspace-sidecar` (macOS). Looking
  for the built name inside the bundle finds nothing and looks like a bundling
  failure.
- **`verify-build` exists because the bundle can carry a stale sidecar.**
  It compares the SHA-256 of the sidecar inside the installer against the one
  just built. Run it after every `build-installer`, never before.
- **The bundle target is a justfile variable**, `nsis` on Windows and `app` on
  macOS. Do not put `"targets": "all"` in `tauri.conf.json`; it also builds a
  per-machine MSI on Windows, which contradicts the per-user install Phase 1
  verified.
- **Never cache or restore `src-tauri/target/` across machines.** That is how a
  stale `externalBin` gets bundled.
- The sidecar's `--add-data` uses `;` on Windows and `:` on macOS/Linux; the
  justfile handles it. A wrong separator is not an error: it is a binary that
  starts and then cannot create its database.

## The macOS archive

`just package-macos` archives the existing release bundle with
`ditto -c -k --sequesterRsrc --keepParent`. The filename includes the version and
actual host target triple. A typical Apple Silicon build produces
`AgentSpace_0.2.0_aarch64-apple-darwin.app.zip` in the macOS bundle directory.
This is a native architecture build, not a universal binary.

Upload the archive as a single file. Uploading an unpacked `.app` through the
workflow artifact service loses executable modes. Tauri ad-hoc signs the
complete bundle with hardened runtime disabled before this step. The disabled
runtime is required because Tauri re-signs the PyInstaller one-file sidecar,
whose extracted Python library otherwise has a different code identity.
`just verify-build` checks the zip's extracted bundle version, executable
modes, signature and signature-normalized sidecar content, then starts that
extracted sidecar against temporary data and verifies EOF shutdown. It does
not click through Gatekeeper or exercise the extracted Tauri window.

The app is not Developer ID signed or notarized. A local build has no download
quarantine attribute, so successfully opening it does not verify the experience
of a user downloading the release. The [0.2.0 release notes](../releases/0.2.0.md)
document Gatekeeper's **Open Anyway** path, the quarantine-removal command, and
the separate Keychain access prompt. Developer ID signing and notarization
remain out of scope for this release.

## Preparing a release

Keep versions aligned in the backend and desktop manifests, the Tauri config
and Rust manifest, their lockfiles, the schemas package, and FastAPI's OpenAPI
version. Run `just schemas` after changing the API version. Add the matching
`docs/releases/<version>.md` before creating a version tag; the release job
reads that exact file.

Run the [local CI sequence](4_testing_and_ci.md#ci), review the platform
artefacts and release notes, then tag the reviewed commit. A pushed `v*` tag
starts the workflow, which publishes both assets only after the test, build
and Windows smoke jobs succeed. Verify the resulting release assets and
downloaded macOS launch separately before claiming the release is validated.

---
