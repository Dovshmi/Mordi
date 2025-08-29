
# mordi_gui2_pro_settings_readonly_notepad.py — ממשק ללא "ייבוא מרוכז", עורך פנימי לקריאה בלבד, וכפתור עריכה ב-Notepad
# -*- coding: utf-8 -*-

from __future__ import annotations
import json, random, re, threading, time, os, subprocess, tempfile, sys
from pathlib import Path
from typing import List, Tuple

# ---------- Selenium ----------
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# ---------- Tkinter GUI ----------
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

def resource_path(rel_path: str) -> str:
    """Works both from source and when bundled with PyInstaller."""
    try:
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    except Exception:
        base = Path(__file__).resolve().parent
    return str((base / rel_path).resolve())

# ---------- Display helpers (human-readable keywords extracted from Regex) ----------
def _regex_to_keywords_display(pattern: str) -> str:
    """
    מנסה לחלץ 'מילות מפתח' לקריאה אנושית מתוך Regex שבנוי ע"פ הבונה.
    אם לא מצליח — חוזר לניחוש סביר על בסיס אותיות עברית, ולבסוף נפילה לאחור לתצוגה מקוצרת של ה-Regex.
    """
    if not isinstance(pattern, str):
        return ""

    pat = pattern.strip()

    # הסר פלגים בתחילת הביטוי (למשל (?i)(?s))
    pat = re.sub(r'^\(\?[a-zA-Z]+\)', '', pat)

    tokens = []

    # 1) הטוקן התקני מהבונה: (?<!\S)(?:[והבכלמש]{1,4})?TERM(?!\S)
    tok_re = re.compile(r'\(\?\<\!\\\\S\)(?:\(\?\:\[והבכלמש\]\{1,4\}\)\?)?(.+?)\(\?\!\\\\S\)')
    for m in tok_re.finditer(pat):
        term = m.group(1)
        # נקה קבוצות לא-לוכדות של מפרידי־פנים, למשל (?:[\s_\-\u05BE])?
        term = re.sub(r'\(\?\:[^\)]*\)', ' ', term)
        # הסר backslashes מיותרים לפני תוים
        term = re.sub(r'\\([^\w])', r'\1', term)
        term = term.replace('\\ ', ' ')
        # נרמל רווחים
        term = re.sub(r'\s+', ' ', term).strip()
        if term:
            tokens.append(term)

    # 2) אם לא נמצאו, נסה אלטרנטיבות בתוך (?:A|B|C)
    if not tokens:
        # ננסה למצוא את הקבוצה הרחבה ביותר עם | שמכילה אותיות עברית
        for grp in re.findall(r'\(\?:([^()]+)\)', pat):
            if '|' in grp and re.search(r'[\u0590-\u05FF]', grp):
                alts = [a.strip() for a in grp.split('|') if a.strip()]
                # נקה escape-ים פשוטים
                cleaned = []
                for t in alts:
                    t = re.sub(r'\\([^\w])', r'\1', t)
                    t = t.replace('\\ ', ' ')
                    t = re.sub(r'\s+', ' ', t).strip()
                    if t:
                        cleaned.append(t)
                tokens.extend(cleaned)
                if tokens:
                    break

    # 3) fallback: אסוף מילים בעברית מתוך הביטוי עצמו
    if not tokens:
        words = re.findall(r'[\u0590-\u05FF]{2,}', pat)
        if words:
            tokens = list(dict.fromkeys(words))  # unique & keep order

    # 4) נפילה אחרונה — קטע קצר מה-Regex עצמו
    if not tokens:
        short = pat
        short = short.replace('\n', ' ')
        short = re.sub(r'\s+', ' ', short)
        short = short.strip()
        if len(short) > 48:
            short = short[:45] + '…'
        return short

    # ייחוד ושמירה על סדר
    tokens = list(dict.fromkeys(tokens))
    # חבר לרשימה ידידותית
    return ", ".join(tokens)


# === Hebrew Regex Character Classes (added by patch) ===
# Single-letter Hebrew prefixes like ו/ה/ב/כ/ל/מ/ש (optionally with geresh), limited to 1-4 letters.
HEB_LETTERS_CLASS = r"[א-ת]"
# Optional niqqud (we keep it simple, not consuming by default; can be expanded if needed)
NIKKUD_CLASS = r"[\u0591-\u05C7]"
# Prefix letters group used by the builder when 'allow_prefixes' is on.
HEB_PREFIX_CLASS = r"[והבכלמש]"
# Word boundary helpers that play nice with Hebrew + spaces/punct
W_BEG = r"(?<!\S)"   # start-of-word using whitespace lookbehind
W_END = r"(?!\S)"    # end-of-word using whitespace lookahead




# ==== Integrated Regex Builder (build_regex + RegexBuilderDialog) ====
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
        esc = esc.replace("\\ ", r"(?:[\\s_\\-\\u05BE])?").replace("\\-", r"(?:[\\s_\\-\\u05BE])?")
    return esc



def _split_terms(terms_raw: str):
    # פיצול לפי פסיקים, התעלמות מריקים
    return [t.strip() for t in terms_raw.split(",") if t.strip()]
def _parse_terms_grammar(terms_raw: str):
    # מפענח תחביר: פסיק = קבוצות, "/" בין מילים = OR בתוך קבוצה, "*" בסוף חלופה => הקבוצה חובה
    # מחזיר (required_groups, optional_groups), כאשר כל קבוצה היא רשימת חלופות (מחרוזות).
    groups = []
    for raw in [t.strip() for t in terms_raw.split(",") if t.strip()]:
        alts = [a.strip() for a in raw.split("/") if a.strip()]
        required = False
        cleaned = []
        for a in alts:
            if a.endswith("*") or a.startswith("*"):
                required = True
                a = a.strip("*").strip()
            cleaned.append(a)
        if cleaned:
            groups.append((required, cleaned))
    req = [alts for (req, alts) in groups if req]
    opt = [alts for (req, alts) in groups if not req]
    return req, opt


def _alts_to_core(alts, allow_inside_sep: bool) -> str:
    # בונה תבנית Regex בסיסית לקבוצת חלופות (ליבה ללא תחיליות/גבולות).
    parts = []
    for t in alts:
        p = _prep_term(t, allow_inside_sep)
        if p:
            parts.append(p)
    if not parts:
        return ""
    return "(?:" + "|".join(parts) + ")"


def _build_keywords_grammar_regex(terms_raw: str, mode: str, case_ins: bool, allow_inside_sep: bool, allow_prefixes: bool) -> str:
    # בונה Regex על פי התחביר החדש
    # "/" בתוך קבוצה = OR בין חלופות
    # "*" בקצה חלופה = הקבוצה כולה חובה
    # אם יש קבוצות חובה וגם לא-חובה: נדרשת גם לפחות אחת לא-חובה
    # אם אין קבוצות חובה: מספיק לפחות אחת לא-חובה
    flags = "(?i)" if case_ins else ""
    pref_once = _prefix_pat(allow_inside_sep, enabled=allow_prefixes)

    req_groups, opt_groups = _parse_terms_grammar(terms_raw)

    def group_lookahead(alts):
        core = _alts_to_core(alts, allow_inside_sep)
        if not core:
            return ""
        return fr"(?=.*(?<!\S){pref_once}{core}(?!\S))"

    if not req_groups and not opt_groups:
        return ""

    if mode == "part":
        looks = []
        # לכל קבוצה חובה — חייבים אחד מהחלופות
        for alts in req_groups:
            la = group_lookahead(alts)
            if la:
                looks.append(la)
        # אם קיימות גם קבוצות לא-חובה — נדרשת לפחות אחת מהן
        if opt_groups:
            all_opt_alts = [a for grp in opt_groups for a in grp]
            la_opt = group_lookahead(all_opt_alts)
            if req_groups:
                looks.append(la_opt)
            else:
                looks = [la_opt]
        return f"{flags}{''.join(looks)}.*"

    # למצב 'whole' נשאיר את ההתנהגות המקורית (ייבנה בהמשך), לכן נחזיר ריק.
    return ""




def _build_core_group(terms_raw: str, allow_inside_sep: bool) -> str:
    parts = []
    for t in _split_terms(terms_raw):
        p = _prep_term(t, allow_inside_sep)
        if p:
            parts.append(p)
    if not parts:
        return ""
    return "(?:" + "|".join(parts) + ")"



def _prefix_pat(allow_inside_sep: bool, enabled: bool = True) -> str:
    """בונה חלק Regex של תחיליות (ו/מ/כ/ה וכו') אם enabled=True, אחרת מחזיר ריק."""
    if not enabled:
        return ""
    sep = r"" if allow_inside_sep else W_BEG
    return fr"(?:{HEB_PREFIX_CLASS}{{1,4}}{sep})?"
def _build_anyorder_lookaheads(terms_raw: str, allow_inside_sep: bool, allow_prefixes: bool) -> str:
    """
    בונה אוסף Lookaheads כך שכל מונח חייב להופיע כטוקן נפרד (רק גבולות רווח/תחילת/סוף שורה).
    מאפשר תחיליות אופציונליות לפני כל מונח.
    דוגמה: (?=.*(?<!\\S)(?:[והבכלמש]{1,4})?סיב(?!\\S))
    """
    lookaheads = []
    pref  = _prefix_pat(allow_inside_sep, enabled=allow_prefixes) if allow_prefixes else ""
    for t in _split_terms(terms_raw):
        p = _prep_term(t, allow_inside_sep)
        if p:
            lookaheads.append(fr"(?=.*(?<!\\S){pref}{p}(?!\\S))")
    return "".join(lookaheads)



def build_regex(terms_raw: str, mode: str, case_ins: bool, allow_inside_sep: bool, allow_prefixes: bool,
                k_spec: dict | None = None) -> str:
    """
    mode: 'whole' / 'part' / 'anyorder'
    """
    # 1) Try the grammar-based builder (new syntax with groups and '*' etc.)
    try:
        _gram_pat = _build_keywords_grammar_regex(terms_raw, mode, case_ins, allow_inside_sep, allow_prefixes)
    except Exception:
        _gram_pat = None
    if _gram_pat:
        return _gram_pat  # success with the new syntax

    # 2) Fallback to legacy behavior so dialog always has a valid regex
    flags = "(?i)" if case_ins else ""
    pref  = _prefix_pat(allow_inside_sep, enabled=allow_prefixes)
    core  = _build_core_group(terms_raw, allow_inside_sep)

    if not core:
        return ""  # no terms, disable confirm button upstream

    if mode == "whole":
        # Exact whole-message match (with optional whitespace around)
        return fr"{flags}^\s*(?:{pref}{core})\s*$"

    if mode == "anyorder":
        # All words must appear as separate tokens, any order.
        la = _build_anyorder_lookaheads(terms_raw, allow_inside_sep, allow_prefixes)
        return f"{flags}{la}.*"

    # default: 'part' — appear as a token inside a sentence (token boundaries)
    return fr"{flags}(?s).*?(?<!\S){pref}{core}(?!\S).*"

