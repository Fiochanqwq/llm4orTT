const { app, BrowserWindow, shell, Tray, Menu, nativeImage } = require('electron');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
let service, window, tray, quitting = false;
// Keep the previous installation's Electron profile and single-instance identity.
app.setPath('userData', process.env.FYPPPPP_QA === '1' && process.env.FYPPPPP_DATA_DIR ? path.join(process.env.FYPPPPP_DATA_DIR, 'electron-profile') : path.join(app.getPath('appData'), 'FYPPPPP'));
const browserOnly = process.argv.includes('--browser');
if (!app.requestSingleInstanceLock()) {
  // The existing instance will receive second-instance, but may be an old build.
  // Warn instead of making a newer executable appear to have silently downgraded.
  app.whenReady().then(async () => {
    try {
      const fs = require('node:fs');
      const directory = process.env.FYPPPPP_DATA_DIR || path.join(process.env.LOCALAPPDATA || '', 'FYPPPPP', 'workspace');
      const runtime = JSON.parse(fs.readFileSync(path.join(directory, 'runtime.json'), 'utf8'));
      if (/^http:\/\/127\.0\.0\.1:\d+$/.test(runtime.origin)) {
        const health = await fetch(runtime.origin + '/api/health', { signal: AbortSignal.timeout(1500) }).then(response => response.json());
        if (health.version !== app.getVersion()) require('electron').dialog.showErrorBox('llm4orTT · 旧版本仍在运行 / Older version running', `运行中 / Running: ${health.version || '?'}\n当前版本 / New version: ${app.getVersion()}\n请从系统托盘退出旧程序，再重新启动。\nQuit the older app from the system tray, then launch again.`);
      }
    } catch { /* The other instance may still be starting. */ }
    app.quit();
  });
}
else {
  function openDesktop() {
    if (!service) return;
    if (window && !window.isDestroyed()) { window.show(); window.focus(); return; }
    window = new BrowserWindow({ width: 1360, height: 900, minWidth: 680, minHeight: 560, show: process.env.FYPPPPP_QA !== '1', title: 'llm4orTT', backgroundColor: '#fafafa', autoHideMenuBar: true, icon: path.join(__dirname, '../dist/saturn-icon.png'), webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true } });
    const origin = service.origin;
    window.webContents.setWindowOpenHandler(({ url }) => { if (/^https:\/\//.test(url)) shell.openExternal(url); return { action: 'deny' }; });
    window.webContents.on('will-navigate', (event, url) => { if (new URL(url).origin !== origin) event.preventDefault(); });
    window.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    window.loadURL(origin + '/#token=' + service.token);
  }
  function openBrowser() { if (service && process.env.FYPPPPP_QA !== '1') shell.openExternal(service.origin + '/#token=' + service.token); }
  app.on('second-instance', (_event, argv) => argv.includes('--browser') ? openBrowser() : openDesktop());
  app.whenReady().then(async () => {
    const { ensureService } = await import(pathToFileURL(path.join(__dirname, '../server/launcher.mjs')).href);
    service = await ensureService();
    const image = nativeImage.createFromPath(path.join(__dirname, '../dist/saturn-icon.png'));
    tray = new Tray(image.resize({ width: 20, height: 20 })); tray.setToolTip('llm4orTT');
    tray.on('right-click', () => tray.popUpContextMenu(Menu.buildFromTemplate([{ label: '打开 llm4orTT', click: openDesktop }, { label: '在浏览器中打开', click: openBrowser }, { type: 'separator' }, { label: '退出', click: () => app.quit() }])));
    tray.on('double-click', openDesktop);
    browserOnly ? openBrowser() : openDesktop();
  }).catch(error => { if (process.env.FYPPPPP_QA === '1') console.error(error.stack || error.message); else require('electron').dialog.showErrorBox('llm4orTT · 启动失败 / Startup failed', error.message); app.quit(); });
  app.on('window-all-closed', () => {});
  app.on('before-quit', event => {
    if (service?.owned && !quitting) {
      event.preventDefault(); quitting = true;
      service.close().finally(() => { service.cleanup(); app.quit(); });
    }
  });
}
