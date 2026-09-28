# Packaging

## Building and verifying the bundles

```
just build-sidecar      # PyInstaller --onefile → src-tauri/binaries/agentbase-sidecar-<triple>
just build-installer    # setup + build-sidecar + tauri build --bundles <nsis|app,dmg>
just verify-build       # AFTER a build: launches binaries and checks installer/disk image contents
just verify-installed   # installs it on THIS machine and runs it with Python scrubbed from PATH (Windows only)
```

The sidecar filename includes the target triple: `x86_64-pc-windows-msvc`,
`aarch64-apple-darwin` (Apple Silicon), or `x86_64-apple-darwin` (Intel).

| | Windows | macOS |
|---|---|---|
| Bundle target | `nsis` | `app,dmg` |
| Bundle location | `apps/desktop/src-tauri/target/release/bundle/nsis/` | `apps/desktop/src-tauri/target/release/bundle/macos/` and `.../bundle/dmg/` |
| Distribution file | `AgentBase_0.3.2_x64-setup.exe` | `AgentBase_0.3.2_<arch>.dmg` |
| Silent install | `AgentBase_0.3.2_x64-setup.exe /S` | N/A (drag the `.app` from the image to Applications) |
| `verify-installed` | Installs the NSIS `.exe` and runs it | Not applicable (no NSIS on macOS) |

Things that will bite:

- **The filename needs the target triple** or Tauri cannot find it. Tauri then
  *strips* it while staging: bundles contain `agentbase-sidecar.exe` (Windows)
  or `agentbase-sidecar` (macOS), not the built name.
- **`verify-build` catches stale bundled sidecars.** It compares installer and
  newly built sidecar SHA-256 values. Run it only after `build-installer`.
- **The justfile sets targets:** `nsis` on Windows and `app,dmg` on macOS. Do
  not set `"targets": "all"` in `tauri.conf.json`; it adds a per-machine
  Windows MSI, contradicting Phase 1's verified per-user install.
- **Never cache or restore `src-tauri/target/` across machines:** it can bundle
  a stale `externalBin`.
- Sidecar `--add-data` uses `;` on Windows and `:` on macOS/Linux; the justfile
  handles it. A wrong separator yields a binary that starts but cannot create
  its database.
- ChatGPT uses pinned `openai-codex`, but freeze excludes its platform-specific
  `openai-codex-cli-bin` (`--exclude-module codex_cli_bin`): one-file sidecars
  unpack on each launch, and bundling it in 0.3.0 doubled startup and sextupled
  download size. The sidecar carries only pinned-wheel manifest
  `codex_runtime.json` and fetches the runtime at first sign-in. Tests require
  `/auth/chatgpt` to report `missing`, not fail, and the binary to stay under
  60 MB.

## The macOS disk image

Tauri's `dmg` target wraps the signed `.app` with an `/Applications` link.
Releases through 0.3.1 used `ditto` zips, leaving apps in Downloads, repeatedly
translocated by Gatekeeper, duplicated in Finder, and absent from Spotlight.
The versioned architecture filename, such as
`AgentBase_0.3.2_aarch64.dmg` in `bundle/dmg/`, is native, not universal.

macOS `_build-installer` sets `CI=true`, making Tauri's `bundle_dmg.sh` skip
the Finder icon-positioning AppleScript. That script requires manually granted
Finder Automation permission and runners skip it, so local and release images
contain the app, `Applications` link, and volume icon, with no background.

Upload the image as one file; artifact-uploading an unpacked `.app` loses modes.
Tauri ad-hoc signs the bundle with hardened runtime disabled because it
re-signs the PyInstaller one-file sidecar, whose extracted Python library would
otherwise have a different code identity. `just verify-build` mounts the image
read-only; verifies exactly the app and `Applications` link; copies the app
with `ditto`; checks version, modes, signature, and signature-normalized
sidecar content; then starts the sidecar against temporary data and verifies
EOF shutdown. It neither passes Gatekeeper nor exercises the Tauri window.

The app lacks Developer ID signing and notarization. Local builds lack download
quarantine, so opening one does not validate a downloader's experience. The
[0.2.0 release notes](../releases/0.2.0.md) document Gatekeeper **Open Anyway**,
quarantine removal, and the separate Keychain prompt. Signing/notarization are
out of scope.

## Preparing a release

Align versions across backend/desktop manifests, Tauri and Rust manifests,
lockfiles, schemas, and FastAPI OpenAPI. Run `just schemas` after API-version
changes. Add `docs/releases/<version>.md` before tagging; release reads it.

Run the [local CI sequence](4_testing_and_ci.md#ci), review artifacts and notes,
then tag the reviewed commit. A pushed `v*` publishes both assets only after
test, build, and Windows smoke. Separately verify release assets and a downloaded
macOS launch before declaring validation.

---
