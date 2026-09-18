# Packaging

## Building and verifying the bundles

```
just build-sidecar      # PyInstaller --onefile → src-tauri/binaries/agentspace-sidecar-<triple>
just build-installer    # setup + build-sidecar + tauri build --bundles <nsis|app,dmg>
just verify-build       # AFTER a build: launches binaries and checks installer/disk image contents
just verify-installed   # installs it on THIS machine and runs it with Python scrubbed from PATH (Windows only)
```

The sidecar filename carries the target triple: `x86_64-pc-windows-msvc` on
Windows, `aarch64-apple-darwin` (Apple Silicon) or `x86_64-apple-darwin`
(Intel) on macOS.

| | Windows | macOS |
|---|---|---|
| Bundle target | `nsis` | `app,dmg` |
| Bundle location | `apps/desktop/src-tauri/target/release/bundle/nsis/` | `apps/desktop/src-tauri/target/release/bundle/macos/` and `.../bundle/dmg/` |
| Distribution file | `AgentSpace_0.3.2_x64-setup.exe` | `AgentSpace_0.3.2_<arch>.dmg` |
| Silent install | `AgentSpace_0.3.2_x64-setup.exe /S` | N/A (drag the `.app` from the image to Applications) |
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
- **The bundle target is a justfile variable**, `nsis` on Windows and `app,dmg`
  on macOS. Do not put `"targets": "all"` in `tauri.conf.json`; it also builds
  a per-machine MSI on Windows, which contradicts the per-user install Phase 1
  verified.
- **Never cache or restore `src-tauri/target/` across machines.** That is how a
  stale `externalBin` gets bundled.
- The sidecar's `--add-data` uses `;` on Windows and `:` on macOS/Linux; the
  justfile handles it. A wrong separator is not an error: it is a binary that
  starts and then cannot create its database.
- ChatGPT access depends on the pinned `openai-codex` package, but its
  platform-specific `openai-codex-cli-bin` runtime is deliberately excluded
  from the freeze (`--exclude-module codex_cli_bin`): a one-file sidecar
  unpacks everything it carries on every launch, and the 0.3.0 build that
  bundled it started twice as slowly and downloaded six times larger. The
  sidecar carries only `codex_runtime.json`, the manifest of pinned wheels,
  and fetches the runtime on the first sign-in. The frozen-sidecar tests
  assert that `/auth/chatgpt` reports the runtime as `missing` rather than
  failing, and that the binary stays under 60 MB.

## The macOS disk image

Tauri's `dmg` target wraps the signed `.app` in a disk image beside a link to
`/Applications`, so installing is the drag every Mac user knows. Releases up
to 0.3.1 shipped a `ditto` zip instead, and the first bug report against them
was the predictable one: the app stayed in Downloads, Gatekeeper ran a fresh
translocated copy on every launch, Finder searches found several AgentSpace
entries and Spotlight listed none. The filename includes the version and the
architecture; a typical Apple Silicon build produces
`AgentSpace_0.3.2_aarch64.dmg` in `bundle/dmg/`. This is a native
architecture build, not a universal binary.

The macOS `_build-installer` recipe sets `CI=true`, which makes Tauri's
`bundle_dmg.sh` skip the Finder AppleScript that positions the icons. That
script needs Automation permission for Finder, which a terminal has to be
granted by hand, and GitHub's runners skip it anyway, so a local image is
built the same way as the released one: the app, the `Applications` link and
a volume icon, no background picture.

Upload the image as a single file. Uploading an unpacked `.app` through the
workflow artifact service loses executable modes. Tauri ad-hoc signs the
complete bundle with hardened runtime disabled before imaging it. The disabled
runtime is required because Tauri re-signs the PyInstaller one-file sidecar,
whose extracted Python library otherwise has a different code identity.
`just verify-build` mounts the image read-only, checks that it holds exactly
the app and the `Applications` link, copies the app out with `ditto` as a drag
would, and checks that copy's bundle version, executable modes, signature and
signature-normalized sidecar content, then starts that sidecar against
temporary data and verifies EOF shutdown. It does not click through Gatekeeper
or exercise the Tauri window.

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
