# -*- coding: utf-8 -*-
"""
mordi_regexbuilder_no_punc_no_niqqud.py
---------------------------------------
גרסה עצמאית של בנאי ה-Regex (עצמאי):
- ללא "התעלם מניקוד עברי"
- ללא "סימני פיסוק סביב הביטוי"
- מצב "מילה/ביטוי לבדו (כל ההודעה)" דורש התאמה של *כל ההודעה*
- מצב: "כל המילים – סדר חופשי" (Positive lookaheads)
- בדיקת תקינות בזמן אמת (קומפילציה) + בדיקה חיה על טקסט הדוגמה
- חדש: תחיליות עבריות נפוצות אופציונליות (ו/ה/ב/כ/ל/מ/ש), עם תמיכה במפרידי־פנים לאחר התחילית
"""

import re
import tkinter as tk
from tkinter import ttk, messagebox

HEB_PREFIX_CLASS = "[והבכלמש]"  # ו ה ב כ ל מ ש

# ---------- Helpers ----------

def _prep_term(term: str, allow_inside_sep: bool) -> str:
    """
    מכין מונח בודד ללב הביטוי:
    - escape מלא
    - אופציונלית: מתיר מפרידי־פנים (רווח/מקף/מקף עברי/קו תחתון) במקום space או '-' במקור.
    """
    t = term.strip()
    if not t:
        return ""
    esc = re.escape(t)
    if allow_inside_sep:
        esc = esc.replace("\\ ", "(?:[\\s_\\-\\u05BE])?").replace("\\-", "(?:[\\s_\\-\\u05BE])?")
    return esc

def _split_terms(terms_raw: str):
    # פיצול לפי פסיקים, התעלמות מריקים
    return [t.strip() for t in terms_raw.split(",") if t.strip()]

def _build_core_group(terms_raw: str, allow_inside_sep: bool) -> str:
    parts = []
    for t in _split_terms(terms_raw):
        p = _prep_term(t, allow_inside_sep)
        if p:
            parts.append(p)
    if not parts:
        return ""
    return "(?:" + "|".join(parts) + ")"

def _prefix_pat(allow_inside_sep: bool) -> str:
    """
    מחזיר דפוס לתחיליות עבריות נפוצות (אפשר עד 1–4 אותיות רצופות), ואופציונלית מפריד-פנים אחרי התחילית.
    דוגמאות שיתאימו: "וסיב", "והסיב", "ומ-סיב" (כשמפרידי-פנים פעיל).
    """
    if allow_inside_sep:
        sep = "(?:[\\s_\\-\\u05BE])?"
    else:
        sep = ""
    return f"(?:{HEB_PREFIX_CLASS}{{1,4}}{sep})?"

def _build_anyorder_lookaheads(terms_raw: str, allow_inside_sep: bool, allow_prefixes: bool) -> str:
    """
    בונה אוסף Lookaheads כך שכל מונח חייב להופיע כטוקן נפרד (רק גבולות רווח/תחילת/סוף שורה).
    מאפשר תחיליות אופציונליות לפני כל מונח.
    דוגמה: (?=.*(?<!\S)(?:[והבכלמש]{1,4})?סיב(?!\S))
    """
    lookaheads = []
    pref = _prefix_pat(allow_inside_sep) if allow_prefixes else ""
    for t in _split_terms(terms_raw):
        p = _prep_term(t, allow_inside_sep)
        if p:
            lookaheads.append(f"(?=.*(?<!\\S){pref}{p}(?!\\S))")
    return "".join(lookaheads)

# ---------- Core builder ----------

