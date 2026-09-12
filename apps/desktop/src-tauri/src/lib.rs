//! The Tauri shell.
//!
//! Its one real job in Phase 1 is owning the sidecar's lifetime: spawn the
//! frozen FastAPI binary at startup, and make sure it is gone at exit.
//!
//! The exit half is the part that is easy to get wrong. PyInstaller's
//! `--onefile` bootloader unpacks to a temp directory and execs the real
//! interpreter as a child process, so the PID this shell holds is the
//! bootloader's, not the server's. Killing it leaves the server running and
//! holding port 8787 — the trap called out in BUILD_SPEC §5 Phase 1.
//!
//! So this never reaches for `kill` as its opening move. It writes the line
//! `shutdown` to the sidecar's stdin, then drops the handle, which closes the
//! pipe. The sidecar stops itself on either signal, from inside the process
//! that actually is the server. `kill` exists only as a timeout backstop, and
//! even then it closes stdin on the way out.

use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_keyring::KeyringExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Matches the `externalBin` entry in `tauri.conf.json`. Tauri appends the
/// target triple when resolving it on disk.
const SIDECAR_NAME: &str = "agentspace-sidecar";

/// Must match `agentspace.config.DEFAULT_BIND_PORT` and the `connect-src` in
/// the CSP. The sidecar binds 127.0.0.1 only, hardcoded on its side
/// (BUILD_SPEC §1 constraint 3).
const SIDECAR_PORT: u16 = 8787;

/// Written to the sidecar's stdin to request a clean stop. Must match
/// `agentspace.main.SHUTDOWN_COMMAND`.
const SHUTDOWN_LINE: &[u8] = b"shutdown\n";

/// How long to let the sidecar exit on its own before forcing the issue.
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);

/// Keychain service name. Matches the bundle identifier so the entries are
/// attributable to this app in the Windows Credential Manager UI.
const KEYCHAIN_SERVICE: &str = "dev.agentspace.desktop";

/// Keychain account names, which double as the JSON field names in the stdin
/// handshake. Must match `agentspace.secrets.SECRET_KEYS`.
///
/// The bot token arrived with the Phase 8 channel adapter. A bot token is a
/// credential in the same sense an API key is — it authenticates this
/// application to a third party and is replayable by anyone who reads it — so it
/// travels the same route and never touches the `settings` table, which sits on
/// disk in the clear beside the event log.
const SECRET_NAMES: [&str; 3] = [
    "anthropic_api_key",
    "openai_api_key",
    "discord_bot_token",
];

#[derive(Default)]
struct SidecarState(Mutex<Option<CommandChild>>);

/// The origin the webview should talk to.
#[tauri::command]
fn sidecar_base_url() -> String {
    format!("http://127.0.0.1:{SIDECAR_PORT}")
}

/// The keychain service the settings screen writes secrets under.
///
/// Handed to the webview rather than duplicated there, so the entry the
/// settings screen creates is the one `send_secrets` reads at the next launch.
/// The webview writes and clears; reading back stays here, in Rust, at spawn.
#[tauri::command]
fn keychain_service() -> String {
    KEYCHAIN_SERVICE.to_string()
}

/// Environment variable the sidecar reads its data directory from. Must match
/// `agentspace.config.DATA_DIR_ENV_VAR`.
const DATA_DIR_ENV: &str = "AGENTSPACE_DATA_DIR";

/// The data directory: the one the justfile exported for a dev run, else the
/// one Tauri derives from the bundle identifier. One function, because the
/// sidecar is spawned with it and `reveal_folder` refuses anything outside it,
/// and those two must agree about where it is.
fn data_dir(app: &AppHandle) -> Result<PathBuf, tauri::Error> {
    match std::env::var_os(DATA_DIR_ENV) {
        Some(inherited) => Ok(PathBuf::from(inherited)),
        // `app_local_data_dir()`, deliberately, not `app_data_dir()`. On
        // Windows the latter is %APPDATA% — the *roaming* profile, which is
        // copied to and from a server on every logon in a domain environment.
        // Roaming a live SQLite database (plus its -wal and -shm files, an
        // agent workspace and logs) invites corruption and bloats every logon.
        // This one is %LOCALAPPDATA%, which is also what
        // `agentspace.config.default_data_dir` computes, so the injected value
        // and the sidecar's own fallback name the same directory.
        None => app.path().app_local_data_dir(),
    }
}

