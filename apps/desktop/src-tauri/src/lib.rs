//! Tauri shell: spawn the frozen sidecar with its data directory and keys, then
//! stop it at exit.
//!
//! PyInstaller `--onefile` exposes the bootloader PID, not the server's; killing
//! it would orphan port 8787. Send `shutdown` and close stdin instead; `kill` is
//! a timeout backstop.

use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Matches `tauri.conf.json` `externalBin`; Tauri appends the target triple.
const SIDECAR_NAME: &str = "agentbase-sidecar";

/// Matches `agentbase.config.DEFAULT_BIND_PORT` and CSP `connect-src`. The
/// sidecar hardcodes localhost-only binding (BUILD_SPEC §1 constraint 3).
const SIDECAR_PORT: u16 = 8787;

/// Clean-stop stdin command; matches `agentbase.main.SHUTDOWN_COMMAND`.
const SHUTDOWN_LINE: &[u8] = b"shutdown\n";

/// Grace period before forced sidecar shutdown.
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);

/// Keychain service matches the bundle identifier for Credential Manager.
const KEYCHAIN_SERVICE: &str = "dev.agentbase.desktop";

/// Pre-rename AgentSpace service; read-only fallback preserves credentials until
/// an AgentBase key is written.
const LEGACY_KEYCHAIN_SERVICE: &str = "dev.agentspace.desktop";

/// Keychain accounts and stdin JSON fields; matches `agentbase.secrets.SECRET_KEYS`.
const SECRET_NAMES: [&str; 3] = ["anthropic_api_key", "openai_api_key", "discord_bot_token"];

#[derive(Default)]
struct SidecarState(Mutex<Option<CommandChild>>);

/// Per-launch tag env var echoed from `/health`; matches
/// `agentbase.main.INSTANCE_ENV_VAR`.
const INSTANCE_ENV: &str = "AGENTBASE_INSTANCE";

/// Per-launch, non-secret tag lets the webview distinguish this sidecar from
/// another process on the fixed port.
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

/// Return the sidecar origin for the webview.
#[tauri::command]
fn sidecar_base_url() -> String {
    format!("http://127.0.0.1:{SIDECAR_PORT}")
}

/// Return the `/health` tag the webview requires for trust.
#[tauri::command]
fn sidecar_instance(instance: tauri::State<'_, Instance>) -> String {
    instance.0.clone()
}

/// Return the settings keychain service; Rust alone reads secrets.
#[tauri::command]
fn keychain_service() -> String {
    KEYCHAIN_SERVICE.to_string()
}

/// Return the predecessor service for removing adopted credentials only; the
/// webview never reads either keychain service.
#[tauri::command]
fn legacy_keychain_service() -> String {
    LEGACY_KEYCHAIN_SERVICE.to_string()
}

/// Sidecar data-directory env var; matches `agentbase.config.DATA_DIR_ENV_VAR`.
const DATA_DIR_ENV: &str = "AGENTBASE_DATA_DIR";

/// Return the justfile-provided dev directory or Tauri's bundle-derived local
/// data directory; sidecar spawning and folder validation share it.
fn data_dir(app: &AppHandle) -> Result<PathBuf, tauri::Error> {
    match std::env::var_os(DATA_DIR_ENV) {
        Some(inherited) => Ok(PathBuf::from(inherited)),
        // Avoid roaming `app_data_dir()` on Windows; match the sidecar fallback.
        None => app.path().app_local_data_dir(),
    }
}

/// Canonicalize an existing directory and require it under AgentBase data.
fn validated_data_directory(app: &AppHandle, path: &str) -> Result<PathBuf, String> {
    let root = data_dir(app).map_err(|error| error.to_string())?;
    let root = std::fs::canonicalize(&root).map_err(|error| error.to_string())?;
    let wanted = std::fs::canonicalize(path)
        .map_err(|_| format!("{path} does not exist yet: it is created by the first run"))?;
    if !wanted.starts_with(&root) {
        return Err(format!("{path} is not inside AgentBase's data directory"));
    }
    if !wanted.is_dir() {
        return Err(format!("{path} is not a folder"));
    }
    Ok(wanted)
}

