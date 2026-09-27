"""Dithered wallpaper with sampled widget backgrounds and native keyboard controls."""
import io
import os
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont, ttk
from PIL import Image, ImageDraw, ImageOps

BG='#0c0b0b'; SURFACE='#1d1515'; INPUT='#302222'; TEXT='#eee4d0'; MUTED='#b7aa94'; ACCENT='#dec084'


def pixels(image):
    data=io.BytesIO();image.convert('RGB').save(data,format='PPM');return data.getvalue()


def update_image(photo,image):
    photo.configure(width=image.width,height=image.height,data=pixels(image),format='PPM')


def theme(root):
    families=set(tkfont.families(root))
    body=next((name for name in ('Segoe UI Variable Text','Segoe UI','Arial') if name in families),'Arial')
    title=next((name for name in ('Yu Mincho','MS Mincho','Yu Gothic','Meiryo') if name in families),body)
    root.configure(background=BG)
    style=ttk.Style(root);style.theme_use('clam')
    style.configure('.',background=BG,foreground=TEXT,font=(body,10),borderwidth=0,
                    bordercolor=INPUT,lightcolor=INPUT,darkcolor=INPUT)
    style.configure('TLabel',foreground=ACCENT)
    style.configure('TButton',background=BG,padding=(12,6),focusthickness=0)
    style.map('TButton',foreground=[('disabled',MUTED),('active',TEXT)],background=[('disabled',BG),('active',BG)])
    style.configure('Primary.TButton',foreground='#ffe3ac',font=(body,10,'bold'))
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
    for name,primary in (('TButton',False),('Primary.TButton',True),('TEntry',False),('TCombobox',False)):
        images=[]
        for color in (('#812a2a' if primary else INPUT),'#191616','#a23b36','#684036'):
            tile=Image.new('RGBA',(32,32));ImageDraw.Draw(tile).rounded_rectangle((0,0,31,31),radius=9,fill=color)
            data=io.BytesIO();tile.save(data,format='PNG');images.append(tk.PhotoImage(master=root,data=data.getvalue()))
        root.rounded_images.extend(images)
        children=style.layout(name)[0][1].get('children',[])
        element='Rounded'+name+'.surface'
        style.element_create(element,'image',images[0],('disabled',images[1]),('pressed',images[2]),('active',images[3]),border=9,sticky='nsew')
        style.layout(name,[(element,dict(sticky='nsew',**({'children':children} if children else {})))])
    return body,title