/// Show a space's folder in the OS file manager.
///
/// The one path-opening command the webview may call, and it opens nothing
/// it is merely told to: the path has to resolve inside the data directory
/// this shell spawned the sidecar with. A space's folder always does — it is
/// `<data dir>/spaces/<id>` by construction — and anything else is refused
/// with a sentence rather than opened. The plugin's own JavaScript commands
/// are not granted to the webview at all; this is the whole surface.
#[tauri::command]
fn reveal_folder(app: AppHandle, path: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;

    let root = data_dir(&app).map_err(|error| error.to_string())?;
    let root = std::fs::canonicalize(&root).map_err(|error| error.to_string())?;
    let wanted = std::fs::canonicalize(&path)
        .map_err(|_| format!("{path} does not exist yet — it is created by the first run"))?;
    if !wanted.starts_with(&root) {
        return Err(format!("{path} is not inside AgentSpace's data directory"));
    }
    if !wanted.is_dir() {
        return Err(format!("{path} is not a folder"));
    }
    app.opener()
        .open_path(wanted.to_string_lossy(), None::<&str>)
        .map_err(|error| error.to_string())
}

/// Start the sidecar and keep its handle for shutdown.
///
/// The data directory is resolved here, through Tauri's path API, and handed
/// over at spawn time — BUILD_SPEC §5 Phase 2 asks for exactly that. The
/// sidecar can resolve an OS app-data directory by itself and falls back to
/// doing so, but the two answers are only incidentally equal: Tauri derives
/// its path from the bundle identifier, so letting each side guess separately
/// is how an upgrade quietly starts reading a different, empty database.
///
/// It travels as an environment variable rather than `argv` for the same
/// reason API keys will in Phase 3 — `argv` is world-readable via `ps` — and
/// keeping one channel for spawn-time configuration avoids a second, weaker
/// one appearing later.
fn spawn_sidecar(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    // An inherited value wins. The justfile exports this so a dev run keeps its
    // database in `.dev/data` where it can be inspected and deleted; silently
    // overriding it here would move dev state into the real app-data directory
    // and quietly contradict the layout CLAUDE.md documents. A packaged app has
    // no such variable set, so it takes Tauri's path.
    let data_dir = data_dir(app)?;
    std::fs::create_dir_all(&data_dir)?;

    let (mut rx, mut child) = app
        .shell()
        .sidecar(SIDECAR_NAME)?
        .env(DATA_DIR_ENV, data_dir.as_os_str())
        .spawn()?;

    // The API-key handshake, written before anything else can reach the
    // sidecar. See `send_secrets` for why this channel and not `argv`.
    //
    // A failure here is logged, not propagated: a missing key must not stop the
    // app from starting. The sidecar reports it as a legible "no API key
    // configured" on first use, which is a far better outcome than a window
    // that never opens.
    if let Err(error) = send_secrets(app, &mut child) {
        eprintln!("[sidecar] could not send the key handshake: {error}");
    }

    app.state::<SidecarState>()
        .0
        .lock()
        .expect("sidecar state poisoned")
        .replace(child);

    // Drain the sidecar's output. Without a reader the pipe fills and the
    // sidecar blocks on its own logging.
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    eprintln!("[sidecar] {}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Error(message) => {
                    eprintln!("[sidecar] error: {message}");
                }
                CommandEvent::Terminated(payload) => {
                    eprintln!("[sidecar] exited with {:?}", payload.code);
                }
                _ => {}
            }
        }
    });

    Ok(())
}

