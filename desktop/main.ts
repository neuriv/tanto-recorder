import { app, BrowserWindow, dialog, globalShortcut, ipcMain, Menu, screen, shell } from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn, spawnSync, ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';
import { atomicJSON, createSession, readJSON, readSession } from './storage';
import { exportSessions, sessionFolders } from './export';
import type { Health, Session, Settings, View, Take } from './types';

const root = path.resolve(__dirname, '..');
const smoke = process.argv.includes('--ui-smoke');
const automated = process.argv.includes('--record-seconds');
const captureReport = option('--capture-report');
const stateRoot = process.env.TANTO_STATE_ROOT || path.join(process.env.LOCALAPPDATA || app.getPath('userData'), 'Tanto', 'Recorder');
const settingsFile = path.join(stateRoot, 'settings.json');
const version = readJSON(path.join(root, 'product.json')).version;
let settings: Settings;
let window: BrowserWindow;
let session: Session | null = null;
let folder: string | null = null;
let worker: ChildProcessWithoutNullStreams | null = null;
let exporting = false;
let closing = false;
let closeRequested = false;
let dialogBusy = false;
let bindingShortcut = false;
let stopPending = false;
let stopRequestedAt = 0;
let workerDone: Promise<void> = Promise.resolve();
let lastHeartbeat = 0;
let cueStarted = false;
let errorText = '';
let health: Health = { state: 'idle', detail: 'Name the encounter. Start before the move; stop just after it.', actions: 0, bytes: 0, last_t: 0, tail: [] };

function option(name: string): string | undefined {
  // Read explicit automation arguments without involving a shell or simulated keys.
  // Leave a missing value undefined so the caller can reject an incomplete command.
  // Normal launches keep using saved settings and the interactive controls.
  const index = process.argv.indexOf(name);
  const value = index < 0 ? undefined : process.argv[index + 1];
  return value?.startsWith('--') ? undefined : value;
}

async function timedCapture(): Promise<void> {
  // Exercise the ordinary application's Start/Stop path for a bounded live capture.
  // Wait for worker closure and disk sync before publishing counts and the session path.
  // Use a new session, preserve earlier recordings, and fail visibly on zero IDs or an early exit.
  const seconds = Number(option('--record-seconds')), boss = option('--boss');
  if (!Number.isFinite(seconds) || seconds < 1 || seconds > 300 || !boss || !captureReport)
    throw Error('Use --record-seconds 1–300 --boss "name" --capture-report "path.json".');
  ({ folder, session } = createSession(settings.recordings_directory, boss));
  settings.boss_draft = boss;
  const started = Date.now();
  toggle(boss);
  const stopTimer = setTimeout(() => { if (worker) toggle(boss); }, seconds * 1000);
  const timeout = setTimeout(() => { worker?.kill(); }, (seconds + 10) * 1000);
  try { await workerDone; }
  finally { clearTimeout(stopTimer); clearTimeout(timeout); }
  const elapsed = (Date.now() - started) / 1000;
  const passed = health.state === 'stopped' && health.actions > 0 && elapsed >= seconds;
  atomicJSON(captureReport, { passed, version, packaged: app.isPackaged, elapsed, folder, health });
  closing = true; app.exit(passed ? 0 : 1);
}

