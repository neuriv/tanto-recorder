import type { View } from './types';

let state: View;
let page = 'record';
let guidePage = 0;
let editing: string | null = null;
let binding = false;
let initialized = false;
let activeAudio: HTMLAudioElement | null = null;
let noteSaving = false;
let draftQueue: Promise<unknown> = Promise.resolve();
const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const guides = [
  { title: 'A move, in three steps.', lead: 'Recorder collects action IDs for later review. You play Nioh normally; it never changes the game.',
    steps: [['Name the encounter', 'Choose a suggested boss or type a custom name. The name labels your session; capture includes every readable actor.'], ['Start before the move', 'Press your recording shortcut or Start. Wait for the saved-ID counter to increase before relying on the recording.'], ['Stop just after the move', 'The last few action IDs are the starting point for matching your description. A short ending is easier to review.']] },
  { title: 'Know what was saved.', lead: 'A running application is not the same as a working capture. Watch the evidence, not just the timer.',
    steps: [['Waiting means waiting', 'A waiting or red status has no promise of useful data. Check Nioh is running and the supported game build is in use.'], ['Saved IDs are the signal', 'The counter shows action observations synced to disk. Repeated observations are not necessarily separate hits.'], ['Long sessions are welcome', 'Recording stays in an append-only journal. Loading screens and missing actors are logged as gaps; earlier data remains.']] },
  { title: 'Put the ending into words.', lead: 'After Stop, describe the movement you wanted. The description stays beside that take and its ending time.',
    steps: [['Be concrete', 'Describe hit count, direction, movement and follow-up. For example: two slashes, a leap, then an overhead cut.'], ['Add review priority', 'Write Low priority, Mid priority or High priority. Priority orders our review; it is separate from Low, Mid and High stances.'], ['Save and refine', 'Draft text autosaves. Ctrl+S saves a description; select a saved description to edit it. Notes are retained even if no IDs were captured.']] },
  { title: 'Keep your old recordings.', lead: 'Choose your library, bind a shortcut and adjust cue volume in Settings. Upgrades preserve your recordings.',
    steps: [['Choose your library', 'Settings → Choose folder can point at an older Tanto Recordings directory. Existing sessions are preserved.'], ['Open or start fresh', 'Open restores a saved session. Each Start adds a take; New prepares a separate encounter without deleting the old one.'], ['Check interruptions', 'On reopening a session, Recorder reads its journal to recover saved counts. A interrupted or empty take needs review, not assumed success.']] },
  { title: 'One ZIP. Everything selected.', lead: 'Export all the sessions you want to share, including their raw action IDs, boss labels and descriptions.',
    steps: [['Finish recording first', 'Stop and wait for the final save. Export takes a stable snapshot of the selected sessions.'], ['Select folders in Explorer', 'Choose Export ZIP. Ctrl or Shift selects several folders; Ctrl+A selects all. You can also select the parent library.'], ['Send the ZIP from Downloads', 'The completed .zip goes directly into Downloads. It includes draft-only sessions too, so failed captures do not silently discard your notes.']] }
];

async function call(name: string, value?: unknown): Promise<void> {
  // All effects go through the fixed preload bridge; this page cannot read files or spawn workers.
  // Main-process failures remain readable without injecting strings as HTML.
  // Ordinary rejected operations leave the rest of the recorder controls usable.
  try { render(await window.recorder.call(name, value)); }
  catch (error) { $('footer-status').textContent = String(error).replace(/^Error: Error invoking remote method 'recorder': Error: /, ''); }
}

function tab(name: string): void {
  // Keep recording controls visible above every page, including the tutorial.
  // Switch existing DOM sections rather than rebuilding text editors during capture.
  // The active underline and keyboard focus provide orientation without solid tab backgrounds.
  page = name;
  document.body.dataset.page = name;
  for (const element of document.querySelectorAll<HTMLElement>('.page')) element.classList.toggle('hidden', element.id !== name);
  for (const button of document.querySelectorAll<HTMLElement>('[data-tab]')) button.classList.toggle('active', button.dataset.tab === name);
  if (name === 'guide') showGuide();
}

