"""Read-only contributor UI; workers never access Tk or control the game."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import threading
import time
import uuid
import winsound
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from encounter_recording import BOSSES, DEFAULT_SIGNATURES, atomic_json, latest_sample_time, load_annotations, record_encounter, save_annotation
from recording_bundle import export_capture, intake_bundle
from recording_hotkey import GlobalHotkey, HOTKEYS
from recorder_theme import SURFACE, INPUT, TEXT, MUTED, ACCENT, InkBackdrop, SequenceList, QuickGuide, theme
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
        self.events=queue.SimpleQueue();self.operation=None;self.closing=False;self.close_job=None;self.hotkey=None
        self.draft_job=None;self.editing=None;self.sounded=False
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
        panel.columnconfigure(0,weight=1);panel.rowconfigure(8,weight=1)
        form=ttk.Frame(panel);form.grid(row=2,column=0,sticky='ew');form.columnconfigure(0,weight=1)
        self.backdrop.label(form,text='Boss or enemy name · required').grid(row=0,column=0,sticky='w')
        self.backdrop.label(form,text='Global start / stop key').grid(row=0,column=1,sticky='w',padx=(16,0))
        self.boss=tk.StringVar(value=settings.get('boss',''));self.selector=ttk.Combobox(form,textvariable=self.boss,values=sorted(set([b['name'] for b in BOSSES.values()]+settings.get('custom_bosses',[]))))
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
        self.session_name=tk.StringVar(value='No session open')
        self.session_label=self.backdrop.label(panel,textvariable=self.session_name,style='Muted.TLabel',wraplength=610)
        self.session_label.grid(row=5,column=0,sticky='ew',pady=(0,8))
        tools=ttk.Frame(panel);tools.grid(row=6,column=0,sticky='ew',pady=(0,8))
        self.idle_buttons=[]
        for title,command in [('New session',self.new_session),('Open session',self.open_session),('Export ZIP',self.export)]:
            button=ttk.Button(tools,text=title,command=command);button.pack(side='left',padx=(0,6));self.idle_buttons.append(button)
        table=ttk.Frame(panel);table.grid(row=8,column=0,sticky='nsew');table.columnconfigure(0,weight=1);table.rowconfigure(0,weight=1)
        self.labels=SequenceList(table,self.backdrop)
        self.labels.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.labels.yview);scroll.grid(row=0,column=1,sticky='ns')
        def position_scroll(first,last):
            scroll.set(first,last)
            if first<=0 and last>=1:scroll.grid_remove()
            else:scroll.grid()
        self.labels.configure(yscrollcommand=position_scroll);self.labels.bind('<Double-1>',lambda event:self.edit_selected())
        self.labels.bind('<Return>',lambda event:self.edit_selected())
        notes=ttk.Frame(panel);notes.grid(row=7,column=0,sticky='ew',pady=(0,10));notes.columnconfigure(0,weight=1)
        self.backdrop.label(notes,text='Sequence description · drafts save automatically').grid(row=0,column=0,sticky='w')
        self.description=tk.Text(notes,height=3,width=30,wrap='word',background=INPUT,foreground=TEXT,
            insertbackground=TEXT,font=(fonts[0],11),relief='flat',padx=10,pady=8,undo=True)
        self.description.grid(row=1,column=0,sticky='ew',pady=5)
        self.description.bind('<<Modified>>',self.draft_changed)
        self.save_button=ttk.Button(notes,text='Save description',command=self.save_description)
        self.save_button.grid(row=1,column=1,padx=(10,0))
        self.note_status=tk.StringVar(value='Write what happened. Stop recording before saving a sequence.')
        self.backdrop.label(notes,textvariable=self.note_status,style='Muted.TLabel',wraplength=600).grid(row=2,column=0,columnspan=2,sticky='ew')
        root.bind('<Control-s>',lambda event:self.save_description())
        help_text='Pause Nioh, stop recording, then describe the sequence. Export when finished.'
        self.help_label=self.backdrop.label(panel,text=help_text,style='Muted.TLabel',wraplength=610)
        self.help_label.grid(row=9,column=0,sticky='ew',pady=(10,0))
        panel.bind('<Configure>',lambda event:self.resize_text(event.width))
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.custom_bosses=settings.get('custom_bosses',[])
        self.set_draft(settings.get('draft',{}))
        if settings.get('last_session'):
            try:self.load_session(Path(settings['last_session']))
            except (OSError,ValueError,KeyError,TypeError) as error:self.status.set('Could not reopen previous session: '+str(error))
        self.boss.trace_add('write',self.draft_changed)
        if enable_hotkey: self.configure_hotkey(persist=False)
        self.poll()

    def resize_text(self,width):
        for label in (self.hotkey_label,self.session_label,self.help_label): label.configure(wraplength=max(300,width-48))
        self.status_label.configure(wraplength=max(300,width-116))

    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def draft(self):
        return dict(text=self.description.get('1.0','end-1c'),editing=self.editing)

    def set_draft(self,value):
        self.editing=value.get('editing');self.description.delete('1.0','end')
        self.description.insert('1.0',value.get('text',''));self.description.edit_modified(False);self.description.edit_reset()

    def draft_changed(self,*args):
        if self.closing:return
        if args and isinstance(args[0],tk.Event) and not self.description.edit_modified():return
        self.description.edit_modified(False)
        if self.draft_job:self.root.after_cancel(self.draft_job)
        self.draft_job=self.root.after(300,self.save_settings)

    def save_settings(self):
        if self.draft_job:self.root.after_cancel(self.draft_job);self.draft_job=None
        try:
            self.settings_path.parent.mkdir(parents=True,exist_ok=True)
            if self.folder:
                atomic_json(self.folder/'draft.json',self.draft())
            atomic_json(self.settings_path,dict(hotkey=self.key.get(),tutorial_seen=self.tutorial_seen,
                boss=self.boss.get(),custom_bosses=self.custom_bosses,last_session=str(self.folder) if self.folder else None,draft=self.draft()))
            self.note_status.set('Draft saved' if self.draft()['text'] else 'Write what happened. Ctrl+S saves the sequence.')
            return True
        except OSError as error:
            self.note_status.set('Save failed: '+str(error));return False

    def cue(self,kind):
        # Nonblocking local WAV playback; never controller vibration or game input.
        base=Path(os.environ.get('TANTO_PRODUCT_ROOT',Path(__file__).resolve().parents[1]))
        try:winsound.PlaySound(str(base/'src/assets'/f'{kind}.wav'),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
        except RuntimeError:self.status.set('Audio cue unavailable; check the recording status above.')

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
        if self.closing or self.operation=='export': return
        if self.busy():
            self.stop.set();self.headline.set('Finishing recording…');self.status.set('Flushing the take and preserving its evidence.')
        else: self.start(resume=self.folder is not None)

    def start(self,resume=False):
        if self.busy() or self.closing: return
        if self.folder and self.description.get('1.0','end-1c').strip() and list(self.folder.glob('take-*/events.jsonl')):
            if not self.save_description():return
        try:
            if resume:
                manifest=json.loads((self.folder/'encounter.json').read_text(encoding='utf8'))
                boss,name=manifest['boss_id'],manifest.get('boss_name',manifest['boss_id'])
                signature=manifest.get('signature');(self.folder/'STOP').unlink(missing_ok=True)
            else:
                boss,name=boss_identity(self.boss.get());signature=None
                folder=self.recordings/f'{boss}-{time.time_ns()}'
                folder.mkdir(parents=True)
                signature=DEFAULT_SIGNATURES.get(boss,[])
                atomic_json(folder/'encounter.json',dict(schema_version=1,boss_id=boss,boss_name=name,signature=signature,
                    recording_id=uuid.uuid4().hex,created_at=time.time(),mode='external_read_only',
                    identity_basis='source action/motion fingerprint' if signature else 'unassigned encounter context'))
                self.folder=folder
                self.labels.delete(*self.labels.get_children())
        except (OSError,ValueError,KeyError,TypeError) as error:
            self.headline.set('Cannot start');self.status.set(str(error));return
        self.boss.set(name);self.session_name.set(name);folder=self.folder
        if name not in self.custom_bosses:self.custom_bosses.append(name)
        self.selector.configure(values=sorted(set([b['name'] for b in BOSSES.values()]+self.custom_bosses)))
        if not self.save_settings():return
        self.sounded=False
        self.stop.clear();self.operation='capture';self.latest=dict(state='starting',detail='Looking for Nioh and encounter actors.')
        def capture():
            try:
                record_encounter(boss,folder,stop_event=self.stop,boss_name=name,signature=signature,
                                 status_callback=lambda value:self.events.put(('capture_status',(folder,value),None)))
            except Exception as error:self.events.put(('capture_status',(folder,dict(state='error',detail=str(error))),None))
            finally:self.events.put(('capture_finished',folder,None))
        self.thread=threading.Thread(target=capture,daemon=False);self.thread.start()

    def new_session(self):
        if self.busy(): return
        if not self.save_settings():return
        self.set_draft({});self.folder=None;self.latest={};self.boss.set('');self.labels.delete(*self.labels.get_children())
        self.session_name.set('Previous session remains saved in Downloads / Tanto Recordings')
        self.headline.set('New session');self.status.set('Enter the boss or enemy name before starting.');self.selector.focus_set();self.save_settings()

    def open_session(self):
        if self.busy(): return
        chosen=filedialog.askdirectory(title='Open recording session',parent=self.root,initialdir=self.recordings if self.recordings.exists() else self.recordings.parent)
        if not chosen: return
        if not self.save_settings():return
        try:self.load_session(Path(chosen));self.save_settings()
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as error:
            messagebox.showerror('Cannot open session',str(error),parent=self.root)

    def load_session(self,folder):
        manifest=json.loads((folder/'encounter.json').read_text(encoding='utf8'))
        labels=load_annotations(folder);name=manifest.get('boss_name',manifest['boss_id']);boss_identity(name)
        draft=json.loads((folder/'draft.json').read_text(encoding='utf8')) if (folder/'draft.json').exists() else {}
        self.folder=folder;self.boss.set(name);self.latest={};self.session_name.set(name+' · '+str(len(list(folder.glob('take-*/events.jsonl'))))+' saved takes');self.refresh_labels(labels);self.set_draft(draft)
        self.headline.set('Session restored');self.status.set('Each Start adds a new take. Previous recordings and notes are preserved.')

    def refresh_labels(self,labels=None):
        self.labels.delete(*self.labels.get_children())
        for label in load_annotations(self.folder) if labels is None else labels:
            marks=' · '+', '.join(label['markers']) if label['markers'] else ''
            self.labels.insert('','end',iid=label['label_id'],values=(label['take'],f"{label['start_t']:.2f} – {label['end_t']:.2f}",label['label']+marks))

    def describe(self):
        self.description.focus_set()
        self.note_status.set('Type below. Drafts save automatically; Ctrl+S saves a stopped sequence.')

    def edit_selected(self):
        selected=self.labels.selection()
        if not selected or not self.folder or self.busy():return
        if self.description.get('1.0','end-1c').strip() and not self.save_description():return
        try:
            label=next(x for x in load_annotations(self.folder) if x['label_id']==selected[0])
            self.set_draft(dict(text=label['label'],editing=label));self.save_settings();self.describe()
        except (OSError,ValueError,StopIteration) as error:self.note_status.set('Cannot edit: '+str(error))

    def save_description(self):
        if not self.save_settings():return False
        if self.busy():self.note_status.set('Draft saved. Stop recording to attach it to a sequence.');return False
        if not self.description.get('1.0','end-1c').strip():return True
        if not self.folder:self.note_status.set('Draft saved. Start a recording to attach a sequence.');return False
        try:
            takes=sorted(self.folder.glob('take-*/events.jsonl'),key=lambda p:int(p.parent.name[5:]))
            if not takes:raise ValueError('Draft saved. No recorded samples yet.')
            label=self.editing
            take=label['take'] if label else takes[-1].parent.name
            end=label['end_t'] if label else latest_sample_time(self.folder/take/'events.jsonl')
            start=label['start_t'] if label else min(end,max((x['end_t'] for x in load_annotations(self.folder) if x['take']==take),default=0))
            save_annotation(self.folder,self.description.get('1.0','end-1c'),take,start,end,
                (label or {}).get('markers',[]),(label or {}).get('label_id'))
            self.set_draft({});self.refresh_labels();self.save_settings();self.note_status.set('Description saved to '+take)
            return True
        except (OSError,ValueError) as error:self.note_status.set(str(error));return False

    def export(self):
        if self.busy() or not self.folder: return
        if not self.save_description():return
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
            elif kind=='capture_status':
                folder,value=value
                if folder!=self.folder:continue
                self.latest=value
                if value.get('state')=='recording' and not self.sounded:self.cue('start');self.sounded=True
            elif kind=='capture_finished':
                if value!=self.folder:continue
                self.cue('stop');self.sounded=False
                self.session_name.set(self.boss.get()+' · '+str(len(list(self.folder.glob('take-*/events.jsonl'))))+' saved takes')
                self.save_settings()
                self.note_status.set('Stopped. Describe this sequence, then Save or press Ctrl+S.')
            elif kind.startswith('hotkey_'): self.hotkey_status.set(value)
            elif kind=='exported': self.operation=None;self.headline.set('Export saved');self.status.set(str(value))
            elif kind=='export_error': self.operation=None;self.headline.set('Export failed');self.status.set(value)
        busy=self.busy()
        if not busy and self.operation=='capture': self.operation=None
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
        self.save_button.configure(state='disabled' if busy else 'normal')
        self.pulse.itemconfigure(self.dot,fill=ACCENT if busy else MUTED)
        self.after_id=self.root.after(100,self.poll)

    def close(self):
        if not self.closing and not self.save_settings():return
        self.closing=True;self.stop.set()
        if self.hotkey: self.hotkey.close();self.hotkey=None
        if self.close_job:self.root.after_cancel(self.close_job);self.close_job=None
        if self.busy(): self.close_job=self.root.after(150,self.close);return
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
        import tempfile
        fixture=tempfile.TemporaryDirectory(prefix='tanto-ui-smoke-')
        folder=Path(fixture.name);take=folder/'take-0001';take.mkdir()
        atomic_json(folder/'encounter.json',dict(boss_id='okatsu',boss_name='Okatsu'))
        (take/'events.jsonl').write_text('{"kind":"end","t":1}\n',encoding='utf8')
        app.load_session(folder);app.description.insert('1.0','Smoke: slash and jump')
        saved=app.save_description() and load_annotations(folder)[0]['label']=='Smoke: slash and jump'
        app.description.insert('1.0','Unfinished note');app.save_settings();app.set_draft({});app.load_session(folder)
        restored=app.description.get('1.0','end-1c')=='Unfinished note'
        app.backdrop.on_guide()
        app.guide.attributes('-alpha',0)
        def finish():
            rendered=app.backdrop.picture.width()==app.backdrop.winfo_width()
            args.ui_smoke.write_text(json.dumps(dict(passed=not errors and rendered and saved and restored and app.guide.picture.width()>1,game_access=False,
                local_guide=app.guide.winfo_exists()==1,wallpaper_rendered=rendered,description_saved=saved,draft_restored=restored,errors=errors)))
            app.close();fixture.cleanup()
        root.after(500,finish)
    root.mainloop();return 0
