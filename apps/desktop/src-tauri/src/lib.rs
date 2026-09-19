//! The Tauri shell: spawn the frozen sidecar at startup, hand it its data
//! directory and its keys, and make sure it is gone at exit.
//!
//! With PyInstaller's `--onefile` the PID this shell holds is the bootloader's,
//! not the server's, so killing it would orphan the server on port 8787.
//! Shutdown writes `shutdown` to the sidecar's stdin and drops the handle;
//! the sidecar stops itself on either. `kill` is only a timeout backstop.

use std::path::PathBuf;
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

/// Keychain service name. Matches the bundle identifier so the entries are
/// attributable to this app in the Windows Credential Manager UI.
const KEYCHAIN_SERVICE: &str = "dev.agentspace.desktop";

/// Keychain account names, which double as the JSON field names in the stdin
/// handshake. Must match `agentspace.secrets.SECRET_KEYS`; a test compares them.
const SECRET_NAMES: [&str; 3] = ["anthropic_api_key", "openai_api_key", "discord_bot_token"];

#[derive(Default)]
struct SidecarState(Mutex<Option<CommandChild>>);

/// Environment variable carrying this launch's tag to the sidecar, which
/// echoes it from `/health`. Must match `agentspace.main.INSTANCE_ENV_VAR`.
const INSTANCE_ENV: &str = "AGENTSPACE_INSTANCE";

/// The tag for this launch, handed to both the sidecar and the webview so the
/// webview can tell the shell's own sidecar from whatever else holds the fixed
/// port. Not a secret; unique per launch is all it has to be.
struct Instance(String);

impl Instance {
    fn mint() -> Self {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|since| since.as_nanos())
            .unwrap_or(0);
        Self(format!("{}-{nanos:x}", std::process::id()))
    }
}

/// The origin the webview should talk to.
#[tauri::command]
fn sidecar_base_url() -> String {
    format!("http://127.0.0.1:{SIDECAR_PORT}")
}

/// The tag `/health` must echo for the webview to trust what answered.
#[tauri::command]
fn sidecar_instance(instance: tauri::State<'_, Instance>) -> String {
    instance.0.clone()
}

/// The keychain service the settings screen writes secrets under, handed to
/// the webview rather than duplicated there. Reading back stays in Rust.
#[tauri::command]
fn keychain_service() -> String {
    KEYCHAIN_SERVICE.to_string()
}

/// Environment variable the sidecar reads its data directory from. Must match
/// `agentspace.config.DATA_DIR_ENV_VAR`.
const DATA_DIR_ENV: &str = "AGENTSPACE_DATA_DIR";

/// The data directory: the one the justfile exported for a dev run, else the
/// one Tauri derives from the bundle identifier. One function, because the
/// sidecar is spawned with it and `reveal_folder` refuses anything outside it.
fn data_dir(app: &AppHandle) -> Result<PathBuf, tauri::Error> {
    match std::env::var_os(DATA_DIR_ENV) {
        Some(inherited) => Ok(PathBuf::from(inherited)),
        // `app_local_data_dir()`, not `app_data_dir()`: on Windows the latter
        // is the roaming profile, and this one matches the sidecar's own fallback.
        None => app.path().app_local_data_dir(),
    }
}

/// Resolve one existing directory and prove it belongs to AgentSpace's data.
fn validated_data_directory(app: &AppHandle, path: &str) -> Result<PathBuf, String> {
    let root = data_dir(app).map_err(|error| error.to_string())?;
    let root = std::fs::canonicalize(&root).map_err(|error| error.to_string())?;
    let wanted = std::fs::canonicalize(path)
        .map_err(|_| format!("{path} does not exist yet: it is created by the first run"))?;
    if !wanted.starts_with(&root) {
        return Err(format!("{path} is not inside AgentSpace's data directory"));
    }
    if !wanted.is_dir() {
        return Err(format!("{path} is not a folder"));
    }
    Ok(wanted)
}

/// Show a space's folder in the OS file manager: the one path-opening command
/// the webview may call, and it refuses any path outside the data directory.
#[tauri::command]
fn reveal_folder(app: AppHandle, path: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;

    let wanted = validated_data_directory(&app, &path)?;
    app.opener()
        .open_path(wanted.to_string_lossy(), None::<&str>)
        .map_err(|error| error.to_string())
}