def build_regex(terms_raw: str, mode: str, case_ins: bool, allow_inside_sep: bool, allow_prefixes: bool,
                 k_spec: dict | None = None) -> str:
    """
    mode: 'whole' / 'part' / 'anyorder'
    whole    – התאמה רק אם כל ההודעה (למעט רווחים בתחילה/סוף) שווה לביטוי/אחד מן הביטויים
    part     – התאמה בכל מקום (גם בתוך משפט/מילה)
    anyorder – כל המילים המוזנות (מופרדות בפסיק) חייבות להופיע כטוקנים נפרדים, בסדר חופשי
    """
    flags = "(?i)" if case_ins else ""
    pref  = _prefix_pat(allow_inside_sep) if allow_prefixes else ""


    
    
    # ----- Per-term K via "term:K" syntax -----
    terms_list = list(k_spec.keys()) if k_spec else [t for t in _split_terms(terms_raw) if t]
    flags = "(?i)" if case_ins else ""
    pref_once = _prefix_pat(allow_inside_sep) if allow_prefixes else ""

    # k_spec: dict of base-term -> K (>=1). default 1 when missing.
    def token_for(term: str) -> str:
        tok = _prep_term(term, allow_inside_sep)
        return f"(?<!\\S){pref_once}{tok}(?!\\S)" if tok else ""

    # If any term has K>1 OR there is more than one term, we can compose lookaheads that enforce per-term counts.
    if terms_list and k_spec and any((lambda d: any(v>1 for v in d.values()))(k_spec) for _ in [0]):
        lookaheads = []
        for t in terms_list:
            tok = token_for(t)
            if not tok:
                continue
            k = 1
            try:
                k = int(k_spec.get(t, 1))
            except Exception:
                k = 1
            if k > 1:
                lookaheads.append(f"(?=(?:.*?{tok}){{{k}}})")
            else:
                # at least one
                lookaheads.append(f"(?=.*{tok})")

        # In 'whole' mode with K, we still allow arbitrary text but require counts; anchor full string
        if lookaheads:
            if mode == "whole":
                # WHOLE: only listed tokens allowed + counts enforced
                alts = []
                for t in terms_list:
                    tok = _prep_term(t, allow_inside_sep)
                    if tok:
                        alts.append(f"(?<!\S){pref_once}{tok}(?!\S)")
                alt = "(?:" + "|".join(alts) + ")" if alts else ""
                only_allowed = f"(?:\s*{alt}\s*)+" if alt else ""
                return f"{flags}{''.join(lookaheads)}^{only_allowed}$"
            elif mode == "part":
                # PART: OR semantics — match if ANY one term condition is satisfied.
                # Build per-term alternatives: for K>1 use counting lookahead; for K=1 require simple presence.
                alts = []
                for t in terms_list:
                    tok = token_for(t)
                    if not tok:
                        continue
                    k = 1
                    try:
                        k = int(k_spec.get(t, 1))
                    except Exception:
                        k = 1
                    if k > 1:
                        alts.append(f"(?=(?:.*?{tok}){{{k}}}).*")
                    else:
                        alts.append(f"(?=.*{tok}).*")
                if alts:
                    return f"{flags}(?s)(?:{'|'.join(alts)})"
                # fallback (shouldn't happen)
                return f"{flags}.*"
            else:
                # ANYORDER: ALL terms must appear at least once (or K times if specified)
                return f"{flags}{''.join(lookaheads)}.*"
    if mode == "anyorder":
        la = _build_anyorder_lookaheads(terms_raw, allow_inside_sep, allow_prefixes)
        if not la:
            return ""
        # דוגמה סופית: (?i)(?=.*...)(?=.*...).*
        return f"{flags}{la}.*"



    core = _build_core_group(terms_raw, allow_inside_sep)
    if not core:
        return ""

    if mode == "part":
        # תחילית משותפת לכל הביטויים (אם הופעלה)
        return f"{flags}{pref}{core}" if allow_prefixes else f"{flags}{core}"

    # whole: חייב להיות כל ההודעה בלבד (עם רווחים אופציונליים מסביב)
    # תחילית לפני קבוצת הביטויים (אם הופעלה)
    return f"{flags}^\\s*(?:{pref}{core})\\s*$"

