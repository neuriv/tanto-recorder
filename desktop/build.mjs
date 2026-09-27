// Compile the small desktop shell without a development server or UI framework.
// Electron remains external to main/preload; renderer receives no Node capability.
// This builds JavaScript only; EXE releases must enter through Engine's release gate.
import { build } from 'esbuild';
import { mkdir, copyFile } from 'node:fs/promises';
await mkdir('desktop-dist', { recursive: true });
await build({ entryPoints: ['desktop/main.ts', 'desktop/preload.ts'], outdir: 'desktop-dist',
  outExtension: { '.js': '.cjs' }, bundle: true, platform: 'node', target: 'node22', external: ['electron'] });
await build({ entryPoints: ['desktop/renderer.ts'], outfile: 'desktop-dist/renderer.js',
  bundle: true, platform: 'browser', target: 'chrome130' });
await copyFile('desktop/index.html', 'desktop-dist/index.html');
await copyFile('desktop/style.css', 'desktop-dist/style.css');
