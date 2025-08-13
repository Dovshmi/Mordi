# mordi_gui2_pro_settings.py — ממשק מודרני עם סייד־בר + דף הגדרות (אופציה רביעית)
# -*- coding: utf-8 -*-
"""
מורדי — אפליקציה לניהול בוט מילות מפתח ל-WhatsApp (Selenium + Tkinter)
גרסת ממשק עם סרגל ניווט ימני (במקום טאבים), RTL מלא, עיצוב מודרני,
ודף "הגדרות" הכולל מצב כהה/בהיר ושמירה אוטומטית של המאגר.

חידושים עיקריים בגרסה זו:
1) "הגדרות" (אופציה רביעית בניווט):
   • מצב כהה/בהיר (מוחל מיידית).
   • שמירה אוטומטית של המאגר (הפעל/כבה + מרווח בשניות).
   • אישור לפני מחיקות.
   • התחלת חלון במצב ממוקסם.
   • מהירות פולינג (קריאת הודעות) לבוט.
   • שמירת ההגדרות בקובץ settings.json וטעינה אוטומטית בהפעלה.

2) מצב כהה/בהיר:
   • התאמת צבעים ל-ttk ולווידג'טים רגילים (Text).
   • פונקציה apply_theme() שמחליפה סטיילים בזמן אמת.

3) שמירה אוטומטית:
   • אם מופעל, האפליקציה שומרת את קובץ ה-JSON (dataset) במרווח קבוע.
   • בנוסף, בכל שינוי בכלל/תגובות — מסמן "מלוכלך" ושומר בסבב הבא.ש
   • כפתורי "שמור" ו"שמור בשם" עדיין זמינים כרגיל.

4) ניהול מאגר — אופציית "מסך מלא" לעריכה נשמרת כבעבר.

נבדק עם: Python 3.11+, Selenium 4.11+
דרישות: pip install --upgrade selenium
"""

from __future__ import annotations
import json, random, re, threading, time, os
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
from tkinter import ttk, filedialog, messagebox

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
    """RTL לעורכי טקסט: יישור לימין + הדבקת תגית על כל שינוי כדי לשמר RTL לטקסט חדש."""
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

# ==== Helpers: fullscreen editor + bulk validate/from-file ====
def open_full_editor(self):
    """פתח עורך תגובות במסך מלא (נשמר קיים)."""
    top = tk.Toplevel(self)
    top.title("עריכת תגובות — מסך מלא")
    w, h = self.winfo_screenwidth(), self.winfo_screenheight()
    top.geometry(f"{int(w*0.8)}x{int(h*0.8)}+80+40")
    top.transient(self)
    top.grab_set()
    top.columnconfigure(0, weight=1)
    top.rowconfigure(0, weight=1)

    frame = ttk.Frame(top, padding=6)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    txt = tk.Text(frame, wrap="word")
    vsb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=vsb.set)
    txt.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    try:
        _rtl_text_widget(txt)
    except Exception:
        pass

    # preload
    try:
        txt.insert("1.0", self.replies_txt.get("1.0", "end-1c"))
    except Exception:
        pass

    btns = ttk.Frame(frame)
    btns.grid(row=1, column=0, sticky="e", pady=(6,0))
    ttk.Button(btns, text="שמור וסגור",
               command=lambda: (_apply_fullscreen_to_main(self, txt), top.destroy())).pack(side="right", padx=4)
    ttk.Button(btns, text="סגור בלי לשמור", command=top.destroy).pack(side="right", padx=4)

def _apply_fullscreen_to_main(self, txt):
    try:
        self.replies_txt.delete("1.0", "end")
        self.replies_txt.insert("1.0", txt.get("1.0", "end-1c"))
        self._mark_dirty()
    except Exception:
        pass

def bulk_validate(self):
    pat = getattr(self, "bulk_pattern_var", None).get().strip() if getattr(self, "bulk_pattern_var", None) else ""
    if not pat:
        messagebox.showwarning("בדיקת Regex", "נא להזין ביטוי.")
        return
    try:
        re.compile(pat, re.IGNORECASE)
        messagebox.showinfo("בדיקת Regex", "תקין ✔️")
    except re.error as e:
        messagebox.showerror("שגיאת Regex", f"ביטוי לא תקין: {e}")

