
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
    דוגמה: (?=.*(?<!\S)(?:[והבכלמש]{1,4})?סיב(?!\S))
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
    whole    – התאמה רק אם כל ההודעה (למעט רווחים בתחילה/סוף) שווה לביטוי/אחד מן הביטויים
    part     – התאמה בכל מקום (גם בתוך משפט/מילה)
    anyorder – כל המילים המוזנות (מופרדות בפסיק) חייבות להופיע כטוקנים נפרדים, בסדר חופשי
    """
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
        ttk.Label(c, text="מילות מפתח (הפרדה בפסיק):").grid(row=0, column=1, sticky="e", padx=6, pady=(0,6))
        self.var_terms = tk.StringVar(value="")
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
        self.var_test = tk.StringVar(value="")
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
    


# ==== End Regex Builder Integration ====



APP_TITLE = "מורדי — מנהל בוט מילות מפתח ל-WhatsApp"
DEFAULT_DATASET = "keywords.json"
DEFAULT_GROUP   = "S"
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
        מזהה מצבים הנפוצים: whole/part, קידומות, סדר חופשי, ומילות מפתח.
        """
        try:
            pat = pattern.strip()
            if not pat:
                return
            # זיהוי מצב 'לבדו' (כל ההודעה רק מהמילים המותרות)
            is_whole = bool(re.search(r'^\^\s*\(\?:\s*\(\?:\\s\*\(\?:', pat)) and pat.endswith('$')
            # זיהוי קידומות
            has_prefix = r'(?:[והבכלמש]{1,4})?' in pat

            # זיהוי "סט מילים – סדר חופשי": רצף lookaheads (?=.*(?<!\S){pref}term(?!\S))
            lookahead_terms = re.findall(r'\(\?\=\.\*\(\?\<\!\\S\)\s*(?:\(\?\:[והבכלמש]\{1,4\}\)\?)?\s*([^\)]+?)\s*\(\?\!\\S\)\)', pat)
            free_order = len(lookahead_terms) >= 2

            terms = []
            if free_order:
                # בתוך ה-lookaheads, הטרמז כבר ללא עוגני מילה וקידומת – אבל עשוי להכיל escape
                for t in lookahead_terms:
                    t = t.strip()
                    # נסה להוריד escaping
                    t = bytes(t, 'utf-8').decode('unicode_escape') if '\\' in t else t
                    terms.append(t)
            else:
                # אלטרנטיבות מהצורה (?<!\S)(?:prefix)?term(?!\S)
                alts = re.findall(r'\(\?\<\!\\S\)(?:\(\?\:\[והבכלמש\]\{1,4\}\)\?)?([^|()]+?)\(\?\!\\S\)', pat)
                if alts:
                    for t in alts:
                        t = t.strip()
                        t = bytes(t, 'utf-8').decode('unicode_escape') if '\\' in t else t
                        terms.append(t)

            # נפילה לאחור: אם לא נמצאו, אולי האלטרנטיבות עטופות ב- (?:A|B|C)
            if not terms:
                pipe_terms = re.findall(r'\(\?:([^()]+)\)', pat)
                for grp in pipe_terms:
                    if '|' in grp and '(?<!\\S)' in pat:
                        for t in grp.split('|'):
                            t = t.strip()
                            # הסר עטיפות עוגנים אם נכנסו
                            t = re.sub(r'^\(\?\<\!\\S\)', '', t)
                            t = re.sub(r'\(\?\!\\S\)$', '', t)
                            t = bytes(t, 'utf-8').decode('unicode_escape') if '\\' in t else t
                            if t:
                                terms.append(t)
                        break

            # עדכון השדות
            if terms:
                # אל תכניס עוגנים לתוך מילות המפתח
                clean_terms = [re.sub(r'\\b|\\s\+|\(\?\<\!\\S\)|\(\?\!\\S\)', '', t) for t in terms]
                self.var_terms.set(", ".join(dict.fromkeys(clean_terms)))  # ייחוד + סדר מקורי
            else:
                self.var_terms.set("")

            self.var_mode.set("whole" if is_whole else "part")
            self.var_prefixes.set(bool(has_prefix))
            self.var_free_order.set(bool(free_order))
            self._refresh_builder()

            # אם הבניה שוות ערך לביטוי — שים בתצוגה המקדימה
            built = self.var_preview.get().strip()
            if built and built == pat:
                self.var_preview.set(pat)
        except Exception:
            # אל תכשיל את העריכה אם לא זוהה היטב
            pass


class KeywordRule:
    def __init__(self, pattern: str, replies: List[str]):
        self.pattern = pattern
        self.replies = replies

    def to_dict(self):
        return {"keyword": self.pattern, "replies": self.replies}

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
            self.rules.append(KeywordRule(item["keyword"], replies))
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

    def add_rule(self, pattern: str, replies: List[str]):
        self.rules.append(KeywordRule(pattern, replies))
        self._recompile()

    def delete_rule(self, idx: int):
        del self.rules[idx]
        self._recompile()

    def update_rule(self, idx: int, pattern: str, replies: List[str]):
        self.rules[idx].pattern = pattern
        self.rules[idx].replies = replies
        self._recompile()

