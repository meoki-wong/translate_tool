use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;

pub struct AppState {
    pub python_process: Mutex<Option<Child>>,
}

#[tauri::command]
fn start_backend(state: tauri::State<AppState>) -> Result<String, String> {
    let mut process = state.python_process.lock().map_err(|e| e.to_string())?;

    if process.is_some() {
        return Ok("Backend already running".to_string());
    }

    // Try multiple possible paths for the Python binary
    let python_paths = [
        "../backend/venv/bin/python",
        "../../backend/venv/bin/python",
        "./backend/venv/bin/python",
    ];

    let mut last_err = String::new();
    for py_path in &python_paths {
        match Command::new(py_path)
            .arg(if py_path.contains("../../") || py_path.contains("./backend") {
                if py_path.contains("../../") { "../../backend/main.py" } else { "./backend/main.py" }
            } else {
                "../backend/main.py"
            })
            .spawn()
        {
            Ok(child) => {
                *process = Some(child);
                return Ok(format!("Backend started with {}", py_path));
            }
            Err(e) => {
                last_err = format!("{}: {}", py_path, e);
                continue;
            }
        }
    }

    Err(format!("Failed to start backend. Tried: {}", last_err))
}

#[tauri::command]
fn stop_backend(state: tauri::State<AppState>) -> Result<String, String> {
    let mut process = state.python_process.lock().map_err(|e| e.to_string())?;

    if let Some(mut child) = process.take() {
        let _ = child.kill();
        let _ = child.wait();
        Ok("Backend stopped".to_string())
    } else {
        Ok("Backend not running".to_string())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(AppState {
            python_process: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![start_backend, stop_backend])
        .setup(|app| {
            // Auto-start Python backend on app launch
            let state = app.state::<AppState>();
            let mut process = state.python_process.lock().unwrap();

            let python_paths = [
                ("../backend/venv/bin/python", "../backend/main.py"),
                ("../../backend/venv/bin/python", "../../backend/main.py"),
                ("./backend/venv/bin/python", "./backend/main.py"),
            ];

            for (py, script) in &python_paths {
                match Command::new(py).arg(script).spawn() {
                    Ok(child) => {
                        println!("Python backend started: {}", py);
                        *process = Some(child);
                        break;
                    }
                    Err(e) => {
                        eprintln!("Tried {} : {}", py, e);
                        continue;
                    }
                }
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