def bulk_from_file(self):
    path = filedialog.askopenfilename(title="ייבוא מקובץ טקסט", filetypes=[("Text", "*.txt"), ("All files", "*.*")])
    if not path:
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = f.read()
        self.bulk_txt.delete("1.0", "end")
        self.bulk_txt.insert("1.0", data)
        try:
            _rtl_text_widget(self.bulk_txt)
        except Exception:
            pass
        if hasattr(self, "_log"):
            self._log(f"יובאו {len([ln for ln in data.splitlines() if ln.strip()])} שורות מקובץ.")
    except Exception as e:
        messagebox.showerror("ייבוא מקובץ", str(e))

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

# ---------- App GUI (Right Sidebar + Settings page) ----------
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
            # נשתמש ב-theme קיים, אחר כך נצבע ידנית לפי מצב
            if "vista" in style.theme_names():
                style.theme_use("vista")
            else:
                style.theme_use(style.theme_use())
        except Exception:
            pass

        # עיצוב מודרני
        style.configure("Nav.TButton", font=("Arial", 11), padding=(10, 10))
        style.configure("Primary.TButton", font=("Arial", 11, "bold"))
        style.configure("TLabel", font=("Arial", 11))
        style.configure("TLabelframe.Label", font=("Arial", 11, "bold"))
        style.configure("Treeview", rowheight=24, font=("Arial", 11))
        style.configure("Treeview.Heading", font=("Arial", 11, "bold"))

        # החלת ערכת נושא (כהה/בהיר) לפי ההגדרות
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
        self.page_bulk = ttk.Frame(self.content)       # "ייבוא מרוכז"
        self.page_settings = ttk.Frame(self.content)   # "הגדרות" (אופציה רביעית)
        for p in (self.page_bot, self.page_dataset, self.page_bulk, self.page_settings):
            p.grid(row=0, column=0, sticky="nsew")

        # ---- סייד־בר ימני ----
        self.sidebar = ttk.Frame(self)
        self.sidebar.grid(row=0, column=1, sticky="ns")
        self.sidebar.rowconfigure(6, weight=1)  # רווח דוחף

        ttk.Label(self.sidebar, text="ניווט", anchor="e").grid(row=0, column=0, sticky="ew", padx=12, pady=(16,6))
        self.btn_bot  = ttk.Button(self.sidebar, text="בוט", style="Nav.TButton", command=lambda: self.show_page(self.page_bot))
        self.btn_data = ttk.Button(self.sidebar, text="ניהול מאגר", style="Nav.TButton", command=lambda: self.show_page(self.page_dataset))
        self.btn_bulk = ttk.Button(self.sidebar, text="ייבוא מרוכז", style="Nav.TButton", command=lambda: self.show_page(self.page_bulk))
        self.btn_settings = ttk.Button(self.sidebar, text="הגדרות", style="Nav.TButton", command=lambda: self.show_page(self.page_settings))
        self.btn_bot.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        self.btn_data.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        self.btn_bulk.grid(row=3, column=0, sticky="ew", padx=12, pady=6)
        self.btn_settings.grid(row=4, column=0, sticky="ew", padx=12, pady=6)

        # קו מפריד דק
        sep = ttk.Separator(self, orient="vertical")
        sep.grid(row=0, column=1, sticky="nsw")

        # בנה דפי תוכן
        self._build_bot_page()
        self._build_dataset_page()
        self._build_bulk_page()
        self._build_settings_page()

        self.show_page(self.page_bot)

        # אם ביקשת להתחיל ממוקסם — החל מיידית
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

        # חל על חלון ושכבות
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

        # Text widgets (שאינם ttk)
        def patch_text_colors(widget: tk.Text):
            try:
                widget.configure(bg=box, fg=fg, insertbackground=fg)
            except Exception:
                pass

        # נרשום hook לכל יצירת Text כדי לצבוע אוטומטית
        # (נחיל ידנית על אלה שכבר נוצרו בהמשך)
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
        self._patch_text_colors(self.status)  # התאמת צבעים לפי ערכת נושא
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

        self.rules = ttk.Treeview(rules_frame, columns=("pattern","count"), show="headings", selectmode="browse")
        self.rules.heading("pattern", text="ביטוי (Regex)")
        self.rules.heading("count", text="מס׳ תגובות")
        self.rules.column("pattern", anchor="e", width=420)
        self.rules.column("count", anchor="center", width=120)
        self.rules.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self.rules.bind("<<TreeviewSelect>>", self.on_tree_select)

        btns = ttk.Frame(rules_frame)
        btns.grid(row=0, column=0, sticky="e", padx=6, pady=(8,0))
        ttk.Button(btns, text="הוסף", command=self.on_add_rule).pack(side="right", padx=3)
        ttk.Button(btns, text="ערוך", command=self.on_edit_rule).pack(side="right", padx=3)
        ttk.Button(btns, text="מחק", command=self.on_delete_rule).pack(side="right", padx=3)
        ttk.Button(btns, text="שכפל", command=self.on_dup_rule).pack(side="right", padx=3)

        # עורך (שמאל): עריכה
        editor = ttk.LabelFrame(frm, text="עורך כלל")
        editor.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        editor.columnconfigure(0, weight=1)

        row = ttk.Frame(editor)
        row.grid(row=0, column=0, sticky="ew")
        ttk.Label(row, text="ביטוי (Regex):").pack(side="right")
        self.pattern_var = tk.StringVar()
        ent_pattern = ttk.Entry(row, textvariable=self.pattern_var, justify="right")
        ent_pattern.pack(side="right", fill="x", expand=True, padx=6)

        ttk.Label(editor, text="תגובות (אחת בכל שורה):").grid(row=1, column=0, sticky="e", pady=(6,0))
        self.replies_txt = tk.Text(editor, height=16)
        self.replies_txt.grid(row=2, column=0, sticky="nsew")
        vsb_replies = ttk.Scrollbar(editor, orient='vertical', command=self.replies_txt.yview)
        self.replies_txt.configure(yscrollcommand=vsb_replies.set)
        editor.rowconfigure(2, weight=1)
        vsb_replies.grid(row=2, column=1, sticky='ns')
        _rtl_text_widget(self.replies_txt)
        self._patch_text_colors(self.replies_txt)

        # סימון מלוכלך על שינוי
        def _mark_dirty_on_edit(event=None):
            self._mark_dirty()
        self.replies_txt.bind("<<Modified>>", lambda e: (self.replies_txt.edit_modified(False), _mark_dirty_on_edit()), add=True)
        ent_pattern.bind("<KeyRelease>", _mark_dirty_on_edit, add=True)

        actions = ttk.Frame(editor)
        actions.grid(row=3, column=0, sticky="e", pady=6)
        ttk.Button(actions, text='מסך מלא…', command=lambda: open_full_editor(self)).pack(side='right', padx=4)
        ttk.Button(actions, text="החל על הנבחר/ת", command=self.on_apply_changes).pack(side="right", padx=4)
        ttk.Button(actions, text="הוסף ככלל חדש", command=self.on_add_from_editor).pack(side="right", padx=4)
        ttk.Button(actions, text="נקה עורך", command=lambda: (self.pattern_var.set(""), self.replies_txt.delete("1.0", "end"), self._mark_dirty())).pack(side="right", padx=4)

        self.refresh_rules_tree()

    # --------- תוכן: דף ייבוא מרוכז ---------
    def _build_bulk_page(self):
        frm = self.page_bulk
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(3, weight=1)

        ttk.Label(frm, text="הדבק/י תגובות (שורה לכל תגובה). הזן/י Regex והגדירו אפשרויות ייבוא.").grid(row=0, column=0, sticky="e", padx=10, pady=(10,6))

        row = ttk.Frame(frm)
        row.grid(row=1, column=0, sticky="ew", padx=10)
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text="ביטוי (Regex):").grid(row=0, column=2, sticky="e")
        self.bulk_pattern_var = tk.StringVar()
        ent_bulk_pat = ttk.Entry(row, textvariable=self.bulk_pattern_var, justify="right")
        ent_bulk_pat.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(row, text="בדוק Regex", command=lambda: bulk_validate(self)).grid(row=0, column=0, sticky="w")

        opts = ttk.Frame(frm)
        opts.grid(row=2, column=0, sticky="ew", padx=10, pady=(0,6))
        opts.columnconfigure(0, weight=1)
        self.bulk_mode_var = tk.StringVar(value="new")
        self.bulk_dedupe = tk.BooleanVar(value=True)
        self.bulk_trim = tk.BooleanVar(value=True)

        ttk.Label(opts, text="התנהגות אם קיים כלל עם אותו Regex:").grid(row=0, column=2, sticky="e")
        modes = ttk.Frame(opts)
        modes.grid(row=0, column=1, sticky="e")
        ttk.Radiobutton(modes, text="צור כלל חדש", value="new", variable=self.bulk_mode_var).pack(side="right", padx=3)
        ttk.Radiobutton(modes, text="צרף לתגובות קיימות", value="append", variable=self.bulk_mode_var).pack(side="right", padx=3)
        ttk.Radiobutton(modes, text="החלף תגובות קיימות", value="replace", variable=self.bulk_mode_var).pack(side="right", padx=3)

        flags = ttk.Frame(opts)
        flags.grid(row=1, column=1, sticky="e", pady=(4,0))
        ttk.Checkbutton(flags, text="מחק כפולים", variable=self.bulk_dedupe, command=self._mark_dirty).pack(side="right", padx=6)
        ttk.Checkbutton(flags, text="נקה רווחים מיותרים", variable=self.bulk_trim, command=self._mark_dirty).pack(side="right", padx=6)

        box = ttk.Frame(frm)
        box.grid(row=3, column=0, sticky="nsew", padx=10, pady=(6,8))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.bulk_txt = tk.Text(box, height=16, wrap="word")
        vsb = ttk.Scrollbar(box, orient="vertical", command=self.bulk_txt.yview)
        self.bulk_txt.configure(yscrollcommand=vsb.set)
        self.bulk_txt.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        _rtl_text_widget(self.bulk_txt)
        self._patch_text_colors(self.bulk_txt)

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, sticky="e", padx=10, pady=(0,10))
        ttk.Button(btns, text="ייבוא מקובץ…", command=lambda: bulk_from_file(self)).pack(side="right", padx=4)
        ttk.Button(btns, text="נקה", command=lambda: (self.bulk_txt.delete("1.0","end"), self._mark_dirty())).pack(side="right", padx=4)
        ttk.Button(btns, text="צור/עדכן כלל", command=self.on_bulk_create).pack(side="right", padx=4)

    # --------- תוכן: דף הגדרות (אופציה רביעית) ---------
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

    # ---------- שמירה אוטומטית ----------
    def _mark_dirty(self):
        self._dirty = True

    def schedule_autosave(self):
        if self._autosave_after_id:
            try:
                self.after_cancel(self._autosave_after_id)
            except Exception:
                pass
        interval = max(5, int(self.settings.values.get("autosave_interval_sec", 15)))
        self._autosave_after_id = self.after(interval * 1000, self._autosave_tick)

    def _autosave_tick(self):
        try:
            if self.settings.values.get("autosave_enabled", True) and self._dirty:
                # שמירה של המאגר לפתיב
                self.dataset.save(self.dataset.path)
                self._dirty = False
                self._log(f"שמירה אוטומטית: {self.dataset.path}")
        finally:
            # לתזמן שוב
            self.schedule_autosave()

    # ---------- dataset handlers ----------
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
            # רענון תצוגה בכל הדפים
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
        # לעדכן poll_interval מההגדרות (ייתכן ושונו עכשיו)
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

    # ---------- rules tree & editor ----------
    def refresh_rules_tree(self):
        # ננקה
        for iid in self.rules.get_children():
            self.rules.delete(iid)
        # נמלא
        for idx, r in enumerate(self.dataset.rules):
            self.rules.insert("", "end", iid=str(idx),
                              values=(r.pattern, len(r.replies)))

    def on_tree_select(self, event=None):
        sel = self.rules.selection()
        if not sel:
            return
        idx = int(sel[0])
        rule = self.dataset.rules[idx]
        self.pattern_var.set(rule.pattern)
        self.replies_txt.delete("1.0", "end")
        self.replies_txt.insert("1.0", "\n".join(rule.replies))

    def on_add_rule(self):
        self.pattern_var.set("(?i)(\\bbe\\b)")
        self.replies_txt.delete("1.0", "end")
        self._log("הזן/י ביטוי ותגובות, ואז לחץ/י 'הוסף ככלל חדש'.")
        self._mark_dirty()

    def on_add_from_editor(self):
        pat = self.pattern_var.get().strip()
        replies = [ln.strip() for ln in self.replies_txt.get("1.0","end").splitlines() if ln.strip()]
        if not pat:
            messagebox.showwarning("הוספה", "שדה הביטוי (Regex) לא יכול להיות ריק.")
            return
        try:
            re.compile(pat, re.IGNORECASE)
        except re.error as e:
            messagebox.showerror("שגיאת Regex", f"ביטוי לא תקין: {e}")
            return
        self.dataset.add_rule(pat, replies)
        self.refresh_rules_tree()
        self._log(f"נוסף כלל: {pat} ({len(replies)} תגובות)")
        self._mark_dirty()

    def on_apply_changes(self):
        sel = self.rules.selection()
        if not sel:
            messagebox.showinfo("החלה", "בחר/י כלל תחילה.")
            return
        idx = int(sel[0])
        pat = self.pattern_var.get().strip()
        replies = [ln.strip() for ln in self.replies_txt.get("1.0","end").splitlines() if ln.strip()]
        if not pat:
            messagebox.showwarning("החלה", "שדה הביטוי (Regex) לא יכול להיות ריק.")
            return
        try:
            re.compile(pat, re.IGNORECASE)
        except re.error as e:
            messagebox.showerror("שגיאת Regex", f"ביטוי לא תקין: {e}")
            return
        self.dataset.update_rule(idx, pat, replies)
        self.refresh_rules_tree()
        self._log(f"עודכן כלל [{idx}].")
        self._mark_dirty()

    def on_edit_rule(self):
        # בחירה מתוך העץ תעמיס כבר את הערכים לעורך
        if not self.rules.selection():
            messagebox.showinfo("עריכה", "בחר/י כלל לעריכה בעץ הכללים.")
        else:
            self._log("עריכה פתוחה. עדכן/י ושמור/י.")

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
        self.replies_txt.delete("1.0", "end")
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

    def on_bulk_create(self):
        pat = self.bulk_pattern_var.get().strip()
        if not pat:
            messagebox.showwarning("ייבוא מרוכז", "שדה הביטוי (Regex) לא יכול להיות ריק.")
            return
        try:
            re.compile(pat, re.IGNORECASE)
        except re.error as e:
            messagebox.showerror("שגיאת Regex", f"ביטוי לא תקין: {e}")
            return
        lines = [ln.strip() for ln in self.bulk_txt.get("1.0","end").splitlines() if ln.strip()]
        if not lines:
            messagebox.showwarning("ייבוא מרוכז", "הדבק/י תגובות — שורה לכל תגובה.")
            return
        if getattr(self, "bulk_trim", None) and self.bulk_trim.get():
            lines = [re.sub(r"\s+", " ", ln).strip() for ln in lines]
        if getattr(self, "bulk_dedupe", None) and self.bulk_dedupe.get():
            seen, uniq = set(), []
            for ln in lines:
                if ln not in seen:
                    seen.add(ln); uniq.append(ln)
            lines = uniq
        mode = getattr(self, "bulk_mode_var", None).get() if getattr(self, "bulk_mode_var", None) else "new"
        existing_idx = None
        for i, r in enumerate(self.dataset.rules):
            if getattr(r, "pattern", None) == pat:
                existing_idx = i
                break
        if existing_idx is None or mode == "new":
            self.dataset.add_rule(pat, lines)
            if hasattr(self, "_log"):
                self._log(f"נוצר כלל חדש: {pat} ({len(lines)} תגובות)")
        else:
            if mode == "append":
                self.dataset.rules[existing_idx].replies.extend(lines)
                self.dataset._recompile()
                if hasattr(self, "_log"):
                    self._log(f"תוגברו תגובות לכלל קיים: {pat} (+{len(lines)})")
            elif mode == "replace":
                self.dataset.rules[existing_idx].replies = lines
                self.dataset._recompile()
                if hasattr(self, "_log"):
                    self._log(f"הוחלפו תגובות לכלל קיים: {pat} ({len(lines)} חדשות)")
        self.refresh_rules_tree()
        self._mark_dirty()

    # ---------- Settings handlers ----------
    def on_change_theme(self):
        mode = self.theme_var.get()
        self.settings.values["theme"] = mode
        self.apply_theme(mode)
        self.on_update_settings()

        # לצבוע טקסטים קיימים מחדש
        for txt in [getattr(self, "status", None), getattr(self, "replies_txt", None), getattr(self, "bulk_txt", None)]:
            if isinstance(txt, tk.Text):
                self._patch_text_colors(txt)

    def on_toggle_autosave(self):
        enabled = bool(self.autosave_enabled.get())
        self.settings.values["autosave_enabled"] = enabled
        if enabled:
            self.schedule_autosave()
        else:
            if self._autosave_after_id:
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
        # עדכון ערכים מתוך הווידג'טים
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