function showGuide(): void {
  // Render one compact tutorial page so it fits the ordinary application window.
  // Text nodes keep tutorial content independent of HTML parsing and layout injection.
  // Five topics retain capture, diagnosis, description, restoration and export instructions.
  const item = guides[guidePage];
  $('guide-number').textContent = `QUICK GUIDE · 0${guidePage + 1} / 05`;
  $('guide-title').textContent = item.title; $('guide-lead').textContent = item.lead;
  $('guide-steps').replaceChildren(...item.steps.map(([title, description], index) => {
    // Each numbered step has one short title and a concrete explanation.
    // Build nodes directly so changing text cannot introduce interactive markup.
    // CSS controls common spacing rather than position calculations per page.
    const row = document.createElement('div'); row.className = 'guide-step';
    const number = document.createElement('span'); number.textContent = `0${index + 1}`;
    const body = document.createElement('div'), heading = document.createElement('h3'), text = document.createElement('p');
    heading.textContent = title; text.textContent = description; body.append(heading, text); row.append(number, body); return row;
  }));
  $('guide-dots').replaceChildren(...guides.map((_item, index) => {
    // Dots are accessible page selectors, with no hidden dependence on pointer position.
    // Their labels announce the target page to keyboard and screen-reader users.
    // Keep selection local; acknowledging the final page persists tutorial completion.
    const button = document.createElement('button'); button.ariaLabel = `Guide page ${index + 1}`;
    button.classList.toggle('active', index === guidePage); button.onclick = () => { guidePage = index; showGuide(); }; return button;
  }));
  $<HTMLButtonElement>('guide-prev').disabled = guidePage === 0;
  $('guide-next').textContent = guidePage === guides.length - 1 ? 'Ready to record →' : 'Next →';
}

function notes(): void {
  // Show saved descriptions as text-first selectable rows, keeping the complete wording.
  // Editing retains the original take/time boundary instead of reassigning it to a new recording.
  // A missing take is explicitly a note without captured evidence.
  const labels = state.session?.annotations || [];
  $('notes-count').textContent = String(labels.length);
  if (!labels.length) { const p = document.createElement('p'); p.className = 'empty'; p.textContent = 'Record. Describe. Repeat.'; $('notes').replaceChildren(p); return; }
  $('notes').replaceChildren(...labels.slice().reverse().map(note => {
    // Render contributor text with textContent, never as executable HTML.
    // Keep long descriptions wrapping while the sampled endpoint remains legible.
    // Selecting one row changes the editor only; Save performs the metadata write.
    const button = document.createElement('button'); button.className = 'note';
    const text = document.createElement('span'), time = document.createElement('small');
    text.textContent = note.text; time.textContent = note.take ? `${note.end_t.toFixed(1)}s · Edit` : 'Note only · Edit';
    button.append(text, time); button.onclick = () => { editing = note.id; $<HTMLTextAreaElement>('description').value = note.text; $('draft-state').textContent = '· editing saved description'; $<HTMLTextAreaElement>('description').focus(); }; return button;
  }));
}