class InkBackdrop(tk.Canvas):
    def __init__(self,root,scale,fonts):
        super().__init__(root,background=BG,highlightthickness=0)
        self.scale=scale;self.fonts=fonts;self.panel=None;self.pending=None;self.skins={};self.revision=0;self.on_guide=None
        base=Path(os.environ.get('TANTO_PRODUCT_ROOT',Path(__file__).resolve().parents[1]))
        with Image.open(base/'src/assets/background.png') as image: self.source=image.convert('RGB')
        self.background=Image.new('RGB',(1,1),BG);self.picture=tk.PhotoImage(master=root,width=1,height=1)
        self.create_image(0,0,anchor='nw',image=self.picture,tags='wallpaper')
        self.pack(fill='both',expand=True);self.bind('<Configure>',self.redraw)
        self.bind('<Destroy>',self.dispose,add='+')

    def dispose(self,event):
        if event.widget is self and self.pending:
            self.after_cancel(self.pending);self.pending=None

    def redraw(self,event):
        width,height=event.width,event.height;s=self.scale
        fitted=ImageOps.fit(self.source,(max(1,width),max(1,height)),method=Image.Resampling.BILINEAR)
        self.background=Image.blend(Image.new('RGB',fitted.size,BG),fitted,.65)
        update_image(self.picture,self.background);self.revision+=1
        self.delete('title')
        self.create_text(26*s,17*s,anchor='nw',text='短刀',font=(self.fonts[1],27),fill=ACCENT,tags='title')
        self.create_text(115*s,23*s,anchor='nw',text='tanto recorder',font=(self.fonts[0],17,'bold'),fill=ACCENT,tags='title')
        self.create_text(28*s,69*s,anchor='nw',text='Capture. Describe. Share.',font=(self.fonts[0],10),fill=MUTED,tags='title')
        self.create_text(width-28*s,35*s,anchor='ne',text='Quick guide  /  F1',font=(self.fonts[0],10),fill=ACCENT,tags=('title','guide'))
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

    def skin(self):
        self.pending=None
        def visit(parent):
            for widget in parent.winfo_children():
                yield widget
                yield from visit(widget)
        for widget in visit(self):
            if hasattr(widget,'paint'): widget.paint();continue
            kind=widget.winfo_class()
            if kind not in ('TFrame','Canvas') or widget.winfo_width()<2 or widget.winfo_height()<2:continue
            box=(widget.winfo_rootx(),widget.winfo_rooty(),widget.winfo_width(),widget.winfo_height(),self.revision)
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
        self.typeface=font or (wallpaper.fonts[0],10)
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
            self.create_text(x*s,10*s,anchor='nw',text=title,fill=MUTED,font=(self.wallpaper.fonts[0],9))
        if not self.rows:
            self.create_text(8*s,55*s,anchor='nw',text='Your described sequences will appear here.',fill=MUTED,font=(self.wallpaper.fonts[0],10))
        for offset,key in enumerate(tuple(self.rows)[self.first:self.first+page]):
            y=(35+offset*48)*s;values=self.rows[key]
            if key in self.chosen:self.create_line(1,y+3*s,1,y+34*s,fill=ACCENT,width=2)
            for x,value in zip((8,106,246),values):
                self.create_text(x*s,y+6*s,anchor='nw',text=str(value),fill=TEXT if x==246 else MUTED,
                                 font=(self.wallpaper.fonts[0],10),width=max(1,w-x*s-10))
        if self.scroll:self.scroll(self.first/max(1,len(self.rows)),min(1,(self.first+page)/max(1,len(self.rows))))


class QuickGuide(tk.Toplevel):
    def __init__(self,root,wallpaper,done):
        super().__init__(root)
        self.title('Tanto Recorder · Quick guide');self.transient(root)
        s=wallpaper.scale;self.geometry(f'{round(580*s)}x{round(470*s)}');self.minsize(round(520*s),round(440*s))
        canvas=tk.Canvas(self,background=BG,highlightthickness=0);canvas.pack(fill='both',expand=True)
        self.picture=tk.PhotoImage(master=self,width=1,height=1)
        button=ttk.Button(canvas,text='Got it',style='Primary.TButton',command=done)
        def draw(event):
            size=(max(1,event.width),max(1,event.height))
            fitted=ImageOps.fit(wallpaper.source,size,method=Image.Resampling.BILINEAR)
            update_image(self.picture,Image.blend(Image.new('RGB',size,BG),fitted,.55))
            canvas.delete('all');canvas.create_image(0,0,anchor='nw',image=self.picture)
            y=26*s
            for text,point,color in [('Your first recording',19,ACCENT),
                    ('1. Enter the boss or enemy name.',11,TEXT),
                    ('2. Press F8 or Start. Wait for Recording before fighting.',11,TEXT),
                    ('3. Pause Nioh, F8 to stop. Type a description; click Save.',11,TEXT),
                    ('4. F8 adds another take. Export ZIP when finished.',11,TEXT),
                    ('Saved in Downloads / Tanto Recordings.\nDrafts and the last session reopen automatically. New names stay unverified.',10,MUTED)]:
                item=canvas.create_text(26*s,y,anchor='nw',text=text,width=max(1,event.width-52*s),
                    fill=color,font=(wallpaper.fonts[0],point,'bold' if point==19 else 'normal'))
                y=canvas.bbox(item)[3]+19*s
            canvas.create_window(event.width-26*s,event.height-22*s,anchor='se',window=button)
        canvas.bind('<Configure>',draw);self.protocol('WM_DELETE_WINDOW',done)
        self.bind('<Escape>',lambda event:done());button.focus_set()
