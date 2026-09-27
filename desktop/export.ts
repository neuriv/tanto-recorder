import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { pipeline } from 'node:stream/promises';
import { Transform, Readable } from 'node:stream';
import { ZipFile } from 'yazl';
import { readJSON } from './storage';

export function sessionFolders(selected: string[]): string[] {
  // Accept individual sessions or their parent library, including Ctrl+A folder selections.
  // Deduplicate resolved session paths; folder names alone are not unique identities.
  // Empty sessions remain valid exports because their draft notes may be the only surviving evidence.
  const result = new Set<string>();
  for (const folder of selected) {
    if (fs.existsSync(path.join(folder, 'encounter.json'))) result.add(fs.realpathSync(folder));
    else for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
      if (entry.isDirectory() && !entry.isSymbolicLink() && fs.existsSync(path.join(folder, entry.name, 'encounter.json')))
        result.add(fs.realpathSync(path.join(folder, entry.name)));
    }
  }
  if (!result.size) throw Error('No saved session folders were found in the selection.');
  return [...result];
}

async function* filesUnder(folder: string, relative = ''): AsyncGenerator<string> {
  // Walk actual files without following links outside the selected session.
  // Preserve drafts, saved labels and legacy raw takes instead of guessing a short allowlist.
  // Skip only transient lock/temp files; their contents are not recording evidence.
  for (const entry of await fsp.readdir(path.join(folder, relative), { withFileTypes: true })) {
    const name = path.join(relative, entry.name);
    if (entry.isSymbolicLink()) throw Error(`Session contains a symbolic link: ${name}`);
    if (entry.isDirectory()) yield* filesUnder(folder, name);
    else if (entry.isFile() && !entry.name.endsWith('.tmp') && entry.name !== 'recorder.lock' && entry.name !== 'STOP') yield name;
  }
}

export async function exportSessions(folders: string[], destination: string,
  progress: (count: number) => void): Promise<void> {
  // Stream every selected session into one ZIP64-capable archive directly in Downloads.
  // Hash the same bytes entering compression; memory usage does not scale with recording duration.
  // Publish the .zip only after the archive closes and syncs; failure removes only our .partial file.
  if (fs.existsSync(destination)) throw Error('The export filename already exists.');
  const temporary = destination + '.partial';
  const zip = new ZipFile();
  const manifest = { schema_version: 2, kind: 'tanto_session_archive',
    sessions: [] as { path: string; recording_id: string; boss_name: string }[],
    files: [] as { path: string; size: number; sha256: string }[] };
  const output = fs.createWriteStream(temporary, { flags: 'wx' });
  const abort = new AbortController();
  zip.on('error', error => (zip.outputStream as Readable).destroy(error));
  const completed = pipeline(zip.outputStream, output);
  // Observe errors immediately while entry enumeration awaits filesystem reads.
  let writeError: Error | undefined;
  void completed.catch(error => { writeError = error; abort.abort(error); });
  try {
    for (const [index, folder] of folders.entries()) {
      const encounter = readJSON(path.join(folder, 'encounter.json'));
      if (!encounter?.recording_id) throw Error(`Invalid session: ${path.basename(folder)}`);
      const prefix = `sessions/${String(index + 1).padStart(4, '0')}-${path.basename(folder)}`;
      manifest.sessions.push({ path: prefix, recording_id: encounter.recording_id, boss_name: encounter.boss_name || encounter.boss_id });
      for await (const relative of filesUnder(folder)) {
        if (writeError) throw writeError;
        const source = path.join(folder, relative);
        const before = await fsp.stat(source);
        const entry = { path: `${prefix}/${relative.split(path.sep).join('/')}`, size: 0, sha256: '' };
        const hash = crypto.createHash('sha256');
        const stream = new Transform({ transform(chunk, _encoding, callback) {
          // Count and hash each bounded chunk before it enters the ZIP compressor.
          // Passing the original bytes onward keeps the manifest tied to exported content.
          // Node stream backpressure prevents a large take from filling process memory.
          hash.update(chunk); entry.size += chunk.length; callback(null, chunk);
        } });
        zip.addReadStream(stream, entry.path, { mtime: before.mtime });
        await pipeline(fs.createReadStream(source), stream, { signal: abort.signal });
        const after = await fsp.stat(source);
        if (before.size !== after.size || before.mtimeMs !== after.mtimeMs) throw Error('A selected session changed during export. Stop recording and try again.');
        entry.sha256 = hash.digest('hex'); manifest.files.push(entry);
      }
      progress(index + 1);
    }
    zip.addBuffer(Buffer.from(JSON.stringify(manifest, null, 2)), 'manifest.json');
    zip.end(); await completed;
    const handle = await fsp.open(temporary, 'r+');
    try { await handle.sync(); } finally { await handle.close(); }
    await fsp.rename(temporary, destination);
  } catch (error) {
    (zip.outputStream as Readable).destroy(); output.destroy();
    await completed.catch(() => undefined);
    await fsp.rm(temporary, { force: true });
    throw writeError || error;
  }
}
