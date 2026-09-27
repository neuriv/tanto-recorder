"""Code-drawn ink, vermilion and gold. No image/font downloads or runtime assets."""
import math
import tkinter as tk
from tkinter import font, ttk

BG='#100d0d'; SURFACE='#1e1515'; INPUT='#302020'; TEXT='#f0e5cf'; MUTED='#bfae98'; ACCENT='#dfbc70'


def theme(root):
    families=set(font.families(root))
    body=next((name for name in ('Segoe UI Variable Text','Segoe UI','Arial') if name in families),'TkDefaultFont')
    title=next((name for name in ('Yu Mincho','MS Mincho','Yu Gothic','Meiryo') if name in families),body)
    root.configure(background=BG)
    style=ttk.Style(root);style.theme_use('clam')
    style.configure('.',background=BG,foreground=TEXT,font=(body,10),borderwidth=0,
                    bordercolor=INPUT,lightcolor=INPUT,darkcolor=INPUT)
    style.configure('TLabel',foreground=ACCENT)
    style.configure('TButton',background=INPUT,padding=(12,9),focusthickness=2,focuscolor=ACCENT)
    style.map('TButton',background=[('active','#532727'),('disabled',SURFACE)],foreground=[('disabled',MUTED)])
    style.configure('Primary.TButton',background='#922b2b',foreground='#ffe3a1',font=(body,10,'bold'))
    style.map('Primary.TButton',background=[('active','#b23838'),('disabled',INPUT)],foreground=[('disabled',MUTED)])
    style.configure('TEntry',fieldbackground=INPUT,insertcolor=TEXT,padding=8)
    style.configure('TCombobox',fieldbackground=INPUT,arrowcolor=ACCENT,padding=7)
    style.map('TCombobox',fieldbackground=[('readonly',INPUT)],selectbackground=[('readonly',INPUT)],selectforeground=[('readonly',TEXT)])
    style.configure('TCheckbutton',background=BG,indicatorbackground=INPUT)
    style.map('TCheckbutton',background=[('active',BG)])
    style.configure('Card.TFrame',background=SURFACE)
    style.configure('Card.TLabel',background=SURFACE,foreground=TEXT)
    style.configure('Muted.TLabel',foreground=MUTED)
    style.configure('Treeview',background=SURFACE,fieldbackground=SURFACE,rowheight=32)
    style.map('Treeview',background=[('selected','#673030')],foreground=[('selected',TEXT)])
    style.configure('Treeview.Heading',background=INPUT,foreground=ACCENT,padding=8)
    style.configure('Vertical.TScrollbar',background=INPUT,troughcolor=BG,arrowcolor=MUTED,
                    bordercolor=BG,lightcolor=INPUT,darkcolor=INPUT)
    root.option_add('*TCombobox*Listbox.background',INPUT)
    root.option_add('*TCombobox*Listbox.foreground',TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground','#673030')
    return body,title


class InkBackdrop(tk.Canvas):
    def __init__(self,root,scale,fonts):
        super().__init__(root,background=BG,highlightthickness=0)
        self.scale=scale;self.fonts=fonts;self.panel=None
        self.pack(fill='both',expand=True)
        self.bind('<Configure>',self.redraw)

    def redraw(self,event):
        width,height=event.width,event.height;s=self.scale
        self.delete('ink')
        # A restrained gradient and ASCII mountains/waves remain behind opaque controls.
        for row in range(32):
            fade=(1-row/32)**2
            color=f'#{int(16+35*fade):02x}{int(13+3*fade):02x}{int(13+5*fade):02x}'
            self.create_rectangle(0,row*height/32,width,(row+1)*height/32+1,fill=color,outline='',tags='ink')
        columns=max(1,int(width/(7*s)))
        for row in range(16):
            chars=[]
            for column in range(columns):
                x=column/max(1,columns-1)
                radius=math.hypot((x-.80)*65,(row-4)*1.25)
                ridge=8+abs(x-.68)*18
                char=' .:+*#'[max(0,min(5,int(6-radius)))] if radius<6 else ' '
                if abs(row-ridge)<.55: char='/' if x<.68 else '\\'
                elif row>11 and (column+row*3)%11<5: char='~' if row%2 else '.'
                chars.append(char)
            self.create_text(0,row*7*s,anchor='nw',text=''.join(chars),font=('Consolas',8),fill='#663434',tags='ink')
        # Clear the title region so texture never competes with the typography.
        self.create_rectangle(16*s,12*s,min(width-16*s,440*s),91*s,fill=BG,outline='',tags='ink')
        self.create_text(26*s,16*s,anchor='nw',text='短刀',font=(self.fonts[1],27),fill=ACCENT,tags='ink')
        self.create_text(115*s,22*s,anchor='nw',text='TANTO  /  RECORDER',font=(self.fonts[0],17,'bold'),fill=ACCENT,tags='ink')
        self.create_text(28*s,68*s,anchor='nw',text='Record the encounter. Preserve the detail.',font=(self.fonts[0],10),fill=MUTED,tags='ink')
        self.tag_lower('ink')
        if self.panel:
            self.coords(self.panel,24*s,106*s)
            self.itemconfigure(self.panel,width=max(1,width-48*s),height=max(1,height-126*s))
