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
    # Make a readable glass-like panel using only the supplied wallpaper pixels.
    # Blur and tint the interior, magnify a narrow rim, and paint a lit rounded bevel.
    # This is a lightweight optical approximation; it never samples the desktop or game screen.
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
    # Convert a rendered RGB image into bytes Tk can display.
    # Pillow writes an in-memory PPM stream, avoiding temporary files and alpha-format differences.
    # This is UI pixel transport, not a screenshot or a change to the saved wallpaper asset.
    data=io.BytesIO();image.convert('RGB').save(data,format='PPM');return data.getvalue()


def update_image(photo,image):
    # Refresh an existing Tk image after its panel is repainted.
    # Replace its dimensions and PPM payload together so labels sample the correctly sized background.
    # Reusing the image object keeps Tk widget references valid across resizes.
    photo.configure(width=image.width,height=image.height,data=pixels(image),format='PPM')


@lru_cache(maxsize=1)
def load_fonts():
    # Make the bundled Inter fonts available only to this Recorder process.
    # AddFontResourceExW with FR_PRIVATE avoids installing fonts into the user's Windows font collection.
    # Cache the load so repeated windows/tests do not repeatedly register the same font resources.
    assets=Path(__file__).resolve().parent/'assets/fonts'
    gdi=C.WinDLL('gdi32');gdi.AddFontResourceExW.argtypes=[C.c_wchar_p,C.c_uint32,C.c_void_p]
    for path in assets.glob('*.ttf'):gdi.AddFontResourceExW(str(path),0x10,None)


