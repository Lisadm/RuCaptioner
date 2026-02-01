/**
 * CaptionFoundry - Electron Main Process
 * 
 * Launches the Python FastAPI backend as a subprocess and creates
 * the Electron BrowserWindow to load the frontend.
 */

const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// Try to load tree-kill for graceful shutdown, fall back to basic kill
let treeKill;
try {
    treeKill = require('tree-kill');
} catch (e) {
    treeKill = (pid, signal, callback) => {
        try {
            process.kill(pid, signal);
            if (callback) callback();
        } catch (err) {
            if (callback) callback(err);
        }
    };
}

// Configuration
const BACKEND_PORT = 8765;
const BACKEND_URL = `http://localhost:${BACKEND_PORT}`;
const isDev = process.argv.includes('--dev');

let mainWindow = null;
let pythonProcess = null;

/**
 * Get the path to the Python executable
 */
function getPythonPath() {
    const projectRoot = path.dirname(__dirname);

    // In production (bundled app), the backend executable should be in resources/backend
    // path.join(process.resourcesPath, 'backend', 'backend.exe')
    const bundledBackendPath = path.join(process.resourcesPath, 'backend', 'backend.exe');
    if (fs.existsSync(bundledBackendPath)) {
        console.log(`[Electron] Found bundled backend at: ${bundledBackendPath}`);
        return bundledBackendPath;
    }

    // Dev mode: Check for local venv
    const venvPaths = [
        path.join(projectRoot, 'dist', 'backend', 'backend.exe'), // Local build test
        path.join(projectRoot, 'backend', 'dist', 'backend', 'backend.exe'), // Another local build test
        path.join(projectRoot, 'venv', 'Scripts', 'python.exe'),  // Windows venv
        path.join(projectRoot, 'venv', 'bin', 'python'),          // Unix venv
        path.join(projectRoot, '.venv', 'Scripts', 'python.exe'), // Windows .venv
        path.join(projectRoot, '.venv', 'bin', 'python'),         // Unix .venv
    ];

    for (const venvPath of venvPaths) {
        if (fs.existsSync(venvPath)) {
            console.log(`[Electron] Found Python/Backend at: ${venvPath}`);
            return venvPath;
        }
    }

    // Fall back to system Python
    console.log('[Electron] No venv or bundled backend found, using system Python');
    return process.platform === 'win32' ? 'python' : 'python3';
}

/**
 * Start the FastAPI backend server
 */
function startBackend() {
    return new Promise((resolve, reject) => {
        const projectRoot = path.dirname(__dirname);
        const pythonPath = getPythonPath();

        console.log(`[Electron] Starting backend with: ${pythonPath}`);
        console.log(`[Electron] Working directory: ${projectRoot}`);

        // Spawn the Python backend
        let args = ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT)];
        let spawnCwd = projectRoot;

        // If using bundled executable, don't pass uvicorn args and fix CWD
        if (pythonPath.endsWith('backend.exe')) {
            console.log('[Electron] Running bundled backend executable');
            args = [];
            spawnCwd = path.dirname(pythonPath);
        }

        pythonProcess = spawn(pythonPath, args, {
            cwd: spawnCwd,
            env: { ...process.env, PYTHONUNBUFFERED: '1' },
            stdio: ['pipe', 'pipe', 'pipe'] // Enable stdin pipe for the watchdog
        });

        let started = false;

        pythonProcess.stdout.on('data', (data) => {
            const output = data.toString();
            console.log(`[Backend] ${output}`);

            // Check if server has started (Uvicorn standard or our explicit signal)
            if (!started && (output.includes('Uvicorn running') || output.includes('CAPTION_FOUNDRY_BACKEND_READY'))) {
                started = true;
                console.log('[Electron] Backend server is ready');
                resolve();
            }
        });

        let stderrOutput = '';

        pythonProcess.stderr.on('data', (data) => {
            const output = data.toString();
            console.error(`[Backend Error] ${output}`);
            stderrOutput += output;

            // Uvicorn also logs startup to stderr
            if (!started && (output.includes('Uvicorn running') || output.includes('CAPTION_FOUNDRY_BACKEND_READY'))) {
                started = true;
                console.log('[Electron] Backend server is ready');
                resolve();
            }
        });

        pythonProcess.on('error', (err) => {
            console.error('[Electron] Failed to start Python backend:', err);
            reject(err);
        });

        pythonProcess.on('exit', (code) => {
            console.log(`[Electron] Python backend exited with code ${code}`);
            pythonProcess = null;

            if (!started) {
                const errorMsg = stderrOutput ? `\n\nError Log:\n${stderrOutput.slice(-1000)}` : '';
                reject(new Error(`Backend failed to start (exit code ${code})${errorMsg}`));
            }
        });

        // Timeout after 45 seconds (increased to allow for database migrations on first run)
        setTimeout(() => {
            if (!started) {
                console.log('[Electron] Backend startup timeout - assuming it\'s running');
                resolve();
            }
        }, 45000);
    });
}