/// Open a validated space folder; the webview's only path-opening command.
#[tauri::command]
fn reveal_folder(app: AppHandle, path: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;

    let wanted = validated_data_directory(&app, &path)?;
    app.opener()
        .open_path(wanted.to_string_lossy(), None::<&str>)
        .map_err(|error| error.to_string())
}

/// Open a generated Excel workbook in the person's spreadsheet app. Only a
/// visible `.xlsx` file inside AgentBase's data directory qualifies; the
/// webview cannot name any other file.
#[tauri::command]
fn open_workbook(app: AppHandle, path: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;

    let root = data_dir(&app).map_err(|error| error.to_string())?;
    let root = std::fs::canonicalize(&root).map_err(|error| error.to_string())?;
    let wanted = std::fs::canonicalize(&path).map_err(|_| format!("{path} does not exist"))?;
    let workbook = workbook_inside(&root, &wanted)?;
    app.opener()
        .open_path(workbook.to_string_lossy(), None::<&str>)
        .map_err(|error| error.to_string())
}

/// A canonical path that is a visible `.xlsx` file under `root`.
fn workbook_inside(root: &Path, wanted: &Path) -> Result<PathBuf, String> {
    let Ok(relative) = wanted.strip_prefix(root) else {
        return Err(format!("{} is not inside AgentBase's data directory", wanted.display()));
    };
    let hidden = relative
        .components()
        .any(|part| part.as_os_str().to_string_lossy().starts_with('.'));
    let workbook = wanted
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("xlsx"));
    if hidden || !workbook || !wanted.is_file() {
        return Err(format!("{} is not an Excel workbook AgentBase wrote", wanted.display()));
    }
    Ok(wanted.to_path_buf())
}

fn obsidian_vault_url(path: &std::path::Path) -> Result<tauri::Url, String> {
    use percent_encoding::{utf8_percent_encode, NON_ALPHANUMERIC};

    let path_text = path.to_string_lossy();
    let encoded = utf8_percent_encode(&path_text, NON_ALPHANUMERIC);
    tauri::Url::parse(&format!("obsidian://open?path={encoded}")).map_err(|error| error.to_string())
}

/// Return standard Obsidian install locations. Offer the vault shortcut only
/// when one exists; other installs can use Obsidian's vault picker.
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
        // Current and legacy per-user installer locations.
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

/// Report whether the Knowledge vault link can work.
#[tauri::command]
fn obsidian_available() -> bool {
    obsidian_candidates()
        .iter()
        .any(|candidate| candidate.exists())
}

/// Open a validated space folder through Obsidian's documented vault URI.
#[tauri::command]
fn open_obsidian_vault(app: AppHandle, path: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;

    let wanted = validated_data_directory(&app, &path)?;
    let url = obsidian_vault_url(&wanted)?;
    app.opener()
        .open_url(url.as_str(), None::<&str>)
        .map_err(|error| {
            // Log the launcher status; tell the user the remaining workaround.
            eprintln!("[obsidian] {error}");
            format!(
                "Obsidian did not open the folder. Open it as a vault from Obsidian's own \
                 vault picker instead: {}",
                wanted.display()
            )
        })
}

/// Open a Codex App Server OAuth page. The webview cannot call the plugin;
/// permit only OpenAI-owned HTTPS hosts, not arbitrary URLs.
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

/// Relaunch after a key write so the next spawn receives it. Run off the main
/// thread so `RunEvent::Exit` stops the sidecar; stop it first as well, avoiding
/// a port-8787 race regardless of Tauri's restart path.
#[tauri::command]
fn restart_app(app: AppHandle) {
    std::thread::spawn(move || {
        shutdown_sidecar(&app);
        app.restart();
    });
}

