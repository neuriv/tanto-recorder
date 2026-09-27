"""Dithered wallpaper with sampled widget backgrounds and native keyboard controls."""
import io
import ctypes as C
from functools import lru_cache
import os
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont, ttk
from PIL import Image, ImageDraw, ImageOps, ImageFilter

BG='#0c0b0b'; SURFACE='#211e21'; INPUT='#272327'; TEXT='#faf4ea'; MUTED='#cec5b9'; ACCENT='#f0cf92'


def glass(image,scale=1):
    """Frosted wallpaper, a magnified rim and a lit bevel; no screen capture."""
    w,h=image.size;r=min(round(20*scale),w//2,h//2);edge=max(1,round(6*scale))
    mask=Image.new('L',image.size);draw=ImageDraw.Draw(mask)
    draw.rounded_rectangle((0,0,w-1,h-1),r,fill=255)
    rim=mask.copy();ImageDraw.Draw(rim).rounded_rectangle((edge,edge,w-edge-1,h-edge-1),max(0,r-edge),fill=0)
    warped=image.resize((w+edge*2,h+edge*2),Image.Resampling.BILINEAR).crop((edge,edge,w+edge,h+edge))
    material=Image.composite(warped,image.filter(ImageFilter.GaussianBlur(5*scale)),rim)
    material=Image.blend(material,Image.new('RGB',image.size,SURFACE),.68).convert('RGBA')
    sheen=Image.new('RGBA',image.size);draw=ImageDraw.Draw(sheen)
    for y in range(h):draw.line((0,y,w,y),fill=(255,239,211,round(17*(1-y/max(1,h-1)))))
    material=Image.alpha_composite(material,sheen).convert('RGB');draw=ImageDraw.Draw(material)
    draw.rounded_rectangle((0,0,w-1,h-1),r,outline='#766c64',width=max(1,round(scale)))
    draw.rounded_rectangle((2,2,w-3,h-3),max(0,r-2),outline='#383337')
    if w>2*r:draw.line((r,1,w-r,1),fill='#b1a18a',width=max(1,round(scale)))
    return Image.composite(material,image,mask)


def pixels(image):
    data=io.BytesIO();image.convert('RGB').save(data,format='PPM');return data.getvalue()


def update_image(photo,image):
    photo.configure(width=image.width,height=image.height,data=pixels(image),format='PPM')


@lru_cache(maxsize=1)
def load_fonts():
    assets=Path(__file__).resolve().parent/'assets/fonts'
    gdi=C.WinDLL('gdi32');gdi.AddFontResourceExW.argtypes=[C.c_wchar_p,C.c_uint32,C.c_void_p]
    for path in assets.glob('*.ttf'):gdi.AddFontResourceExW(str(path),0x10,None)


def theme(root):
    load_fonts()
    families=set(tkfont.families(root))
    body=next((name for name in ('Inter','Segoe UI Variable Text','Segoe UI','Arial') if name in families),'Arial')
    title=next((name for name in ('Inter SemiBold','Inter','Segoe UI') if name in families),body)
    root.configure(background=BG)
    style=ttk.Style(root);style.theme_use('clam')
    style.configure('.',background=BG,foreground=TEXT,font=(body,12),borderwidth=0,
                    bordercolor=INPUT,lightcolor=INPUT,darkcolor=INPUT)
    style.configure('TLabel',foreground=ACCENT)
    style.configure('TButton',background=BG,padding=(14,8),focusthickness=1,focuscolor=ACCENT)
    style.map('TButton',foreground=[('disabled',MUTED),('active',TEXT)],background=[('disabled',BG),('active',BG)])
    style.configure('Primary.TButton',foreground='#ffe8bc',font=(title,12,'bold'))
    style.configure('Tab.TButton',padding=(24,10))
    style.configure('Selected.Tab.TButton',foreground=ACCENT,font=(title,12,'bold'),padding=(24,10))
    style.configure('TEntry',fieldbackground=INPUT,insertcolor=TEXT,padding=8)
    style.configure('TCombobox',fieldbackground=INPUT,arrowcolor=ACCENT,padding=8)
    style.map('TCombobox',fieldbackground=[('readonly',INPUT)],selectbackground=[('readonly',INPUT)],selectforeground=[('readonly',TEXT)])
    style.configure('TCheckbutton',background=BG,indicatorbackground=INPUT)
    style.map('TCheckbutton',background=[('active',BG)])
    style.configure('Card.TFrame',background=BG)
    style.configure('Card.TLabel',background=BG,foreground=TEXT)
    style.configure('Muted.TLabel',foreground=MUTED)
    style.configure('Vertical.TScrollbar',background=INPUT,troughcolor=BG,arrowcolor=MUTED,
                    bordercolor=BG,lightcolor=INPUT,darkcolor=INPUT,arrowsize=10)
    root.option_add('*TCombobox*Listbox.background',INPUT)
    root.option_add('*TCombobox*Listbox.foreground',TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground','#673030')
    root.rounded_images=[]
    for name,primary in (('TButton',False),('Primary.TButton',True),('Tab.TButton',False),('Selected.Tab.TButton',True),('TEntry',False),('TCombobox',False)):
        images=[]
        for color in (('#62342e' if primary else '#343035'),'#201d20','#96513e','#51464a'):
            tile=Image.new('RGBA',(48,48));draw=ImageDraw.Draw(tile)
            draw.rounded_rectangle((1,1,46,46),radius=16,fill=color,outline='#887b69')
            draw.rounded_rectangle((3,3,44,44),radius=14,outline='#44383b')
            draw.line((16,2,32,2),fill='#c0ac89',width=1)
            data=io.BytesIO();tile.save(data,format='PNG');images.append(tk.PhotoImage(master=root,data=data.getvalue()))
        root.rounded_images.extend(images)
        children=style.layout(name)[0][1].get('children',[])
        element='Rounded'+name+'.surface'
        style.element_create(element,'image',images[0],('disabled',images[1]),('pressed',images[2]),('active',images[3]),border=16,sticky='nsew')
        style.layout(name,[(element,dict(sticky='nsew',**({'children':children} if children else {})))])
    return body,title


class InkBackdrop(tk.Canvas):
    def __init__(self,root,scale,fonts):
        super().__init__(root,background=BG,highlightthickness=0)
        self.scale=scale;self.fonts=fonts;self.panel=None;self.pending=None;self.skins={};self.revision=0;self.on_guide=None
        self.glass_widgets=[];self.composition=None;self.paint_revision=0
        base=Path(os.environ.get('TANTO_PRODUCT_ROOT',Path(__file__).resolve().parents[1]))
        with Image.open(base/'src/assets/background.png') as image: self.source=image.convert('RGB')
        self.background=Image.new('RGB',(1,1),BG);self.picture=tk.PhotoImage(master=root,width=1,height=1)
        self.wallpaper=self.background
        self.create_image(0,0,anchor='nw',image=self.picture,tags='wallpaper')
        self.pack(fill='both',expand=True);self.bind('<Configure>',self.redraw)
        self.bind('<Destroy>',self.dispose,add='+')

    def dispose(self,event):
        if event.widget is self and self.pending:
            self.after_cancel(self.pending);self.pending=None

    def redraw(self,event):
        width,height=event.width,event.height;s=self.scale
        fitted=ImageOps.fit(self.source,(max(1,width),max(1,height)),method=Image.Resampling.BILINEAR)
        self.wallpaper=Image.blend(Image.new('RGB',fitted.size,BG),fitted,.65)
        self.background=self.wallpaper.copy()
        update_image(self.picture,self.background);self.revision+=1
        self.delete('title')
        self.create_text(26*s,17*s,anchor='nw',text='短刀',font=('Yu Mincho',30),fill=ACCENT,tags='title')
        self.create_text(115*s,21*s,anchor='nw',text='tanto recorder',font=(self.fonts[1],24,'bold'),fill=TEXT,tags='title')
        self.create_text(118*s,60*s,anchor='nw',text='Capture. Describe. Share.',font=(self.fonts[0],12),fill=MUTED,tags='title')
        self.create_text(width-28*s,35*s,anchor='ne',text='Guide  /  F1',font=(self.fonts[0],12),fill=ACCENT,tags=('title','guide'))
        self.tag_bind('guide','<Button-1>',lambda event:self.on_guide() if self.on_guide else None)
        if self.panel:
            self.coords(self.panel,24*s,96*s)
            self.itemconfigure(self.panel,width=max(1,width-48*s),height=max(1,height-116*s))
        self.schedule_skin()

    def crop(self,widget):
        x=widget.winfo_rootx()-self.winfo_rootx();y=widget.winfo_rooty()-self.winfo_rooty()
        return self.background.crop((x,y,x+max(1,widget.winfo_width()),y+max(1,widget.winfo_height())))

    def schedule_skin(self,event=None):
        if self.pending: self.after_cancel(self.pending)
        self.pending=self.after_idle(self.skin)

    def label(self,parent,**options):
        return WallpaperLabel(parent,self,**options)

    def card(self,parent,**options):
        widget=ttk.Frame(parent,padding=(round(18*self.scale),round(12*self.scale)),**options)
        self.glass_widgets.append(widget);widget.bind('<Configure>',self.schedule_skin,add='+')
        return widget

    def skin(self):
        self.pending=None
        boxes=[(widget.winfo_rootx()-self.winfo_rootx(),widget.winfo_rooty()-self.winfo_rooty(),
                widget.winfo_width(),widget.winfo_height()) for widget in self.glass_widgets if widget.winfo_ismapped()]
        composition=(self.revision,tuple(boxes))
        if composition!=self.composition:
            self.background=self.wallpaper.copy()
            for x,y,w,h in boxes:
                if w>40 and h>40:self.background.paste(glass(self.background.crop((x,y,x+w,y+h)),self.scale),(x,y))
            update_image(self.picture,self.background);self.composition=composition;self.paint_revision+=1
        def visit(parent):
            for widget in parent.winfo_children():
                yield widget
                yield from visit(widget)
        for widget in visit(self):
            if hasattr(widget,'paint'): widget.paint();continue
            kind=widget.winfo_class()
            if kind not in ('TFrame','Canvas') or widget.winfo_width()<2 or widget.winfo_height()<2:continue
            box=(widget.winfo_rootx(),widget.winfo_rooty(),widget.winfo_width(),widget.winfo_height(),self.paint_revision)
            record=self.skins.get(widget)
            if record and record['box']==box:continue
            if record is None:
                image=tk.PhotoImage(master=self,width=1,height=1)
                if kind=='Canvas':
                    item=widget.create_image(0,0,anchor='nw',image=image);widget.tag_lower(item)
                else:
                    background=tk.Label(widget,image=image,borderwidth=0,highlightthickness=0,padx=0,pady=0,anchor='nw')
                    background.place(x=0,y=0,relwidth=1,relheight=1);background.lower()
                record=self.skins[widget]=dict(image=image)
                widget.bind('<Configure>',self.schedule_skin,add='+')
            update_image(record['image'],self.crop(widget));record['box']=box


class WallpaperLabel(tk.Canvas):
    def __init__(self,parent,wallpaper,text='',textvariable=None,font=None,style='',wraplength=0):
        self.wallpaper=wallpaper;self.text=text;self.variable=textvariable;self.wrap=wraplength
        self.typeface=font or (wallpaper.fonts[0],12)
        self.color=MUTED if style=='Muted.TLabel' else TEXT if style=='Card.TLabel' else ACCENT
        super().__init__(parent,background=BG,highlightthickness=0,height=22,width=1)
        self.photo=tk.PhotoImage(master=self,width=1,height=1)
        self.metrics=tkfont.Font(self,font=self.typeface)
        value=self.variable.get() if self.variable else self.text
        self.configure(width=min(wraplength or 10000,self.metrics.measure(value)),height=self.metrics.metrics('linespace'))
        self.bind('<Configure>',lambda event:self.paint())
        self.trace=self.variable.trace_add('write',lambda *args:self.paint()) if self.variable else None
        self.bind('<Destroy>',self.dispose)
    def dispose(self,event):
        if self.trace and event.widget is self:self.variable.trace_remove('write',self.trace)
    def configure(self,cnf=None,**options):
        if 'wraplength' in options:self.wrap=options.pop('wraplength')
        return super().configure(cnf,**options)
    def paint(self):
        if self.winfo_width()<2:return
        update_image(self.photo,self.wallpaper.crop(self))
        self.delete('all');self.create_image(0,0,anchor='nw',image=self.photo)
        item=self.create_text(0,0,anchor='nw',text=self.variable.get() if self.variable else self.text,
            fill=self.color,font=self.typeface,width=max(1,min(self.wrap or 10000,self.winfo_width())))
        bounds=self.bbox(item);height=max(self.metrics.metrics('linespace'),bounds[3] if bounds else 1)
        if int(self.cget('height'))!=height:super().configure(height=height)


class SequenceList(tk.Canvas):
    """Small keyboard-accessible description list drawn directly over the wallpaper."""
    def __init__(self,parent,wallpaper):
        super().__init__(parent,background=BG,highlightthickness=0,takefocus=True,height=190)
        self.wallpaper=wallpaper;self.rows={};self.chosen=();self.first=0;self.scroll=None;self.photo=tk.PhotoImage(master=self,width=1,height=1)
        self.metrics=tkfont.Font(self,font=(wallpaper.fonts[0],12))
        self.bind('<Configure>',lambda event:self.paint());self.bind('<Button-1>',self.pick)
        self.bind('<MouseWheel>',lambda event:self.yview('scroll',-int(event.delta/120),'units'))
        self.bind('<Up>',lambda event:self.step(-1));self.bind('<Down>',lambda event:self.step(1))

    def configure(self,cnf=None,**kwargs):
        if 'yscrollcommand' in kwargs: self.scroll=kwargs.pop('yscrollcommand')
        return super().configure(cnf,**kwargs)

    def get_children(self): return tuple(self.rows)
    def selection(self): return self.chosen
    def selection_set(self,key): self.chosen=(key,);self.paint()
    def delete(self,*keys):
        for key in keys: self.rows.pop(key,None)
        self.chosen=();self.paint()
    def insert(self,parent,index,iid=None,values=()):
        key=iid or str(len(self.rows));self.rows[key]=values;self.paint();return key
    def page(self): return max(1,int((self.winfo_height()-35*self.wallpaper.scale)/(48*self.wallpaper.scale)))
    def yview(self,*args):
        if args:
            self.first=int(float(args[1])*len(self.rows)) if args[0]=='moveto' else self.first+int(args[1])
            self.paint()
    def pick(self,event):
        self.focus_set();index=self.first+int((event.y-35*self.wallpaper.scale)/(48*self.wallpaper.scale))
        if event.y>=35*self.wallpaper.scale and 0<=index<len(self.rows): self.selection_set(tuple(self.rows)[index])
    def step(self,direction):
        keys=tuple(self.rows)
        if not keys:return
        index=max(0,min(len(keys)-1,(keys.index(self.chosen[0]) if self.chosen else -1)+direction))
        self.chosen=(keys[index],);self.first=min(self.first,index)
        if index>=self.first+self.page():self.first=index-self.page()+1
        self.paint()
    def paint(self):
        if self.winfo_width()<2:return
        s=self.wallpaper.scale;w=self.winfo_width();page=self.page();self.first=max(0,min(self.first,max(0,len(self.rows)-page)))
        update_image(self.photo,self.wallpaper.crop(self))
        super().delete('all');self.create_image(0,0,anchor='nw',image=self.photo)
        for x,title in ((8,'Take'),(106,'Seconds'),(246,'Description')):
            self.create_text(x*s,10*s,anchor='nw',text=title,fill=MUTED,font=(self.wallpaper.fonts[0],11))
        if not self.rows:
            self.create_text(8*s,55*s,anchor='nw',text='Your described sequences will appear here.',fill=MUTED,font=(self.wallpaper.fonts[0],12))
        for offset,key in enumerate(tuple(self.rows)[self.first:self.first+page]):
            y=(35+offset*48)*s;values=self.rows[key]
            if key in self.chosen:self.create_line(1,y+3*s,1,y+34*s,fill=ACCENT,width=2)
            for x,value in zip((8,106,246),values):
                limit=(90 if x==8 else 132)*s if x!=246 else max(1,w-x*s-10)
                text=' '.join(str(value).split());preview=text[:160]
                while len(preview)>1 and self.metrics.measure(preview+'…')>limit:preview=preview[:-1]
                if preview!=text:preview+='…'
                self.create_text(x*s,y+6*s,anchor='nw',text=preview,fill=TEXT if x==246 else MUTED,
                                 font=(self.wallpaper.fonts[0],12))
        if self.scroll:self.scroll(self.first/max(1,len(self.rows)),min(1,(self.first+page)/max(1,len(self.rows))))


class QuickGuide(ttk.Frame):
    def __init__(self,parent,wallpaper,done,key):
        super().__init__(parent);self.columnconfigure(0,weight=1);self.rowconfigure(0,weight=1)
        text=tk.Text(self,wrap='word',background=INPUT,foreground=TEXT,relief='flat',borderwidth=0,
            font=(wallpaper.fonts[0],13),padx=18,pady=14,width=1,height=1,cursor='arrow')
        text.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(self,orient='vertical',command=text.yview);scroll.grid(row=0,column=1,sticky='ns')
        text.configure(yscrollcommand=scroll.set)
        text.tag_configure('heading',foreground=ACCENT,font=(wallpaper.fonts[1],15,'bold'),spacing1=12,spacing3=6)
        steps=[('Your first recording','Choose a library in Settings. An existing Tanto Recordings folder works; its sessions stay intact.'),
            ('01  Name the encounter','On Record, enter a boss or enemy name. One encounter per session. Names alone do not verify an actor.'),
            ('02  Start, then fight',f'Press {key} or Start recording. Wait for Recording and the rising tone before fighting. Change the keyboard shortcut in Settings.'),
            ('03  Stop and describe','Pause Nioh yourself, then use the same key or Stop. Wait for Stopped and the falling tone. Describe the sequence; Save or Ctrl+S.'),
            ('04  Continue or revisit','Resume adds takes. New session preserves the old one. Open session restores notes; double-click a saved description to edit it. Drafts save automatically.'),
            ('05  Select and share','Export ZIP opens Explorer. Ctrl / Shift-select session folders from any bosses. The complete ZIP appears in Downloads / tanto-zips. Share it yourself; nothing uploads.'),
            ('Always available','Return here with the Guide tab or F1. Start / Stop stays above every tab. Recording observes game memory; it does not control the game or capture its screen.')]
        for title,body in steps:
            text.insert('end',title+'\n','heading');text.insert('end',body+'\n\n')
        text.configure(state='disabled');self.text=text
        self.done=ttk.Button(self,text='Got it · back to recording',style='Primary.TButton',command=done)
        self.done.grid(row=1,column=0,sticky='w',pady=(14,0))