function view(): View {
  // Send only UI data across the context-isolated bridge.
  // The child process owns capture; renderer restarts cannot silently stop its journal.
  // Boss suggestions label context, without filtering which actors produce evidence.
  return { version, settings, folder, session, health, running: !!worker, exporting,
    bosses: readJSON(path.join(root, 'data', 'bosses.json')).map((row: { name: string }) => row.name),
    changelog: fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8') };
}

function broadcast(): void {
  // Update the one application window if its renderer is still alive.
  // One bounded health update per second avoids rendering every sampled game action.
  // A crashed renderer can reload and request the full current state again.
  if (window && !window.isDestroyed() && !window.webContents.isDestroyed()) window.webContents.send('state', view());
}

function save(): void {
  // Save the current draft and metadata before acknowledging user-visible changes.
  // Recording rows stay in the worker's append-only file; this never rewrites that file.
  // Persist settings separately so an old recording library remains usable across releases.
  if (folder && session) atomicJSON(path.join(folder, 'encounter.json'), session);
  settings.last_session = folder || undefined;
  atomicJSON(settingsFile, settings);
}

function failure(error: unknown): void {
  // Keep a precise failure visible instead of replacing it with a generic stopped message.
  // Existing saved actions and the pending draft remain available for recovery/export.
  // The renderer receives plain text, never HTML assembled from error messages.
  health = { ...health, state: 'error', detail: error instanceof Error ? error.message : String(error) };
  diagnostic('error', { detail: health.detail });
  broadcast();
}

function diagnostic(event: string, fields: Record<string, unknown> = {}): void {
  // Keep workflow failures and shortcut decisions outside individual recording sessions.
  // Two bounded files retain recent history without logging descriptions or every action ID.
  // Diagnostic storage failure must not prevent the independent capture journal from working.
  try {
    fs.mkdirSync(stateRoot, { recursive: true });
    const file = path.join(stateRoot, 'recorder.log');
    if (fs.existsSync(file) && fs.statSync(file).size > 1024 * 1024) fs.renameSync(file, path.join(stateRoot, 'recorder.previous.log'));
    fs.appendFileSync(file, JSON.stringify({ at: new Date().toISOString(), version, event, ...fields }) + '\n');
  } catch (error) { console.error('Recorder diagnostic log unavailable:', String(error)); }
}

function commitContext(value: string): void {
  // A different boss starts a new encounter; earlier raw observations and descriptions stay labeled correctly.
  // Save and detach the old session, then create a folder only when recording or writing a description.
  // The selected boss becomes the shared source for the visible field, saved settings and global hotkey.
  const boss = value.trim().replace(/\s+/g, ' ');
  if (session && session.boss_name !== boss) {
    requireIdle(); save(); folder = null; session = null;
    health = { state: 'idle', detail: 'New encounter selected. Your previous session is saved.', actions: 0, bytes: 0, last_t: 0, tail: [] };
  }
  settings.boss_draft = boss; save();
}

function requireIdle(): void {
  // Session/library changes and export require capture to finish syncing first.
  // This prevents a ZIP snapshot from racing an active journal or description writer.
  // Explicit Stop remains available while the worker is closing.
  if (worker || exporting || dialogBusy) throw Error('Finish recording, export or folder selection before changing sessions.');
}

async function restore(chosen: string): Promise<void> {
  // Recount a new-format journal as a stream after interruption, without loading it into RAM.
  // The journal is authoritative for observed counts; stale metadata cannot erase synced IDs.
  // Leave damaged rows intact and report them rather than silently truncating evidence.
  const restored = readSession(chosen);
  const journals = [{ file: path.join(chosen, 'events.jsonl'), take: '' }, ...fs.readdirSync(chosen, { withFileTypes: true })
    .filter(entry => entry.isDirectory() && /^take-\d+$/.test(entry.name))
    .map(entry => ({ file: path.join(chosen, entry.name, 'events.jsonl'), take: entry.name }))];
  let damaged = 0;
  const takes = new Map(restored.takes.map(take => [take.id, { ...take, actions: 0, last_t: 0 }]));
  for (const journal of journals) {
    if (!fs.existsSync(journal.file)) continue;
    for await (const line of createInterface({ input: fs.createReadStream(journal.file), crlfDelay: Infinity })) {
      if (!line.trim()) continue;
      try {
        const row = JSON.parse(line);
        const id = row.take || journal.take;
        if (typeof id !== 'string' || !id) continue;
        if (!takes.has(id)) takes.set(id, { id, started_at: row.wall_time || restored.created_at, actions: 0, last_t: 0, state: 'interrupted' });
        const take = takes.get(id)!;
        if (row.kind === 'action_state' && row.descriptor?.action_key_u32 !== undefined) take.actions++;
        take.last_t = Math.max(take.last_t, Number(row.t) || 0);
        if (row.kind === 'end') take.state = 'stopped';
      } catch { damaged++; }
    }
  }
  restored.takes = [...takes.values()].map(take => ({ ...take, state: take.state === 'stopped' ? 'stopped' : 'interrupted' }));
  session = restored; folder = chosen; settings.boss_draft = restored.boss_name;
  health = { state: damaged ? 'warning' : 'idle', detail: damaged ? `${damaged} damaged journal rows retained; other evidence recovered.` :
    'Session restored. Start adds a take; previous recordings stay intact.', actions: restored.takes.reduce((n, take) => n + take.actions, 0), bytes: 0, last_t: 0, tail: [] };
}

function setHotkey(value: string): void {
  // Register the replacement first so a conflicting shortcut does not silently remove the old one.
  // Electron owns the OS hotkey; it never sends a key or controller input to Nioh.
  // The smoke check disables registration to avoid interfering with the user's live workflow.
  if (value !== 'Off' && (!/^(?:(?:Control|Ctrl|Alt|Shift)\+)*(?:F(?:[2-9]|10|11)|[A-Z0-9])$/.test(value) ||
      (!/^F\d+$/.test(value) && !/Control\+|Ctrl\+|Alt\+/.test(value)) || /^(?:Control|Ctrl)\+S$|^Alt\+F4$/.test(value)))
    throw Error('Use F2–F11 or a Ctrl/Alt combination; Ctrl+S and Alt+F4 are reserved.');
  if (!smoke && value !== 'Off' && !globalShortcut.isRegistered(value) && !globalShortcut.register(value, shortcut))
    throw Error('That shortcut is already in use. Choose another.');
  if (!smoke && settings.hotkey !== value && settings.hotkey !== 'Off') globalShortcut.unregister(settings.hotkey);
  settings.hotkey = value;
  bindingShortcut = false;
  diagnostic('hotkey_registered', { hotkey: value });
}

function shortcut(): void {
  // Use the same Start/Stop path for the global shortcut and visible control.
  // A recording cannot start before the encounter name reaches the saved session state.
  // Errors remain visible in Recorder and never trigger game input.
  const blocked = exporting || closing || closeRequested || dialogBusy || bindingShortcut || (stopPending && Date.now() - stopRequestedAt <= 8000);
  diagnostic('hotkey_pressed', { hotkey: settings.hotkey, blocked, running: !!worker, dialogBusy, bindingShortcut, stopPending });
  if (blocked) return;
  try { toggle(settings.boss_draft || session?.boss_name || ''); } catch (error) { failure(error); }
}

function toggle(boss: string): void {
  // Start creates durable metadata before launching a separate read-only sampler.
  // Stop is cooperative: keep controls locked until the worker finishes its final fsync.
  // Only a health message with saved action IDs earns the recording cue/status.
  if (worker) {
    if (stopPending && Date.now() - stopRequestedAt > 8000) { worker.kill(); return; }
    if (!stopPending) { stopPending = true; stopRequestedAt = Date.now(); worker.stdin.write('stop\n'); health = { ...health, state: 'stopping', detail: 'Finishing the journal and syncing your action IDs…' }; }
    broadcast(); return;
  }
  requireIdle();
  if (smoke) throw Error('Game capture is disabled in the UI check.');
  const executable = app.isPackaged ? path.join(process.resourcesPath, 'worker', 'TantoCapture.exe') : process.env.TANTO_PYTHON || 'python';
  if (app.isPackaged && !fs.existsSync(executable))
    throw Error('Recorder’s capture worker is missing. Close Recorder completely, then reopen TantoRecorder.exe. No recording was started.');
  commitContext(boss);
  if (!session) ({ folder, session } = createSession(settings.recordings_directory, settings.boss_draft!));
  const take: Take = { id: crypto.randomUUID(), started_at: Date.now() / 1000, actions: 0, last_t: 0, state: 'waiting' };
  session.takes.push(take); save();
  stopPending = cueStarted = false; errorText = '';
  health = { state: 'waiting', detail: 'Waiting for actual action IDs. Do not treat this as a recorded move yet.', actions: 0, bytes: 0, last_t: 0, tail: [] };
  const args = [...(app.isPackaged ? [] : ['-u', '-B', path.join(root, 'launch.py')]), '--journal', path.join(folder!, 'events.jsonl'), '--take', take.id,
    '--discovery-cache', path.join(stateRoot, 'discovery.json')];
  const child = worker = spawn(executable, args, { windowsHide: true, stdio: 'pipe', cwd: app.isPackaged ? path.dirname(executable) : root });
  let launchError = '';
  diagnostic('worker_start', { executable, folder, take: take.id, boss: session.boss_name });
  lastHeartbeat = Date.now();
  const lines = createInterface({ input: child.stdout });
  lines.on('line', line => {
    // Worker health is compact JSON; raw capture never travels through this UI queue.
    // Retain the most recent synced counts and actor tail for description matching.
    // A malformed worker message is visible, rather than interpreted as capture success.
    try {
      const message = JSON.parse(line) as Health;
      if (!['waiting', 'recording', 'stopped', 'error'].includes(message.state) || !Number.isFinite(message.actions)) throw Error('Invalid capture health message');
      if (message.state !== health.state) diagnostic('worker_state', { state: message.state, detail: message.detail, actions: message.actions });
      lastHeartbeat = Date.now(); health = message;
      Object.assign(take, { actions: message.actions, last_t: message.last_t, state: message.state });
      if (message.state === 'recording' && message.actions > 0 && !cueStarted) {
        cueStarted = true; window.webContents.send('cue', 'start');
      }
      broadcast();
    } catch (error) { failure(error); }
  });
  child.stderr.on('data', data => { errorText = (errorText + data.toString()).slice(-4000); });
  child.on('error', error => { launchError = error.message; failure(error); });
  child.stdin.on('error', error => { if (!stopPending) failure(error); });
  workerDone = new Promise(resolve => child.on('close', code => {
    // Process closure is the completion barrier for journal writes and ownership release.
    // Preserve error/zero-ID outcomes; never replace them with an unconditional success.
    // Earlier checkpoints remain recoverable even when the worker exits abnormally.
    worker = null; stopPending = false; take.ended_at = Date.now() / 1000;
    take.state = code === 0 ? 'stopped' : 'interrupted';
    if (code !== 0) health = { ...health, state: 'error', detail: `Capture interrupted. ${health.actions ? 'Earlier synced IDs remain. ' : ''}${launchError || errorText.trim().split(/\r?\n/).at(-1) || `Worker exit ${code}`}` };
    diagnostic('worker_exit', { code, take: take.id, actions: health.actions, launchError, stderr: errorText });
    if (cueStarted && !window.isDestroyed()) window.webContents.send('cue', 'stop');
    try { save(); } catch (error) { failure(error); }
    broadcast(); resolve();
  }));
  broadcast();
}

async function command(name: string, value: any): Promise<View> {
  // Restrict renderer requests to recorder operations rather than arbitrary files or executables.
  // Native folder dialogs supply paths; text/volume inputs receive explicit bounds.
  // Await writes and export completion before reporting their successful result.
  switch (name) {
    case 'state': return view();
    case 'context': settings.boss_draft = String(value || '').slice(0, 100); atomicJSON(settingsFile, settings); break;
    case 'context-commit': requireIdle(); commitContext(String(value || '').slice(0, 100)); diagnostic('encounter_selected', { boss: settings.boss_draft }); break;
    case 'bind-start': requireIdle(); bindingShortcut = true; if (!smoke) globalShortcut.unregister(settings.hotkey); break;
    case 'bind-cancel': if (bindingShortcut) setHotkey(settings.hotkey); break;
    case 'toggle': toggle(String(value || '')); break;
    case 'draft': {
      if (exporting) throw Error('Wait until the export finishes before editing.');
      const text = String(value.text || '');
      if (text.length > 20000) throw Error('Keep a description under 20,000 characters.');
      commitContext(String(value.boss || ''));
      if (!session) ({ folder, session } = createSession(settings.recordings_directory, settings.boss_draft!));
      if (value.editing_id && !session.annotations.some(note => note.id === value.editing_id)) throw Error('That description is no longer available for editing.');
      session.draft = { text, editing_id: value.editing_id || undefined }; save(); break;
    }
    case 'label': {
      if (!session || exporting) throw Error('Open a session before saving a description.');
      const text = String(value.text || '').trim();
      if (!text || text.length > 20000) throw Error('Write a description of 1–20,000 characters.');
      const old = value.id ? session.annotations.find(note => note.id === value.id) : undefined;
      if (value.id && !old) throw Error('That saved description no longer exists.');
      const take = session.takes.at(-1);
      const note = { id: old?.id || crypto.randomUUID(), text, take: old?.take || take?.id || '',
        end_t: old?.end_t ?? take?.last_t ?? 0, updated_at: Date.now() / 1000 };
      if (old) Object.assign(old, note); else session.annotations.push(note);
      session.draft = { text: '' }; save(); break;
    }
    case 'new': requireIdle(); save(); folder = null; session = null; settings.boss_draft = ''; health = { ...health, state: 'idle', actions: 0, tail: [], detail: 'Name the next encounter. Your previous session is saved.' }; save(); break;
    case 'open': {
      requireIdle(); save();
      const result = await pickFolders('Open a saved session');
      requireIdle();
      if (!result.canceled) { await restore(result.filePaths[0]); save(); }
      break;
    }
    case 'library': {
      requireIdle(); save();
      const result = await pickFolders('Choose recording library · existing sessions are preserved');
      requireIdle();
      if (!result.canceled) { fs.accessSync(result.filePaths[0], fs.constants.W_OK); settings.recordings_directory = result.filePaths[0]; save(); }
      break;
    }
    case 'settings': {
      const volume = Number(value.cue_volume);
      if (!Number.isFinite(volume) || volume < 0 || volume > 100) throw Error('Cue volume must be 0–100%.');
      if (value.hotkey !== undefined) setHotkey(String(value.hotkey));
      settings.cue_volume = Math.round(volume); settings.motion = value.motion !== false; save(); break;
    }
    case 'guide-read': settings.tutorial_version = 4; save(); break;
    case 'changelog-read': settings.changelog_seen = version; save(); break;
    case 'export': {
      requireIdle(); save();
      const picked = await pickFolders('Select sessions · Ctrl+A selects all · or select the entire library', true);
      requireIdle();
      if (picked.canceled) break;
      const selected = sessionFolders(picked.filePaths);
      const destination = path.join(app.getPath('downloads'), `Tanto-recordings-${new Date().toISOString().replace(/[:.]/g, '-')}.zip`);
      exporting = true; health = { ...health, state: 'exporting', detail: `Packing ${selected.length} sessions…` }; broadcast();
      try {
        await exportSessions(selected, destination, count => {
          // Report completed sessions, not a made-up byte percentage.
          // Keep the main window responsive while compression follows stream backpressure.
          // The .zip name appears only after a complete archive is synced and published.
          health.detail = `Packed ${count} of ${selected.length} sessions…`; broadcast();
        });
        health = { ...health, state: 'idle', detail: `Exported ${selected.length} sessions to Downloads: ${path.basename(destination)}` };
        shell.showItemInFolder(destination);
      } finally { exporting = false; }
      break;
    }
    default: throw Error('Unknown recorder command.');
  }
  broadcast(); return view();
}

async function pickFolders(title: string, multiple = false): Promise<Electron.OpenDialogReturnValue> {
  // The native picker temporarily owns the workflow; global hotkeys cannot start capture behind it.
  // Release ownership on both cancellation and failure, without changing the selected library.
  // Callers recheck capture/export state after the asynchronous dialog completes.
  dialogBusy = true;
  try { return await dialog.showOpenDialog(window, { title, defaultPath: settings.recordings_directory,
    properties: multiple ? ['openDirectory', 'multiSelections'] : ['openDirectory', 'createDirectory'] }); }
  finally { dialogBusy = false; }
}

async function closeRecorder(): Promise<void> {
  // Drain the renderer's latest draft before destroying it, including queued rapid typing.
  // Then wait for the independent capture worker to finish syncing its journal.
  // Failed draft persistence leaves the window open and permits another close attempt.
  closeRequested = true;
  try {
    await window.webContents.executeJavaScript('window.flushRecorderDraft()');
    save();
    if (worker) toggle(session?.boss_name || '');
    await workerDone;
    closing = true; window.close();
  } catch (error) { failure(error); }
  finally { closeRequested = false; }
}

async function smokeCheck(report: string): Promise<void> {
  // Exercise the actual local renderer with capture and global shortcuts disabled.
  // Save only this app's rendered page, never the desktop or any game window.
  // Check default-window layout, draft persistence and bundled assets before a release is published.
  const checks: Record<string, unknown> = {};
  const directory = path.dirname(report);
  fs.mkdirSync(directory, { recursive: true });
  try {
    await window.webContents.executeJavaScript(`new Promise((resolve,reject)=>{let tries=0;function ready(){if(document.getElementById('version').textContent)resolve(true);else if(++tries>300)reject(Error('Renderer did not initialize'));else requestAnimationFrame(ready)}ready()})`);
    for (const [width, height] of [[1080, 820], [960, 740]]) {
      window.setSize(width, height);
      for (const page of ['record', 'settings', 'guide']) {
        await window.webContents.executeJavaScript(`document.querySelector('[data-tab="${page}"]').click(); new Promise(resolve=>setTimeout(resolve,300))`);
        checks[`${page}-${width}`] = await window.webContents.executeJavaScript(`({horizontal:document.documentElement.scrollWidth<=innerWidth, vertical:document.documentElement.scrollHeight<=innerHeight, width:innerWidth,height:innerHeight})`);
        if (width === 960) fs.writeFileSync(path.join(directory, `ui-${page}.png`), (await window.webContents.capturePage()).toPNG());
      }
    }
    for (let index = 1; index < 5; index++) {
      await window.webContents.executeJavaScript(`document.getElementById('guide-next').click()`);
      checks[`guide-${index + 1}`] = await window.webContents.executeJavaScript(`({horizontal:document.documentElement.scrollWidth<=innerWidth,vertical:document.documentElement.scrollHeight<=innerHeight})`);
    }
    await command('draft', { boss: 'Offline UI check', text: 'Two slashes. High priority.' });
    const saved = readJSON(path.join(folder!, 'encounter.json'));
    checks.draft_saved = saved.draft.text === 'Two slashes. High priority.';
    await command('label', { text: saved.draft.text });
    checks.description_saved = readJSON(path.join(folder!, 'encounter.json')).annotations[0].text === saved.draft.text;
    const previousFolder = folder!;
    await window.webContents.executeJavaScript(`(async()=>{
      const input=document.getElementById('boss'); input.value='Second offline encounter';
      input.dispatchEvent(new Event('input')); input.dispatchEvent(new Event('change'));
      await window.flushRecorderDraft();
    })()`);
    checks.boss_context = folder === null && settings.boss_draft === 'Second offline encounter' &&
      await window.webContents.executeJavaScript(`document.getElementById('boss').value==='Second offline encounter' && document.getElementById('session-name').textContent.includes('Second offline encounter')`);
    checks.prior_description_preserved = readJSON(path.join(previousFolder, 'encounter.json')).annotations[0].text === saved.draft.text;
    checks.assets = ['background.png', 'start.wav', 'stop.wav'].every(name => fs.existsSync(path.join(root, 'src/assets', name)));
    checks.worker = !app.isPackaged || fs.existsSync(path.join(process.resourcesPath, 'worker/TantoCapture.exe'));
    if (app.isPackaged) {
      const executable = path.join(process.resourcesPath, 'worker/TantoCapture.exe');
      const result = spawnSync(executable, ['--help'], { cwd: path.dirname(executable), windowsHide: true, encoding: 'utf8', timeout: 20000 });
      checks.worker_startup = result.status === 0 && result.stdout.includes('--journal');
    }
    await window.webContents.executeJavaScript(`document.getElementById('updates').click()`);
    fs.writeFileSync(path.join(directory, 'ui-updates.png'), (await window.webContents.capturePage()).toPNG());
    const passed = Object.values(checks).every(value => typeof value === 'object' ? (value as any).horizontal && (value as any).vertical : value === true);
    const display = screen.getDisplayMatching(window.getBounds());
    atomicJSON(report, { passed, capture_disabled: true, display: { bounds: display.bounds, scale: display.scaleFactor, primary: display.id === screen.getPrimaryDisplay().id }, checks });
    closing = true; app.exit(passed ? 0 : 1);
  } catch (error) {
    atomicJSON(report, { passed: false, error: String(error), checks }); closing = true; app.exit(1);
  }
}

async function createWindow(): Promise<void> {
  // Prefer the user's secondary 1440p display, respecting its actual work area and scaling.
  // A sandboxed local renderer has no Node APIs, external navigation or permission prompts.
  // Smooth CSS animation is independent of the sampler and pauses with reduced motion.
  const displays = screen.getAllDisplays();
  const display = process.argv.includes('--second-monitor') || smoke ? displays.find(d => d.id !== screen.getPrimaryDisplay().id && Math.round(d.size.height * d.scaleFactor) === 1440) || displays.find(d => d.id !== screen.getPrimaryDisplay().id) || screen.getPrimaryDisplay() : screen.getPrimaryDisplay();
  const area = display.workArea;
  const width = Math.min(1080, area.width), height = Math.min(820, area.height);
  window = new BrowserWindow({ title: `Tanto Recorder · ${version}`, width, height,
    x: Math.round(area.x + (area.width - width) / 2), y: Math.round(area.y + (area.height - height) / 2),
    minWidth: 680, minHeight: 600, backgroundColor: '#111619', autoHideMenuBar: true, show: !automated && !smoke,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true,
      nodeIntegration: false, sandbox: true, backgroundThrottling: !automated && !smoke,
      autoplayPolicy: 'no-user-gesture-required' } });
  Menu.setApplicationMenu(null);
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  window.webContents.on('render-process-gone', () => { if (!closing) void window.loadFile(path.join(__dirname, 'index.html')); });
  window.on('close', event => {
    // Closing waits for the active worker's final sync; export cannot be interrupted here.
    // Drafts reach the main process as they change and are saved before destruction.
    // A failed save leaves the window open with the error instead of discarding work.
    if (closing) return;
    event.preventDefault();
    if (closeRequested) return;
    if (exporting) { failure('Wait for ZIP export to finish before closing.'); return; }
    void closeRecorder();
  });
  await window.loadFile(path.join(__dirname, 'index.html'));
  if (smoke) {
    console.log(JSON.stringify({ ui_ready: true, display: display.bounds, scale: display.scaleFactor }));
    const report = process.argv[process.argv.indexOf('--ui-smoke') + 1];
    if (report && !report.startsWith('--')) await smokeCheck(report);
  }
}

