// Hide the Windows release console; retain it in debug for sidecar stdout/stderr.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    agentbase_desktop_lib::run()
}