function render(value: View): void {
  // Health updates touch counters and status without resetting the user's active text selection.
  // First load restores the draft and shows the updated tutorial once; help remains reopenable.
  // State-specific wording distinguishes waiting, saved evidence, faults and export progress.
  const previous = state;
  state = value;
  if (activeAudio) activeAudio.volume = state.settings.cue_volume / 100;
  const changedSession = previous?.folder !== state.folder;
  document.body.classList.toggle('still', !state.settings.motion);
  $('version').textContent = state.version;
  $('key').textContent = state.settings.hotkey;
  $('state').textContent = state.health.state.toUpperCase();
  $('dot').className = `dot ${state.health.state}`;
  $('headline').textContent = ({ idle: 'Capture the last move.', waiting: 'Waiting for action IDs.', recording: 'Action IDs are being saved.', stopped: state.health.actions ? 'The ending is yours to describe.' : 'No action IDs captured.', stopping: 'Saving the last observations.', error: 'Capture needs attention.', warning: 'Check the recovered session.', exporting: 'Packing your sessions.' } as Record<string, string>)[state.health.state] || 'Ready when you are.';
  $('detail').textContent = state.health.detail;
  $('count').textContent = state.health.actions.toLocaleString();
  $('toggle-label').textContent = state.running ? (state.health.state === 'stalled' ? 'Force stop' : state.health.state === 'stopping' ? 'Finishing…' : 'Stop recording') : 'Start recording';
  $('capture-symbol').textContent = state.running ? '■' : '●';
  $('toggle').classList.toggle('recording', state.running);
  $<HTMLButtonElement>('toggle').disabled = state.exporting || state.health.state === 'stopping';
  $<HTMLInputElement>('boss').disabled = state.running || state.exporting;
  for (const id of ['new', 'open', 'export', 'library', 'bind']) $<HTMLButtonElement>(id).disabled = state.running || state.exporting;
  $<HTMLButtonElement>('save-note').disabled = state.exporting || noteSaving;
  $<HTMLTextAreaElement>('description').disabled = state.exporting || noteSaving;
  const nextBoss = state.settings.boss_draft || '';
  $('session-name').textContent = state.session && nextBoss.trim() === state.session.boss_name ?
    `${state.session.boss_name} · ${state.session.takes.length} takes` : nextBoss ? `${nextBoss} · next encounter` : 'A session keeps your recordings and descriptions together.';
  $('library-path').textContent = state.settings.recordings_directory;
  $('volume-label').textContent = `${state.settings.cue_volume}%`;
  if (document.activeElement !== $('volume')) $<HTMLInputElement>('volume').value = String(state.settings.cue_volume);
  if (!binding) $('bind').textContent = state.settings.hotkey;
  $<HTMLInputElement>('motion').checked = state.settings.motion;
  $('footer-status').textContent = state.exporting ? 'Exporting…' : state.running ? `${Math.floor(state.health.last_t)}s · ${state.health.actors || 0} readable actors` : 'Saved locally';
  $('tail').replaceChildren(...state.health.tail.slice(-5).map(item => {
    // Show a bounded tail of observations while the complete journal remains on disk.
    // The actor address is context in the tooltip, not a permanent move identity.
    // Consecutive equal IDs may be repeated samples; this UI does not label them distinct attacks.
    const span = document.createElement('span'); span.textContent = item.id; span.title = `${item.t.toFixed(2)}s · actor ${item.actor}`; return span;
  }));
  if (!state.health.tail.length) $('tail').textContent = 'IDs appear here only after capture begins.';
  if (!initialized || changedSession) {
    if (document.activeElement !== $('boss')) $<HTMLInputElement>('boss').value = state.settings.boss_draft ?? state.session?.boss_name ?? '';
    if (document.activeElement !== $('description')) $<HTMLTextAreaElement>('description').value = state.session?.draft.text || '';
    editing = state.session?.draft.editing_id || null;
    $('draft-state').textContent = editing ? '· edit draft restored' : '· autosaved';
  }
  if (!initialized || JSON.stringify(previous?.session?.annotations) !== JSON.stringify(state.session?.annotations)) notes();
  if (!initialized) {
    $('bosses').replaceChildren(...state.bosses.map(name => { const option = document.createElement('option'); option.value = name; return option; }));
    if (state.settings.tutorial_version !== 4) tab('guide');
    else if (state.settings.changelog_seen !== state.version) showUpdates();
    initialized = true;
  }
}

function showUpdates(): void {
  // Display release notes sourced from the shipped changelog, not a fabricated update feed.
  // Use the same artwork in the banner and keep the dialog short and reopenable.
  // Showing notes does not download or install software.
  const section = state.changelog.split(`## ${state.version}`)[1]?.split('\n## ')[0]?.trim() || 'Development build. Release notes are not published yet.';
  $('update-version').textContent = `VERSION ${state.version}`; $('release-notes').textContent = section;
  $<HTMLDialogElement>('changelog').showModal();
}

function cue(name: 'start' | 'stop'): void {
  // Play the user's bundled WAV directly with application-local volume.
  // Volume zero mutes the cue without changing Windows or Nioh audio settings.
  // The start cue is requested only after the worker confirms synced action evidence.
  if (activeAudio) activeAudio.pause();
  if (state.settings.cue_volume === 0) return;
  activeAudio = new Audio(`../src/assets/${name}.wav`); activeAudio.volume = state.settings.cue_volume / 100;
  void activeAudio.play().catch(() => { $('footer-status').textContent = 'Sound unavailable; use the visible capture status.'; });
}

async function saveNote(): Promise<void> {
  // Finish pending draft saves before committing the description's explicit take endpoint.
  // Editing a prior description preserves its evidence boundary.
  // Clear the editor only after main confirms the metadata write succeeded.
  if (noteSaving) return;
  noteSaving = true; render(state);
  try {
    await draftQueue;
    const text = $<HTMLTextAreaElement>('description').value;
    render(await window.recorder.call('label', { text, id: editing }));
    editing = null; $<HTMLTextAreaElement>('description').value = ''; $('draft-state').textContent = '· saved';
  } catch (error) { $('draft-state').textContent = `· save failed: ${String(error)}`; }
  finally { noteSaving = false; render(state); }
}