def theme(root):
    # Configure larger type, dark inputs and beveled controls consistently across Recorder.
    # Prefer bundled Inter, retain installed-font fallbacks, and keep Tk references to generated button images.
    # The style layer changes presentation only; ordinary Tk controls keep their keyboard behavior.
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
        # Create the wallpaper canvas shared by panels, labels and saved-sequence rows.
        # Load the packaged/source asset through the product-root contract and retain the original pixels.
        # Track resize/repaint state locally so the glass treatment never needs desktop capture.
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
        # Cancel a queued wallpaper repaint when its canvas is destroyed.
        # Only handle destruction of this canvas, not a child widget's event.
        # Clearing the pending timer prevents a callback from touching a dead Tk object.
        if event.widget is self and self.pending:
            self.after_cancel(self.pending);self.pending=None

    def redraw(self,event):
        # Fit the unchanged wallpaper to the current window and reposition the header/content area.
        # Blend its pixels against the same dark base, then increment the layout revision.
        # Schedule panel repainting after Tk has settled widget geometry so every crop uses matching coordinates.
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
        self.tag_bind('guide','<Button-1>',lambda event: (
            # Make the header's Guide text act like the Guide tab.
            # Call the assigned application handler only after one has been connected.
            # The backdrop draws the link but does not own tutorial or recording state.
            self.on_guide() if self.on_guide else None
        ))
        if self.panel:
            self.coords(self.panel,24*s,96*s)
            self.itemconfigure(self.panel,width=max(1,width-48*s),height=max(1,height-116*s))
        self.schedule_skin()

    def crop(self,widget):
        # Return the background pixels directly underneath a child widget.
        # Translate root-window coordinates into wallpaper-canvas coordinates before cropping.
        # A minimum one-pixel image supports widgets that are still being laid out.
        x=widget.winfo_rootx()-self.winfo_rootx();y=widget.winfo_rooty()-self.winfo_rooty()
        return self.background.crop((x,y,x+max(1,widget.winfo_width()),y+max(1,widget.winfo_height())))

    def schedule_skin(self,event=None):
        # Coalesce repeated layout events into one background repaint.
        # Cancel the previous idle callback before scheduling its replacement.
        # Painting after layout avoids redundant work and mismatched panel/label samples during resizing.
        if self.pending: self.after_cancel(self.pending)
        self.pending=self.after_idle(self.skin)

    def label(self,parent,**options):
        # Create a text label whose background matches the composed wallpaper.
        # Pass the shared backdrop into the custom canvas label so its crop stays aligned.
        # The caller still supplies normal text, variables, fonts and wrapping options.
        return WallpaperLabel(parent,self,**options)

    def card(self,parent,**options):
        # Create a padded content panel and register its rectangle for glass rendering.
        # The frame handles layout; the backdrop paints the frosted surface beneath its children.
        # Track geometry changes so rounded panel edges follow resizes and tab switches.
        widget=ttk.Frame(parent,padding=(round(18*self.scale),round(12*self.scale)),**options)
        self.glass_widgets.append(widget);widget.bind('<Configure>',self.schedule_skin,add='+')
        return widget

    def skin(self):
        # Compose visible glass panels, then give each widget the pixels beneath it.
        # Cache the wallpaper revision and panel geometry to avoid recomputing an unchanged composition.
        # Custom painters draw their own text; ordinary frames receive a lowered image that cannot cover controls.
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
            # Walk the backdrop's widget tree in parent-before-child order.
            # Yield each descendant once so nested frames and their text can receive aligned samples.
            # This traverses UI objects only and never scans applications outside Recorder.
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
        # Draw readable text over the same pixels as its enclosing glass panel.
        # Measure the chosen font and subscribe to an optional Tk text variable.
        # Keep image and trace references alive until widget destruction so updates remain stable.
        self.wallpaper=wallpaper;self.text=text;self.variable=textvariable;self.wrap=wraplength
        self.typeface=font or (wallpaper.fonts[0],12)
        self.color=MUTED if style=='Muted.TLabel' else TEXT if style=='Card.TLabel' else ACCENT
        super().__init__(parent,background=BG,highlightthickness=0,height=22,width=1)
        self.photo=tk.PhotoImage(master=self,width=1,height=1)
        self.metrics=tkfont.Font(self,font=self.typeface)
        value=self.variable.get() if self.variable else self.text
        self.configure(width=min(wraplength or 10000,self.metrics.measure(value)),height=self.metrics.metrics('linespace'))
        self.bind('<Configure>',lambda event: (
            # Repaint this custom widget after its geometry changes.
            # Its paint method samples the aligned backdrop and redraws current text or rows.
            # The Configure event itself carries no persistent recording data.
            self.paint()
        ))
        self.trace=self.variable.trace_add('write',lambda *args: (
            # Repaint the label when its Tk text variable changes.
            # Trace arguments identify the variable change but the label reads its bound value directly.
            # Status updates therefore remain visually synchronized without a separate polling timer.
            self.paint()
        )) if self.variable else None
        self.bind('<Destroy>',self.dispose)
    def dispose(self,event):
        # Remove this label's subscription to its text variable when it is destroyed.
        # Check the event's widget because child destruction can also propagate through Tk.
        # Without removing the trace, later status updates could call a deleted label.
        if self.trace and event.widget is self:self.variable.trace_remove('write',self.trace)
    def configure(self,cnf=None,**options):
        # Accept a wrapping width in addition to ordinary Canvas options.
        # Store wraplength locally because a Canvas does not implement the Label-style option.
        # Forward all remaining options to Tk without changing text or application state.
        if 'wraplength' in options:self.wrap=options.pop('wraplength')
        return super().configure(cnf,**options)
    def paint(self):
        # Repaint the label's sampled background and current text.
        # Limit wrapping to the actual available width and measure the resulting canvas text bounds.
        # Adjust only the requested height when needed, preventing a constant resize/repaint loop.
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
        # Create the keyboard-accessible list of saved description previews.
        # Keep full row values and stable label IDs separately from the clipped text drawn on screen.
        # Connect mouse, arrow and wheel input locally; no events are sent to Nioh.
        super().__init__(parent,background=BG,highlightthickness=0,takefocus=True,height=190)
        self.wallpaper=wallpaper;self.rows={};self.chosen=();self.first=0;self.scroll=None;self.photo=tk.PhotoImage(master=self,width=1,height=1)
        self.metrics=tkfont.Font(self,font=(wallpaper.fonts[0],12))
        self.bind('<Configure>',lambda event: (
            # Repaint this custom widget after its geometry changes.
            # Its paint method samples the aligned backdrop and redraws current text or rows.
            # The Configure event itself carries no persistent recording data.
            self.paint()
        ));self.bind('<Button-1>',self.pick)
        self.bind('<MouseWheel>',lambda event: (
            # Convert a Windows mouse-wheel notch into saved-list row scrolling.
            # Wheel delta uses 120 units per notch; invert its sign to match downward list movement.
            # The list clamps the resulting first row instead of scrolling outside its stored descriptions.
            self.yview('scroll',-int(event.delta/120),'units')
        ))
        self.bind('<Up>',lambda event: (
            # Move the highlighted saved description one row upward.
            # The list's step method clamps the index and keeps selection visible.
            # This is local list navigation and does not modify annotation history.
            self.step(-1)
        ));self.bind('<Down>',lambda event: (
            # Move the highlighted saved description one row downward.
            # The list's step method also adjusts the first visible row when necessary.
            # Editing remains a separate Return or double-click action.
            self.step(1)
        ))

    def configure(self,cnf=None,**kwargs):
        # Accept the scrollbar callback alongside ordinary Canvas options.
        # Keep yscrollcommand locally because this list performs its own row-based scrolling.
        # Forward other configuration directly to Tk so sizing remains compatible with the surrounding layout.
        if 'yscrollcommand' in kwargs: self.scroll=kwargs.pop('yscrollcommand')
        return super().configure(cnf,**kwargs)

    def get_children(self):
        # Return the saved label IDs currently displayed by the list.
        # Dictionary insertion order preserves the annotation order chosen by the caller.
        # A tuple snapshot lets the caller delete/rebuild rows without mutating its iteration source.
        return tuple(self.rows)
    def selection(self):
        # Report the highlighted saved-label ID, if one exists.
        # Use a tuple to match the selection interface expected by the description editor.
        # Reading selection does not edit a description or move the scroll position.
        return self.chosen
    def selection_set(self,key):
        # Highlight a specific saved description and redraw its selection mark.
        # Store the stable annotation ID rather than its current visual row number.
        # This keeps selection meaningful when scrolling changes which rows are visible.
        self.chosen=(key,);self.paint()
    def delete(self,*keys):
        # Remove the requested preview rows from the UI model.
        # Clear selection because a previously highlighted annotation may have disappeared.
        # Repaint the list only; actual annotation history remains in the session's labels file.
        for key in keys: self.rows.pop(key,None)
        self.chosen=();self.paint()
    def insert(self,parent,index,iid=None,values=()):
        # Add one saved-description preview to the list's ordered model.
        # Use its annotation ID when supplied, retaining the complete take/time/text values.
        # Return the row ID for editor selection; drawing may shorten text without changing the stored value.
        key=iid or str(len(self.rows));self.rows[key]=values;self.paint();return key
    def page(self):
        # Calculate how many description rows fit below the list header.
        # Scale header and row heights with the window's DPI factor.
        # Keep at least one logical row so scrolling stays defined while the layout is being resized.
        return max(1,int((self.winfo_height()-35*self.wallpaper.scale)/(48*self.wallpaper.scale)))
    def yview(self,*args):
        # Translate scrollbar movement into the first visible description row.
        # Support both fractional jumps and relative row scrolling using the list's current size.
        # Painting clamps the result to the available range and reports updated scrollbar fractions.
        if args:
            self.first=int(float(args[1])*len(self.rows)) if args[0]=='moveto' else self.first+int(args[1])
            self.paint()
    def pick(self,event):
        # Select the description row underneath a mouse click.
        # Subtract the header height and translate the remaining position into a scrolled row index.
        # Ignore clicks in the header or below existing rows instead of selecting a different annotation.
        self.focus_set();index=self.first+int((event.y-35*self.wallpaper.scale)/(48*self.wallpaper.scale))
        if event.y>=35*self.wallpaper.scale and 0<=index<len(self.rows): self.selection_set(tuple(self.rows)[index])
    def step(self,direction):
        # Move the saved-description selection with the Up/Down keys.
        # Clamp the target index and scroll just enough to keep that row visible.
        # An empty list stays unchanged; full description text is loaded only by the editor action.
        keys=tuple(self.rows)
        if not keys:return
        index=max(0,min(len(keys)-1,(keys.index(self.chosen[0]) if self.chosen else -1)+direction))
        self.chosen=(keys[index],);self.first=min(self.first,index)
        if index>=self.first+self.page():self.first=index-self.page()+1
        self.paint()
    def paint(self):
        # Draw visible saved descriptions over their glass-panel background.
        # Clamp scrolling and shorten previews to fit columns, retaining complete text in the row model.
        # Report visible fractions to the scrollbar; rendering does not rewrite annotation files.
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
        # Build the tutorial as a scrollable page inside Recorder.
        # Describe library reuse, the current shortcut, notes and collection export using larger readable text.
        # The page owns no popup or input grab, so the shared Start/Stop controls remain available.
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