fn obsidian_vault_url(path: &std::path::Path) -> Result<tauri::Url, String> {
    use percent_encoding::{utf8_percent_encode, NON_ALPHANUMERIC};

    let path_text = path.to_string_lossy();
    let encoded = utf8_percent_encode(&path_text, NON_ALPHANUMERIC);
    tauri::Url::parse(&format!("obsidian://open?path={encoded}")).map_err(|error| error.to_string())
}

/// Where Obsidian's own installer puts it. The vault button is offered only
/// when one of these exists: without Obsidian the `obsidian://` link has no
/// handler and the launcher fails with an exit status nobody can act on. An
/// install elsewhere loses only the shortcut; the folder is a vault that
/// Obsidian's picker opens.
fn obsidian_candidates() -> Vec<PathBuf> {
    #[cfg(target_os = "macos")]
    {
        let mut found = vec![PathBuf::from("/Applications/Obsidian.app")];
        if let Some(home) = std::env::var_os("HOME") {
            found.push(PathBuf::from(home).join("Applications/Obsidian.app"));
        }
        found
    }
    #[cfg(target_os = "windows")]
    {
        // The per-user installer, in its current and its older location.
        let mut found = Vec::new();
        if let Some(local) = std::env::var_os("LOCALAPPDATA") {
            let local = PathBuf::from(local);
            found.push(local.join("Programs").join("Obsidian").join("Obsidian.exe"));
            found.push(local.join("Obsidian").join("Obsidian.exe"));
        }
        found
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        Vec::new()
    }
}

/// Whether Obsidian is installed where the Knowledge section can expect the
/// vault link to work.
#[tauri::command]
fn obsidian_available() -> bool {
    obsidian_candidates()
        .iter()
        .any(|candidate| candidate.exists())
}

/// Open a validated space folder as a vault through Obsidian's documented URI.
#[tauri::command]
fn open_obsidian_vault(app: AppHandle, path: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;

    let wanted = validated_data_directory(&app, &path)?;
    let url = obsidian_vault_url(&wanted)?;
    app.opener()
        .open_url(url.as_str(), None::<&str>)
        .map_err(|error| {
            // The launcher's exit status is for the log; the message says
            // what still works.
            eprintln!("[obsidian] {error}");
            format!(
                "Obsidian did not open the folder. Open it as a vault from Obsidian's own \
                 vault picker instead: {}",
                wanted.display()
            )
        })
}

/// Open the OAuth page returned by Codex App Server. The webview cannot use
/// the opener plugin directly, and this command accepts only OpenAI-owned
/// HTTPS hosts rather than becoming a general URL launcher.
#[tauri::command]
fn open_auth_url(app: AppHandle, url: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;

    if !auth_url_is_allowed(&url) {
        return Err("refusing an unexpected ChatGPT sign-in URL".to_string());
    }
    app.opener()
        .open_url(url, None::<&str>)
        .map_err(|error| error.to_string())
}

fn auth_url_is_allowed(url: &str) -> bool {
    let Ok(parsed) = tauri::Url::parse(url) else {
        return false;
    };
    let allowed_host = matches!(parsed.host_str(), Some("auth.openai.com" | "chatgpt.com"));
    parsed.scheme() == "https" && allowed_host
}

/// Quit and relaunch, so a key written to the keychain reaches the next
/// spawn's handshake without the user finding the app in the Dock. The work
/// runs on a thread of its own: `restart` from the main thread would skip the
/// `RunEvent::Exit` callback and orphan the sidecar on its port, while from
/// any other thread it requests an exit, waits for that callback (which stops
/// the sidecar) and then execs a fresh copy of this binary. The sidecar is
/// stopped here first anyway, so the new instance never races the old one for
/// port 8787 whichever path Tauri takes.
#[tauri::command]
fn restart_app(app: AppHandle) {
    std::thread::spawn(move || {
        shutdown_sidecar(&app);
        app.restart();
    });
}