def fallback_prefill(dialog, pattern: str):
    """Prefill best-effort when structured parse fails; ensures builder isn't empty."""
    try:
        pat = (pattern or "").strip()
        if not pat:
            return
        import re as _re
        cores = _re.findall(r'\(\?\<\!\\S\)\(?:\(\?\:\[והבכלמש\]\{1,4\}\)\)\?((?:\(\?:.*?\))|[^()|]+?)\(\?\!\\S\)', pat)
        groups = []
        for core in cores:
            if core.startswith('(?:') and core.endswith(')'):
                inner = core[3:-1]
                alts = [a.strip() for a in inner.split('|') if a.strip()]
                groups.append(alts)
            else:
                groups.append([core.strip()])
        cleaned_groups = []
        for alts in groups:
            out = []
            for a in alts:
                try:
                    if '\\' in a:
                        a = bytes(a, 'utf-8').decode('unicode_escape')
                except Exception:
                    pass
                a = a.replace('(?<!\\S)','').replace('(?!\\S)','')
                out.append(a)
            cleaned_groups.append(out)
        if cleaned_groups and not dialog.var_terms.get().strip():
            terms_line = ", ".join(("/".join(g) if len(g)>1 else g[0]) for g in cleaned_groups)
            dialog.var_mode.set("part")
            dialog.var_terms.set(terms_line)
            dialog._refresh()
    except Exception:
        pass


    flags = "(?i)" if case_ins else ""
    pref  = _prefix_pat(allow_inside_sep, enabled=allow_prefixes)


    
    
    # ----- Per-term K via "term:K" syntax -----
    terms_list = list(k_spec.keys()) if k_spec else [t for t in _split_terms(terms_raw) if t]
    flags = "(?i)" if case_ins else ""
    pref_once = _prefix_pat(allow_inside_sep, enabled=allow_prefixes)

    # k_spec: dict of base-term -> K (>=1). default 1 when missing.
    def token_for(term: str) -> str:
        tok = _prep_term(term, allow_inside_sep)
        return fr"(?<!\\S){pref_once}{tok}(?!\\S)" if tok else ""

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
                        alts.append(fr"(?<!\S){pref_once}{tok}(?!\S)")
                alt = "(?:" + "|".join(alts) + ")" if alts else ""
                only_allowed = fr"(?:\s*{alt}\s*)+" if alt else ""
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
    return fr"{flags}^\\s*(?:{pref}{core})\\s*$"
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
        ttk.Label(c, text="מילות מפתח: פסיק = רשימה, '/' = או, '*' = חובה").grid(row=0, column=1, sticky="e", padx=6, pady=(0,6))
        self.var_terms = tk.StringVar(value="")
        ent_terms = ttk.Entry(c, textvariable=self.var_terms, justify="right")
        ent_terms.grid(row=0, column=0, sticky="ew", padx=6, pady=(0,6))

        # Mode radios
        ttk.Label(c, text="צורת זיהוי:").grid(row=1, column=1, sticky="e", padx=6, pady=(8,2))
        self.var_mode = tk.StringVar(value="whole")
        ttk.Radiobutton(c, text="מילה/ביטוי לבדו (כל ההודעה)", value="whole",    variable=self.var_mode, command=self._refresh).grid(row=1, column=0, sticky="w", padx=6)
        ttk.Radiobutton(c, text="מופע כחלק ממשפט",               value="part",     variable=self.var_mode, command=self._refresh).grid(row=2, column=0, sticky="w", padx=6)# (נוטרל לפי בקשה) 
        ttk.Radiobutton(c, text="כל המילים – סדר חופשי",         value="anyorder", variable=self.var_mode, command=self._refresh).grid(row=3, column=0, sticky="w", padx=6)

# ↑ אופציית "כל המילים – סדר חופשי" בוטלה
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

        
        # Human-readable terms summary (as entered)
    # Validity (real-time)
        self.var_valid = tk.StringVar(value="")
        lbl_valid = ttk.Label(c, textvariable=self.var_valid)
        lbl_valid.grid(row=6, column=0, sticky="w", padx=6, pady=(0,4))

        # Note
        ttk.Label(c, text="הערה: במצב 'לבדו' ההודעה כולה חייבת להיות רק המילה/הביטוי (מותר רווחים בתחילה/סוף).", foreground="#666").grid(row=7, column=0, sticky="w", padx=6, pady=(0,8))

        # Test
        ttk.Label(c, text="בדוק מול טקסט (רשות):").grid(row=8, column=1, sticky="e", padx=6, pady=(6,2))
        self.var_test = tk.StringVar(value="")
        ent_test = ttk.Entry(c, textvariable=self.var_test, justify="right")
        ent_test.grid(row=8, column=0, sticky="ew", padx=6, pady=(6,2))
        self.var_test_res = tk.StringVar(value="")
        ttk.Label(c, textvariable=self.var_test_res, foreground="#0a7").grid(row=9, column=0, sticky="w", padx=6, pady=(0,6))

        # Actions
        # --- Save edited values (including repeat) and activate ---
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

        

        # Update "terms as entered" display (normalized spacing only)
        terms_raw = (self.var_terms.get() or "").strip()
        if terms_raw:
            # Normalize spaces around separators , and / but keep symbols like * and :n intact
            parts = [t.strip() for t in terms_raw.split(",") if t.strip()]
            normalized_groups = []
            for g in parts:
                alts = [a.strip() for a in g.split("/") if a.strip()]
                normalized_groups.append("/".join(alts))
            getattr(self,'var_terms_disp', None) and self.var_terms_disp.set(", ".join(normalized_groups))
        else:
            getattr(self,'var_terms_disp', None) and self.var_terms_disp.set("")
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
                try:
                    self.on_done(pat, self.var_terms.get().strip())
                except TypeError:
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
        

        # Update "terms as entered" display (normalized spacing only)
        terms_raw = (self.var_terms.get() or "").strip()
        if terms_raw:
            # Normalize spaces around separators , and / but keep symbols like * and :n intact
            parts = [t.strip() for t in terms_raw.split(",") if t.strip()]
            normalized_groups = []
            for g in parts:
                alts = [a.strip() for a in g.split("/") if a.strip()]
                normalized_groups.append("/".join(alts))
            getattr(self,'var_terms_disp', None) and self.var_terms_disp.set(", ".join(normalized_groups))
        else:
            getattr(self,'var_terms_disp', None) and self.var_terms_disp.set("")
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
    


# ==== End Regex Builder Integration ====



APP_TITLE = "Mordi 6.0"
DEFAULT_DATASET = "keywords.json"
DEFAULT_GROUP   = ""
FREE_CHOICE = "(בחירה חופשית)"
SETTINGS_PATH   = Path("settings.json")

PROFILE_DIR = Path.home() / "selenium_profile"
SEARCH_BOX = ("//div[@role='textbox' and @contenteditable='true' and "
              "(@aria-label='Search input textbox' or @data-tab='3')]")
CHAT_ITEM   = "//span[@title=%s]"
MSG_AREA    = "//footer//div[@role='textbox' and @contenteditable='true']"
BUBBLES_IN_CSS  = "div.message-in span.selectable-text"
BUBBLES_ANY_CSS = "div.copyable-text span.selectable-text"
MEDIA_PLACEHOLDER = "[תוכן מדיה]"

# ברירת מחדל: פולינג כל 2 שניות
DEFAULT_POLL_INTERVAL = 2

# ---------- RTL helpers ----------
def _norm(s: str) -> str:
    return s.strip().casefold()

def _rtl_text_widget(txt: tk.Text):
    """RTL לעורכי טקסט: יישור לימין + תגית RTL מתמשכת."""
    try:
        txt.configure(wrap="word")
        txt.tag_configure("rtl", justify="right", lmargin1=8, lmargin2=8)
        txt.tag_add("rtl", "1.0", "end")
        def _enforce_rtl(event=None):
            try:
                event.widget.tag_add("rtl", "1.0", "end")
                event.widget.edit_modified(False)
            except Exception:
                pass
        txt.bind("<<Modified>>", _enforce_rtl, add=True)
        txt.edit_modified(False)
    except Exception:
        pass

# ---------- Selenium helpers ----------
def build_driver(start_maximized: bool=True) -> webdriver.Chrome:
    PROFILE_DIR.mkdir(exist_ok=True)
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR.resolve()}")
    if start_maximized:
        opts.add_argument("--start-maximized")
    opts.add_argument("--log-level=3")
    opts.add_argument("--disable-logging")
    opts.add_experimental_option("detach", True)
    return webdriver.Chrome(options=opts)

def wait_for_login(drv, sec=120):
    try:
        WebDriverWait(drv, sec).until(
            EC.presence_of_element_located((By.XPATH, SEARCH_BOX))
        )
    except TimeoutException:
        messagebox.showinfo("WhatsApp Web",
                            "סרוק/י את קוד ה-QR בכרום שנפתח. לאחר הסריקה לחץ/י אישור.")
        WebDriverWait(drv, sec).until(
            EC.presence_of_element_located((By.XPATH, SEARCH_BOX))
        )

def open_chat(drv, name):
    search = drv.find_element(By.XPATH, SEARCH_BOX)
    search.clear()
    search.send_keys(name)
    chat = WebDriverWait(drv, 10).until(
        EC.element_to_be_clickable((By.XPATH, CHAT_ITEM % repr(name)))
    )
    chat.click()

def last_incoming_text(drv):
    bubbles = drv.find_elements(By.CSS_SELECTOR, BUBBLES_IN_CSS)
    if not bubbles:
        bubbles = drv.find_elements(By.CSS_SELECTOR, BUBBLES_ANY_CSS)
    if not bubbles:
        return MEDIA_PLACEHOLDER
    text = bubbles[-1].text.strip()
    return text if text else MEDIA_PLACEHOLDER

# ---------- Dataset model ----------

    
def load_from_pattern(self, pattern: str):
        """
        נסה לפענח Regex שהופק בבונה, ולהזין את כל הרובריקות בהתאם.
        תומך בתחביר החדש: פסיק (רשימות), "/" (OR בתוך קבוצה), "*" (קבוצה חובה).
        """
        try:
            pat = (pattern or "").strip()
            if not pat:
                return

            # מצב: whole אם יש ^...$; אחרת part
            is_whole = pat.startswith("^") and pat.endswith("$")
            self.var_mode.set("whole" if is_whole else "part")

            # קידומות (ו/ה/ב/כ/ל/מ/ש) — אותן מזהה לפי נוכחות התבנית
            has_prefix = "(?:[והבכלמש]{1,4})?" in pat
            self.var_pref.set(bool(has_prefix))

            # casefold תמיד מופעל אצלנו כברירת מחדל
            self.var_case.set(True)

            # מפרידי־פנים (רווחים/מקפים) — אם רואים \s בתוך התבנית נניח שמותר
            self.var_seps.set(("\\s*" in pat) or ("\\s" in pat) or ("[\\s" in pat))

            terms_line = ""

            if not is_whole:
                # פירוק ה-lookaheads: מוציאים את הליבה (core) של האלטרנטיבות
                # דוגמה: (?=.*(?<!\S)(?:[והבכלמש]{1,4})?(?:A|B|C)(?!\S))
                lookahead_cores = re.findall(
                    r'\(\?=\.\*\(\?\<\!\\S\)\(?:\(\?\:\[והבכלמש\]\{1,4\}\)\)\?\(?P<core>\(\?:.*?\)\)\(\?\!\\S\)\)',
                    pat
                )
                groups = []
                for core in lookahead_cores:
                    # core הוא בצורה (?:...|...)
                    inner = core[3:-1] if core.startswith('(?:') and core.endswith(')') else core
                    alts = [a.strip() for a in inner.split('|') if a.strip()]
                    # הסר escape של יוניקוד כדי להחזיר טקסט קריא
                    cleaned = []
                    for a in alts:
                        try:
                            if '\\' in a:
                                a = bytes(a, 'utf-8').decode('unicode_escape')
                        except Exception:
                            pass
                        a = a.replace('(?<!\\S)','').replace('(?!\\S)','')
                        cleaned.append(a)
                    groups.append(cleaned)

                # היסק "חובה": אם יש יותר מקבוצה אחת, נניח שכל lookahead שהוא לא "מאוחד-אופציונלי" הוא חובה.
                opt_idx = None
                if len(groups) >= 2:
                    flat = [t for g in groups for t in g]
                    total = len(set(flat))
                    for i, g in enumerate(groups):
                        if len(set(g)) >= max(2, total - 1):
                            opt_idx = i
                            break

                parts = []
                for i, g in enumerate(groups):
                    token = "/".join(g) if len(g) > 1 else (g[0] if g else "")
                    if not token:
                        continue
                    if opt_idx is None:
                        parts.append(token + ("*" if len(groups) > 1 else ""))
                    else:
                        if i != opt_idx:
                            token += "*"
                        parts.append(token)
                terms_line = ", ".join(parts)

            else:
                m = re.search(r'\(\?\:\s*(?P<grp>[^)]+)\)\)\s*\+\$\s*$', pat)
                if m:
                    inner = m.group('grp')
                    alts = [a.strip() for a in inner.split('|') if a.strip()]
                    cleaned = []
                    for a in alts:
                        try:
                            if '\\' in a:
                                a = bytes(a, 'utf-8').decode('unicode_escape')
                        except Exception:
                            pass
                        cleaned.append(a)
                    terms_line = ", ".join(cleaned)

            if terms_line:
                self.var_terms.set(terms_line)

            self._refresh()

        except Exception:
            pass