# ---------- Settings model ----------
DEFAULT_SETTINGS = {
    "theme": "dark",                  # "dark" / "light"
    "autosave_enabled": True,
    "autosave_interval_sec": 15,      # כמה שניות בין שמירות
    "confirm_deletions": True,
    "start_maximized": True,
    "poll_interval_sec": DEFAULT_POLL_INTERVAL,
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
            self.on_status("החיבור בוצע. פותח את הצ'אט…")
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
                style.theme_use("vista")
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
        """mode: 'dark' / 'light'"""
        bg_dark  = "#1f1f23"
        fg_dark  = "#e6e6e6"
        box_dark = "#26262b"
        bg_light = "#f2f2f2"
        fg_light = "#202020"
        box_light= "#ffffff"

        if mode == "dark":
            bg, fg, box = bg_dark, fg_dark, box_dark
        else:
            bg, fg, box = bg_light, fg_light, box_light

        self.configure(bg=bg)
        style = ttk.Style(self)
        style.configure(".", background=bg, foreground=fg)
        style.configure("TFrame", background=bg)
        style.configure("TLabelframe", background=bg)
        style.configure("TLabelframe.Label", background=bg, foreground=fg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TButton", background=box)
        style.map("TButton", background=[("active", box)])
        style.configure("Nav.TButton", background=box)
        style.configure("Treeview", background=box, fieldbackground=box, foreground=fg)
        style.configure("Treeview.Heading", background=bg, foreground=fg)

        def patch_text_colors(widget: tk.Text):
            try:
                widget.configure(bg=box, fg=fg, insertbackground=fg)
            except Exception:
                pass
        self._patch_text_colors = patch_text_colors

    def show_page(self, page: ttk.Frame):
        page.tkraise()

    # --------- תוכן: דף הבוט ---------
    def _build_bot_page(self):
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
        self.group_var = tk.StringVar(value=DEFAULT_GROUP)
        ttk.Entry(ctrl, textvariable=self.group_var, width=24, justify="right").grid(row=0, column=1, padx=6, sticky="e")
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
            display = _regex_to_keywords_display(r.pattern)
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

        def _add_from_builder(pattern: str):

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

            self.dataset.add_rule(pattern.strip(), [])

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
        """פותח את 'בונה הסינטקס' בדיוק כמו 'הוסף', אך עם מילוי אוטומטי מהתבנית הנוכחית — ושומר על הכלל הנבחר."""
        sel = self.rules.selection()
        if not sel:
            from tkinter import messagebox
            messagebox.showinfo("עריכה", "בחר/י כלל לעריכה בעץ הכללים.")
            return
        idx = int(sel[0])
        rule = self.dataset.rules[idx]

        def _save_from_builder(pattern: str):
            if not pattern or not pattern.strip():
                return
            import re as _re
            try:
                _re.compile(pattern, _re.IGNORECASE)
            except _re.error as e:
                from tkinter import messagebox
                messagebox.showerror("Regex לא תקין", f"לא ניתן לשמור: {e}")
                return
            # עדכון רק התבנית; השארת התגובות
            self.dataset.update_rule(idx, pattern, list(rule.replies))
            self.dataset.save(self.dataset.path)
            self._mark_dirty()
            self._log(f"עודכן Regex לכלל #{idx}: {pattern}")
            # רענון העץ ושמירת הבחירה
            cur = str(idx)
            self.refresh_rules_tree()
            try:
                self.rules.selection_set(cur)
                self.rules.see(cur)
            except Exception:
                pass
            # עדכון שדות שמאל
            self.pattern_var.set(pattern)
            self._set_replies_display("\n".join(rule.replies))

        try:
            dlg = RegexBuilderDialog(self, on_done=_save_from_builder)
            # מילוי הבונה מהתבנית הנוכחית (אם אפשר)
            try:
                dlg.load_from_pattern(rule.pattern)
            except Exception:
                pass
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("בונה סינטקס", f"כשל בפתיחת הבונה: {e}")


        def _save_from_builder(pattern: str):
            if not pattern or not pattern.strip():
                return
            import re as _re
            try:
                _re.compile(pattern, _re.IGNORECASE)
            except _re.error as e:
                from tkinter import messagebox
                messagebox.showerror("Regex לא תקין", f"לא ניתן לשמור: {e}")
                return
            # Update only the pattern; keep replies
            self.dataset.update_rule(idx, pattern, list(rule.replies))
            self.dataset.save(self.dataset.path)
            self._mark_dirty()
            self._log(f"עודכן Regex לכלל #{idx}: {pattern}")
            # Refresh UI and keep selection
            cur = str(idx)
            self.refresh_rules_tree()
            try:
                self.rules.selection_set(cur)
                self.rules.see(cur)
            except Exception:
                pass
            self.pattern_var.set(pattern)
            self._set_replies_display("\\n".join(rule.replies))

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

if __name__ == "__main__":
    main()
