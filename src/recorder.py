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
from recording_bundle import export_capture, export_sessions, intake_bundle
from recording_hotkey import GlobalHotkey, HOTKEYS, parse_hotkey, key_event_name
from recorder_theme import SURFACE, INPUT, TEXT, MUTED, ACCENT, InkBackdrop, SequenceList, QuickGuide, theme
from windows_paths import downloads_dir, choose_recording_folders



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
        self.tutorial_seen=settings.get('tutorial_version')==2;self.guide=None;self.binding=None
        fonts=theme(root)
        base=Path(os.environ.get('TANTO_PRODUCT_ROOT',Path(__file__).resolve().parents[1]))
        version_file=base/'build-manifest.json' if (base/'build-manifest.json').exists() else base/'product.json'
        version=json.loads(version_file.read_text(encoding='utf8'));version=version.get('product',version).get('version','development')
        root.title('Tanto Recorder · '+version)
        self.recordings=Path(settings.get('recordings_directory') or downloads_dir()/'Tanto Recordings').resolve()
        self.scale=max(1,float(root.tk.call('tk','scaling'))/(96/72));s=self.scale
        root.geometry(f'{round(1060*s)}x{round(850*s)}');root.minsize(round(760*s),round(800*s))
        self.backdrop=InkBackdrop(root,s,fonts);self.backdrop.on_guide=self.show_guide
        root.bind('<F1>',lambda event:self.show_guide())
        panel=ttk.Frame(self.backdrop);panel.columnconfigure(0,weight=1);panel.rowconfigure(2,weight=1)
        self.backdrop.panel=self.backdrop.create_window(24,96,anchor='nw',window=panel)
        nav=ttk.Frame(panel);nav.grid(row=0,column=0,sticky='ew',pady=(0,10))
        self.tabs={};self.current_tab='Record'
        for title in ('Record','Settings','Guide'):
            button=ttk.Button(nav,text=title,style='Tab.TButton',command=lambda name=title:self.show_tab(name))
            button.pack(side='left',padx=(0,8));self.tabs[title]=button
        card=self.backdrop.card(panel);card.grid(row=1,column=0,sticky='ew',pady=(0,10));card.columnconfigure(1,weight=1)
        self.pulse=tk.Canvas(card,width=24,height=24,background=SURFACE,highlightthickness=0)
        self.pulse.grid(row=0,column=0,rowspan=2,padx=(0,12));self.dot=self.pulse.create_oval(6,6,18,18,fill=MUTED,outline='')
        self.headline=tk.StringVar(value='Ready when you are')
        self.backdrop.label(card,textvariable=self.headline,style='Card.TLabel',font=(fonts[1],15,'bold')).grid(row=0,column=1,sticky='w')
        self.status=tk.StringVar(value='Enter the boss name, then start before fighting.')
        self.status_label=self.backdrop.label(card,textvariable=self.status,style='Card.TLabel',wraplength=550)
        self.status_label.grid(row=1,column=1,sticky='ew',pady=(4,0))
        self.primary=ttk.Button(card,text='Start recording',style='Primary.TButton',command=self.toggle)
        self.primary.grid(row=0,column=2,rowspan=2,padx=(16,0))
        stack=ttk.Frame(panel);stack.grid(row=2,column=0,sticky='nsew');stack.columnconfigure(0,weight=1);stack.rowconfigure(0,weight=1)
        self.pages={name:(ttk.Frame(stack) if name=='Record' else self.backdrop.card(stack)) for name in self.tabs}
        page=self.pages['Record'];page.columnconfigure(0,weight=1);page.rowconfigure(3,weight=1)
        form=self.backdrop.card(page);form.grid(row=0,column=0,sticky='ew',pady=(0,8));form.columnconfigure(0,weight=1);form.columnconfigure(1,weight=1)
        self.backdrop.label(form,text='Boss or enemy name · required').grid(row=0,column=0,sticky='w')
        self.boss=tk.StringVar(value=settings.get('boss',''))
        self.selector=ttk.Combobox(form,textvariable=self.boss,values=sorted(set([b['name'] for b in BOSSES.values()]+settings.get('custom_bosses',[]))))
        self.selector.grid(row=1,column=0,sticky='ew',pady=(5,0))
        self.session_name=tk.StringVar(value='No session open')
        self.session_label=self.backdrop.label(form,textvariable=self.session_name,style='Muted.TLabel',wraplength=280)
        self.session_label.grid(row=0,column=1,rowspan=2,sticky='ew',padx=(20,0))
        tools=ttk.Frame(page);tools.grid(row=1,column=0,sticky='ew',pady=(0,8));self.idle_buttons=[]
        for title,command in [('New session',self.new_session),('Open session',self.open_session),('Export ZIP',self.export)]:
            button=ttk.Button(tools,text=title,command=command);button.pack(side='left',padx=(0,8));self.idle_buttons.append(button)
        notes=self.backdrop.card(page);notes.grid(row=2,column=0,sticky='ew',pady=(0,8));notes.columnconfigure(0,weight=1)
        self.backdrop.label(notes,text='Sequence description · autosaved drafts').grid(row=0,column=0,sticky='w')
        self.description=tk.Text(notes,height=3,width=30,wrap='word',background=INPUT,foreground=TEXT,
            insertbackground=TEXT,font=(fonts[0],13),relief='flat',padx=10,pady=8,undo=True)
        self.description.grid(row=1,column=0,sticky='ew',pady=5);self.description.bind('<<Modified>>',self.draft_changed)
        self.save_button=ttk.Button(notes,text='Save description',command=self.save_description);self.save_button.grid(row=1,column=1,padx=(10,0))
        self.note_status=tk.StringVar(value='Describe the sequence. Stop before saving.')
        self.note_label=self.backdrop.label(notes,textvariable=self.note_status,style='Muted.TLabel',wraplength=600)
        self.note_label.grid(row=2,column=0,columnspan=2,sticky='ew')
        root.bind('<Control-s>',lambda event:self.save_description())
        table=self.backdrop.card(page);table.grid(row=3,column=0,sticky='nsew');table.columnconfigure(0,weight=1);table.rowconfigure(0,weight=1)
        self.labels=SequenceList(table,self.backdrop);self.labels.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.labels.yview);scroll.grid(row=0,column=1,sticky='ns')
        def position_scroll(first,last):
            scroll.set(first,last)
            if first<=0 and last>=1:scroll.grid_remove()
            else:scroll.grid()
        self.labels.configure(yscrollcommand=position_scroll);self.labels.bind('<Double-1>',lambda event:self.edit_selected())
        self.labels.bind('<Return>',lambda event:self.edit_selected())
        self.help_label=self.backdrop.label(page,text='Pause the game yourself. Stop, describe, then export selected sessions.',style='Muted.TLabel',wraplength=610)
        self.help_label.grid(row=4,column=0,sticky='ew',pady=(8,0))
        settings_page=self.pages['Settings'];settings_page.columnconfigure(0,weight=1)
        self.backdrop.label(settings_page,text='Your recording library',font=(fonts[1],19,'bold')).grid(row=0,column=0,sticky='w',pady=(0,12))
        self.library_path=tk.StringVar(value=str(self.recordings))
        self.library_label=self.backdrop.label(settings_page,textvariable=self.library_path,style='Card.TLabel',wraplength=640)
        self.library_label.grid(row=1,column=0,sticky='ew',pady=(0,12))
        choose=ttk.Button(settings_page,text='Choose recording folder…',command=self.choose_recordings)
        choose.grid(row=2,column=0,sticky='w',pady=(0,14));self.idle_buttons.append(choose)
        self.backdrop.label(settings_page,text='Choose your old Tanto Recordings folder to keep using it. Existing recordings stay intact. New sessions use this folder; Open session revisits an earlier one.',style='Card.TLabel',wraplength=640).grid(row=3,column=0,sticky='ew',pady=(0,24))
        self.backdrop.label(settings_page,text='Recording hotkey',font=(fonts[1],19,'bold')).grid(row=4,column=0,sticky='w',pady=(0,12))
        key=settings.get('hotkey','F8')
        try:parse_hotkey(key)
        except (ValueError,AttributeError):key='F8'
        self.key=tk.StringVar(value=key)
        keyrow=ttk.Frame(settings_page);keyrow.grid(row=5,column=0,sticky='ew',pady=(0,12))
        self.key_selector=ttk.Combobox(keyrow,textvariable=self.key,values=list(HOTKEYS),state='readonly',width=18)
        self.key_selector.pack(side='left');self.key_selector.bind('<<ComboboxSelected>>',self.configure_hotkey)
        self.bind_button=ttk.Button(keyrow,text='Bind a key…',command=self.begin_binding);self.bind_button.pack(side='left',padx=(12,0))
        self.hotkey_status=tk.StringVar(value='Hotkey off. Use Start / Stop above.')
        self.hotkey_label=self.backdrop.label(settings_page,textvariable=self.hotkey_status,style='Card.TLabel',wraplength=640)
        self.hotkey_label.grid(row=6,column=0,sticky='ew',pady=(0,12))
        self.backdrop.label(settings_page,text='Choose a preset or press Bind a key, then your keyboard shortcut. Escape cancels. Use a function key or Ctrl / Alt plus a letter or number. F1 opens this guide; Ctrl+S saves a description.',style='Muted.TLabel',wraplength=640).grid(row=7,column=0,sticky='ew')
        panel.bind('<Configure>',lambda event:self.resize_text(event.width))
        self.show_tab('Record')
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
        for label in (self.hotkey_label,self.help_label,self.note_label,self.library_label):label.configure(wraplength=max(240,width-56))
        self.session_label.configure(wraplength=max(160,(width-80)//2))
        self.status_label.configure(wraplength=max(180,width-300*self.scale))

    def show_tab(self,name):
        for page in self.pages.values():page.grid_remove()
        self.pages[name].grid(row=0,column=0,sticky='nsew');self.current_tab=name
        for title,button in self.tabs.items():button.configure(style='Selected.Tab.TButton' if title==name else 'Tab.TButton')
        if name=='Guide':
            if self.guide:self.guide.destroy()
            self.guide=QuickGuide(self.pages['Guide'],self.backdrop,self.finish_guide,self.key.get() if self.key.get()!='Off' else 'Start')
            self.guide.pack(fill='both',expand=True)
        self.backdrop.schedule_skin()

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
            atomic_json(self.settings_path,dict(hotkey=self.key.get(),tutorial_seen=self.tutorial_seen,tutorial_version=2 if self.tutorial_seen else 0,
                recordings_directory=str(self.recordings),
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
        if not self.closing:self.show_tab('Guide')

    def finish_guide(self):
        self.tutorial_seen=True;self.save_settings();self.show_tab('Record')

    def choose_recordings(self):
        if self.busy():return
        chosen=filedialog.askdirectory(title='Choose recording library (existing folders are welcome)',parent=self.root,
            initialdir=self.recordings if self.recordings.exists() else self.recordings.parent)
        if chosen:
            try:self.set_recordings(Path(chosen))
            except (OSError,ValueError) as error:self.status.set(str(error))

    def set_recordings(self,folder):
        if self.busy():return False
        folder=Path(folder).resolve()
        if (folder/'encounter.json').exists():raise ValueError('Choose the library containing your sessions, not an individual session.')
        if not self.save_settings():return False
        folder.mkdir(parents=True,exist_ok=True)
        if self.folder:self.new_session()
        self.recordings=folder;self.library_path.set(str(folder))
        self.status.set('Recording library selected. Existing sessions are preserved.')
        return self.save_settings()

    def begin_binding(self):
        if self.busy() or self.binding:return
        if self.hotkey:self.hotkey.close();self.hotkey=None
        self.hotkey_generation+=1
        self.bind_button.focus_set();self.hotkey_status.set('Press a shortcut now. Escape cancels.')
        self.binding=self.root.bind('<KeyPress>',self.capture_binding,add='+')

    def capture_binding(self,event):
        if event.keysym=='Escape':name=None
        else:
            try:name=key_event_name(event)
            except ValueError as error:self.hotkey_status.set(str(error));return 'break'
            if name is None:return 'break'
        self.root.unbind('<KeyPress>',self.binding);self.binding=None
        if name:self.key.set(name)
        if self.guide:self.guide.destroy();self.guide=None
        self.configure_hotkey();return 'break'

    def configure_hotkey(self,event=None,persist=True):
        self.hotkey_generation+=1;generation=self.hotkey_generation
        if self.hotkey: self.hotkey.close();self.hotkey=None
        self.hotkey_status.set('Hotkey off. Use Start / Stop above.' if self.key.get()=='Off' else 'Registering hotkey…')
        if self.enable_hotkey and self.key.get()!='Off':
            self.hotkey=GlobalHotkey(self.key.get(),lambda kind,value:self.events.put((kind,value,generation)))
        if persist: self.save_settings()

    def toggle(self):
        if self.closing or self.binding or self.operation=='export': return
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
        self.session_name.set('Previous session remains saved in your recording library')
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

    def export(self,folders=None):
        if self.busy() or self.closing:return
        if self.folder:
            if not self.save_description():return
        elif not self.save_settings():return
        if folders is None:
            if self.hotkey:self.hotkey.close();self.hotkey=None
            self.hotkey_generation+=1
            try:folders=choose_recording_folders(self.root.winfo_id(),self.recordings)
            except OSError as error:self.headline.set('Cannot choose folders');self.status.set(str(error));return
            finally:self.configure_hotkey(persist=False)
        if not folders:return
        self.operation='export';self.latest={};self.headline.set('Preparing export…')
        self.status.set(f'Packing {len(folders)} sessions. You can keep using the guide while this finishes.')
        def work():
            try:
                path=export_sessions(folders,downloads_dir()/'tanto-zips'/f'Tanto-{time.time_ns()}.zip')
                self.events.put(('exported',path,None))
            except Exception as error:self.events.put(('export_error',str(error),None))
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
        self.bind_button.configure(state='disabled' if busy else 'normal')
        self.key_selector.configure(state='disabled' if busy or self.binding else 'readonly')
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
        def finish():
            rendered=app.backdrop.picture.width()==app.backdrop.winfo_width()
            args.ui_smoke.write_text(json.dumps(dict(passed=not errors and rendered and saved and restored and app.guide.winfo_toplevel() is root,game_access=False,
                local_guide=app.guide.winfo_exists()==1,wallpaper_rendered=rendered,description_saved=saved,draft_restored=restored,errors=errors)))
            app.close();fixture.cleanup()
        root.after(500,finish)
    root.mainloop();return 0