/// Start the sidecar, retain its shutdown handle, and pass the resolved data
/// directory through the environment.
fn spawn_sidecar(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let data_dir = data_dir(app)?;
    std::fs::create_dir_all(&data_dir)?;

    // Log binding failure; the webview rejects a port occupant with another tag.
    if port_is_open(SIDECAR_PORT) {
        eprintln!(
            "[sidecar] port {SIDECAR_PORT} is already in use: another AgentBase, or a dev \
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

    // Log, rather than propagate, a missing-key handshake error.
    if let Err(error) = send_secrets(&mut child) {
        eprintln!("[sidecar] could not send the key handshake: {error}");
    }

    app.state::<SidecarState>()
        .0
        .lock()
        .expect("sidecar state poisoned")
        .replace(child);

    // Drain output so a full pipe cannot block sidecar logging.
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

/// Read API keys and write one JSON line to sidecar stdin before it becomes the
/// shutdown watchdog (§1 constraint 4). Never use `argv`, which other processes
/// can read; write the line even when empty.
///
/// Read directly through `keyring`: the plugin turns every error into `None`,
/// making a macOS Deny prompt appear unset. Only `NoEntry` means "not set".
enum KeychainLookup {
    Value(String),
    Missing,
    Unavailable,
}

/// Read one keychain entry without conflating failures with absence, preventing
/// a legacy AgentSpace key from bypassing a denied or unavailable AgentBase key.
fn read_keychain_entry(service: &str, name: &str) -> KeychainLookup {
    match keyring::Entry::new(service, name).and_then(|entry| entry.get_password()) {
        Ok(value) => KeychainLookup::Value(value),
        Err(keyring::Error::NoEntry) => KeychainLookup::Missing,
        // Service and account are identifiers, never secret values.
        Err(error) => {
            eprintln!("[keychain] could not read {name} from {service}: {error}");
            KeychainLookup::Unavailable
        }
    }
}

/// Prefer AgentBase keys; consult the legacy service only after explicit
/// `NoEntry`. Empty or unavailable current entries remain authoritative.
fn secret_for_name(
    name: &str,
    mut lookup: impl FnMut(&str, &str) -> KeychainLookup,
) -> Option<String> {
    let entry = match lookup(KEYCHAIN_SERVICE, name) {
        KeychainLookup::Missing => lookup(LEGACY_KEYCHAIN_SERVICE, name),
        entry => entry,
    };

    match entry {
        KeychainLookup::Value(value) if !value.is_empty() => Some(value),
        KeychainLookup::Value(_) | KeychainLookup::Missing | KeychainLookup::Unavailable => None,
    }
}

fn send_secrets(child: &mut CommandChild) -> Result<(), Box<dyn std::error::Error>> {
    let mut secrets = serde_json::Map::new();

    for name in SECRET_NAMES {
        if let Some(value) = secret_for_name(name, read_keychain_entry) {
            secrets.insert(name.to_string(), serde_json::Value::String(value));
        }
    }

    // Log names only; never write values to the console.
    let names: Vec<&str> = secrets.keys().map(String::as_str).collect();
    eprintln!("[keychain] sending {} key(s): {:?}", names.len(), names);

    let mut line = serde_json::to_vec(&serde_json::Value::Object(secrets))?;
    line.push(b'\n');
    child.write(&line)?;

    Ok(())
}

/// Stop the sidecar through mechanisms that reach the real server.
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

    // 1. Request shutdown through the stdin watchdog.
    if let Err(error) = child.write(SHUTDOWN_LINE) {
        eprintln!("[sidecar] could not write shutdown command: {error}");
    }

    // 2. Allow graceful exit.
    let deadline = Instant::now() + SHUTDOWN_GRACE;
    while Instant::now() < deadline {
        if !port_is_open(SIDECAR_PORT) {
            // Dropping `child` closes stdin, so an ignored command still yields EOF.
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    // 3. Backstop: `kill` consumes the handle and closes stdin.
    eprintln!("[sidecar] did not exit within {SHUTDOWN_GRACE:?}; killing");
    if let Err(error) = child.kill() {
        eprintln!("[sidecar] kill failed: {error}");
    }
}

/// Return whether anything listens on the sidecar port.
fn port_is_open(port: u16) -> bool {
    use std::net::{Ipv4Addr, SocketAddr, TcpStream};

    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    TcpStream::connect_timeout(&address, Duration::from_millis(200)).is_ok()
}

/// Build and run the application.
///
/// # Panics
///
/// Panics when Tauri cannot build the application, for example from malformed
/// `tauri.conf.json`.
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
            legacy_keychain_service,
            reveal_folder,
            open_workbook,
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
        .expect("failed to build the AgentBase application");

    app.run(|app, event| {
        if matches!(event, RunEvent::Exit) {
            shutdown_sidecar(app);
        }
    });
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::{
        auth_url_is_allowed, obsidian_candidates, obsidian_vault_url, secret_for_name,
        workbook_inside, KeychainLookup, KEYCHAIN_SERVICE, LEGACY_KEYCHAIN_SERVICE,
    };

    #[test]
    fn only_a_visible_workbook_inside_the_data_directory_opens() {
        let root = std::env::temp_dir().join(format!("agentbase-workbook-{}", std::process::id()));
        let predictions = root.join("spaces/main/predictions");
        let hidden = root.join("spaces/main/.agentbase");
        std::fs::create_dir_all(&predictions).unwrap();
        std::fs::create_dir_all(&hidden).unwrap();
        for file in [
            predictions.join("2026-10.xlsx"),
            predictions.join("forecasts.json"),
            hidden.join("2026-10.xlsx"),
        ] {
            std::fs::write(file, b"x").unwrap();
        }
        let outside = std::env::temp_dir().join("agentbase-outside.xlsx");
        std::fs::write(&outside, b"x").unwrap();

        assert!(workbook_inside(&root, &predictions.join("2026-10.xlsx")).is_ok());
        assert!(workbook_inside(&root, &predictions.join("forecasts.json")).is_err());
        assert!(workbook_inside(&root, &hidden.join("2026-10.xlsx")).is_err());
        assert!(workbook_inside(&root, &predictions).is_err());
        assert!(workbook_inside(&root, &outside).is_err());

        std::fs::remove_dir_all(&root).unwrap();
        std::fs::remove_file(&outside).unwrap();
    }

    #[test]
    fn agentbase_keychain_entry_wins_without_reading_legacy() {
        let mut calls = Vec::new();
        let secret = secret_for_name("openai_api_key", |service, name| {
            calls.push((service.to_string(), name.to_string()));
            match service {
                KEYCHAIN_SERVICE => KeychainLookup::Value("current".to_string()),
                LEGACY_KEYCHAIN_SERVICE => panic!("legacy entry must not be read"),
                _ => unreachable!("unexpected keychain service"),
            }
        });

        assert_eq!(secret.as_deref(), Some("current"));
        assert_eq!(
            calls,
            vec![(KEYCHAIN_SERVICE.to_string(), "openai_api_key".to_string())]
        );
    }

    #[test]
    fn missing_agentbase_keychain_entry_reads_legacy_once() {
        let mut calls = Vec::new();
        let secret = secret_for_name("openai_api_key", |service, name| {
            calls.push((service.to_string(), name.to_string()));
            match service {
                KEYCHAIN_SERVICE => KeychainLookup::Missing,
                LEGACY_KEYCHAIN_SERVICE => KeychainLookup::Value("legacy".to_string()),
                _ => unreachable!("unexpected keychain service"),
            }
        });

        assert_eq!(secret.as_deref(), Some("legacy"));
        assert_eq!(
            calls,
            vec![
                (KEYCHAIN_SERVICE.to_string(), "openai_api_key".to_string()),
                (
                    LEGACY_KEYCHAIN_SERVICE.to_string(),
                    "openai_api_key".to_string()
                ),
            ]
        );
    }

    #[test]
    fn unavailable_agentbase_keychain_entry_does_not_read_legacy() {
        let mut calls = Vec::new();
        let secret = secret_for_name("openai_api_key", |service, _| {
            calls.push(service.to_string());
            match service {
                KEYCHAIN_SERVICE => KeychainLookup::Unavailable,
                LEGACY_KEYCHAIN_SERVICE => {
                    panic!("legacy entry must not bypass an unavailable current entry")
                }
                _ => unreachable!("unexpected keychain service"),
            }
        });

        assert!(secret.is_none());
        assert_eq!(calls, vec![KEYCHAIN_SERVICE.to_string()]);
    }

    #[test]
    fn empty_agentbase_keychain_entry_does_not_read_legacy() {
        let mut calls = Vec::new();
        let secret = secret_for_name("openai_api_key", |service, _| {
            calls.push(service.to_string());
            match service {
                KEYCHAIN_SERVICE => KeychainLookup::Value(String::new()),
                LEGACY_KEYCHAIN_SERVICE => {
                    panic!("legacy entry must not replace a current empty entry")
                }
                _ => unreachable!("unexpected keychain service"),
            }
        });

        assert!(secret.is_none());
        assert_eq!(calls, vec![KEYCHAIN_SERVICE.to_string()]);
    }

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
