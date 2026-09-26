"""Contributor UI. Recording never controls the game or loads the mod runtime."""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import zipfile

from encounter_recording import BOSSES, annotate_recent, record_encounter


def export_capture(folder, destination):
    # Share only completed capture data and labels, never developer state or personal paths.
    # Hash the exact exported bytes and include a literal-text CSV for ordinary spreadsheet apps.
    # Keep raw takes because human descriptions do not establish exact move boundaries.
    folder, destination = Path(folder), Path(destination)
    manifest = json.loads((folder/'encounter.json').read_text(encoding='utf8'))
    files = sorted(folder.glob('take-*/events.jsonl'))
    if (folder/'labels.jsonl').exists(): files.append(folder/'labels.jsonl')
    if not files: raise ValueError('No recorded data is available to export.')
    summary = io.StringIO(newline=''); writer = csv.writer(summary)
    writer.writerow(['Boss','Take','Sampled time','Description','Timing confidence'])
    labels = folder/'labels.jsonl'
    if labels.exists():
        for line in labels.read_text(encoding='utf8').splitlines():
            label = json.loads(line)
            text = label.get('label','')
            if text.startswith(('=','+','-','@')): text = "'"+text
            writer.writerow([manifest['boss_id'],label.get('take',''),label.get('last_recorded_t',''),text,'User annotation; boundary unverified'])
    export = dict(schema_version=1, kind='tanto_recording', boss_id=manifest['boss_id'],
                  recording_id=manifest['recording_id'], created_at=manifest['created_at'], files=[])
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            data = path.read_bytes(); name = path.relative_to(folder).as_posix()
            archive.writestr(name,data)
            export['files'].append(dict(path=name,sha256=hashlib.sha256(data).hexdigest(),size=len(data)))
        archive.writestr('manifest.json',json.dumps(export,indent=2))
        archive.writestr('Descriptions.csv',summary.getvalue().encode('utf-8-sig'))
    return destination


class Recorder:
    def __init__(self, root):
        # Present task language instead of native action identifiers.
        # Run discovery/capture on a worker while Tk owns all widgets.
        # Keep Stop cooperative so the active take is flushed before export.
        self.root=root; self.thread=None; self.folder=None; self.stop=threading.Event(); self.latest={}
        root.title('Tanto Recorder'); root.geometry('600x300')
        panel=ttk.Frame(root,padding=20);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='Tanto Recorder',font=('Segoe UI',20,'bold')).pack(anchor='w')
        self.choices={boss['name']:key for key,boss in BOSSES.items()}
        self.boss=tk.StringVar(value=next(iter(self.choices)))
        self.selector=ttk.Combobox(panel,textvariable=self.boss,values=list(self.choices),state='readonly')
        self.selector.pack(anchor='w',pady=12)
        bar=ttk.Frame(panel);bar.pack(anchor='w')
        for title,command in [('Record',self.start),('Describe last move',self.describe),('Stop',self.stop.set),('Export',self.export)]:
            ttk.Button(bar,text=title,command=command).pack(side='left',padx=(0,6))
        self.status=tk.StringVar(value='Choose a boss. Start recording before fighting.')
        ttk.Label(panel,textvariable=self.status,wraplength=550).pack(anchor='w',pady=14)
        ttk.Label(panel,text='Pause Nioh yourself after a move, then describe it here.\nCapture continues until you press Stop.',wraplength=550).pack(anchor='w')
        root.protocol('WM_DELETE_WINDOW',self.close);root.after(200,self.poll)

    def start(self):
        # Give every session its own folder and explicit boss selection.
        # Never report readiness before the backend has resolved the source actor.
        # Worker failures remain visible instead of silently ending a recording.
        if self.thread and self.thread.is_alive(): return
        boss=self.choices[self.boss.get()];self.stop.clear()
        self.folder=Path.home()/'Downloads/Tanto Recordings'/f'{boss}-{time.time_ns()}'
        self.latest=dict(state='starting',detail='Looking for Nioh and the selected boss.')
        def capture():
            # Run only the read-only encounter backend.
            # Publish status as immutable snapshots for Tk's polling loop.
            # Preserve an actionable error if discovery or capture exits unexpectedly.
            try: record_encounter(boss,self.folder,stop_event=self.stop,status_callback=lambda state:setattr(self,'latest',state))
            except Exception as error: self.latest=dict(state='error',detail=str(error))
        self.thread=threading.Thread(target=capture,daemon=False);self.thread.start()

    def describe(self):
        # Associate ordinary language with the latest completed capture record.
        # The player chooses when to pause and which move to describe.
        # Reject descriptions before any valid take exists.
        if self.folder is None: return
        text=simpledialog.askstring('Describe last move','What happened? Mention extra attacks or uncertainty.',parent=self.root)
        if text:
            try: annotate_recent(self.folder,text)
            except (OSError,ValueError) as error: messagebox.showerror('Description not saved',str(error),parent=self.root)

    def export(self):
        # Export a stopped capture so every included take has a stable end.
        # Open its Downloads folder for manual sharing.
        # The app never uploads contributor data automatically.
        if self.thread and self.thread.is_alive():
            messagebox.showinfo('Stop recording first','Press Stop and wait for Stopped before exporting.',parent=self.root);return
        if self.folder is None: return
        try:
            path=export_capture(self.folder,Path.home()/'Downloads'/f'Tanto-{self.folder.name}-{time.time_ns()}.zip')
            self.status.set('Export saved: '+path.name);os.startfile(str(path.parent))
        except (OSError,ValueError) as error: messagebox.showerror('Export failed',str(error),parent=self.root)

    def poll(self):
        # Reflect worker progress without interacting with the game window.
        # Readiness requires attributed boss sampling, not just a selected name.
        # Keep discovery and recovery failures understandable to contributors.
        value=self.latest
        if value:
            ready=value.get('state')=='recording' and value.get('actor_identified')
            self.status.set(('Ready to fight. Recording.' if ready else value.get('state','').replace('_',' ').capitalize())+' '+str(value.get('detail',''))[:180])
        self.selector.configure(state='disabled' if self.thread and self.thread.is_alive() else 'readonly')
        self.root.after(200,self.poll)

    def close(self):
        # Request a clean stop before closing the recorder.
        # Leave Tk responsive while the worker finishes its last take.
        # Avoid truncating evidence by terminating the process mid-write.
        self.stop.set()
        if self.thread and self.thread.is_alive(): self.root.after(200,self.close)
        else: self.root.destroy()


def main(argv=None):
    # Keep the app launch separate from capture and allow a non-game UI smoke check.
    # Smoke checks instantiate widgets but never start discovery or open Nioh.
    # Normal launches wait for the contributor to press Record.
    parser=argparse.ArgumentParser(description='Tanto read-only boss recorder')
    parser.add_argument('--ui-smoke',type=Path);args=parser.parse_args(argv)
    root=tk.Tk()
    if args.ui_smoke: root.withdraw()
    Recorder(root)
    if args.ui_smoke:
        args.ui_smoke.write_text(json.dumps(dict(passed=True,game_access=False)));root.after(200,root.destroy)
    root.mainloop()
    return 0
