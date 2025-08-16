# -*- coding: utf-8 -*-
"""
mordi_regexbuilder_no_punc_no_niqqud.py
---------------------------------------
גרסה עצמאית של בנאי ה-Regex:
- ללא "התעלם מניקוד עברי"
- ללא "סימני פיסוק סביב הביטוי"
- מצב "מילה/ביטוי לבדו (כל ההודעה)" כעת דורש התאמה של *כל ההודעה*, לא רק מילה נפרדת.
"""

import re
import tkinter as tk
from tkinter import ttk, messagebox

def _prep_term(term: str, allow_inside_sep: bool) -> str:
    t = term.strip()
    if not t:
        return ""
    esc = re.escape(t)
    if allow_inside_sep:
        esc = esc.replace("\\ ", "(?:[\\s_\\-\\u05BE])?").replace("\\-", "(?:[\\s_\\-\\u05BE])?")
    return esc

def _build_core_group(terms_raw: str, allow_inside_sep: bool) -> str:
    parts = []
    for t in terms_raw.split(","):
        p = _prep_term(t, allow_inside_sep)
        if p:
            parts.append(p)
    if not parts:
        return ""
    return "(?:" + "|".join(parts) + ")"

def build_regex(terms_raw: str, mode: str, case_ins: bool, allow_inside_sep: bool) -> str:
    """
    mode: 'whole' / 'part'
    whole  – התאמה רק אם כל ההודעה (למעט רווחים בתחילה/סוף) שווה לביטוי
    part   – התאמה בכל מקום (גם בתוך משפט/מילה)
    """
    core = _build_core_group(terms_raw, allow_inside_sep)
    if not core:
        return ""
    flags = "(?i)" if case_ins else ""
    if mode == "part":
        return f"{flags}{core}"
    # whole: חייב להיות כל ההודעה בלבד (עם רווחים אופציונליים מסביב)
    return f"{flags}^\\s*{core}\\s*$"

class RegexBuilderDialog(tk.Toplevel):
    def __init__(self, master=None, on_done=None):
        super().__init__(master)
        self.title("בניית סינטקס למילת מפתח")
        self.resizable(True, False)
        self.on_done = on_done

        c = ttk.Frame(self, padding=12)
        c.grid(row=0, column=0, sticky="nsew")
        c.columnconfigure(0, weight=1)

        # Terms
        ttk.Label(c, text="מילות מפתח (הפרדה בפסיק):").grid(row=0, column=1, sticky="e", padx=6, pady=(0,6))
        self.var_terms = tk.StringVar(value="ליעד, סיב, סיבים")
        ttk.Entry(c, textvariable=self.var_terms, justify="right").grid(row=0, column=0, sticky="ew", padx=6, pady=(0,6))

        # Whole/Part radios
        ttk.Label(c, text="צורת זיהוי:").grid(row=1, column=1, sticky="e", padx=6, pady=(8,2))
        self.var_mode = tk.StringVar(value="whole")
        ttk.Radiobutton(c, text="מילה/ביטוי לבדו (כל ההודעה)", value="whole", variable=self.var_mode, command=self._refresh).grid(row=1, column=0, sticky="w", padx=6)
        ttk.Radiobutton(c, text="מופע כחלק ממשפט",               value="part",  variable=self.var_mode, command=self._refresh).grid(row=2, column=0, sticky="w", padx=6)

        # Options (no niqqud / no punctuation options here)
        opt = ttk.LabelFrame(c, text="אפשרויות נוספות")
        opt.grid(row=3, column=0, columnspan=2, sticky="ew", padx=6, pady=6)
        self.var_case = tk.BooleanVar(value=True)
        self.var_seps = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="התעלם מאותיות גדולות/קטנות (Case-insensitive)", variable=self.var_case, command=self._refresh).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Checkbutton(opt, text="אפשר מפרידי־פנים (רווח/מקף)",                     variable=self.var_seps, command=self._refresh).grid(row=0, column=0, sticky="w", padx=6)

        # Preview
        ttk.Label(c, text="תבנית שנבנתה (Regex):").grid(row=4, column=1, sticky="e", padx=6, pady=(10,2))
        self.var_prev = tk.StringVar(value="")
        ttk.Entry(c, textvariable=self.var_prev, justify="left").grid(row=4, column=0, sticky="ew", padx=6, pady=(10,2))

        # Note about whole mode
        ttk.Label(c, text="הערה: במצב 'לבדו' ההודעה כולה חייבת להיות רק המילה/הביטוי (מותר רווחים בתחילה/סוף).", foreground="#666").grid(row=5, column=0, sticky="w", padx=6, pady=(0,8))

        # Test
        ttk.Label(c, text="בדוק מול טקסט (רשות):").grid(row=6, column=1, sticky="e", padx=6, pady=(6,2))
        self.var_test = tk.StringVar(value="ליעד משהו; מסיבה טובה; סיבים; סיב טוב")
        ttk.Entry(c, textvariable=self.var_test, justify="right").grid(row=6, column=0, sticky="ew", padx=6, pady=(6,2))
        self.var_test_res = tk.StringVar(value="")
        ttk.Label(c, textvariable=self.var_test_res, foreground="#0a7").grid(row=7, column=0, sticky="w", padx=6, pady=(0,6))
        ttk.Button(c, text="בדיקה", command=self._on_test).grid(row=8, column=0, sticky="e", padx=6, pady=(0,8))

        # Actions
        btns = ttk.Frame(c)
        btns.grid(row=9, column=0, columnspan=2, sticky="e", padx=6, pady=(6,0))
        ttk.Button(btns, text="אישור והמשך…", command=self._on_accept).pack(side="right", padx=4)
        ttk.Button(btns, text="סגור", command=self.destroy).pack(side="right", padx=4)

        # React to changes
        for v in (self.var_terms, self.var_mode, self.var_case, self.var_seps):
            v.trace_add('write', lambda *_: self._refresh())

        self._refresh()

    def _refresh(self, *_):
        self.var_prev.set(build_regex(
            terms_raw=self.var_terms.get(),
            mode=self.var_mode.get(),
            case_ins=self.var_case.get(),
            allow_inside_sep=self.var_seps.get(),
        ))

    def _on_test(self):
        pat = self.var_prev.get().strip()
        txt = self.var_test.get()
        if not pat:
            self.var_test_res.set("אין תבנית לבדיקה.")
            return
        try:
            ok = re.search(pat, txt) is not None
            self.var_test_res.set("✅ נמצא התאמה" if ok else "❌ אין התאמה")
        except re.error as e:
            self.var_test_res.set(f"שגיאת Regex: {e}")

    def _on_accept(self):
        pat = self.var_prev.get().strip()
        if not pat:
            messagebox.showwarning("חסר", "לא הוגדרה תבנית.")
            return
        if self.on_done:
            try:
                self.on_done(pat)
            except Exception as e:
                messagebox.showerror("שגיאה", f"פעולת ההמשך נכשלה: {e}")
                return
        self.destroy()


# Standalone demo
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Demo – Regex Builder (no punc/niqqud options)")
    def open_builder():
        def on_done(pat):
            from tkinter import messagebox
            messagebox.showinfo("Pattern", pat)
        RegexBuilderDialog(root, on_done=on_done)
    ttk.Button(root, text="בנה…", command=open_builder).pack(padx=12, pady=12)
    root.mainloop()
