"""Contributor UI. Recording never controls the game or loads the mod runtime."""
import argparse
import json
import os
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from encounter_recording import BOSSES, latest_sample_time, load_annotations, record_encounter, save_annotation
from recording_bundle import export_capture, intake_bundle


class Recorder:
    def __init__(self, root):
        # Present task language instead of native action identifiers.
        # Run discovery/capture on a worker while Tk owns all widgets.
        # Keep Stop cooperative so the active take is flushed before export.
        self.root=root; self.thread=None; self.folder=None; self.stop=threading.Event(); self.latest={}
        root.title('Tanto Recorder'); root.geometry('900x560')
        panel=ttk.Frame(root,padding=20);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='Tanto Recorder',font=('Segoe UI',20,'bold')).pack(anchor='w')
        self.choices={boss['name']:key for key,boss in BOSSES.items()}
        self.boss=tk.StringVar(value=next(iter(self.choices)))
        self.selector=ttk.Combobox(panel,textvariable=self.boss,values=list(self.choices),state='readonly')
        self.selector.pack(anchor='w',pady=12)
        bar=ttk.Frame(panel);bar.pack(anchor='w')
        for title,command in [('Record new',self.start),('Open session',self.open_session),
                              ('Resume session',lambda:self.start(resume=True)),
                              ('Describe last move',self.describe),('Stop',self.stop.set),('Export',self.export)]:
            ttk.Button(bar,text=title,command=command).pack(side='left',padx=(0,6))
        self.status=tk.StringVar(value='Choose a boss. Start recording before fighting.')
        ttk.Label(panel,textvariable=self.status,wraplength=550).pack(anchor='w',pady=14)
        ttk.Label(panel,text='Pause Nioh yourself after a move, then describe it here. Capture continues until Stop.').pack(anchor='w')
        self.session_name=tk.StringVar(value='No session open')
        ttk.Label(panel,textvariable=self.session_name,wraplength=850).pack(anchor='w',pady=8)
        self.labels=ttk.Treeview(panel,columns=('take','start','end','description','markers'),show='headings',height=9)
        for key,title,width in [('take','Take',100),('start','Start (s)',80),('end','End (s)',80),
                                 ('description','Description',360),('markers','Markers',150)]:
            self.labels.heading(key,text=title);self.labels.column(key,width=width)
        self.labels.pack(fill='both',expand=True)
        self.labels.bind('<Double-1>',lambda event:self.edit_selected())
        ttk.Button(panel,text='Edit selected label',command=self.edit_selected).pack(anchor='w',pady=8)
        root.protocol('WM_DELETE_WINDOW',self.close);root.after(200,self.poll)

    def start(self, resume=False):
        # Give every session its own folder and explicit boss selection.
        # Never report readiness before the backend has resolved the source actor.
        # Worker failures remain visible instead of silently ending a recording.
        if self.thread and self.thread.is_alive(): return
        boss=self.choices[self.boss.get()];self.stop.clear()
        if resume:
            if self.folder is None: return
            try:
                manifest=json.loads((self.folder/'encounter.json').read_text(encoding='utf8'))
                boss=manifest['boss_id']
                (self.folder/'STOP').unlink(missing_ok=True)
            except (OSError,ValueError,KeyError) as error:
                messagebox.showerror('Cannot resume',str(error),parent=self.root);return
        else:
            self.folder=Path.home()/'Downloads/Tanto Recordings'/f'{boss}-{time.time_ns()}'
            self.labels.delete(*self.labels.get_children())
        self.session_name.set(str(self.folder))
        self.latest=dict(state='starting',detail='Looking for Nioh and the selected boss.')
        def capture():
            # Run only the read-only encounter backend.
            # Publish status as immutable snapshots for Tk's polling loop.
            # Preserve an actionable error if discovery or capture exits unexpectedly.
            try: record_encounter(boss,self.folder,stop_event=self.stop,status_callback=lambda state:setattr(self,'latest',state),
                                  signature=manifest.get('signature') if resume else None)
            except Exception as error: self.latest=dict(state='error',detail=str(error))
        self.thread=threading.Thread(target=capture,daemon=False);self.thread.start()

    def describe(self):
        if self.folder is None: return
        self.edit_label()

    def open_session(self):
        if self.thread and self.thread.is_alive():
            messagebox.showinfo('Stop recording first','Press Stop before opening another session.',parent=self.root);return
        chosen=filedialog.askdirectory(title='Open recording session',parent=self.root,
                                       initialdir=Path.home()/'Downloads/Tanto Recordings')
        if not chosen: return
        try:
            folder=Path(chosen)
            manifest=json.loads((folder/'encounter.json').read_text(encoding='utf8'))
            labels=load_annotations(folder)
            boss=manifest['boss_id']
            if boss not in BOSSES: raise ValueError('This session has no configured boss')
        except (OSError,ValueError,KeyError) as error:
            messagebox.showerror('Cannot open session',str(error),parent=self.root);return
        self.folder=folder;self.boss.set(BOSSES[boss]['name']);self.latest={}
        self.session_name.set(str(folder));self.refresh_labels(labels)
        self.status.set('Session reopened. Edit labels, export, or resume recording into a new take.')

    def refresh_labels(self, labels=None):
        self.labels.delete(*self.labels.get_children())
        for label in load_annotations(self.folder) if labels is None else labels:
            self.labels.insert('', 'end', iid=label['label_id'],values=(label['take'],label['start_t'],
                label['end_t'],label['label'],', '.join(label['markers'])))

    def edit_selected(self):
        selected=self.labels.selection()
        if not selected or self.folder is None: return
        try:
            label=next(label for label in load_annotations(self.folder) if label['label_id']==selected[0])
            self.edit_label(label)
        except (OSError,ValueError) as error:
            messagebox.showerror('Cannot edit label',str(error),parent=self.root)

    def edit_label(self, label=None):
        takes=sorted(path.parent.name for path in self.folder.glob('take-*/events.jsonl'))
        if not takes:
            messagebox.showinfo('No sampled data','Wait until a recorded take is available.',parent=self.root);return
        folder=self.folder
        try: end=label['end_t'] if label else latest_sample_time(folder/takes[-1]/'events.jsonl')
        except (OSError,ValueError) as error:
            messagebox.showerror('Cannot describe yet',str(error),parent=self.root);return
        dialog=tk.Toplevel(self.root);dialog.title('Edit label' if label else 'Describe sequence')
        dialog.transient(self.root);dialog.grab_set()
        panel=ttk.Frame(dialog,padding=16);panel.pack(fill='both',expand=True)
        take=tk.StringVar(value=label['take'] if label else takes[-1])
        start=tk.StringVar(value=str(label['start_t'] if label else end));finish=tk.StringVar(value=str(end))
        ttk.Label(panel,text='Take').grid(row=0,column=0,sticky='w')
        selector=ttk.Combobox(panel,textvariable=take,values=takes,state='readonly');selector.grid(row=0,column=1,sticky='ew')
        duration=tk.StringVar()
        def show_duration(event=None):
            try: duration.set(f"Recorded through {latest_sample_time(folder/take.get()/'events.jsonl'):.3f} seconds")
            except (OSError,ValueError) as error: duration.set(str(error))
        selector.bind('<<ComboboxSelected>>',show_duration);show_duration()
        ttk.Label(panel,textvariable=duration).grid(row=1,column=0,columnspan=2,sticky='w')
        for row,title,value in [(2,'Start seconds',start),(3,'End seconds',finish)]:
            ttk.Label(panel,text=title).grid(row=row,column=0,sticky='w')
            ttk.Entry(panel,textvariable=value).grid(row=row,column=1,sticky='ew')
        ttk.Label(panel,text='Describe the sequence; interval boundaries remain estimates.').grid(row=4,column=0,columnspan=2,pady=8)
        description=tk.Text(panel,width=64,height=5,wrap='word');description.grid(row=5,column=0,columnspan=2)
        if label: description.insert('1.0',label['label'])
        marks=ttk.Frame(panel);marks.grid(row=6,column=0,columnspan=2,sticky='w',pady=8)
        markers={name:tk.BooleanVar(value=name in (label or {}).get('markers',[])) for name in ('repeat','unsure','interrupted')}
        for name,value in markers.items(): ttk.Checkbutton(marks,text=name.capitalize(),variable=value).pack(side='left',padx=6)
        def save():
            try:
                save_annotation(folder,description.get('1.0','end'),take.get(),float(start.get()),float(finish.get()),
                                [name for name,value in markers.items() if value.get()],(label or {}).get('label_id'))
                self.refresh_labels();dialog.destroy()
            except (OSError,ValueError) as error:
                messagebox.showerror('Description not saved',str(error),parent=dialog)
        ttk.Button(panel,text='Save label',command=save).grid(row=7,column=1,sticky='e')
        description.focus_set()

    def export(self):
        # Export a stopped capture so every included take has a stable end.
        # Open its Downloads folder for manual sharing.
        # The app never uploads contributor data automatically.
        if self.thread and self.thread.is_alive():
            messagebox.showinfo('Stop recording first','Press Stop and wait for Stopped before exporting.',parent=self.root);return
        if self.folder is None: return
        try:
            path=export_capture(self.folder,Path.home()/'Downloads'/f'Tanto-{self.folder.name}-{time.time_ns()}.zip')
            self.latest={}
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
    parser.add_argument('--ui-smoke',type=Path)
    parser.add_argument('--intake',type=Path,help='Validate a contributor ZIP and stage review evidence without opening the UI')
    parser.add_argument('--intake-dir',type=Path,default=Path.home()/'Downloads/Tanto Intake')
    args=parser.parse_args(argv)
    if args.intake:
        report=intake_bundle(args.intake,args.intake_dir)
        print(json.dumps(report,indent=2));return 0
    root=tk.Tk()
    if args.ui_smoke: root.withdraw()
    Recorder(root)
    if args.ui_smoke:
        args.ui_smoke.write_text(json.dumps(dict(passed=True,game_access=False)));root.after(200,root.destroy)
    root.mainloop()
    return 0