/**
 * Stop the Python backend
 */
async function stopBackend() {
    if (pythonProcess) {
        const pid = pythonProcess.pid;
        console.log(`[Electron] Stopping Python backend (PID: ${pid})...`);

        // 1. Try graceful shutdown via API
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 2000);

            await fetch(`${BACKEND_URL}/api/system/shutdown`, {
                method: 'POST',
                signal: controller.signal
            });

            clearTimeout(timeoutId);
            console.log('[Electron] Graceful shutdown request sent');
        } catch (err) {
            console.log('[Electron] Graceful shutdown request failed or timed out, falling back to tree-kill');
        }

        // 2. Fallback to tree-kill to ensure it's gone
        if (pythonProcess) {
            treeKill(pid, 'SIGTERM', (err) => {
                if (err) {
                    console.error('[Electron] Error killing backend:', err);
                    treeKill(pid, 'SIGKILL');
                }
            });
        }

        pythonProcess = null;
    }
}

/**
 * Create the main application window
 */
function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1280,
        height: 800,
        minWidth: 1024,
        minHeight: 700,
        backgroundColor: '#1a1a1a',
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js')
        },
        icon: path.join(__dirname, '..', 'frontend', 'img', 'logo.png'),
        show: false,
        title: 'RuCaptioner'
    });

    // Disable cache in development mode to ensure fresh files
    mainWindow.webContents.session.clearCache();

    // Load the frontend
    if (isDev) {
        mainWindow.loadURL(`${BACKEND_URL}/`);
    } else {
        // In production, load from local file system to avoid backend 404s
        mainWindow.loadFile(path.join(__dirname, '..', 'frontend', 'index.html'));
    }

    // Show window when ready
    mainWindow.once('ready-to-show', () => {
        mainWindow.show();

        if (isDev) {
            mainWindow.webContents.openDevTools();
        }
    });

    // Add keyboard shortcut to toggle DevTools (F12 or Ctrl+Shift+I)
    mainWindow.webContents.on('before-input-event', (event, input) => {
        if (input.type === 'keyDown') {
            if (input.key === 'F12' || (input.control && input.shift && input.key === 'I')) {
                mainWindow.webContents.toggleDevTools();
                event.preventDefault();
            }
            // Ctrl+Shift+R or Ctrl+F5 for hard reload (bypass cache)
            if ((input.control && input.shift && input.key === 'R') || (input.control && input.key === 'F5')) {
                mainWindow.webContents.reloadIgnoringCache();
                event.preventDefault();
            }
            // F5 or Ctrl+R for normal reload
            if (input.key === 'F5' || (input.control && input.key === 'r')) {
                mainWindow.webContents.reload();
                event.preventDefault();
            }
        }
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

// ============================================================
// IPC Handlers - Bridge between renderer and Node.js
// ============================================================

// Folder selection dialog
ipcMain.handle('select-folder', async (event, title = 'Select Folder') => {
    const result = await dialog.showOpenDialog(mainWindow, {
        title: title,
        properties: ['openDirectory']
    });

    if (result.canceled || result.filePaths.length === 0) {
        return null;
    }
    return result.filePaths[0];
});

// File selection dialog
ipcMain.handle('select-file', async (event, title = 'Select File', filters = []) => {
    const result = await dialog.showOpenDialog(mainWindow, {
        title: title,
        properties: ['openFile'],
        filters: filters
    });

    if (result.canceled || result.filePaths.length === 0) {
        return null;
    }
    return result.filePaths[0];
});

// Save dialog
ipcMain.handle('select-save-location', async (event, title = 'Save File', defaultPath = '', filters = []) => {
    const result = await dialog.showSaveDialog(mainWindow, {
        title: title,
        defaultPath: defaultPath,
        filters: filters
    });

    if (result.canceled) {
        return null;
    }
    return result.filePath;
});

// Open external URL
ipcMain.handle('open-external', async (event, url) => {
    const { shell } = require('electron');
    await shell.openExternal(url);
    return true;
});

// Log from renderer
ipcMain.on('log', (event, level, module, message, data) => {
    const timestamp = new Date().toISOString();
    const dataStr = data ? ` ${JSON.stringify(data)}` : '';
    console.log(`[${timestamp}] [${level.toUpperCase()}] [${module}] ${message}${dataStr}`);
});

// ============================================================
// App Lifecycle
// ============================================================

app.whenReady().then(async () => {
    console.log('[Electron] App ready, starting backend...');

    try {
        await startBackend();
        createWindow();
    } catch (err) {
        console.error('[Electron] Failed to start:', err);
        dialog.showErrorBox('Startup Error', `Failed to start the backend server:\n\n${err.message}\n\nMake sure Python is installed and dependencies are set up.`);
        app.quit();
    }

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});

app.on('window-all-closed', async () => {
    await stopBackend();
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('before-quit', async () => {
    await stopBackend();
});

// Handle uncaught exceptions
process.on('uncaughtException', (err) => {
    console.error('[Electron] Uncaught exception:', err);
    stopBackend();
});