/// Start the sidecar and keep its handle for shutdown. The data directory is
/// resolved here and handed over in the environment, so the two sides cannot
/// guess it separately.
fn spawn_sidecar(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let data_dir = data_dir(app)?;
    std::fs::create_dir_all(&data_dir)?;

    // Otherwise silent: the sidecar cannot bind and exits, and the webview
    // refuses whatever holds the port by its tag. This line is for the log.
    if port_is_open(SIDECAR_PORT) {
        eprintln!(
            "[sidecar] port {SIDECAR_PORT} is already in use: another AgentSpace, or a dev \
             sidecar? This app's sidecar will not be able to bind it."
        );
    }

    let instance = app.state::<Instance>().0.clone();
    let (mut rx, mut child) = app
        .shell()
        .sidecar(SIDECAR_NAME)?
        .env(DATA_DIR_ENV, data_dir.as_os_str())
        .env(INSTANCE_ENV, &instance)
        .spawn()?;

    // Logged, not propagated: a missing key must not stop the window opening.
    if let Err(error) = send_secrets(&mut child) {
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

/// Read the API keys from the OS keychain and write them to the sidecar's stdin
/// as one JSON line, first, before the stream becomes the shutdown watchdog
/// (§1 constraint 4). stdin, never `argv`, which any process can read. The line
/// is always written, even empty.
///
/// The read goes to the `keyring` crate directly, not the plugin's
/// `get_password`, which folds every failure into `None`: on macOS a user
/// clicking Deny on the keychain prompt then looked like an unset key.
/// `NoEntry` is the one error that means "not set".
fn send_secrets(child: &mut CommandChild) -> Result<(), Box<dyn std::error::Error>> {
    let mut secrets = serde_json::Map::new();

    for name in SECRET_NAMES {
        match keyring::Entry::new(KEYCHAIN_SERVICE, name)?.get_password() {
            Ok(value) if !value.is_empty() => {
                secrets.insert(name.to_string(), serde_json::Value::String(value));
            }
            Ok(_) => {}
            // A miss is normal: the user has not set that key.
            Err(keyring::Error::NoEntry) => {}
            // The keychain refusing or failing: the one place that can be seen.
            Err(error) => eprintln!("[keychain] could not read {name}: {error}"),
        }
    }

    // Names only; the values must not reach the console.
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
            // Dropping `child` closes stdin: even a sidecar that ignored the command sees EOF.
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    // 3. Backstop. `kill` consumes the handle, so stdin closes here too.
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
/// Panics if the Tauri application cannot be built (a malformed `tauri.conf.json`).
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_keyring::init())
        .plugin(tauri_plugin_opener::init())
        .manage(SidecarState::default())
        .manage(Instance::mint())
        .invoke_handler(tauri::generate_handler![
            sidecar_base_url,
            sidecar_instance,
            keychain_service,
            reveal_folder,
            obsidian_available,
            open_obsidian_vault,
            open_auth_url,
            restart_app
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

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::{auth_url_is_allowed, obsidian_candidates, obsidian_vault_url};

    #[test]
    fn obsidian_is_looked_for_where_its_installer_puts_it() {
        let candidates = obsidian_candidates();
        if cfg!(target_os = "macos") {
            assert!(candidates.contains(&std::path::PathBuf::from("/Applications/Obsidian.app")));
            assert!(candidates.iter().all(|path| path.ends_with("Obsidian.app")));
        } else if cfg!(target_os = "windows") {
            assert!(candidates.iter().all(|path| path.ends_with("Obsidian.exe")));
        } else {
            assert!(candidates.is_empty());
        }
    }

    #[test]
    fn obsidian_vault_url_keeps_the_exact_path_as_one_query_value() {
        let path = Path::new("/tmp/Agent Space/research & memory");
        let url = obsidian_vault_url(path).expect("a valid Obsidian URL");
        let decoded_path = url
            .query_pairs()
            .find_map(|(key, value)| (key == "path").then(|| value.into_owned()));

        assert_eq!(decoded_path.as_deref(), path.to_str());
        assert_eq!(url.scheme(), "obsidian");
        assert_eq!(url.host_str(), Some("open"));
        assert!(url
            .as_str()
            .contains("%2Ftmp%2FAgent%20Space%2Fresearch%20%26%20memory"));
        assert!(!url.as_str().contains('+'));
    }

    #[test]
    fn oauth_url_requires_an_exact_openai_https_host() {
        assert!(auth_url_is_allowed(
            "https://auth.openai.com/oauth/authorize?client_id=test"
        ));
        assert!(auth_url_is_allowed("https://chatgpt.com/auth/callback"));
        assert!(!auth_url_is_allowed(
            "http://auth.openai.com/oauth/authorize"
        ));
        assert!(!auth_url_is_allowed(
            "https://auth.openai.com.example.com/phish"
        ));
        assert!(!auth_url_is_allowed("not a URL"));
    }
}