class KeywordRule:
    def __init__(self, pattern: str, replies: List[str], source_terms: str | None = None):
        self.pattern = pattern
        self.replies = replies
        self.source_terms = source_terms

    def to_dict(self):
        d = {"keyword": self.pattern, "replies": self.replies}
        if getattr(self, 'source_terms', None):
            d["source_terms"] = self.source_terms
        return d

class Dataset:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.rules: List[KeywordRule] = []
        self.compiled: List[Tuple[re.Pattern, List[str]]] = []
        self.reply_norm_set = set()

    def load(self):
        self.rules.clear()
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = []
        for item in data:
            replies = item["replies"]
            # מיגרציה: אם נשמרה תגובה אחת עם תווי "\\n" — נפרק לשורות
            if isinstance(replies, list) and len(replies) == 1 and "\\n" in replies[0]:
                replies = [part.strip() for part in replies[0].split("\\n") if part.strip()]
            self.rules.append(KeywordRule(item["keyword"], replies, item.get("source_terms")))
        self._recompile()

    def save(self, path: Path | None = None):
        if path is not None:
            self.path = Path(path)
        data = [rule.to_dict() for rule in self.rules]
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def _recompile(self):
        self.compiled.clear()
        self.reply_norm_set = set()
        for rule in self.rules:
            try:
                pat = re.compile(rule.pattern, re.IGNORECASE)
            except re.error:
                continue
            self.compiled.append((pat, rule.replies))
            for r in rule.replies:
                self.reply_norm_set.add(_norm(r))

    def is_bot_reply(self, msg: str) -> bool:
        if msg == MEDIA_PLACEHOLDER:
            return False
        return _norm(msg) in self.reply_norm_set

    def match(self, msg: str) -> str | None:
        if msg == MEDIA_PLACEHOLDER:
            return None
        for pat, replies in self.compiled:
            if pat.search(msg):
                return random.choice(replies) if replies else None
        return None

    def add_rule(self, pattern: str, replies: List[str], source_terms: str | None = None):
        self.rules.append(KeywordRule(pattern, replies, source_terms))
        self._recompile()

    def delete_rule(self, idx: int):
        del self.rules[idx]
        self._recompile()

    def update_rule(self, idx: int, pattern: str, replies: List[str], source_terms: str | None = None):
        self.rules[idx].pattern = pattern
        self.rules[idx].replies = replies
        if source_terms is not None:
            try:
                self.rules[idx].source_terms = source_terms
            except Exception:
                pass
        self._recompile()

# ---------- Settings model ----------
DEFAULT_SETTINGS = {
    "theme": "light",                  # "dark" / "light"
    "autosave_enabled": True,
    "autosave_interval_sec": 15,      # כמה שניות בין שמירות
    "confirm_deletions": True,
    "start_maximized": False,
    "poll_interval_sec": DEFAULT_POLL_INTERVAL,
        "recent_groups": [],
    "group_history": [],
}

class Settings:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.values = DEFAULT_SETTINGS.copy()

    def load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.values.update({k: data.get(k, v) for k, v in DEFAULT_SETTINGS.items()})
            except Exception:
                pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.values, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print("Cannot save settings:", e)

# ---------- Bot engine ----------
class BotThread(threading.Thread):
    def __init__(self, dataset: Dataset, group_name: str, on_status, settings: Settings):
        super().__init__(daemon=True)
        self.dataset = dataset
        self.group_name = group_name
        self.stop_event = threading.Event()
        self.on_status = on_status
        self.driver = None
        self.settings = settings

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            self.on_status("פותח את WhatsApp Web…")
            self.driver = build_driver(start_maximized=self.settings.values.get("start_maximized", True))
            self.driver.get("https://web.whatsapp.com")
            self.on_status("ממתין/ה להתחברות…")
            wait_for_login(self.driver)
            if self.group_name == FREE_CHOICE:
                self.on_status("החיבור בוצע. מצב בחירה חופשית: בחר/י ידנית צ\'אט ב-WhatsApp…")
                try:
                    WebDriverWait(self.driver, 600).until(EC.element_to_be_clickable((By.XPATH, MSG_AREA)))
                except Exception:
                    self.on_status("פג הזמן לבחירת צ\'אט. עצירה.")
                    return
                self.on_status("נבחר צ\'אט. הבוט פועל ומאזין להודעות…")
            else:
                self.on_status("החיבור בוצע. פותח את הצ\'אט…")
                open_chat(self.driver, self.group_name)
                self.on_status("הבוט פועל ומאזין להודעות…")
            last_processed = None
            poll = max(1, int(self.settings.values.get("poll_interval_sec", DEFAULT_POLL_INTERVAL)))
            while not self.stop_event.is_set():
                try:
                    msg = last_incoming_text(self.driver)
                except Exception as e:
                    self.on_status(f"שגיאה בקריאת הודעות: {e}")
                    time.sleep(2)
                    continue
                if msg != last_processed:
                    if self.dataset.is_bot_reply(msg):
                        self.on_status("דילוג: ההודעה האחרונה היא תגובה של הבוט.")
                    else:
                        self.on_status(f"התקבלה הודעה: {msg}")
                        reply = self.dataset.match(msg)
                        if reply:
                            try:
                                box = WebDriverWait(self.driver, 10).until(
                                    EC.element_to_be_clickable((By.XPATH, MSG_AREA))
                                )
                                time.sleep(0.6)
                                box.send_keys(reply, Keys.ENTER)
                                self.on_status(f"נשלחה תגובה: {reply}")
                            except Exception as e:
                                self.on_status(f"כשל בשליחה: {e}")
                        else:
                            self.on_status("אין התאמת מילת מפתח. ממתין/ה…")
                    last_processed = msg
                time.sleep(poll)
        except Exception as e:
            self.on_status(f"שגיאה קריטית: {e}")
        finally:
            try:
                if self.driver:
                    self.driver.quit()
            except Exception:
                pass
            self.on_status("הבוט נעצר.")

# ---------- App GUI (Right Sidebar, without Bulk page) ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x760")

        # הגדרות
        self.settings = Settings(SETTINGS_PATH)
        self.settings.load()

