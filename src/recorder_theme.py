"""Dithered wallpaper with sampled widget backgrounds and native keyboard controls."""
import io
import ctypes as C
from functools import lru_cache
import os
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont, ttk
from PIL import Image, ImageOps

BG='#0c0b0b'; SURFACE='#191619'; INPUT='#292329'; TEXT='#f5ead8'; MUTED='#c6bba9'; ACCENT='#e9c58c'


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
    # Make the bundled Source Serif fonts available only to this Recorder process.
    # AddFontResourceExW with FR_PRIVATE avoids installing fonts into the user's Windows font collection.
    # Cache the load so repeated windows/tests do not repeatedly register the same font resources.
    assets=Path(__file__).resolve().parent/'assets/fonts'
    gdi=C.WinDLL('gdi32');gdi.AddFontResourceExW.argtypes=[C.c_wchar_p,C.c_uint32,C.c_void_p]
    for path in assets.glob('*.ttf'):gdi.AddFontResourceExW(str(path),0x10,None)


def theme(root):
    # Use compact serif type and flat dark surfaces with one warm accent color.
    # Prefer the bundled Small Text face; native control layouts retain their fields, arrows and focus behavior.
    # Font registration is private to this process, so a standalone EXE needs no font installation.
    load_fonts()
    families=set(tkfont.families(root))
    body=next((name for name in ('Source Serif 4 SmText','Georgia','Cambria') if name in families),'Times New Roman')
    title=next((name for name in ('Source Serif 4 SmText Semibold','Source Serif 4 SmText') if name in families),body)
    root.configure(background=BG)
    style=ttk.Style(root);style.theme_use('clam')
    style.configure('.',background=BG,foreground=TEXT,font=(body,10),borderwidth=0,
                    bordercolor=INPUT,lightcolor=INPUT,darkcolor=INPUT)
    style.configure('TLabel',foreground=ACCENT)
    style.configure('TButton',background=INPUT,padding=(12,6),focusthickness=1,focuscolor=ACCENT,relief='flat')
    style.map('TButton',foreground=[('disabled',MUTED),('active',TEXT)],background=[('disabled',SURFACE),('active','#42312b')])
    style.configure('Primary.TButton',foreground=TEXT,background='#5c322b',font=(title,10,'bold'))
    style.map('Primary.TButton',background=[('disabled',SURFACE),('active','#754137')])
    style.configure('Tab.TButton',padding=(16,6),width=12)
    style.configure('Selected.Tab.TButton',foreground=ACCENT,background='#42312b',font=(title,10,'bold'),padding=(16,6))
    style.configure('TEntry',fieldbackground=INPUT,insertcolor=TEXT,padding=8)
    style.configure('TCombobox',fieldbackground=INPUT,arrowcolor=ACCENT,padding=8)
    style.map('TCombobox',fieldbackground=[('readonly',INPUT)],selectbackground=[('readonly',INPUT)],selectforeground=[('readonly',TEXT)])
    style.configure('TCheckbutton',background=BG,indicatorbackground=INPUT)
    style.configure('Horizontal.TScale',background=ACCENT,troughcolor=INPUT)
    style.map('TCheckbutton',background=[('active',BG)])
    style.configure('Card.TFrame',background=SURFACE)
    style.configure('Card.TLabel',background=SURFACE,foreground=TEXT)
    style.configure('Muted.TLabel',foreground=MUTED)
    style.configure('Vertical.TScrollbar',background=INPUT,troughcolor=BG,arrowcolor=MUTED,
                    bordercolor=BG,lightcolor=INPUT,darkcolor=INPUT,arrowsize=10)
    root.option_add('*TCombobox*Listbox.background',INPUT)
    root.option_add('*TCombobox*Listbox.foreground',TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground','#673030')
    return body,title


def fit_window(root,scale):
    # Start with the original 960 by 740 layout and keep it inside the usable Windows desktop.
    # Reserve titlebar space; cap this app's text scaling only if its minimum layout would not fit.
    # This reads display bounds only; it never moves, captures or controls another application's window.
    from ctypes import wintypes
    area=wintypes.RECT()
    if not C.windll.user32.SystemParametersInfoW(48,0,C.byref(area),0):
        area.right=root.winfo_screenwidth();area.bottom=root.winfo_screenheight()
    available_width=area.right-area.left-24;available_height=area.bottom-area.top-60
    fitted=min(scale,available_width/680,available_height/650)
    if fitted<scale:root.tk.call('tk','scaling',fitted*(96/72))
    scale=fitted
    width=min(round(960*scale),available_width)
    height=min(round(740*scale),available_height)
    root.geometry(f'{width}x{height}+{area.left+(area.right-area.left-width)//2}+{area.top+max(0,(area.bottom-area.top-height-40)//2)}')
    root.minsize(min(round(680*scale),width),min(round(650*scale),height))
    return scale


class InkBackdrop(tk.Canvas):
    def __init__(self,root,scale,fonts):
        # Create the wallpaper canvas shared by panels, labels and saved-sequence rows.
        # Load the packaged/source asset through the product-root contract and retain the original pixels.
        # Track resize/repaint state locally; no effect needs desktop or game capture.
        super().__init__(root,background=BG,highlightthickness=0)
        self.scale=scale;self.fonts=fonts;self.panel=None;self.pending=None;self.skins={};self.revision=0;self.on_guide=None
        base=Path(os.environ.get('TANTO_PRODUCT_ROOT',Path(__file__).resolve().parents[1]))
        with Image.open(base/'src/assets/background.png') as image: self.source=image.convert('RGB')
        self.background=Image.new('RGB',(1,1),BG);self.picture=tk.PhotoImage(master=root,width=1,height=1)
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
        self.background=Image.blend(Image.new('RGB',fitted.size,BG),fitted,.65)
        update_image(self.picture,self.background);self.revision+=1
        self.delete('title')
        self.create_text(26*s,17*s,anchor='nw',text='短刀',font=('Yu Mincho',27),fill=ACCENT,tags='title')
        self.create_text(115*s,23*s,anchor='nw',text='tanto recorder',font=(self.fonts[1],17,'bold'),fill=TEXT,tags='title')
        self.create_text(28*s,69*s,anchor='nw',text='Capture. Describe. Share.',font=(self.fonts[0],10),fill=MUTED,tags='title')
        self.create_text(width-28*s,35*s,anchor='ne',text='Guide  /  F1',font=(self.fonts[0],10),fill=ACCENT,tags=('title','guide'))
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
        # Give a child its enclosing solid panel color or the wallpaper underneath it.
        # Walk widget parents so nested rows share the panel surface without blurred or offset copies.
        # Keep a one-pixel minimum for widgets still being laid out.
        parent=widget
        while parent is not None and parent is not self:
            if getattr(parent,'solid_surface',False):
                return Image.new('RGB',(max(1,widget.winfo_width()),max(1,widget.winfo_height())),SURFACE)
            parent=parent.master
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
        # Group related controls on one opaque, dark reading surface.
        # Mark the parent so nested labels and frames inherit the same color.
        # Compact padding keeps the original window size useful without any glass rendering.
        widget=ttk.Frame(parent,style='Card.TFrame',padding=(round(12*self.scale),round(8*self.scale)),**options)
        widget.solid_surface=True
        return widget

    def skin(self):
        # Align wallpaper samples and solid panel surfaces underneath their controls.
        # Cache geometry and wallpaper revisions so unchanged frames do not keep copying images.
        # Lower frame backgrounds beneath controls and include padding in their painted area.
        self.pending=None
        self.skins={widget:record for widget,record in self.skins.items() if widget.winfo_exists()}
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
            box=(widget.winfo_rootx(),widget.winfo_rooty(),widget.winfo_width(),widget.winfo_height(),self.revision)
            record=self.skins.get(widget)
            if record and record['box']==box:continue
            if record is None:
                image=tk.PhotoImage(master=self,width=1,height=1)
                if kind=='Canvas':
                    item=widget.create_image(0,0,anchor='nw',image=image);widget.tag_lower(item)
                else:
                    background=tk.Label(widget,image=image,borderwidth=0,highlightthickness=0,padx=0,pady=0,anchor='nw')
                    # Include frame padding in the image area so its sampled pixels start at the real panel origin.
                    background.place(x=0,y=0,relwidth=1,relheight=1,bordermode='outside');background.lower()
                record=self.skins[widget]=dict(image=image)
                widget.bind('<Configure>',self.schedule_skin,add='+')
            update_image(record['image'],self.crop(widget));record['box']=box


class WallpaperLabel(tk.Canvas):
    def __init__(self,parent,wallpaper,text='',textvariable=None,font=None,style='',wraplength=0):
        # Draw readable text on its enclosing solid panel or sampled wallpaper.
        # Measure the chosen font and subscribe to an optional Tk text variable.
        # Keep image and trace references alive until widget destruction so updates remain stable.
        self.wallpaper=wallpaper;self.text=text;self.variable=textvariable;self.wrap=wraplength
        self.typeface=font or (wallpaper.fonts[0],10)
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
        self.metrics=tkfont.Font(self,font=(wallpaper.fonts[0],10))
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
        # Draw visible saved descriptions on the same solid surface as their panel.
        # Clamp scrolling and shorten previews to fit columns, retaining complete text in the row model.
        # Report visible fractions to the scrollbar; rendering does not rewrite annotation files.
        if self.winfo_width()<2:return
        s=self.wallpaper.scale;w=self.winfo_width();page=self.page();self.first=max(0,min(self.first,max(0,len(self.rows)-page)))
        update_image(self.photo,self.wallpaper.crop(self))
        super().delete('all');self.create_image(0,0,anchor='nw',image=self.photo)
        for x,title in ((8,'Take'),(106,'Seconds'),(246,'Description')):
            self.create_text(x*s,10*s,anchor='nw',text=title,fill=MUTED,font=(self.wallpaper.fonts[0],10))
        if not self.rows:
            self.create_text(8*s,55*s,anchor='nw',text='Your described sequences will appear here.',fill=MUTED,font=(self.wallpaper.fonts[0],10))
        for offset,key in enumerate(tuple(self.rows)[self.first:self.first+page]):
            y=(35+offset*48)*s;values=self.rows[key]
            if key in self.chosen:self.create_line(1,y+3*s,1,y+34*s,fill=ACCENT,width=2)
            for x,value in zip((8,106,246),values):
                limit=(90 if x==8 else 132)*s if x!=246 else max(1,w-x*s-10)
                text=' '.join(str(value).split());preview=text[:160]
                while len(preview)>1 and self.metrics.measure(preview+'…')>limit:preview=preview[:-1]
                if preview!=text:preview+='…'
                self.create_text(x*s,y+6*s,anchor='nw',text=preview,fill=TEXT if x==246 else MUTED,
                                 font=(self.wallpaper.fonts[0],10))
        if self.scroll:self.scroll(self.first/max(1,len(self.rows)),min(1,(self.first+page)/max(1,len(self.rows))))


class QuickGuide(ttk.Frame):
    def __init__(self,parent,wallpaper,done,key):
        # Fit four short recording steps into the original default window.
        # Keep scrolling available for smaller windows and describe the real shortcut, including Off.
        # The inline page never grabs input or hides the shared Start/Stop control.
        super().__init__(parent);self.columnconfigure(0,weight=1);self.rowconfigure(0,weight=1)
        text=tk.Text(self,wrap='word',background=SURFACE,foreground=TEXT,relief='flat',borderwidth=0,
            font=(wallpaper.fonts[0],11),padx=8,pady=4,width=1,height=1,cursor='arrow')
        text.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(self,orient='vertical',command=text.yview);scroll.grid(row=0,column=1,sticky='ns')
        def position_scroll(first,last):
            # Show scrolling only when a smaller window cannot fit the complete intro.
            # Convert Tk's fractional strings before checking whether both ends are visible.
            # Removing the scrollbar preserves its grid settings for later resizes.
            scroll.set(first,last)
            if float(first)<=0 and float(last)>=1:scroll.grid_remove()
            else:scroll.grid()
        text.configure(yscrollcommand=position_scroll)
        text.tag_configure('heading',foreground=ACCENT,font=(wallpaper.fonts[1],12,'bold'),spacing1=4,spacing3=2)
        trigger=f'Press {key} or click Start recording' if key!='Off' else 'Click Start recording'
        steps=[('01  Name the encounter','Enter the boss or enemy name on Record. Keep one encounter per session.'),
            ('02  Record, then stop',f'{trigger}. Wait for Recording, then fight. Pause Nioh yourself before stopping.'),
            ('03  Describe and continue','After Stopped, write what happened and Save or Ctrl+S. Start again to add a take; double-click a saved description to edit.'),
            ('04  Export and share','Export ZIP opens Explorer. Select saved session folders; share the ZIP from Downloads/tanto-zips.')]
        for title,body in steps:
            text.insert('end',title+'\n','heading');text.insert('end',body+'\n')
        text.insert('end','\nSettings holds your recording folder, hotkey and sound volume. Drafts save automatically. F1 reopens this guide.')
        text.configure(state='disabled');self.text=text
        self.done=ttk.Button(self,text='Got it · back to recording',style='Primary.TButton',command=done)
        self.done.grid(row=1,column=0,sticky='w',pady=(8,0))
