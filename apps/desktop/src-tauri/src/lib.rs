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

use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent};
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

#[derive(Default)]
struct SidecarState(Mutex<Option<CommandChild>>);

/// The origin the webview should talk to.
#[tauri::command]
fn sidecar_base_url() -> String {
    format!("http://127.0.0.1:{SIDECAR_PORT}")
}

/// Start the sidecar and keep its handle for shutdown.
fn spawn_sidecar(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let (mut rx, child) = app.shell().sidecar(SIDECAR_NAME)?.spawn()?;

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
        .manage(SidecarState::default())
        .invoke_handler(tauri::generate_handler![sidecar_base_url])
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