# בסיס: סטייל/פונט
        style = ttk.Style(self)
        try:
            if "vista" in style.theme_names():
                style.theme_use("clam")
            else:
                style.theme_use(style.theme_use())
        except Exception:
            pass

        style.configure("Nav.TButton", font=("Arial", 11), padding=(10, 10))
        style.configure("Primary.TButton", font=("Arial", 11, "bold"))
        style.configure("TLabel", font=("Arial", 11))
        style.configure("TLabelframe.Label", font=("Arial", 11, "bold"))
        style.configure("Treeview", rowheight=24, font=("Arial", 11))
        style.configure("Treeview.Heading", font=("Arial", 11, "bold"))

        self.apply_theme(self.settings.values.get("theme", "dark"))

        self.dataset = Dataset(Path(DEFAULT_DATASET))
        try:
            self.dataset.load()
        except Exception as e:
            messagebox.showwarning("מאגר", f"שגיאה בטעינת המאגר: {e}")
        self.bot: BotThread | None = None

        # דגל שמירה אוטומטית
        self._dirty = False
        self._autosave_after_id = None
        if self.settings.values.get("autosave_enabled", True):
            self.schedule_autosave()

        # מבנה כללי: אזור תוכן + סייד־בר ימני
        self.columnconfigure(0, weight=1)  # אזור התוכן
        self.columnconfigure(1, weight=0)  # סייד־בר
        self.rowconfigure(0, weight=1)

        # ---- אזור התוכן (Stack of frames) ----
        self.content = ttk.Frame(self)
        self.content.grid(row=0, column=0, sticky="nsew")
        for i in range(1):
            self.content.rowconfigure(i, weight=1)
            self.content.columnconfigure(i, weight=1)

        self.page_bot = ttk.Frame(self.content)        # "בוט"
        self.page_dataset = ttk.Frame(self.content)    # "ניהול מאגר"
        self.page_settings = ttk.Frame(self.content)   # "הגדרות"
        for p in (self.page_bot, self.page_dataset, self.page_settings):
            p.grid(row=0, column=0, sticky="nsew")

        # ---- סייד־בר ימני ----
        self.sidebar = ttk.Frame(self)
        self.sidebar.grid(row=0, column=1, sticky="ns")
        self.sidebar.rowconfigure(6, weight=1)  # רווח דוחף

        ttk.Label(self.sidebar, text="ניווט", anchor="e").grid(row=0, column=0, sticky="ew", padx=12, pady=(16,6))
        self.btn_bot  = ttk.Button(self.sidebar, text="בוט", style="Nav.TButton", command=lambda: self.show_page(self.page_bot))
        self.btn_data = ttk.Button(self.sidebar, text="ניהול מאגר", style="Nav.TButton", command=lambda: self.show_page(self.page_dataset))
        # הוסר: self.btn_bulk — אין אופציה שלישית
        self.btn_settings = ttk.Button(self.sidebar, text="הגדרות", style="Nav.TButton", command=lambda: self.show_page(self.page_settings))
        self.btn_bot.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        self.btn_data.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        self.btn_settings.grid(row=3, column=0, sticky="ew", padx=12, pady=6)

        # קו מפריד דק
        sep = ttk.Separator(self, orient="vertical")
        sep.grid(row=0, column=1, sticky="nsw")

        # בנה דפי תוכן
        self._build_bot_page()
        self._build_dataset_page()
        # הוסר: self._build_bulk_page()
        self._build_settings_page()

        self.show_page(self.page_bot)

        if self.settings.values.get("start_maximized", True):
            try:
                self.state('zoomed')
            except Exception:
                pass

    # --- Theme ---
    def apply_theme(self, mode: str):


        """
        mode: 'dark' / 'light'
        התאמות מצב כהה: inputs שחורים עם outline לבן, טקסט קריא, וכפתורים קריאים.
        """
        import tkinter as tk
        from tkinter import ttk

        # --------- Palette ---------
        bg_dark  = "#1c1f24"   # app background
        fg_dark  = "#f2f4f8"   # text
        box_dark = "#0f1115"   # entry/combobox background (almost black)
        line     = "#ffffff"   # white outline

        bg_light = "#f2f2f2"
        fg_light = "#202020"
        box_light= "#ffffff"

        style = ttk.Style(self)
        if mode == "dark":
            try:
                style.theme_use("clam")
            except Exception:
                pass
            bg, fg, box = bg_dark, fg_dark, box_dark
        else:
            try:
                if "vista" in style.theme_names():
                    style.theme_use("clam")
            except Exception:
                pass
            bg, fg, box = bg_light, fg_light, box_light

        # Window + common
        try:
            self.configure(bg=bg)
        except Exception:
            pass
        style.configure(".", background=bg, foreground=fg)
        style.configure("TFrame", background=bg)
        style.configure("TLabelframe", background=bg)
        style.configure("TLabelframe.Label", background=bg, foreground=fg)
        style.configure("TLabel", background=bg, foreground=fg)

        # Buttons
        if mode == "light":
            # In LIGHT mode, make all buttons black with white text
            style.configure("Nav.TButton", background="#000000", foreground="#ffffff", padding=(10,8))
            style.map("Nav.TButton",
                      background=[("active", "#1A4FC3"), ("pressed", "#111111")],
                      foreground=[("disabled", "#b3b3b3")])
            style.configure("TButton", background="#000000", foreground="#ffffff")
            style.map("TButton",
                      background=[("active", "#1A4FC3"), ("pressed", "#111111")],
                      foreground=[("disabled", "#b3b3b3")])
            style.configure("Primary.TButton", background="#8735BA", foreground="#ffffff")
            style.map("Primary.TButton",
                      background=[("active", "#3fbc60"), ("pressed", "#111111")],
                      foreground=[("disabled", "#b3b3b3")])
        else:
            # DARK mode — keep existing contrasty defaults
            style.configure("Nav.TButton", background="#ffffff", foreground="#111111", padding=(10,8))
            style.map("Nav.TButton", background=[("active", "#4b41b9")], foreground=[("disabled", "#7a7a7a")])
            style.configure("TButton", background="#ffffff", foreground="#111111")
            style.map("TButton", background=[("active", "#1648B5")], foreground=[("disabled", "#7a7a7a")])
            style.configure("Primary.TButton", background="#3b82f6", foreground="#ffffff")
            style.map("Primary.TButton", background=[("active", "#3727c7")], foreground=[("disabled", "#cbd5e1")])
        # Inputs (Entry/Spinbox/Combobox) — black + white outline in dark
        entry_common = dict(fieldbackground=box, foreground=fg,
                            bordercolor=line, lightcolor=line, darkcolor=line,
                            borderwidth=1)
        for sty in ("TEntry", "TSpinbox", "TCombobox"):
            try:
                style.configure(sty, **entry_common)
            except Exception:
                pass

        # readonly combobox colors
        style.map("TCombobox",
                  fieldbackground=[("readonly", box)],
                  foreground=[("readonly", fg)],
                  selectbackground=[("!disabled", box)],
                  selectforeground=[("!disabled", fg)])

        # Text widgets (multi-line)
        def patch_text_colors(widget: tk.Text):
            try:
                widget.configure(bg=box, fg=fg, insertbackground=fg,
                                 highlightthickness=1,
                                 highlightbackground=line,
                                 highlightcolor=line)
            except Exception:
                pass
        self._patch_text_colors = patch_text_colors

        # Apply to existing Text widgets now
        def _walk_widgets(root):
            try:
                kids = root.winfo_children()
            except Exception:
                kids = []
            for w in kids:
                if isinstance(w, tk.Text):
                    patch_text_colors(w)
                _walk_widgets(w)
        try:
            _walk_widgets(self)
        except Exception:
            pass

        # Treeview
        style.configure("Treeview", background=box, fieldbackground=box, foreground=fg, bordercolor=line)
        style.configure("Treeview.Heading", background=bg, foreground=fg)
        style.map("Treeview", background=[("selected", "#272b32")], foreground=[("selected", "#ffffff")])

        # Check/Radio
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("TRadiobutton", background=bg, foreground=fg)

    def show_page(self, page: ttk.Frame):
        page.tkraise()

    # --------- תוכן: דף הבוט ---------
    def _build_bot_page(self):
        ICO_FILE = "mordi_icon.ico"
        try:
            self.iconbitmap(default=resource_path(ICO_FILE))  # Windows: uses .ico
        except tk.TclError:
    # Optional fallback (Linux/macOS): use a PNG if you have one
    # img = tk.PhotoImage(file=resource_path("mordi_icon.png"))
    # self.iconphoto(True, img)
            pass
        frm = self.page_bot
        for i in range(2):
            frm.columnconfigure(i, weight=1)
        frm.rowconfigure(3, weight=1)

        ds_frame = ttk.LabelFrame(frm, text="מאגר")
        ds_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
        self.ds_path_var = tk.StringVar(value=str(Path(DEFAULT_DATASET).resolve()))
        entry = ttk.Entry(ds_frame, textvariable=self.ds_path_var, justify="right")
        entry.grid(row=0, column=2, sticky="ew", padx=6, pady=6)
        ds_frame.columnconfigure(2, weight=1)
        ttk.Button(ds_frame, text="פתח…", command=self.on_open_dataset).grid(row=0, column=1, padx=4, pady=6, sticky="e")
        ttk.Button(ds_frame, text="שמור", command=self.on_save_dataset).grid(row=0, column=0, padx=4, pady=6, sticky="e")
        ttk.Button(ds_frame, text="שמור בשם…", command=self.on_save_as_dataset).grid(row=1, column=1, padx=4, pady=6, sticky="e")
        ttk.Button(ds_frame, text="רענן", command=self.on_reload_dataset).grid(row=1, column=0, padx=4, pady=6, sticky="e")

        
        ttk.Button(ds_frame, text="מאגר חדש…", command=self.on_new_dataset).grid(row=1, column=2, padx=4, pady=6, sticky="w")
        ctrl = ttk.LabelFrame(frm, text="שליטה בבוט")
        ctrl.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
        ttk.Label(ctrl, text="שם הקבוצה:").grid(row=0, column=2, padx=6, pady=6, sticky="e")
        # Build initial list: FREE_CHOICE + recents
        _rec = list(self.settings.values.get("recent_groups", []))
        if FREE_CHOICE not in _rec:
            _rec.insert(0, FREE_CHOICE)
        self.group_var = tk.StringVar(value=_rec[0] if _rec else FREE_CHOICE)
        self.group_combo = ttk.Combobox(
            ctrl,
            textvariable=self.group_var,
            values=_rec,
            state="normal",
            width=24,
            justify="right"
        )
        self.group_combo.grid(row=0, column=1, padx=6, sticky="e")
        # Autocomplete: filter from full history on each key release
        self.group_combo.bind("<KeyRelease>", self._filter_group_suggestions)
        self._group_combo_first_edit = True
        self.group_combo.bind("<FocusIn>", self._on_group_focus_in)
        self.group_combo.bind("<KeyPress>", self._on_group_keypress)
        self.group_combo.bind("<<ComboboxSelected>>", lambda e: (self.group_var.set(self.group_combo.get()), setattr(self, "_group_combo_first_edit", False)))
        ttk.Button(ctrl, text="התחל", style="Primary.TButton", command=self.on_start).grid(row=0, column=0, padx=6, sticky="e")
        ttk.Button(ctrl, text="עצור", command=self.on_stop).grid(row=0, column=3, padx=6, sticky="e")

        ttk.Label(frm, text="סטטוס").grid(row=2, column=1, padx=10, sticky="e")
        self.status = tk.Text(frm, height=10)
        self.status.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0,10))
        _rtl_text_widget(self.status)
        self._patch_text_colors(self.status)
        self._log("מוכן.")

    # --------- תוכן: דף ניהול מאגר ---------
    def _build_dataset_page(self):
        frm = self.page_dataset
        for i in range(2):
            frm.columnconfigure(i, weight=1)
        frm.rowconfigure(1, weight=1)

        # עץ כללים (ימין): תצוגה
        rules_frame = ttk.LabelFrame(frm, text="כללים")
        rules_frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=10, pady=10)
        rules_frame.columnconfigure(0, weight=1)
        rules_frame.rowconfigure(1, weight=1)

        self.rules = ttk.Treeview(rules_frame, columns=("count","keywords","idx"), show="headings", selectmode="browse")
        self.rules.heading("count", text="מס׳ תגובות")
        self.rules.heading("keywords", text="מילות מפתח (תצוגה)")
        self.rules.heading("idx", text="#")
        self.rules.column("count", anchor="center", width=120)
        self.rules.column("keywords", anchor="center", width=520)
        self.rules.column("idx", anchor="center", width=50)
        self.rules.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self.rules.bind("<<TreeviewSelect>>", self.on_tree_select)

        btns = ttk.Frame(rules_frame)
        btns.grid(row=0, column=0, sticky="e", padx=6, pady=(8,0))
        ttk.Button(btns, text="הוסף", command=self.on_add_rule).pack(side="right", padx=3)
        ttk.Button(btns, text="ערוך", command=self.on_edit_regex).pack(side="right", padx=3)
        ttk.Button(btns, text="מחק", command=self.on_delete_rule).pack(side="right", padx=3)
        ttk.Button(btns, text="שכפל", command=self.on_dup_rule).pack(side="right", padx=3)

        # עורך (שמאל): קריאה בלבד + כפתור עריכה ב-Notepad
        editor = ttk.LabelFrame(frm, text="כלל נבחר (תצוגה)")
        editor.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        editor.columnconfigure(0, weight=1)

        row = ttk.Frame(editor)
        row.grid(row=0, column=0, sticky="ew")
        ttk.Label(row, text="ביטוי (Regex):").pack(side="right")
        self.pattern_var = tk.StringVar()
        ent_pattern = ttk.Entry(row, textvariable=self.pattern_var, justify="right")
        ent_pattern.pack(side="right", fill="x", expand=True, padx=6)
        ent_pattern.bind("<FocusOut>", self.on_pattern_commit)
        ent_pattern.bind("<Return>", self.on_pattern_commit)

        ttk.Label(editor, text="תגובות (אחת בכל שורה) — תצוגה בלבד:").grid(row=1, column=0, sticky="e", pady=(6,0))
        self.replies_txt = tk.Text(editor, height=16, state="disabled")
        self.replies_txt.grid(row=2, column=0, sticky="nsew")
        vsb_replies = ttk.Scrollbar(editor, orient='vertical', command=self.replies_txt.yview)
        self.replies_txt.configure(yscrollcommand=vsb_replies.set)
        editor.rowconfigure(2, weight=1)
        vsb_replies.grid(row=2, column=1, sticky='ns')
        _rtl_text_widget(self.replies_txt)
        self._patch_text_colors(self.replies_txt)

        actions = ttk.Frame(editor)
        actions.grid(row=3, column=0, sticky="e", pady=6)
        ttk.Button(actions, text='ערוך בפנקס רשימות…', command=self.on_edit_in_notepad).pack(side='right', padx=4)

        self.refresh_rules_tree()

    # --------- דף הגדרות ---------
    def _build_settings_page(self):
        frm = self.page_settings
        for i in range(2):
            frm.columnconfigure(i, weight=1)

        # ערכת נושא
        theme_frame = ttk.LabelFrame(frm, text="ערכת נושא")
        theme_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        ttk.Label(theme_frame, text="בחר/י מצב:").grid(row=0, column=1, sticky="e", padx=6, pady=6)
        self.theme_var = tk.StringVar(value=self.settings.values.get("theme", "dark"))
        ttk.Radiobutton(theme_frame, text="כהה", value="dark", variable=self.theme_var,
                        command=self.on_change_theme).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(theme_frame, text="בהיר", value="light", variable=self.theme_var,
                        command=self.on_change_theme).grid(row=1, column=0, sticky="w")

        # שמירה אוטומטית
        autosave_frame = ttk.LabelFrame(frm, text="שמירה אוטומטית של המאגר")
        autosave_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        self.autosave_enabled = tk.BooleanVar(value=self.settings.values.get("autosave_enabled", True))
        ttk.Checkbutton(autosave_frame, text="הפעל שמירה אוטומטית",
                        variable=self.autosave_enabled, command=self.on_toggle_autosave).grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(autosave_frame, text="כל כמה שניות לשמור:").grid(row=0, column=1, sticky="e")
        self.autosave_interval = tk.IntVar(value=int(self.settings.values.get("autosave_interval_sec", 15)))
        spin = ttk.Spinbox(autosave_frame, from_=5, to=600, textvariable=self.autosave_interval, width=6, command=self.on_change_autosave_interval)
        spin.grid(row=0, column=2, sticky="w", padx=6)

        # התנהגות
        behavior = ttk.LabelFrame(frm, text="התנהגות")
        behavior.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        self.confirm_del = tk.BooleanVar(value=self.settings.values.get("confirm_deletions", True))
        ttk.Checkbutton(behavior, text="אישור לפני מחיקה", variable=self.confirm_del, command=self.on_update_settings).grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.start_maximized = tk.BooleanVar(value=self.settings.values.get("start_maximized", True))
        ttk.Checkbutton(behavior, text="פתח חלון ממוקסם", variable=self.start_maximized, command=self.on_update_settings).grid(row=0, column=1, sticky="w", padx=6, pady=6)

        ttk.Label(behavior, text="מרווח פולינג לבוט (שניות):").grid(row=1, column=1, sticky="e", padx=6)
        self.poll_interval = tk.IntVar(value=int(self.settings.values.get("poll_interval_sec", DEFAULT_POLL_INTERVAL)))
        ttk.Spinbox(behavior, from_=1, to=60, textvariable=self.poll_interval, width=6, command=self.on_update_settings).grid(row=1, column=0, sticky="w", padx=6)

        # כפתור שמירה
        savebar = ttk.Frame(frm)
        savebar.grid(row=3, column=0, sticky="e", padx=10, pady=(0,10))
        ttk.Button(savebar, text="שמור הגדרות", command=self.on_save_settings_clicked).grid(row=0, column=0, padx=6)

    # ---------- עזרי תצוגה/שמירה אוטומטית ----------
    def _mark_dirty(self):
        self._dirty = True

    def schedule_autosave(self):
        if hasattr(self, "_autosave_after_id") and self._autosave_after_id:
            try:
                self.after_cancel(self._autosave_after_id)
            except Exception:
                pass
        interval = max(5, int(self.settings.values.get("autosave_interval_sec", 15)))
        self._autosave_after_id = self.after(interval * 1000, self._autosave_tick)

    def _autosave_tick(self):
        try:
            if self.settings.values.get("autosave_enabled", True) and self._dirty:
                self.dataset.save(self.dataset.path)
                self._dirty = False
                self._log(f"שמירה אוטומטית: {self.dataset.path}")
        finally:
            self.schedule_autosave()

    # ---------- dataset handlers ----------

    def on_new_dataset(self):
        """
        יוצר מאגר חדש ריק (JSON) באותה תיקייה של המאגר הנוכחי, לפי שם שהמשתמש בוחר,
        טוען אותו מיד — ללא שינויי UI נוספים.
        """
        from pathlib import Path
        from tkinter import messagebox, simpledialog
        try:
            cur = Path(self.ds_path_var.get()).expanduser()
        except Exception:
            cur = Path("keywords.json")
        parent = cur.parent if cur.parent.exists() else Path(".")
        name = simpledialog.askstring("מאגר חדש", "שם הקובץ (ללא סיומת):", initialvalue="keywords_new")
        if not name:
            return
        name = name.strip()
        if not name:
            messagebox.showwarning("שם חסר", "נא להזין שם לקובץ.")
            return
        if not name.lower().endswith(".json"):
            name += ".json"
        new_path = (parent / name).resolve()
        if new_path.exists():
            if not messagebox.askyesno("קובץ קיים", f"הקובץ {new_path.name} כבר קיים. להחליף?"):
                return
        try:
            new_path.write_text("[]", encoding="utf-8")
            self.dataset = Dataset(new_path)
            self.dataset.load()
            self.ds_path_var.set(str(new_path))
            self.refresh_rules_tree()
            self._dirty = False
            if hasattr(self, "_log"):
                self._log(f"נוצר מאגר חדש: {new_path}")
        except Exception as e:
            messagebox.showerror("יצירת מאגר", f"שגיאה: {e}")



    def on_open_dataset(self):
        path = filedialog.askopenfilename(
            title="פתח מאגר",
            filetypes=[("JSON‏ קבצי", "*.json"), ("כל הקבצים","*.*")],
            initialfile=str(self.dataset.path)
        )
        if not path:
            return
        try:
            self.dataset = Dataset(Path(path))
            self.dataset.load()
            self.ds_path_var.set(str(Path(path).resolve()))
            self.refresh_rules_tree()
            self._log(f"נפתח מאגר: {path}")
        except Exception as e:
            messagebox.showerror("פתח מאגר", str(e))

    def on_save_dataset(self):
        try:
            self.dataset.save(self.dataset.path)
            self._dirty = False
            self._log(f"נשמר: {self.dataset.path}")
        except Exception as e:
            messagebox.showerror("שמירה", str(e))

    def on_save_as_dataset(self):
        path = filedialog.asksaveasfilename(
            title="שמור בשם…",
            defaultextension=".json",
            filetypes=[("JSON‏ קבצי", "*.json")]
        )
        if not path:
            return
        try:
            self.dataset.save(Path(path))
            self.ds_path_var.set(str(Path(path).resolve()))
            self._dirty = False
            self._log(f"שמירה בשם: {path}")
        except Exception as e:
            messagebox.showerror("שמור בשם", str(e))

    def on_reload_dataset(self):
        try:
            self.dataset.load()
            self.refresh_rules_tree()
            self._log("המאגר נטען מחדש.")
        except Exception as e:
            messagebox.showerror("רענון", str(e))

    # ---------- bot handlers ----------
    def _remember_group_name(self, name: str):
        name = (name or "").strip()
        if not name or name == FREE_CHOICE:
            return
        lst = [n for n in self.settings.values.get("recent_groups", []) if n.strip() and n != name]
        lst.insert(0, name)
        self.settings.values["recent_groups"] = lst[:10]
        hist = [n for n in self.settings.values.get("group_history", []) if n.strip() and n != name]
        hist.insert(0, name)
        self.settings.values["group_history"] = hist[:200]
        self.settings.save()
        try:
            if hasattr(self, "group_combo"):
                vals = [FREE_CHOICE] + [g for g in self.settings.values["recent_groups"] if g != FREE_CHOICE]
                self.group_combo["values"] = vals
        except Exception:
            pass

    def _filter_group_suggestions(self, event=None):
        """Autocomplete: filter combobox values based on typed text, using full history."""
        try:
            q = (self.group_var.get() or "").strip()
            hist = self.settings.values.get("group_history", [])
            base = [g for g in hist if (not q or q in g)]
            rec = [g for g in self.settings.values.get("recent_groups", []) if (not q or q in g)]
            seen = set()
            merged = []
            for name in ([FREE_CHOICE] + rec + base):
                if name not in seen:
                    merged.append(name); seen.add(name)
            self.group_combo["values"] = merged[:200]
        except Exception:
            pass


    def _on_group_focus_in(self, event=None):
        """Select all on focus, so first typed char replaces the placeholder/value."""
        try:
            self.group_combo.selection_range(0, tk.END)
        except Exception:
            pass

    def _on_group_keypress(self, event=None):
        """On first printable keypress, clear the field once (modern input UX)."""
        try:
            if not getattr(self, "_group_combo_first_edit", False):
                return
            keysym = getattr(event, "keysym", "")
            ch = getattr(event, "char", "")
            printable = bool(ch and ch.isprintable())
            to_clear = printable or keysym in ("BackSpace", "Delete")
            if to_clear:
                self.group_var.set("")
                try:
                    self.group_combo.icursor(tk.END)
                except Exception:
                    pass
                self._group_combo_first_edit = False
        except Exception:
            pass


    def _filter_group_suggestions(self, event=None):
        """Autocomplete: filter combobox values based on typed text, using full history."""
        try:
            q = (self.group_var.get() or "").strip()
            hist = self.settings.values.get("group_history", [])
            base = [g for g in hist if (not q or q in g)]
            rec = [g for g in self.settings.values.get("recent_groups", []) if (not q or q in g)]
            seen = set()
            merged = []
            for name in ([FREE_CHOICE] + rec + base):
                if name not in seen:
                    merged.append(name); seen.add(name)
            self.group_combo["values"] = merged[:200]
        except Exception:
            pass

        name = (name or "").strip()
        if not name or name == FREE_CHOICE:
            return
        lst = [n for n in self.settings.values.get("recent_groups", []) if n.strip() and n != name]
        lst.insert(0, name)
        self.settings.values["recent_groups"] = lst[:10]
        hist = [n for n in self.settings.values.get("group_history", []) if n.strip() and n != name]
        hist.insert(0, name)
        self.settings.values["group_history"] = hist[:200]
        self.settings.save()
        try:
            if hasattr(self, "group_combo"):
                self.group_combo["values"] = [FREE_CHOICE] + [g for g in self.settings.values["recent_groups"] if g != FREE_CHOICE]
        except Exception:
            pass



    def on_start(self):
        if self.bot and not self.bot.is_alive():
            self.bot = None
        if self.bot and self.bot.is_alive():
            messagebox.showinfo("בוט", "הבוט כבר פועל.")
            return
        group = self.group_var.get().strip()
        if not group:
            messagebox.showwarning("קבוצה", "נא להזין שם קבוצה.")
            return
        self._remember_group_name(group)
        self.settings.values["poll_interval_sec"] = int(self.poll_interval.get())
        self.bot = BotThread(self.dataset, group, self._log, self.settings)
        self.bot.start()

    def on_stop(self):
        if self.bot and self.bot.is_alive():
            self.bot.stop()
            try:
                self.bot.join(timeout=5)
            except Exception:
                pass
            self.bot = None
            self._log("הבוט נעצר וניתן להפעיל אותו מחדש.")
        else:
            self._log("הבוט אינו פעיל.")

    # ---------- rules tree & viewer ----------
    
    def refresh_rules_tree(self):
        for iid in self.rules.get_children():
            self.rules.delete(iid)
        for idx, r in enumerate(self.dataset.rules, start=1):
            display = (getattr(r, "source_terms", None) or _regex_to_keywords_display(r.pattern))
            self.rules.insert("", "end", iid=str(idx-1), values=(len(r.replies), display, idx))
    def _set_replies_display(self, text: str):
        self.replies_txt.configure(state="normal")
        self.replies_txt.delete("1.0", "end")
        self.replies_txt.insert("1.0", text)
        self.replies_txt.configure(state="disabled")

    def on_tree_select(self, event=None):
        sel = self.rules.selection()
        if not sel:
            return
        idx = int(sel[0])
        rule = self.dataset.rules[idx]
        self.pattern_var.set(rule.pattern)
        self._set_replies_display("\n".join(rule.replies))

    def _current_rule_index(self):
        sel = self.rules.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except Exception:
            return None

    def on_pattern_commit(self, event=None):
        """Validate and save Regex pattern changes for the selected rule."""
        idx = self._current_rule_index()
        if idx is None:
            return
        new_pat = self.pattern_var.get().strip()
        if not new_pat:
            messagebox.showwarning("Regex", "שדה הביטוי (Regex) לא יכול להיות ריק.")
            return "break" if event and getattr(event, "keysym", "") == "Return" else None
        try:
            re.compile(new_pat, re.IGNORECASE)
        except re.error as e:
            messagebox.showerror("שגיאת Regex", f"ביטוי לא תקין: {e}")
            # Restore previous pattern to the Entry UI
            prev = self.dataset.rules[idx].pattern
            self.pattern_var.set(prev)
            return "break" if event and getattr(event, "keysym", "") == "Return" else None

        # Update dataset and save
        replies = self.dataset.rules[idx].replies
        self.dataset.update_rule(idx, new_pat, replies)
        self.dataset.save(self.dataset.path)
        self._mark_dirty()
        self._log(f"עודכן ביטוי לכלל #{idx}: {new_pat}")
        # Refresh tree view while trying to keep selection
        cur = str(idx)
        self.refresh_rules_tree()
        try:
            self.rules.selection_set(cur)
            self.rules.see(cur)
        except Exception:
            pass
        return "break" if event and getattr(event, "keysym", "") == "Return" else None

    def on_add_rule(self):

        """פתח את בונה הסינטקס בעת לחיצה על 'הוסף' והוסף כלל חדש עם תבנית בלבד (ללא תגובות)."""

        def _add_from_builder(pattern: str, terms: str = ""):

            if not pattern or not pattern.strip():

                return

            import re

            try:

                re.compile(pattern, re.IGNORECASE)

            except re.error as e:

                from tkinter import messagebox

                messagebox.showerror("שגיאת Regex", f"ביטוי לא תקין: {e}")

                return

            # הוסף כלל חדש עם רשימת תגובות ריקה (ניתן לערוך אחר כך ב-Notepad)

            self.dataset.add_rule(pattern.strip(), [], terms.strip() or None)

            self.dataset.save(self.dataset.path)

            self.refresh_rules_tree()

            self._mark_dirty()

            self._log(f"נוסף כלל חדש מהבונה: {pattern.strip()}")

    

        # פתח את חלון הבונה

        try:

            RegexBuilderDialog(self, on_done=_add_from_builder)

        except Exception as e:

            from tkinter import messagebox

            messagebox.showerror("בונה סינטקס", f"כשל בפתיחת הבונה: {e}")
        if not self.rules.selection():
            messagebox.showinfo("עריכה", "בחר/י כלל לעריכה בעץ הכללים.")
        else:
            self._log("כפתור העריכה הוא דרך 'ערוך בפנקס רשימות…' בלבד עבור התגובות.")

    def on_delete_rule(self):
        sel = self.rules.selection()
        if not sel:
            messagebox.showinfo("מחיקה", "בחר/י כלל למחיקה.")
            return
        idx = int(sel[0])
        if self.settings.values.get("confirm_deletions", True):
            if not messagebox.askyesno("אישור מחיקה", f"למחוק כלל מספר {idx}?"):
                return
        self.dataset.delete_rule(idx)
        self.refresh_rules_tree()
        self.pattern_var.set("")
        self._set_replies_display("")
        self._log(f"נמחק כלל #{idx}.")
        self._mark_dirty()

    def on_dup_rule(self):
        sel = self.rules.selection()
        if not sel:
            messagebox.showinfo("שכפול", "בחר/י כלל לשכפול.")
            return
        idx = int(sel[0])
        rule = self.dataset.rules[idx]
        self.dataset.add_rule(rule.pattern, list(rule.replies))
        self.refresh_rules_tree()
        self._log(f"שוכפל כלל #{idx}.")
        self._mark_dirty()

    # ---------- עריכת תגובות ב-Notepad ----------

    def on_edit_regex(self):
        """פותח את 'בונה הסינטקס' בדיוק כמו 'הוסף', אך עם מילוי אוטומטי מהתבנית או source_terms — ושומר על הכלל הנבחר."""
        sel = self.rules.selection()
        if not sel:
            from tkinter import messagebox
            messagebox.showinfo("עריכה", "בחר/י כלל לעריכה בעץ הכללים.")
            return
        idx = int(sel[0])
        rule = self.dataset.rules[idx]

        def _save_from_builder(pattern: str, terms: str = ""):
            if not pattern or not pattern.strip():
                return
            import re as _re
            try:
                _re.compile(pattern, _re.IGNORECASE)
            except _re.error as e:
                from tkinter import messagebox
                messagebox.showerror("Regex לא תקין", f"לא ניתן לשמור: {e}")
                return
            self.dataset.update_rule(idx, pattern, list(rule.replies), terms.strip() or getattr(rule, 'source_terms', None))
            self.dataset.save(self.dataset.path)
            self._mark_dirty()
            self._log(f"עודכן Regex לכלל #{idx}: {pattern}")
            cur = str(idx)
            self.refresh_rules_tree()
            try:
                self.rules.selection_set(cur)
                self.rules.see(cur)
            except Exception:
                pass
            self.pattern_var.set(pattern)
            self._set_replies_display("\n".join(rule.replies))

        try:
            dlg = RegexBuilderDialog(self, on_done=_save_from_builder)

            # Prefill from stored 'source_terms' if available (מיידית)
            try:
                st = getattr(rule, 'source_terms', None)
                if st:
                    dlg.var_terms.set(st)
                    dlg.var_mode.set("part")
                    dlg._refresh()
            except Exception:
                pass

            # Try structured load from the existing regex
            try:
                dlg.load_from_pattern(rule.pattern)
            except Exception:
                pass

            # If still empty, do a best-effort fallback extraction
            try:
                if not dlg.var_terms.get().strip():
                    fallback_prefill(dlg, rule.pattern)
            except Exception:
                pass

        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("בונה סינטקס", f"כשל בפתיחת הבונה: {e}")

    def on_edit_in_notepad(self):
        sel = self.rules.selection()
        if not sel:
            messagebox.showinfo("עריכה", "בחר/י כלל לעריכה בעץ הכללים.")
            return
        idx = int(sel[0])
        rule = self.dataset.rules[idx]

        # טמפ קובץ
        tmpdir = Path(tempfile.gettempdir())
        tmpfile = tmpdir / f"mordi_rule_{idx}.txt"
        try:
            with open(tmpfile, "w", encoding="utf-8") as f:
                f.write("\n".join(rule.replies))
        except Exception as e:
            messagebox.showerror("Notepad", f"שגיאה ביצירת קובץ זמני: {e}")
            return

        # פתח Notepad והמתן לסיום
        try:
            if os.name == "nt":
                proc = subprocess.Popen(["notepad.exe", str(tmpfile)])
                proc.wait()
            else:
                # מערכות אחרות: ניסיון לפתוח בעורך ברירת מחדל, ואז לבקש אישור לחזור
                if sys.platform == "darwin":
                    subprocess.Popen(["open", str(tmpfile)]).wait()
                else:
                    subprocess.Popen(["xdg-open", str(tmpfile)]).wait()
                messagebox.showinfo("עריכה", "לאחר שסגרת את העורך, לחץ/י אישור כדי לטעון את השינויים.")
        except Exception as e:
            messagebox.showerror("Notepad", f"שגיאה בפתיחת העורך: {e}")
            return

        # קרא חזרה ועדכן
        try:
            with open(tmpfile, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\r\n") for ln in f.readlines()]
            new_replies = [ln.strip() for ln in lines if ln.strip()]
            self.dataset.update_rule(idx, rule.pattern, new_replies)
            self._mark_dirty()
            self.refresh_rules_tree()
            # שמירה מיידית לקובץ המאגר
            self.dataset.save(self.dataset.path)
            self._log(f"עודכנו תגובות לכלל #{idx} ({len(new_replies)} שורות).")
            # רענון תצוגה
            self.pattern_var.set(self.dataset.rules[idx].pattern)
            self._set_replies_display("\n".join(self.dataset.rules[idx].replies))
        except Exception as e:
            messagebox.showerror("טעינת שינויים", f"שגיאה בטעינת השינויים: {e}")

    # ---------- Settings handlers ----------
    def on_change_theme(self):
        mode = self.theme_var.get()
        self.settings.values["theme"] = mode
        self.apply_theme(mode)
        self.on_update_settings()
        for txt in [getattr(self, "status", None), getattr(self, "replies_txt", None)]:
            if isinstance(txt, tk.Text):
                self._patch_text_colors(txt)

    def on_toggle_autosave(self):
        enabled = bool(self.autosave_enabled.get())
        self.settings.values["autosave_enabled"] = enabled
        if enabled:
            self.schedule_autosave()
        else:
            if hasattr(self, "_autosave_after_id") and self._autosave_after_id:
                try:
                    self.after_cancel(self._autosave_after_id)
                except Exception:
                    pass
                self._autosave_after_id = None
        self.on_update_settings()

    def on_change_autosave_interval(self):
        val = max(5, int(self.autosave_interval.get()))
        self.settings.values["autosave_interval_sec"] = val
        self.schedule_autosave()
        self.on_update_settings()

    def on_update_settings(self):
        self.settings.values["confirm_deletions"] = bool(self.confirm_del.get())
        self.settings.values["start_maximized"]   = bool(self.start_maximized.get())
        self.settings.values["poll_interval_sec"] = max(1, int(self.poll_interval.get()))
        self.settings.save()
        self._log("ההגדרות עודכנו ונשמרו.")

    def on_save_settings_clicked(self):
        self.on_update_settings()
        messagebox.showinfo("הגדרות", "ההגדרות נשמרו.")

    # ---------- logging ----------
    def _log(self, msg: str):
        try:
            self.status.insert("end", msg + "\n", ("rtl",))
            self.status.see("end")
        except Exception:
            self.status.insert("end", msg + "\n")
            self.status.see("end")

def main():
    app = App()
    app.mainloop()

# =========================
#   Scheduler Add-on
#   (non-breaking extension: adds a "תזמון הודעות" page and a background scheduler)
# =========================
from datetime import datetime, timedelta
import json as _json
import threading as _thr
import time as _time
import queue as _queue

SCHEDULES_PATH = Path("schedules.json")

def _edit_text_in_notepad(initial_text: str = "") -> str:
    """
    Opens Windows Notepad to edit a message body. Returns the edited text.
    On non-Windows, falls back to a simple Tk text popup.
    """
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8")
        tmp.write(initial_text or "")
        tmp.flush()
        tmp.close()
        try:
            if os.name == "nt":
                subprocess.call(["notepad.exe", tmp.name])
            else:
                # Simple cross-platform fallback: open default editor if available
                editor = os.environ.get("EDITOR")
                if editor:
                    subprocess.call([editor, tmp.name])
                else:
                    # Very small Tk fallback editor
                    import tkinter as _tk
                    from tkinter import ttk as _ttk
                    root = _tk.Toplevel()
                    root.title("עריכת הודעה")
                    txt = _tk.Text(root, wrap="word", width=80, height=20)
                    txt.pack(fill="both", expand=True)
                    with open(tmp.name, "r", encoding="utf-8") as _f:
                        txt.insert("1.0", _f.read())
                    def _save_and_close():
                        with open(tmp.name, "w", encoding="utf-8") as _fw:
                            _fw.write(txt.get("1.0", "end-1c"))
                        root.destroy()
                    _ttk.Button(root, text="שמור וסגור", command=_save_and_close).pack(pady=6)
                    root.grab_set()
                    root.wait_window()
        finally:
            with open(tmp.name, "r", encoding="utf-8") as r:
                content = r.read()
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
        return content
    except Exception as e:
        try:
            messagebox.showerror("Notepad", f"שגיאה בפתיחת Notepad: {e}")
        except Exception:
            pass
        return initial_text or ""

def _parse_time_from_inputs(date_str: str, hour_str: str, minute_str: str) -> datetime:
    """
    date_str: 'YYYY-MM-DD'
    hour_str, minute_str: 'HH', 'MM'
    Returns naive datetime in local time.
    """
    y, m, d = [int(x) for x in date_str.split("-")]
    hh = int(hour_str)
    mm = int(minute_str)
    return datetime(y, m, d, hh, mm, 0)

def _safe_text_preview(s: str, limit=48) -> str:
    s = (s or "").replace("\n", " ")
    return s if len(s) <= limit else s[:limit-1] + "…"

class _SchedulerThread(_thr.Thread):
    def __init__(self, app_ref):
        super().__init__(daemon=True)
        self.app_ref = app_ref
        self._stop = _thr.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        # Poll every second for due tasks
        while not self._stop.is_set():
            try:
                now = datetime.now()
                due = []
                # work on a copy to avoid concurrent modification
                for it in list(self.app_ref._schedules):
                    if it.get("status") == "pending":
                        try:
                            when = datetime.fromisoformat(it["when"])
                        except Exception:
                            continue
                        if when <= now:
                            due.append(it)

                # Group due items by exact scheduled minute so messages with the same "when" share one WhatsApp session
                buckets = {}
                for it in due:
                    key = (it.get("when") or "").strip()
                    buckets.setdefault(key, []).append(it)

                for when_key, items in buckets.items():
                    # Open one Chrome session (separate profile) per time bucket
                    alt_profile = PROFILE_DIR / "schedule_profile"
                    alt_profile.mkdir(exist_ok=True)
                    _opts = Options()
                    _opts.add_argument(f"--user-data-dir={alt_profile.resolve()}")
                    _opts.add_argument("--start-maximized")
                    _opts.add_argument("--log-level=3")
                    _opts.add_argument("--disable-logging")
                    _opts.add_experimental_option("detach", True)
                    _drv = None
                    try:
                        _drv = webdriver.Chrome(options=_opts)
                        _drv.get("https://web.whatsapp.com/")
                        # ensure logged in
                        wait_for_login(_drv, sec=120)

                        for it in sorted(items, key=lambda x: (str(x.get("group","")), str(x.get("text","")), str(x.get("when","")))):
                            ok = False
                            try:
                                group = (it.get("group") or "").strip()
                                text  = (it.get("text")  or "").strip()
                                if not group or not text:
                                    raise RuntimeError("Group or text missing")

                                # open chat
                                open_chat(_drv, group)

                                # type + send
                                box = WebDriverWait(_drv, 10).until(EC.element_to_be_clickable((By.XPATH, MSG_AREA)))
                                _time.sleep(0.6)
                                box.send_keys(text, Keys.ENTER)

                                # confirm that message appeared
                                sent_ok = False
                                try:
                                    for _ in range(100):  # ~20s
                                        try:
                                            bubbles = _drv.find_elements(By.CSS_SELECTOR, BUBBLES_ANY_CSS)
                                            if bubbles:
                                                last_txt = bubbles[-1].text.strip()
                                                if last_txt == (text or "").strip():
                                                    sent_ok = True
                                                    break
                                        except Exception:
                                            pass
                                        _time.sleep(0.2)
                                except Exception:
                                    sent_ok = False

                                ok = bool(sent_ok)
                            except Exception:
                                ok = False
                            # update item status + UI
                            it["last_status"] = "sent" if ok else "failed"
                            it["sent_at"] = datetime.now().isoformat(timespec="seconds")
                            try:
                                import datetime as _dt
                                rep = (it.get('repeat') or 'once')
                                # normalize label to code (supports Hebrew labels)
                                _rep_map = {
                                    'חד פעמי': 'once', 'חד-פעמי': 'once',
                                    'יומי': 'daily', 'שבועי': 'weekly', 'חודשי': 'monthly',
                                    'once': 'once', 'daily': 'daily', 'weekly': 'weekly', 'monthly': 'monthly'
                                }
                                rep_code = _rep_map.get(str(rep).strip(), 'once')
                                if rep_code and rep_code != 'once':
                                    try:
                                        _when = datetime.fromisoformat(it.get('when',''))
                                    except Exception:
                                        _when = datetime.now()
                                    if rep_code == 'daily':
                                        _when = _when + _dt.timedelta(days=1)
                                    elif rep_code == 'weekly':
                                        _when = _when + _dt.timedelta(weeks=1)
                                    elif rep_code == 'monthly':
                                        y, m = _when.year, _when.month
                                        m += 1
                                        y += (m - 1) // 12
                                        m = ((m - 1) % 12) + 1
                                        day = min(_when.day, [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
                                        _when = _when.replace(year=y, month=m, day=day)
                                    it['when'] = _when.isoformat(timespec='minutes')
                                    it['status'] = 'pending'
                                else:
                                    it["status"] = "sent" if ok else "failed"
                            except Exception:
                                pass
                            try:
                                self.app_ref.after(0, self.app_ref._refresh_sched_table)
                            except Exception:
                                pass
                            try:
                                self.app_ref._save_schedules()
                            except Exception:
                                pass
                            _time.sleep(0.4)
                        # end for items
                    finally:
                        try:
                            if _drv is not None:
                                _time.sleep(1.0)  # wait 1s after the last message before closing the session
                                _drv.quit()
                        except Exception:
                            pass

                # persist once after processing all buckets
                self.app_ref._save_schedules()
            except Exception as e:
                # best-effort logging in status label if exists
                try:
                    self.app_ref._sched_set_status(f"שגיאת מתזמן: {e}")
                except Exception:
                    pass
            _time.sleep(1.0)

class SchedulePageMixin:

    # ----- Start/Stop handlers and repeat helpers -----
    def _repeat_label_to_code(self, lbl: str) -> str:
        m = {'חד פעמי':'once','חד-פעמי':'once','יומי':'daily','שבועי':'weekly','חודשי':'monthly',
             'once':'once','daily':'daily','weekly':'weekly','monthly':'monthly'}
        return m.get((lbl or '').strip(), 'once')

    def _roll_forward(self, when, repeat: str, now=None):
        import datetime as _dt
        now = now or _dt.datetime.now()
        if not isinstance(when, _dt.datetime):
            try:
                when = _dt.datetime.fromisoformat(str(when))
            except Exception:
                when = now
        if repeat == 'daily':
            while when <= now:
                when += _dt.timedelta(days=1)
            return when
        if repeat == 'weekly':
            while when <= now:
                when += _dt.timedelta(weeks=1)
            return when
        if repeat == 'monthly':
            y, m = when.year, when.month
            while when <= now:
                m += 1
                y += (m - 1) // 12
                m = ((m - 1) % 12) + 1
                day = min(when.day, [31,29 if y%4==0 and (y%100!=0 or y%400==0) else 28,31,30,31,30,31,31,30,31,30,31][m-1])
                when = when.replace(year=y, month=m, day=day)
            return when
        if when <= now:
            return when + _dt.timedelta(days=1)
        return when

    def _on_stop_schedule(self):
        sel = self.tree_sched.selection()
        if not sel:
            return
        iid = sel[0]
        it = next((x for x in self._schedules if x.get('id')==iid), None)
        if not it:
            return
        it['status'] = 'paused'
        self._save_schedules()
        self._refresh_sched_table()
        self._sched_set_status('התזמון נעצר (סטטוס: נעצר).')

    def _on_start_schedule(self):
        sel = self.tree_sched.selection()
        if not sel:
            return
        iid = sel[0]
        it = next((x for x in self._schedules if x.get('id')==iid), None)
        if not it:
            return
        import datetime as _dt
        now = _dt.datetime.now()
        try:
            when = _dt.datetime.fromisoformat(it.get('when',''))
        except Exception:
            when = now
        rep = (it.get('repeat') or 'once')
        if rep == 'once':
            if it.get('status') in ('sent','failed') or when <= now:
                when = _dt.datetime.combine(now.date(), _dt.time(when.hour, when.minute)) + _dt.timedelta(days=1)
        else:
            if when <= now:
                when = self._roll_forward(when, rep, now)
        it['when'] = when.isoformat(timespec='minutes')
        it['status'] = 'pending'
        self._save_schedules()
        self._refresh_sched_table()
        self._sched_set_status('התזמון הופעל.')
    """
    Mixin that augments App with:
    - schedules store + persistence
    - "תזמון הודעות" page with a small calendar/time picker and message body edited in Notepad
    - background scheduler that sends via the existing bot driver if available, otherwise via a temporary driver profile
    """
    def _init_schedules_store(self):
        self._schedules_path = SCHEDULES_PATH
        self._schedules = []
        try:
            if self._schedules_path.exists():
                with open(self._schedules_path, "r", encoding="utf-8") as f:
                    self._schedules = _json.load(f)
        except Exception:
            self._schedules = []

    def _save_schedules(self):
        try:
            with open(self._schedules_path, "w", encoding="utf-8") as f:
                _json.dump(self._schedules, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("Failed saving schedules:", e)

    def _start_scheduler(self):
        try:
            self._scheduler_thread = _SchedulerThread(self)
            self._scheduler_thread.start()
        except Exception as e:
            messagebox.showerror("מתזמן", f"כשל בהפעלת המתזמן: {e}")

    def _stop_scheduler(self):
        th = getattr(self, "_scheduler_thread", None)
        if th:
            try:
                th.stop()
            except Exception:
                pass

    # ----- UI injection -----
    def _inject_schedule_ui(self):
        # Ensure store + thread
        self._init_schedules_store()

        # Create the page and add a nav button (row 4 after the existing three)
        try:
            self.page_schedule = ttk.Frame(self.content)
            self.page_schedule.grid(row=0, column=0, sticky="nsew")
        except Exception:
            # Fallback: place directly if content not found
            self.page_schedule = ttk.Frame(self)
            self.page_schedule.grid(row=0, column=0, sticky="nsew")

        # Add navigation button
        try:
            # Find next available row in sidebar
            next_row = 4
            try:
                # probe existing grid slaves to pick next row dynamically
                rows = [w.grid_info().get("row", 0) for w in self.sidebar.grid_slaves()]
                if rows:
                    next_row = max(rows) + 1
            except Exception:
                pass
            self.btn_sched = ttk.Button(self.sidebar, text="תזמון הודעות", style="Nav.TButton",
                                        command=lambda: self.show_page(self.page_schedule))
            self.btn_sched.grid(row=next_row, column=0, sticky="ew", padx=12, pady=6)
        except Exception:
            pass

        # Build page UI
        frm = self.page_schedule
        for i in range(2):
            frm.columnconfigure(i, weight=1)
        frm.rowconfigure(3, weight=1)

        top = ttk.LabelFrame(frm, text="יצירת תזמון")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=10)

        # Group selection (combobox + free text)
        ttk.Label(top, text="שם קבוצה/איש קשר:").grid(row=0, column=2, sticky="e", padx=6, pady=6)
        recent = self.settings.values.get("recent_groups", []) if hasattr(self, "settings") else []
        self.var_sched_group = tk.StringVar(value=(recent[0] if recent else ""))
        self.cb_sched_group = ttk.Combobox(top, textvariable=self.var_sched_group, values=recent, width=32)
        self.cb_sched_group.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=6)

        # Date/time picker
        ttk.Label(top, text="תאריך ושעה:").grid(row=1, column=2, sticky="e", padx=6, pady=6)
        # Try tkcalendar.DateEntry if available
        self.var_date = tk.StringVar()
        self.var_hour = tk.StringVar(value="12")
        self.var_min = tk.StringVar(value="00")
        used_tkcalendar = False
        try:
            from tkcalendar import DateEntry  # type: ignore
            self.date_entry = DateEntry(top, date_pattern="yyyy-mm-dd", width=12)
            # default to now + 10 minutes
            import datetime as _dt
            dt0 = _dt.datetime.now() + _dt.timedelta(minutes=10)
            self.date_entry.set_date(dt0.date())
            self.var_date.set(self.date_entry.get_date().strftime("%Y-%m-%d"))
            self.date_entry.grid(row=1, column=1, sticky="w", padx=6, pady=6)
            used_tkcalendar = True
        except Exception:
            # fallback: three Spinboxes (YYYY-MM-DD)
            y, m, d = datetime.now().year, datetime.now().month, datetime.now().day
            self.var_date.set(f"{y:04d}-{m:02d}-{d:02d}")
            self.ent_date = ttk.Entry(top, textvariable=self.var_date, width=12, justify="center")
            self.ent_date.grid(row=1, column=1, sticky="w", padx=6, pady=6)

        self.spn_hour = ttk.Spinbox(top, from_=0, to=23, wrap=True, width=4, textvariable=self.var_hour, justify="center")
        self.spn_min  = ttk.Spinbox(top, from_=0, to=59, wrap=True, width=4, textvariable=self.var_min, justify="center")
        self.spn_hour.grid(row=1, column=0, sticky="w", padx=(6,2), pady=6)
        self.spn_min.grid(row=1, column=0, sticky="w", padx=(60,2), pady=6)

        # Repeat selection
        self.var_repeat = tk.StringVar(value="חד פעמי")
        self.cb_repeat = ttk.Combobox(top, textvariable=self.var_repeat, values=["חד פעמי","יומי","שבועי","חודשי"], width=12, state="readonly")
        self.cb_repeat.grid(row=1, column=0, sticky="w", padx=(212,2), pady=6)
        # Message body (preview + edit in Notepad button)
        ttk.Label(top, text="הודעה:").grid(row=2, column=2, sticky="e", padx=6, pady=(6,2))
        self.var_sched_text = tk.StringVar(value="")
        self.txt_sched_preview = tk.Text(top, height=4, wrap="word")
        self.txt_sched_preview.grid(row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=(6,2))
        try:
            self._patch_text_colors(self.txt_sched_preview)  # respect theme if available
            _rtl_text_widget(self.txt_sched_preview)
        except Exception:
            pass
        def _edit_now():
            cur = self.txt_sched_preview.get("1.0", "end-1c")
            edited = _edit_text_in_notepad(cur)
            self.txt_sched_preview.delete("1.0", "end")
            self.txt_sched_preview.insert("1.0", edited)

        # Action buttons
        actions = ttk.Frame(top)
        actions.grid(row=3, column=0, columnspan=3, sticky="e", padx=6, pady=(8,2))
        ttk.Button(actions, text="הוסף תזמון", style="Primary.TButton", command=self._on_add_schedule).pack(side="right", padx=6)
        ttk.Button(actions, text="שלח עכשיו", command=self._on_send_now).pack(side="right", padx=6)
        ttk.Button(actions, text="ערוך הודעה ב-Notepad…", command=_edit_now).pack(side="right", padx=6)

        # Table of schedules
        tbl = ttk.LabelFrame(frm, text="תזמונים קיימים")
        tbl.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0,10))
        self.tree_sched = ttk.Treeview(tbl, columns=("when","group","repeat","text","status"), show="headings", height=8)
        self.tree_sched.heading("when", text="מתי")
        self.tree_sched.heading("group", text="קבוצה/איש קשר")
        self.tree_sched.heading("repeat", text="חזרה")
        self.tree_sched.heading("text", text="טקסט")
        self.tree_sched.heading("status", text="סטטוס")
        self.tree_sched.column("when", width=160, anchor="center")
        self.tree_sched.column("group", width=200, anchor="e")
        self.tree_sched.column("repeat", width=80, anchor="center")
        self.tree_sched.column("text", width=440, anchor="w")
        self.tree_sched.column("status", width=100, anchor="center")
        self.tree_sched.pack(fill="both", expand=True, padx=6, pady=6)

        # Row actions
        row_actions = ttk.Frame(frm)
        ttk.Button(row_actions, text="עצור", command=self._on_stop_schedule).pack(side="right", padx=6)
        ttk.Button(row_actions, text="הפעל", command=self._on_start_schedule).pack(side="right", padx=6)
        row_actions.grid(row=2, column=0, columnspan=2, sticky="e", padx=10, pady=(0,10))
        ttk.Button(row_actions, text="מחק", command=self._on_delete_schedule).pack(side="right", padx=6)
        ttk.Button(row_actions, text="ערוך", command=lambda s=self: s._on_edit_schedule()).pack(side="right", padx=6)

        # Status
        self.var_sched_status = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.var_sched_status).grid(row=3, column=0, columnspan=2, sticky="w", padx=12, pady=(0,10))

        self._refresh_sched_table()
        self._start_scheduler()

        # Hook window close to also stop scheduler
        try:
            prev_cb = self.protocol("WM_DELETE_WINDOW")
        except Exception:
            prev_cb = None
        self.protocol("WM_DELETE_WINDOW", self._on_close_with_scheduler)

    def _on_close_with_scheduler(self):
        try:
            self._stop_scheduler()
        except Exception:
            pass
        try:
            # Stop bot if running (preserve original behavior if exists)
            if getattr(self, "bot", None) is not None:
                try:
                    self.bot.stop()
                except Exception:
                    pass
        except Exception:
            pass
        # Finally destroy
        try:
            self.destroy()
        except Exception:
            pass

    def _sched_set_status(self, msg: str):
        try:
            self.var_sched_status.set(msg)
        except Exception:
            pass

    def _get_current_text(self) -> str:
        try:
            return self.txt_sched_preview.get("1.0", "end-1c")
        except Exception:
            return ""

    def _on_add_schedule(self):
        group = self.var_sched_group.get().strip()
        if not group:
            messagebox.showwarning("קבוצה/איש קשר", "נא למלא שם קבוצה או איש קשר.")
            return
        # date
        if hasattr(self, "date_entry"):
            dstr = self.date_entry.get_date().strftime("%Y-%m-%d")
        else:
            dstr = self.var_date.get().strip()
        hh = (self.var_hour.get() or "00").zfill(2)
        mm = (self.var_min.get() or "00").zfill(2)
        try:
            when = _parse_time_from_inputs(dstr, hh, mm)
            if when <= datetime.now():
                messagebox.showwarning("זמן", "התאריך/שעה חייבים להיות בעתיד.")
                return
        except Exception as e:
            messagebox.showerror("זמן", f"זמן לא חוקי: {e}")
            return
        text = self._get_current_text()
        if not text:
            if not messagebox.askyesno("טקסט ריק", "ההודעה ריקה. להוסיף בכל זאת?"):
                return
        item = {
            "id": f"{int(_time.time()*1000)}",
            "when": when.isoformat(timespec="minutes"),
            "group": group,
            "text": text,
            "status": "pending"
        }
        try:
            _rep_lbl = (self.var_repeat.get() or 'חד פעמי').strip()
        except Exception:
            _rep_lbl = 'חד פעמי'
        _rep_map = {'חד פעמי':'once','חד-פעמי':'once','יומי':'daily','שבועי':'weekly','חודשי':'monthly','once':'once','daily':'daily','weekly':'weekly','monthly':'monthly'}
        item['repeat'] = _rep_map.get(_rep_lbl, 'once')

        self._schedules.append(item)
        self._save_schedules()
        self._refresh_sched_table()
        self._sched_set_status("נוסף תזמון.")

    def _on_send_now(self):
        group = self.var_sched_group.get().strip()
        if not group:
            messagebox.showwarning("קבוצה/איש קשר", "נא למלא שם קבוצה או איש קשר.")
            return
        text = self._get_current_text()
        ok = self._send_scheduled_message(group, text)
        self._sched_set_status("נשלח בהצלחה." if ok else "שליחה נכשלה.")

    def _refresh_sched_table(self):
        try:
            for i in self.tree_sched.get_children():
                self.tree_sched.delete(i)
            for it in sorted(self._schedules, key=lambda x: x.get("when", "")):
                self.tree_sched.insert("", "end", iid=it["id"],
                                       values=(it.get("when",""), it.get("group",""),
                                               {'once':"חד פעמי", 'daily':"יומי", 'weekly':"שבועי", 'monthly':"חודשי"}.get(it.get("repeat","once"), "חד פעמי"),
                                               _safe_text_preview(it.get("text","")),
                                               it.get("status","")))
        except Exception:
            pass

    def _on_delete_schedule(self):
        sel = self.tree_sched.selection()
        if not sel:
            return
        iid = sel[0]
        self._schedules = [x for x in self._schedules if x["id"] != iid]
        self._save_schedules()
        self._refresh_sched_table()

    
    def _on_edit_schedule(self):
        """Open edit dialog for selected schedule. Pure edit — does NOT auto-activate."""
        sel = self.tree_sched.selection()
        if not sel:
            return
        iid = sel[0]
        it = next((x for x in self._schedules if x.get("id") == iid), None)
        if not it:
            return

        import tkinter as tk
        from tkinter import ttk, messagebox
        from datetime import datetime as _dt

        # Parse current values
        cur_group = (it.get("group") or "").strip()
        try:
            cur_when = _dt.fromisoformat(it.get("when", ""))
        except Exception:
            cur_when = _dt.now()
        cur_text = (it.get("text") or "")
        cur_repeat = (it.get("repeat") or "once")

        lbl_to_code = {'חד פעמי':'once','חד-פעמי':'once','יומי':'daily','שבועי':'weekly','חודשי':'monthly',
                       'once':'once','daily':'daily','weekly':'weekly','monthly':'monthly'}
        code_to_lbl = {'once':'חד פעמי','daily':'יומי','weekly':'שבועי','monthly':'חודשי'}

        # Dialog
        dlg = tk.Toplevel(self)
        dlg.title("עריכת תזמון")
        try: dlg.transient(self)
        except Exception: pass
        try: dlg.grab_set()
        except Exception: pass
        try: dlg.resizable(False, False)
        except Exception: pass

        c = ttk.Frame(dlg, padding=10)
        c.grid(row=0, column=0, sticky="nsew")
        for col in (0,1):
            c.columnconfigure(col, weight=1)
        c.columnconfigure(2, weight=0)

        # Group
        ttk.Label(c, text="קבוצה/איש קשר:").grid(row=0, column=2, sticky="e", padx=6, pady=6)
        var_group = tk.StringVar(value=cur_group)
        recent = []
        try:
            recent = self.settings.values.get("recent_groups", []) if hasattr(self, "settings") else []
        except Exception:
            pass
        ttk.Combobox(c, textvariable=var_group, values=recent, width=30).grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=6)

        # Date/time
        ttk.Label(c, text="תאריך ושעה:").grid(row=1, column=2, sticky="e", padx=6, pady=6)
        var_date = tk.StringVar(value=cur_when.strftime("%Y-%m-%d"))
        var_hour = tk.StringVar(value=cur_when.strftime("%H"))
        var_min  = tk.StringVar(value=cur_when.strftime("%M"))
        used_tkcalendar = False
        try:
            from tkcalendar import DateEntry  # type: ignore
            date_entry = DateEntry(c, date_pattern="yyyy-mm-dd", width=12)
            date_entry.set_date(cur_when.date())
            date_entry.grid(row=1, column=1, sticky="w", padx=6, pady=6)
            used_tkcalendar = True
        except Exception:
            ent_date = ttk.Entry(c, textvariable=var_date, width=12, justify="center")
            ent_date.grid(row=1, column=1, sticky="w", padx=6, pady=6)
        timef = ttk.Frame(c)
        timef.grid(row=1, column=0, sticky='w', padx=6, pady=6)
        spn_hour = ttk.Spinbox(timef, from_=0, to=23, wrap=True, width=4, textvariable=var_hour, justify='center')
        spn_min  = ttk.Spinbox(timef, from_=0, to=59, wrap=True, width=4, textvariable=var_min,  justify='center')
        spn_hour.pack(side='left', padx=(0,4))
        spn_min.pack(side='left')

        # Repeat
        ttk.Label(c, text="חזרה:").grid(row=2, column=2, sticky="e", padx=6, pady=6)
        var_repeat = tk.StringVar(value=code_to_lbl.get(cur_repeat, "חד פעמי"))
        ttk.Combobox(c, textvariable=var_repeat, values=["חד פעמי","יומי","שבועי","חודשי"], width=12, state="readonly").grid(row=2, column=1, sticky='w', padx=6, pady=6)

        # Message preview + edit (read-only preview; editing via Notepad)
        ttk.Label(c, text="טקסט:").grid(row=2, column=1, sticky="ne", padx=6, pady=(6,2))
        txt = tk.Text(c, width=60, height=5)
        txt.grid(row=2, column=0, sticky="ew", padx=6, pady=(6,2))
        try:
            txt.insert("1.0", cur_text)
        except Exception:
            pass

        edited_msg = {"text": cur_text}

        def _parse_time_from_inputs(dstr: str, hh: str, mm: str):
            return _dt.fromisoformat(f"{(dstr or '').strip()} {(hh or '00').zfill(2)}:{(mm or '00').zfill(2)}")

        def on_edit_msg():
            try:
                new_text = _edit_text_in_notepad(edited_msg["text"])
                edited_msg["text"] = new_text
                try:
                    self._sched_set_status("טקסט ההודעה נערך (טרם נשמר).")
                except Exception:
                    pass
                try:
                    # also reflect in preview
                    txt.delete("1.0", "end")
                    txt.insert("1.0", new_text)
                except Exception:
                    pass
            except Exception as e:
                try:
                    messagebox.showerror("עריכה", f"שגיאה בעריכת טקסט: {e}", parent=dlg)
                except Exception:
                    pass

        def on_apply():
            group = var_group.get().strip()
            if not group:
                messagebox.showwarning("קבוצה/איש קשר", "נא למלא שם קבוצה או איש קשר.", parent=dlg)
                return
            if used_tkcalendar:
                dstr = date_entry.get_date().strftime("%Y-%m-%d")
            else:
                dstr = var_date.get().strip()
            hh = (var_hour.get() or "00").zfill(2)
            mm = (var_min.get() or "00").zfill(2)
            try:
                new_when = _parse_time_from_inputs(dstr, hh, mm)
            except Exception as e:
                messagebox.showerror("זמן", f"זמן לא חוקי: {e}", parent=dlg)
                return

            # Commit edits WITHOUT changing status
            it["group"] = group
            it["when"]  = new_when.isoformat(timespec="minutes")
            it["text"]  = txt.get("1.0", "end-1c")
            rep_lbl = (var_repeat.get() or "חד פעמי").strip()
            it["repeat"] = {'חד פעמי':'once','יומי':'daily','שבועי':'weekly','חודשי':'monthly'}.get(rep_lbl, "once")

            try:
                self._save_schedules()
                self._refresh_sched_table()
                self._sched_set_status("עודכן תזמון (ללא הפעלה).")
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass

        btns = ttk.Frame(c)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", padx=6, pady=(6,0))
        ttk.Button(btns, text="שמירה", style="Primary.TButton", command=on_apply).pack(side="right", padx=6)
        ttk.Button(btns, text="ערוך הודעה ב-Notepad…", command=on_edit_msg).pack(side="right", padx=6)
        ttk.Button(btns, text="ביטול", command=lambda: dlg.destroy()).pack(side="right", padx=6)

class AppWithSchedule(App, SchedulePageMixin):
    def __init__(self):
        super().__init__()
        # Inject new page + scheduler
        try:
            self._inject_schedule_ui()
        except Exception as e:
            try:
                messagebox.showerror("תזמון הודעות", f"כשל בבניית העמוד: {e}")
            except Exception:
                pass

# Replace the original App reference so main() will instantiate the extended one.
App = AppWithSchedule
# =========================
# End Scheduler Add-on
# =========================

if __name__ == "__main__":
    main()