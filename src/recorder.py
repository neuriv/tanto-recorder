"""Read-only contributor UI; workers never access Tk or control the game."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from encounter_recording import BOSSES, atomic_json, latest_sample_time, load_annotations, record_encounter, save_annotation
from recording_bundle import export_capture, intake_bundle
from recording_hotkey import GlobalHotkey, HOTKEYS
from recorder_theme import BG, SURFACE, INPUT, TEXT, MUTED, ACCENT, InkBackdrop, SequenceList, QuickGuide, theme
from windows_paths import downloads_dir



def boss_identity(name):
    name=' '.join(name.split())
    if not name or len(name)>100:
        raise ValueError('Enter a boss or enemy name (1–100 characters) before recording.')
    for key,boss in BOSSES.items():
        if name.casefold() in (boss['name'].casefold(),key.replace('_',' ').casefold()):
            return key,name
    return 'encounter_'+hashlib.sha256(name.casefold().encode()).hexdigest()[:16],name


class Recorder:
    def __init__(self, root, enable_hotkey=True, settings_path=None):
        self.root=root;self.thread=None;self.folder=None;self.stop=threading.Event();self.latest={}
        self.events=queue.SimpleQueue();self.operation=None;self.closing=False;self.dialog=None;self.hotkey=None
        self.hotkey_generation=0;self.enable_hotkey=enable_hotkey;self.after_id=None
        self.settings_path=settings_path or Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Tanto/Recorder/settings.json'
        try: settings=json.loads(self.settings_path.read_text(encoding='utf8'))
        except (OSError,ValueError): settings={}
        if not isinstance(settings,dict): settings={}
        self.tutorial_seen=bool(settings.get('tutorial_seen',False));self.guide=None
        fonts=theme(root);root.title('Tanto Recorder')
        self.recordings=downloads_dir()/'Tanto Recordings'
        self.scale=max(1,float(root.tk.call('tk','scaling'))/(96/72))
        root.geometry(f'{round(960*self.scale)}x{round(740*self.scale)}')
        root.minsize(round(680*self.scale),round(650*self.scale))
        self.backdrop=InkBackdrop(root,self.scale,fonts)
        self.backdrop.on_guide=self.show_guide
        root.bind('<F1>',lambda event:self.show_guide())
        panel=ttk.Frame(self.backdrop)
        self.backdrop.panel=self.backdrop.create_window(24,106,anchor='nw',window=panel)
        panel.columnconfigure(0,weight=1);panel.rowconfigure(7,weight=1)
        form=ttk.Frame(panel);form.grid(row=2,column=0,sticky='ew');form.columnconfigure(0,weight=1)
        self.backdrop.label(form,text='Boss or enemy name · required').grid(row=0,column=0,sticky='w')
        self.backdrop.label(form,text='Global start / stop key').grid(row=0,column=1,sticky='w',padx=(16,0))
        self.boss=tk.StringVar();self.selector=ttk.Combobox(form,textvariable=self.boss,values=[b['name'] for b in BOSSES.values()])
        self.selector.grid(row=1,column=0,sticky='ew',pady=6)
        self.key=tk.StringVar(value=settings.get('hotkey') if settings.get('hotkey') in HOTKEYS else 'F8')
        hotkey=ttk.Combobox(form,textvariable=self.key,values=list(HOTKEYS),state='readonly',width=18)
        hotkey.grid(row=1,column=1,sticky='ew',padx=(16,0),pady=6);hotkey.bind('<<ComboboxSelected>>',self.configure_hotkey)
        self.hotkey_status=tk.StringVar(value='Hotkey off. Use Start / Stop below.')
        self.hotkey_label=self.backdrop.label(form,textvariable=self.hotkey_status,style='Muted.TLabel',wraplength=610)
        self.hotkey_label.grid(row=2,column=0,columnspan=2,sticky='ew',pady=(0,14))
        card=ttk.Frame(panel,style='Card.TFrame');card.grid(row=3,column=0,sticky='ew',pady=14);card.columnconfigure(1,weight=1)
        self.pulse=tk.Canvas(card,width=28,height=28,background=SURFACE,highlightthickness=0)
        self.pulse.grid(row=0,column=0,rowspan=2,padx=(0,12));self.dot=self.pulse.create_oval(8,8,20,20,fill=MUTED,outline='')
        self.headline=tk.StringVar(value='Ready when you are')
        self.backdrop.label(card,textvariable=self.headline,style='Card.TLabel',font=('Segoe UI',14,'bold')).grid(row=0,column=1,sticky='w')
        self.status=tk.StringVar(value='Enter the boss name, then start before fighting.')
        self.status_label=self.backdrop.label(card,textvariable=self.status,style='Card.TLabel',wraplength=550)
        self.status_label.grid(row=1,column=1,sticky='ew',pady=(4,0))
        controls=ttk.Frame(panel);controls.grid(row=4,column=0,sticky='ew',pady=14)
        self.primary=ttk.Button(controls,text='Start recording',style='Primary.TButton',command=self.toggle)
        self.primary.pack(side='left')
        self.describe_button=ttk.Button(controls,text='Describe sequence',command=self.describe)
        self.describe_button.pack(side='left',padx=8)
        self.reduced=tk.BooleanVar(value=bool(settings.get('reduced_motion',False)))
        motion_label=self.backdrop.label(controls,text='Reduce motion',style='Muted.TLabel')
        motion_label.pack(side='right',padx=(4,0))
        motion_label.bind('<Button-1>',lambda event:(self.reduced.set(not self.reduced.get()),self.save_settings()))
        ttk.Checkbutton(controls,variable=self.reduced,command=self.save_settings).pack(side='right')
        self.session_name=tk.StringVar(value='No session open')
        self.session_label=self.backdrop.label(panel,textvariable=self.session_name,style='Muted.TLabel',wraplength=610)
        self.session_label.grid(row=5,column=0,sticky='ew',pady=(0,8))
        tools=ttk.Frame(panel);tools.grid(row=6,column=0,sticky='ew',pady=(0,8))
        self.idle_buttons=[]
        for title,command in [('New session',self.new_session),('Open session',self.open_session),('Export ZIP',self.export)]:
            button=ttk.Button(tools,text=title,command=command);button.pack(side='left',padx=(0,6));self.idle_buttons.append(button)
        table=ttk.Frame(panel);table.grid(row=7,column=0,sticky='nsew');table.columnconfigure(0,weight=1);table.rowconfigure(0,weight=1)
        self.labels=SequenceList(table,self.backdrop)
        self.labels.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.labels.yview);scroll.grid(row=0,column=1,sticky='ns')
        def position_scroll(first,last):
            scroll.set(first,last)
            if first<=0 and last>=1:scroll.grid_remove()
            else:scroll.grid()
        self.labels.configure(yscrollcommand=position_scroll);self.labels.bind('<Double-1>',lambda event:self.edit_selected())
        self.labels.bind('<Return>',lambda event:self.edit_selected())
        help_text='Pause Nioh, stop recording, then describe the sequence. Export when finished.'
        self.help_label=self.backdrop.label(panel,text=help_text,style='Muted.TLabel',wraplength=610)
        self.help_label.grid(row=9,column=0,sticky='ew',pady=(10,0))
        panel.bind('<Configure>',lambda event:self.resize_text(event.width))
        root.protocol('WM_DELETE_WINDOW',self.close)
        if enable_hotkey: self.configure_hotkey(persist=False)
        self.poll()

    def resize_text(self,width):
        for label in (self.hotkey_label,self.session_label,self.help_label): label.configure(wraplength=max(300,width-48))
        self.status_label.configure(wraplength=max(300,width-116))

    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def save_settings(self):
        try: atomic_json(self.settings_path,dict(hotkey=self.key.get(),reduced_motion=self.reduced.get(),tutorial_seen=self.tutorial_seen))
        except OSError as error: self.hotkey_status.set('Settings could not be saved: '+str(error))

    def show_guide(self):
        if self.closing:return
        if self.guide and self.guide.winfo_exists():self.guide.lift();return
        def done():
            self.tutorial_seen=True;self.save_settings();self.guide.destroy();self.guide=None
        self.guide=QuickGuide(self.root,self.backdrop,done)

    def configure_hotkey(self,event=None,persist=True):
        self.hotkey_generation+=1;generation=self.hotkey_generation
        if self.hotkey: self.hotkey.close();self.hotkey=None
        self.hotkey_status.set('Hotkey off. Use Start / Stop below.' if self.key.get()=='Off' else 'Registering hotkey…')
        if self.enable_hotkey and self.key.get()!='Off':
            self.hotkey=GlobalHotkey(self.key.get(),lambda kind,value:self.events.put((kind,value,generation)))
        if persist: self.save_settings()

    def toggle(self):
        if self.closing or self.dialog or self.operation=='export': return
        if self.busy():
            self.stop.set();self.headline.set('Finishing recording…');self.status.set('Flushing the take and preserving its evidence.')
        else: self.start(resume=self.folder is not None)

    def start(self,resume=False):
        if self.busy() or self.closing: return
        try:
            if resume:
                manifest=json.loads((self.folder/'encounter.json').read_text(encoding='utf8'))
                boss,name=manifest['boss_id'],manifest.get('boss_name',manifest['boss_id'])
                signature=manifest.get('signature');(self.folder/'STOP').unlink(missing_ok=True)
            else:
                boss,name=boss_identity(self.boss.get());signature=None
                self.folder=self.recordings/f'{boss}-{time.time_ns()}'
                self.labels.delete(*self.labels.get_children())
        except (OSError,ValueError,KeyError,TypeError) as error:
            self.headline.set('Cannot start');self.status.set(str(error));return
        self.boss.set(name);self.session_name.set(self.folder.name);folder=self.folder
        self.stop.clear();self.operation='capture';self.latest=dict(state='starting',detail='Looking for Nioh and encounter actors.')
        def capture():
            try:
                record_encounter(boss,folder,stop_event=self.stop,boss_name=name,signature=signature,
                                 status_callback=lambda value:setattr(self,'latest',value))
            except Exception as error: self.latest=dict(state='error',detail=str(error))
        self.thread=threading.Thread(target=capture,daemon=False);self.thread.start()

    def new_session(self):
        if self.busy(): return
        self.folder=None;self.latest={};self.boss.set('');self.labels.delete(*self.labels.get_children())
        self.session_name.set('Previous session remains saved in Downloads / Tanto Recordings')
        self.headline.set('New session');self.status.set('Enter the boss or enemy name before starting.');self.selector.focus_set()

    def open_session(self):
        if self.busy(): return
        chosen=filedialog.askdirectory(title='Open recording session',parent=self.root,initialdir=self.recordings)
        if not chosen: return
        try:
            folder=Path(chosen);manifest=json.loads((folder/'encounter.json').read_text(encoding='utf8'))
            labels=load_annotations(folder);name=manifest.get('boss_name',manifest['boss_id'])
            boss_identity(name)
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as error:
            messagebox.showerror('Cannot open session',str(error),parent=self.root);return
        self.folder=folder;self.boss.set(name);self.latest={};self.session_name.set(folder.name);self.refresh_labels(labels)
        self.headline.set('Session opened');self.status.set('Resume into a new take, edit descriptions, or export.')

    def refresh_labels(self,labels=None):
        self.labels.delete(*self.labels.get_children())
        for label in load_annotations(self.folder) if labels is None else labels:
            marks=' · '+', '.join(label['markers']) if label['markers'] else ''
            self.labels.insert('','end',iid=label['label_id'],values=(label['take'],f"{label['start_t']:.2f} – {label['end_t']:.2f}",label['label']+marks))

    def describe(self):
        if self.folder and self.operation!='export': self.edit_label()

    def edit_selected(self):
        selected=self.labels.selection()
        if not selected or not self.folder or self.operation=='export': return
        try: self.edit_label(next(label for label in load_annotations(self.folder) if label['label_id']==selected[0]))
        except (OSError,ValueError,StopIteration) as error:
            messagebox.showerror('Cannot edit description',str(error) or 'Description changed. Reopen the session.',parent=self.root)

    def edit_label(self,label=None):
        if self.dialog: self.dialog.lift();return
        takes=sorted((p.parent.name for p in self.folder.glob('take-*/events.jsonl')),key=lambda name:int(name[5:]))
        if not takes:
            self.status.set('No sampled take yet. Wait for recording to begin.');return
        folder=self.folder
        try:
            end=label['end_t'] if label else latest_sample_time(folder/takes[-1]/'events.jsonl')
            prior=load_annotations(folder)
        except (OSError,ValueError) as error: self.status.set(str(error));return
        dialog=self.dialog=tk.Toplevel(self.root);dialog.title('Describe sequence')
        dialog.geometry(f'{round(660*self.scale)}x{round(480*self.scale)}');dialog.minsize(round(530*self.scale),round(430*self.scale))
        dialog.configure(background=BG);dialog.transient(self.root);dialog.grab_set()
        def close(): self.dialog=None;dialog.destroy()
        dialog.protocol('WM_DELETE_WINDOW',close)
        panel=ttk.Frame(dialog,padding=20);panel.pack(fill='both',expand=True);panel.columnconfigure(1,weight=1);panel.rowconfigure(5,weight=1)
        take=tk.StringVar(value=label['take'] if label else takes[-1])
        beginning=max((x['end_t'] for x in prior if x['take']==take.get()),default=0)
        start=tk.StringVar(value=str(label['start_t'] if label else min(beginning,end)));finish=tk.StringVar(value=str(end))
        ttk.Label(panel,text='Take').grid(row=0,column=0,sticky='w')
        selector=ttk.Combobox(panel,textvariable=take,values=takes,state='readonly');selector.grid(row=0,column=1,sticky='ew')
        duration=tk.StringVar()
        def show_duration(event=None):
            try:
                last=latest_sample_time(folder/take.get()/'events.jsonl');duration.set(f'Recorded through {last:.3f} seconds')
                if event: start.set('0');finish.set(str(last))
            except (OSError,ValueError) as error: duration.set(str(error))
        selector.bind('<<ComboboxSelected>>',show_duration);show_duration()
        ttk.Label(panel,textvariable=duration,style='Muted.TLabel').grid(row=1,column=0,columnspan=2,sticky='w',pady=8)
        for row,title,value in [(2,'Start seconds',start),(3,'End seconds',finish)]:
            ttk.Label(panel,text=title).grid(row=row,column=0,sticky='w',padx=(0,16));ttk.Entry(panel,textvariable=value).grid(row=row,column=1,sticky='ew',pady=3)
        ttk.Label(panel,text='What happened? Timing boundaries remain estimates.',style='Muted.TLabel').grid(row=4,column=0,columnspan=2,sticky='w',pady=10)
        description=tk.Text(panel,width=35,height=4,wrap='word',background=INPUT,foreground=TEXT,insertbackground=TEXT,font=('Segoe UI',11),relief='flat',padx=10,pady=10)
        description.grid(row=5,column=0,columnspan=2,sticky='nsew')
        if label: description.insert('1.0',label['label'])
        marks=ttk.Frame(panel);marks.grid(row=6,column=0,columnspan=2,sticky='w',pady=10)
        markers={name:tk.BooleanVar(value=name in (label or {}).get('markers',[])) for name in ('repeat','unsure','interrupted')}
        for name,value in markers.items(): ttk.Checkbutton(marks,text=name.capitalize(),variable=value).pack(side='left',padx=(0,12))
        def save():
            try:
                save_annotation(folder,description.get('1.0','end'),take.get(),float(start.get()),float(finish.get()),
                                [name for name,value in markers.items() if value.get()],(label or {}).get('label_id'))
                self.refresh_labels();close()
            except (OSError,ValueError) as error: messagebox.showerror('Description not saved',str(error),parent=dialog)
        ttk.Button(panel,text='Save description',style='Primary.TButton',command=save).grid(row=7,column=1,sticky='e')
        description.focus_set()

    def export(self):
        if self.busy() or not self.folder: return
        folder=self.folder;self.operation='export';self.latest={};self.headline.set('Preparing export…');self.status.set('Building reports and checking evidence. You can resize this window while it works.')
        def work():
            try:
                path=export_capture(folder,self.recordings/'Exports'/f'Tanto-{folder.name}-{time.time_ns()}.zip')
                self.events.put(('exported',path,None))
            except Exception as error: self.events.put(('export_error',str(error),None))
        self.thread=threading.Thread(target=work,daemon=False);self.thread.start()

    def poll(self):
        while not self.events.empty():
            kind,value,generation=self.events.get()
            if generation is not None and generation!=self.hotkey_generation: continue
            if kind=='toggle': self.toggle()
            elif kind.startswith('hotkey_'): self.hotkey_status.set(value)
            elif kind=='exported': self.headline.set('Export saved');self.status.set(str(value))
            elif kind=='export_error': self.headline.set('Export failed');self.status.set(value)
        busy=self.busy()
        if not busy: self.operation=None
        value=self.latest
        if value and self.operation!='export':
            state=value.get('state','starting')
            self.headline.set('Finishing recording…' if busy and self.stop.is_set() else
                ('Recording · boss verified' if value.get('actor_identified') else 'Recording · identity unverified') if state=='recording' else state.replace('_',' ').capitalize())
            self.status.set(str(value.get('detail',''))[:260])
        self.selector.configure(state='disabled' if busy or self.folder else 'normal')
        self.primary.configure(text='Stop recording' if busy else 'Resume recording' if self.folder else 'Start recording',
            state='disabled' if self.operation=='export' or (busy and self.stop.is_set()) else 'normal')
        for button in self.idle_buttons: button.configure(state='disabled' if busy else 'normal')
        for button in (self.describe_button,): button.configure(state='normal' if self.folder and self.operation!='export' else 'disabled')
        radius=6+(2*math.sin(time.monotonic()*4) if busy and not self.reduced.get() else 0)
        self.pulse.coords(self.dot,14-radius,14-radius,14+radius,14+radius)
        self.pulse.itemconfigure(self.dot,fill=ACCENT if busy else MUTED)
        self.after_id=self.root.after(50 if busy and not self.reduced.get() else 150,self.poll)

    def close(self):
        self.closing=True;self.stop.set()
        if self.hotkey: self.hotkey.close();self.hotkey=None
        if self.busy(): self.root.after(150,self.close);return
        if self.after_id: self.root.after_cancel(self.after_id)
        self.root.update_idletasks()
        self.root.destroy()


def main(argv=None):
    parser=argparse.ArgumentParser(description='Tanto read-only boss recorder')
    parser.add_argument('--ui-smoke',type=Path)
    parser.add_argument('--intake',type=Path,help='Validate and stage a contributor ZIP without opening the UI')
    parser.add_argument('--intake-dir',type=Path,default=downloads_dir()/'Tanto Intake')
    args=parser.parse_args(argv)
    if args.intake:
        print(json.dumps(intake_bundle(args.intake,args.intake_dir),indent=2));return 0
    root=tk.Tk()
    errors=[]
    if args.ui_smoke:
        root.attributes('-alpha',0)
        root.report_callback_exception=lambda kind,error,trace:errors.append(str(error))
    app=Recorder(root,enable_hotkey=not args.ui_smoke,
                 settings_path=args.ui_smoke.parent/'recorder-smoke-settings.json' if args.ui_smoke else None)
    if not args.ui_smoke and not app.tutorial_seen:root.after(100,app.show_guide)
    if args.ui_smoke:
        app.backdrop.on_guide()
        app.guide.attributes('-alpha',0)
        def finish():
            rendered=app.backdrop.picture.width()==app.backdrop.winfo_width()
            args.ui_smoke.write_text(json.dumps(dict(passed=not errors and rendered and app.guide.picture.width()>1,game_access=False,
                local_guide=app.guide.winfo_exists()==1,wallpaper_rendered=rendered,errors=errors)))
            app.close()
        root.after(500,finish)
    root.mainloop();return 0