# ---------- UI ----------

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
        ent_terms = ttk.Entry(c, textvariable=self.var_terms, justify="right")
        ent_terms.grid(row=0, column=0, sticky="ew", padx=6, pady=(0,6))

        # Mode radios
        ttk.Label(c, text="צורת זיהוי:").grid(row=1, column=1, sticky="e", padx=6, pady=(8,2))
        self.var_mode = tk.StringVar(value="whole")
        ttk.Radiobutton(c, text="מילה/ביטוי לבדו (כל ההודעה)", value="whole",    variable=self.var_mode, command=self._refresh).grid(row=1, column=0, sticky="w", padx=6)
        ttk.Radiobutton(c, text="מופע כחלק ממשפט",               value="part",     variable=self.var_mode, command=self._refresh).grid(row=2, column=0, sticky="w", padx=6)
        ttk.Radiobutton(c, text="כל המילים – סדר חופשי",         value="anyorder", variable=self.var_mode, command=self._refresh).grid(row=3, column=0, sticky="w", padx=6)

        # Options (no niqqud / no punctuation options here)
        opt = ttk.LabelFrame(c, text="אפשרויות נוספות")
        opt.grid(row=4, column=0, columnspan=2, sticky="ew", padx=6, pady=6)

        # K controls
        self.var_case = tk.BooleanVar(value=True)
        self.var_seps = tk.BooleanVar(value=True)
        self.var_pref = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="התעלם מאותיות גדולות/קטנות (Case-insensitive)", variable=self.var_case, command=self._refresh).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Checkbutton(opt, text="אפשר מפרידי־פנים (רווח/מקף)",                     variable=self.var_seps, command=self._refresh).grid(row=0, column=0, sticky="w", padx=6)
        ttk.Checkbutton(opt, text="אפשר תחיליות נפוצות (ו/ה/ב/כ/ל/מ/ש)",             variable=self.var_pref, command=self._refresh).grid(row=1, column=0, sticky="w", padx=6, pady=(6,0))
        ttk.Label(opt, text="* התחיליות חלות לפני המילה: לדוגמה 'והתקנה', 'וסיב', 'וב-סיב' (אם מפרידי־פנים פעיל).", foreground="#666").grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(2,0))


        # Preview
        ttk.Label(c, text="תבנית שנבנתה (Regex):").grid(row=5, column=1, sticky="e", padx=6, pady=(10,2))
        self.var_prev = tk.StringVar(value="")
        ent_prev = ttk.Entry(c, textvariable=self.var_prev, justify="left")
        ent_prev.grid(row=5, column=0, sticky="ew", padx=6, pady=(10,2))

        # Validity (real-time)
        self.var_valid = tk.StringVar(value="")
        lbl_valid = ttk.Label(c, textvariable=self.var_valid)
        lbl_valid.grid(row=6, column=0, sticky="w", padx=6, pady=(0,4))

        # Note
        ttk.Label(c, text="הערה: במצב 'לבדו' ההודעה כולה חייבת להיות רק המילה/הביטוי (מותר רווחים בתחילה/סוף).", foreground="#666").grid(row=7, column=0, sticky="w", padx=6, pady=(0,8))

        # Test
        ttk.Label(c, text="בדוק מול טקסט (רשות):").grid(row=8, column=1, sticky="e", padx=6, pady=(6,2))
        self.var_test = tk.StringVar(value="ליעד משהו; והתקנה; סיבים; וסיב טוב; ו-סיב; מסיבה טובה")
        ent_test = ttk.Entry(c, textvariable=self.var_test, justify="right")
        ent_test.grid(row=8, column=0, sticky="ew", padx=6, pady=(6,2))
        self.var_test_res = tk.StringVar(value="")
        ttk.Label(c, textvariable=self.var_test_res, foreground="#0a7").grid(row=9, column=0, sticky="w", padx=6, pady=(0,6))

        # Actions
        btns = ttk.Frame(c)
        btns.grid(row=11, column=0, columnspan=2, sticky="e", padx=6, pady=(6,0))
        self.btn_ok = ttk.Button(btns, text="אישור והמשך…", command=self._on_accept)
        self.btn_ok.pack(side="right", padx=4)
        ttk.Button(btns, text="סגור", command=self.destroy).pack(side="right", padx=4)

        # Respond to changes
        for v in (self.var_terms, self.var_mode, self.var_case, self.var_seps, self.var_pref, self.var_test):
            v.trace_add('write', lambda *_: self._refresh())

        self._refresh()

    # ---------- Internal UI logic ----------

    def _refresh(self, *_):
        pat = build_regex(
            terms_raw=self.var_terms.get(),
            mode=self.var_mode.get(),
            case_ins=self.var_case.get(),
            allow_inside_sep=self.var_seps.get(),
            allow_prefixes=self.var_pref.get(),
        )
        self.var_prev.set(pat)

        # Real-time validity
        if not pat:
            self.var_valid.set("")
            self.btn_ok.state(["disabled"])
            self.var_test_res.set("")
            return
        try:
            re.compile(pat)
            self.var_valid.set("✅ תבנית תקינה")
            self.btn_ok.state(["!disabled"])
            # Live test
            self._update_live_test(pat)
        except re.error as e:
            self.var_valid.set(f"❌ שגיאת Regex: {e}")
            self.btn_ok.state(["disabled"])

    def _update_live_test(self, pat: str):
        txt = self.var_test.get()
        try:
            ok = re.search(pat, txt) is not None
            self.var_test_res.set("✅ נמצא התאמה" if ok else "❌ אין התאמה")
        except re.error as e:
            self.var_test_res.set(f"שגיאת Regex: {e}")

    def _on_test(self):
        pat = self.var_prev.get().strip()
        if not pat:
            self.var_test_res.set("אין תבנית לבדיקה.")
            return
        self._update_live_test(pat)

    def _on_accept(self):
        pat = self.var_prev.get().strip()
        if not pat:
            messagebox.showwarning("חסר", "לא הוגדרה תבנית.")
            return
        # וידוא תקינות אחרון
        try:
            re.compile(pat)
        except re.error as e:
            messagebox.showerror("Regex לא תקין", f"לא ניתן לאשר: {e}")
            return

        if self.on_done:
            try:
                self.on_done(pat)
            except Exception as e:
                messagebox.showerror("שגיאה", f"פעולת ההמשך נכשלה: {e}")
                return
        self.destroy()

    def _rebuild_k_terms(self):
        # Rebuild per-term K controls based on current terms input
        if not hasattr(self, 'frm_k_terms'):
            return
        for w in self.frm_k_terms.winfo_children():
            w.destroy()
        self.k_vars = {}
        terms = [t.strip() for t in self.var_terms.get().split(",") if t.strip()]
        if not terms:
            return
        ttk.Label(self.frm_k_terms, text="K למונחים:").grid(row=0, column=0, sticky="w", padx=6)
        for i, t in enumerate(terms, start=1):
            ttk.Label(self.frm_k_terms, text=t).grid(row=i, column=0, sticky="e", padx=6, pady=2)
            v = tk.IntVar(value=1)
            self.k_vars[t] = v
            ttk.Spinbox(self.frm_k_terms, from_=1, to=20, textvariable=v, width=5, command=self._refresh).grid(row=i, column=1, sticky="w", padx=6, pady=2)

    def _refresh(self, *_):
        # rebuild pattern + validity + live test
        # keep existing function body if present; we recreate a minimal one if not
        try:
            # If original refresh exists (was patched earlier), call its inner logic via local duplication
            pass
        except Exception:
            pass
        # Always rebuild per-term K table when terms change or mode changes
        if getattr(self, 'var_k_mode', None):
            if self.var_k_mode.get() == 'perterm':
                self._rebuild_k_terms()
        # Build pattern
        pat = build_regex(
            terms_raw=self.var_terms.get(),
            mode=self.var_mode.get(),
            case_ins=self.var_case.get(),
            allow_inside_sep=self.var_seps.get(),
            allow_prefixes=self.var_pref.get(),
            k_spec=self._parse_k_spec(self.var_terms.get()),
        )
        self.var_prev.set(pat)
        # validity + compile
        if not pat:
            self.var_valid.set("")
            self.btn_ok.state(["disabled"])
            self.var_test_res.set("")
            return
        try:
            re.compile(pat)
            self.var_valid.set("✅ תבנית תקינה")
            self.btn_ok.state(["!disabled"])
            self._update_live_test(pat)
        except re.error as e:
            self.var_valid.set(f"❌ Regex לא תקין: {e}")
            self.btn_ok.state(["disabled"])
    
    def _parse_k_spec(self, terms_raw: str) -> dict:
        # Accept "term:K" or "term : K" (whitespace ignored around ':')
        spec = {}
        parts = [p.strip() for p in terms_raw.split(",") if p.strip()]
        cleaned = []
        for p in parts:
            if ":" in p:
                base, _, k = p.partition(":")
                base = base.strip()
                try:
                    kval = int(k.strip())
                except Exception:
                    kval = 1
                if base:
                    spec[base] = max(1, kval)
                    cleaned.append(base)
            else:
                cleaned.append(p)
                if p not in spec:
                    spec[p] = 1
        # Also update the entry box to show cleaned terms (without :K) on next refresh?
        # לא מחייב לשנות את הטקסט של המשתמש; נשאיר כמות שהוא.
        return spec
    

# Standalone demo
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Demo – Regex Builder (any-order, prefixes, live validity)")
    def open_builder():
        def on_done(pat):
            from tkinter import messagebox
            messagebox.showinfo("Pattern", pat)
        RegexBuilderDialog(root, on_done=on_done)
    ttk.Button(root, text="בנה…", command=open_builder).pack(padx=12, pady=12)
    root.mainloop()