if (!app.requestSingleInstanceLock()) {
  diagnostic('existing_instance', { resources: process.resourcesPath });
  app.quit();
}
else app.whenReady().then(async () => {
  // Restore saved preferences and drafts without creating a new Downloads recording folder.
  // Fresh installs use 40% start/stop cues; explicit existing volume choices survive upgrades.
  // Hotkey and worker failures are visible while the rest of the application remains usable.
  let startupError: unknown;
  diagnostic('startup', { packaged: app.isPackaged, resources: process.resourcesPath });
  let old: any = {};
  try { old = readJSON(settingsFile) || {}; } catch (error) { startupError = error; }
  settings = { ...old, recordings_directory: old.recordings_directory || path.join(stateRoot, 'Recordings'),
    cue_volume: Number.isFinite(old.cue_volume) ? Math.max(0, Math.min(100, old.cue_volume)) : 40,
    hotkey: old.hotkey || 'F8', tutorial_version: old.tutorial_version || 0, motion: old.motion !== false };
  if (settings.last_session && fs.existsSync(settings.last_session)) {
    try { await restore(settings.last_session); settings.boss_draft = old.boss_draft ?? settings.boss_draft; } catch (error) { startupError = error; }
  }
  ipcMain.handle('recorder', async (event, name: string, value: unknown) => {
    // Only the application's own top-level local page may request recorder operations.
    // Rejected requests return a plain visible error without granting a general IPC channel.
    // Capture has its own process, so UI request latency cannot block memory sampling.
    if (event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame) throw Error('Unknown UI sender');
    try { return await command(name, value); } catch (error) { failure(error); throw error; }
  });
  await createWindow();
  if (automated) {
    if (startupError) throw startupError;
    await timedCapture(); return;
  }
  try { setHotkey(settings.hotkey); } catch (error) { failure(error); }
  if (startupError) failure(startupError);
  setInterval(() => {
    // Missing heartbeats are a visible capture fault, not proof that recording still works.
    // Keep existing evidence and let the user Stop; do not silently start duplicate writers.
    // This watchdog is independent of the renderer and of the sampler's discovery thread.
    if (worker && stopPending && Date.now() - stopRequestedAt > 8000) {
      health = { ...health, state: 'stalled', detail: 'The worker is not responding to Stop. Force stop may lose the unfinished checkpoint; earlier synced IDs remain.' }; broadcast();
    } else if (worker && Date.now() - lastHeartbeat > 8000 && health.state !== 'error') failure('Capture health has stopped updating. Stop and restart this take; earlier saved IDs remain.');
  }, 2000).unref();
}).catch(error => {
  // Automated runs report startup failures to their caller without covering the game with a dialog.
  // Interactive launches keep the visible error explaining why Recorder could not open.
  // A failed run exits nonzero and never reports a successful recording.
  if (automated) {
    if (captureReport) atomicJSON(captureReport, { passed: false, error: String(error) });
    console.error(String(error)); app.exit(1);
  } else { dialog.showErrorBox('Tanto Recorder could not open', String(error)); app.quit(); }
});
app.on('second-instance', () => { if (window && !smoke && !automated) { window.restore(); window.focus(); } });
app.on('will-quit', () => globalShortcut.unregisterAll());
app.on('window-all-closed', () => app.quit());