for (const button of document.querySelectorAll<HTMLElement>('[data-tab]')) button.onclick = () => tab(button.dataset.tab!);
$('toggle').onclick = () => { void draftQueue.then(() => call('toggle', $<HTMLInputElement>('boss').value)); };
for (const name of ['new', 'open', 'export', 'library']) $(name).onclick = () => { void draftQueue.then(() => call(name)); };
$('boss').oninput = () => { void call('context', $<HTMLInputElement>('boss').value); };
$('boss').onchange = () => {
  // Commit the encounter once editing finishes, rather than making folders for every keystroke.
  // Preserve queued notes under their original boss before switching to a fresh encounter.
  // Start waits on the same queue, so mouse and shortcut paths receive consistent context.
  const boss = $<HTMLInputElement>('boss').value;
  draftQueue = draftQueue.then(() => call('context-commit', boss));
};
$('description').oninput = () => {
  // Queue draft writes in typing order; each acknowledgement follows an atomic disk save.
  // Saved-description edits remain a draft until Ctrl+S updates that selected annotation.
  // A failed save is shown beside the editor instead of pretending autosave succeeded.
  const text = $<HTMLTextAreaElement>('description').value, boss = $<HTMLInputElement>('boss').value;
  $('draft-state').textContent = '· saving…';
  const editing_id = editing;
  draftQueue = draftQueue.then(() => window.recorder.call('draft', { boss, text, editing_id })).then(value => {
    render(value); $('draft-state').textContent = editing ? '· edit draft saved' : '· draft saved';
  }).catch(error => { $('draft-state').textContent = `· save failed: ${String(error)}`; });
};
$('save-note').onclick = () => { void saveNote(); };
$('updates').onclick = showUpdates;
for (const id of ['close-updates', 'dismiss-updates']) $(id).onclick = () => { $<HTMLDialogElement>('changelog').close(); void call('changelog-read'); };
$('changelog').addEventListener('cancel', () => { void call('changelog-read'); });
$('guide-prev').onclick = () => { guidePage = Math.max(0, guidePage - 1); showGuide(); };
$('guide-next').onclick = () => { if (guidePage === guides.length - 1) { void call('guide-read'); tab('record'); } else { guidePage++; showGuide(); } };
$('bind').onclick = async () => { try { await window.recorder.call('bind-start'); binding = true; $('bind').textContent = 'Press shortcut…'; $('bind').focus(); } catch (error) { $('footer-status').textContent = String(error); } };
for (const id of ['volume', 'motion']) $(id).onchange = () => { void call('settings', { cue_volume: Number($<HTMLInputElement>('volume').value), motion: $<HTMLInputElement>('motion').checked }); };
$('volume').oninput = () => { $('volume-label').textContent = `${$<HTMLInputElement>('volume').value}%`; };
$('preview-sound').onclick = () => cue('start');
document.addEventListener('keydown', event => {
  // Local shortcuts control Recorder only; Electron owns the separate global capture shortcut.
  // Binding captures one keyboard chord and prevents normal form shortcuts from firing.
  // F1 always reopens the guide; Ctrl+S saves the description without a browser dialog.
  if (binding) {
    event.preventDefault();
    if (['Control', 'Shift', 'Alt', 'Meta'].includes(event.key)) return;
    binding = false;
    if (event.key === 'Escape') { void call('bind-cancel'); return; }
    const key = event.key.length === 1 ? event.key.toUpperCase() : event.key;
    const hotkey = [...(event.ctrlKey ? ['Control'] : []), ...(event.altKey ? ['Alt'] : []), ...(event.shiftKey ? ['Shift'] : []), key].join('+');
    void call('settings', { ...state.settings, hotkey }).then(() => call('bind-cancel')); return;
  }
  if (event.key === 'F1') { event.preventDefault(); tab('guide'); }
  if (event.ctrlKey && event.key.toLowerCase() === 's') { event.preventDefault(); void saveNote(); }
});
window.flushRecorderDraft = async () => {
  // Closing waits for queued writes, then sends the current editor once more as the final draft.
  // This covers keystrokes typed while earlier fsync acknowledgements were still pending.
  // Rejecting the final save keeps the window open; an empty untouched form needs no session.
  await draftQueue;
  const text = $<HTMLTextAreaElement>('description').value;
  if (state.session || text) await window.recorder.call('draft', { boss: $<HTMLInputElement>('boss').value, text, editing_id: editing });
};
window.addEventListener('blur', () => { if (binding) { binding = false; void call('bind-cancel'); } });
window.recorder.onState(render); window.recorder.onCue(cue); void call('state');
