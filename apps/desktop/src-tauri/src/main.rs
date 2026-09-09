// Hide the console window on Windows release builds. In debug it is kept, so
// the sidecar's stdout/stderr are visible while developing.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    agentspace_desktop_lib::run()
}
