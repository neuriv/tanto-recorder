import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import type { Note, Session } from './types';

export function atomicJSON(file: string, value: unknown): void {
  // A description save replaces one complete metadata document, never half a JSON file.
  // Sync the temporary file before rename; failed writes preserve the previous version.
  // Temporary names are unique and removed after failure, without touching raw recordings.
  const temporary = `${file}.${crypto.randomUUID()}.tmp`;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  let fd: number | undefined;
  try {
    fd = fs.openSync(temporary, 'wx');
    fs.writeFileSync(fd, JSON.stringify(value, null, 2) + '\n');
    fs.fsyncSync(fd); fs.closeSync(fd); fd = undefined;
    fs.renameSync(temporary, file);
  } finally {
    if (fd !== undefined) fs.closeSync(fd);
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
}

export function readJSON(file: string): any {
  // Parse a specific saved document; malformed existing data is an actionable error.
  // Only absence yields null, so corruption cannot silently reset the user's work.
  // Callers decide whether a missing file is optional or a broken session.
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')) : null;
}

export function readSession(folder: string): Session {
  // Read new two-file sessions and old session directories without rewriting their evidence.
  // Fold old label revisions by ID and retain the old draft until the user edits it.
  // Unknown fields in the old manifest survive the eventual metadata replacement.
  const original = readJSON(path.join(folder, 'encounter.json'));
  if (!original?.recording_id || !original.boss_id) throw Error('Choose a saved session folder containing encounter.json.');
  if (original.schema_version === 2) return original;
  const notes = new Map<string, Note>();
  const labels = path.join(folder, 'labels.jsonl');
  if (fs.existsSync(labels)) for (const [index, line] of fs.readFileSync(labels, 'utf8').split(/\r?\n/).entries()) {
    if (!line.trim()) continue;
    const row = JSON.parse(line);
    const id = row.label_id || row.annotation_id || row.id || `legacy-${index}`;
    notes.set(id, { id, text: row.label || row.text || '', take: row.take || '', end_t: row.end_t || 0, updated_at: row.updated_at || 0 });
  }
  const draft = readJSON(path.join(folder, 'draft.json'));
  return { ...original, schema_version: 2, boss_name: original.boss_name || original.boss_id,
    draft: { text: draft?.text || '' }, annotations: [...notes.values()], takes: [] };
}

export function createSession(library: string, boss: string): { folder: string; session: Session } {
  // A fresh encounter gets a unique directory; an existing library is never cleared.
  // Human boss wording is retained, while a hash creates a safe filesystem identity.
  // Boss labeling never controls which actors the read-only worker is allowed to observe.
  const name = boss.trim().replace(/\s+/g, ' ');
  if (!name || name.length > 100) throw Error('Enter a boss or enemy name (1–100 characters).');
  const id = crypto.randomUUID();
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'encounter';
  const folder = path.join(library, `${slug}-${Date.now()}-${id.slice(0, 6)}`);
  const session: Session = { schema_version: 2, recording_id: id,
    boss_id: 'encounter_' + crypto.createHash('sha256').update(name.toLowerCase()).digest('hex').slice(0, 16),
    boss_name: name, created_at: Date.now() / 1000, draft: { text: '' }, annotations: [], takes: [] };
  atomicJSON(path.join(folder, 'encounter.json'), session);
  return { folder, session };
}