/// Read the API keys from the OS keychain and write them to the sidecar's stdin.
///
/// BUILD_SPEC §1 constraint 4 and §5 Phase 3. Two things about this are load
/// bearing:
///
/// * **stdin, never `argv`.** A command-line argument is readable by any
///   process on the machine — `Get-CimInstance Win32_Process` on Windows, `ps`
///   elsewhere — for as long as the process lives. stdin is a private pipe
///   between exactly these two processes.
/// * **Exactly one line, first.** The sidecar consumes the first line as this
///   handshake and then treats the stream as the shutdown watchdog it has been
///   since Phase 1. `shutdown` is not valid JSON, so the two uses cannot be
///   confused for one another.
///
/// A key that is absent from the keychain is simply omitted; the line is always
/// written, even when empty, so the sidecar's handshake step always completes.
fn send_secrets(
    app: &AppHandle,
    child: &mut CommandChild,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut secrets = serde_json::Map::new();

    for name in SECRET_NAMES {
        // A keychain miss is normal — it means the user has not set that key.
        // Only an actual backend failure is worth reporting, and even then the
        // caller logs rather than aborting startup.
        match app.keyring().get_password(KEYCHAIN_SERVICE, name) {
            Ok(Some(value)) if !value.is_empty() => {
                secrets.insert(name.to_string(), serde_json::Value::String(value));
            }
            Ok(_) => {}
            Err(error) => eprintln!("[keychain] could not read {name}: {error}"),
        }
    }

    // Names only. Printing the map itself would put the keys in the Tauri
    // console, which is the same leak the stdin channel exists to avoid.
    let names: Vec<&str> = secrets.keys().map(String::as_str).collect();
    eprintln!("[keychain] sending {} key(s): {:?}", names.len(), names);

    let mut line = serde_json::to_vec(&serde_json::Value::Object(secrets))?;
    line.push(b'\n');
    child.write(&line)?;

    Ok(())
}

/// Stop the sidecar, preferring the mechanisms that reach the real server.
fn shutdown_sidecar(app: &AppHandle) {
    let Some(mut child) = app
        .state::<SidecarState>()
        .0
        .lock()
        .expect("sidecar state poisoned")
        .take()
    else {
        return;
    };

    // 1. Ask nicely. The sidecar's stdin watchdog stops the server on this.
    if let Err(error) = child.write(SHUTDOWN_LINE) {
        eprintln!("[sidecar] could not write shutdown command: {error}");
    }

    // 2. Give it a moment to go on its own.
    let deadline = Instant::now() + SHUTDOWN_GRACE;
    while Instant::now() < deadline {
        if !port_is_open(SIDECAR_PORT) {
            // Dropping `child` closes stdin, which is the belt to the braces
            // above: even a sidecar that ignored the command sees EOF.
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    // 3. Backstop. `kill` consumes the handle, so stdin closes here too — the
    //    real server still gets its EOF even if the bootloader dies first.
    eprintln!("[sidecar] did not exit within {SHUTDOWN_GRACE:?}; killing");
    if let Err(error) = child.kill() {
        eprintln!("[sidecar] kill failed: {error}");
    }
}

/// Whether anything is still listening on the sidecar's port.
fn port_is_open(port: u16) -> bool {
    use std::net::{Ipv4Addr, SocketAddr, TcpStream};

    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    TcpStream::connect_timeout(&address, Duration::from_millis(200)).is_ok()
}

/// Build and run the application.
///
/// # Panics
///
/// Panics if the Tauri application cannot be built, which means a malformed
/// `tauri.conf.json` — unrecoverable and worth failing loudly at startup.
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_keyring::init())
        .plugin(tauri_plugin_opener::init())
        .manage(SidecarState::default())
        .invoke_handler(tauri::generate_handler![
            sidecar_base_url,
            keychain_service,
            reveal_folder
        ])
        .setup(|app| {
            spawn_sidecar(app.handle())?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the AgentSpace application");

    app.run(|app, event| {
        if matches!(event, RunEvent::Exit) {
            shutdown_sidecar(app);
        }
    });
}
