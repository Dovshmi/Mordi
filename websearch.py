# whatsapp_gui.py — Tkinter wrapper for your WhatsApp keyword bot
# pip install --upgrade selenium
from __future__ import annotations
import threading, queue, time, sys, re, json, random
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple, List

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# ---------------------- Core bot logic (adapted from your script) ----------------------

MEDIA_PLACEHOLDER = "[Media]"

SEARCH_BOX = ("//div[@role='textbox' and @contenteditable='true' and "
              "(@aria-label='Search input textbox' or @data-tab='3')]")
CHAT_ITEM   = "//span[@title=%s]"
MSG_AREA    = "//footer//div[@role='textbox' and @contenteditable='true']"

BUBBLES_IN_CSS  = "div.message-in span.selectable-text"
BUBBLES_ANY_CSS = "div.copyable-text span.selectable-text"

def _norm(s: str) -> str:
    return s.strip().casefold()

def load_keyword_rules(json_path: Path) -> Tuple[List[Tuple[re.Pattern, List[str]]], set]:
    rules = []
    all_replies_set = set()
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for item in data:
        pattern = re.compile(item["keyword"], re.IGNORECASE)
        replies = item["replies"]
        rules.append((pattern, replies))
        for r in replies:
            all_replies_set.add(_norm(r))
    return rules, all_replies_set

def build_driver(profile_dir: Path) -> webdriver.Chrome:
    profile_dir.mkdir(exist_ok=True)
    opts = Options()
    opts.add_argument(f"--user-data-dir={profile_dir.resolve()}")
    opts.add_argument("--start-maximized")
    opts.add_argument("--log-level=3")
    opts.add_argument("--disable-logging")
    opts.add_experimental_option("detach", True)
    return webdriver.Chrome(options=opts)

def wait_for_login(drv: webdriver.Chrome, sec=120):
    try:
        WebDriverWait(drv, sec).until(
            EC.presence_of_element_located((By.XPATH, SEARCH_BOX))
        )
    except TimeoutException:
        # Give the user an extra window to scan QR and press OK in GUI.
        pass

def open_chat(drv: webdriver.Chrome, name: str):
    search = drv.find_element(By.XPATH, SEARCH_BOX)
    search.clear()
    search.send_keys(name)
    chat = WebDriverWait(drv, 10).until(
        EC.element_to_be_clickable((By.XPATH, CHAT_ITEM % repr(name)))
    )
    chat.click()

def last_incoming_text(drv: webdriver.Chrome) -> str:
    bubbles = drv.find_elements(By.CSS_SELECTOR, BUBBLES_IN_CSS)
    if not bubbles:
        bubbles = drv.find_elements(By.CSS_SELECTOR, BUBBLES_ANY_CSS)
    if not bubbles:
        return MEDIA_PLACEHOLDER
    text = bubbles[-1].text.strip()
    return text if text else MEDIA_PLACEHOLDER

def is_bot_reply(msg: str, all_replies_norm: set) -> bool:
    if msg == MEDIA_PLACEHOLDER:
        return False
    return _norm(msg) in all_replies_norm

def match_keyword(msg: str, rules: List[Tuple[re.Pattern, List[str]]]) -> Optional[str]:
    if msg == MEDIA_PLACEHOLDER:
        return None
    for pattern, replies in rules:
        if pattern.search(msg):
            return random.choice(replies)
    return None

def send_reply(drv: webdriver.Chrome, txt: str):
    box = WebDriverWait(drv, 10).until(EC.element_to_be_clickable((By.XPATH, MSG_AREA)))
    time.sleep(0.6)
    box.send_keys(txt, Keys.ENTER)

# ---------------------- Worker Thread ----------------------

@dataclass
class BotConfig:
    group_name: str
    poll_interval: float
    profile_dir: Path
    keywords_path: Path

class BotWorker(threading.Thread):
    def __init__(self, cfg: BotConfig, log_q: queue.Queue, status_q: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.log_q = log_q
        self.status_q = status_q
        self.stop_event = stop_event
        self.drv: Optional[webdriver.Chrome] = None

    def log(self, msg: str):
        self.log_q.put(msg)

    def set_status(self, s: str):
        self.status_q.put(s)

    def run(self):
        try:
            # Load keyword rules
            rules, all_replies_norm = load_keyword_rules(self.cfg.keywords_path)
            self.log(f"Loaded keywords from: {self.cfg.keywords_path}")
        except Exception as e:
            self.log(f"❌ Failed to load keywords: {e}")
            self.set_status("error")
            return

        try:
            self.drv = build_driver(self.cfg.profile_dir)
            self.drv.get("https://web.whatsapp.com")
            self.log("➡️ Opened WhatsApp Web. Scan QR if needed (keep me logged in).")
            self.set_status("waiting-login")
            wait_for_login(self.drv, sec=120)
        except WebDriverException as e:
            self.log(f"❌ Chrome/WebDriver error: {e}")
            self.set_status("error")
            self.cleanup()
            return

        if self.stop_event.is_set():
            self.cleanup()
            return

        try:
            self.set_status("connecting")
            wait = WebDriverWait(self.drv, 10)
            wait.until(EC.presence_of_element_located((By.XPATH, SEARCH_BOX)))
            open_chat(self.drv, self.cfg.group_name)
            self.log(f"✅ Connected. Opened chat: {self.cfg.group_name}")
            self.set_status("running")
        except Exception as e:
            self.log(f"❌ Could not open chat “{self.cfg.group_name}”: {e}")
            self.set_status("error")
            self.cleanup()
            return

        last_processed = None
        try:
            while not self.stop_event.is_set():
                try:
                    msg = last_incoming_text(self.drv)
                except WebDriverException as e:
                    self.log(f"⚠️ WebDriver issue while reading messages: {e}")
                    time.sleep(max(1.0, self.cfg.poll_interval))
                    continue

                if msg != last_processed:
                    if is_bot_reply(msg, all_replies_norm):
                        self.log(f"⏭️ Skipping (my own reply): {msg}")
                    else:
                        self.log(f"📥 New message: {msg}")
                        reply_txt = match_keyword(msg, rules)
                        if reply_txt:
                            try:
                                send_reply(self.drv, reply_txt)
                                self.log(f"💬 Reply sent: {reply_txt}")
                            except WebDriverException as e:
                                self.log(f"❌ Failed to send reply: {e}")
                        else:
                            self.log("⏭️ No keyword match — waiting…")
                    last_processed = msg

                time.sleep(self.cfg.poll_interval)
        finally:
            self.cleanup()

    def cleanup(self):
        try:
            if self.drv:
                self.drv.quit()
        except Exception:
            pass
        self.set_status("stopped")
        self.log("🛑 Bot stopped.")

# ---------------------- Tkinter UI ----------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WhatsApp Auto-Reply Bot — GUI")
        self.geometry("900x600")
        self.minsize(820, 540)

        # Theming
        try:
            self.call("tk", "scaling", 1.2)
        except Exception:
            pass
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("TButton", padding=8)
        style.configure("TLabel", padding=4)
        style.configure("TEntry", padding=4)
        style.configure("Status.TLabel", foreground="#0a7", font=("Segoe UI", 10, "bold"))

        # State
        self.log_q: queue.Queue = queue.Queue()
        self.status_q: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: Optional[BotWorker] = None

        # Defaults
        self.var_group = tk.StringVar(value="S")
        self.var_poll  = tk.DoubleVar(value=2.0)
        self.var_profile = tk.StringVar(value=str(Path.home() / "selenium_profile"))
        self.var_keywords = tk.StringVar(value=str(Path.cwd() / "keywords.json"))

        self._build_ui()
        self.after(100, self._drain_queues)

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # Top form
        frm = ttk.LabelFrame(root, text="Bot Settings", padding=10)
        frm.pack(fill="x")

        # Row 1
        ttk.Label(frm, text="Group name:").grid(row=0, column=0, sticky="w")
        ent_group = ttk.Entry(frm, textvariable=self.var_group, width=30)
        ent_group.grid(row=0, column=1, sticky="we", padx=(6, 12))

        ttk.Label(frm, text="Poll interval (sec):").grid(row=0, column=2, sticky="w")
        ent_poll = ttk.Spinbox(frm, textvariable=self.var_poll, from_=0.5, to=30.0, increment=0.5, width=10)
        ent_poll.grid(row=0, column=3, sticky="w", padx=(6, 12))

        # Row 2
        ttk.Label(frm, text="Chrome profile dir:").grid(row=1, column=0, sticky="w")
        ent_prof = ttk.Entry(frm, textvariable=self.var_profile)
        ent_prof.grid(row=1, column=1, columnspan=2, sticky="we", padx=(6, 12))
        ttk.Button(frm, text="Browse…", command=self._pick_profile).grid(row=1, column=3, sticky="e")

        # Row 3
        ttk.Label(frm, text="keywords.json:").grid(row=2, column=0, sticky="w")
        ent_kw = ttk.Entry(frm, textvariable=self.var_keywords)
        ent_kw.grid(row=2, column=1, columnspan=2, sticky="we", padx=(6, 12))
        ttk.Button(frm, text="Browse…", command=self._pick_keywords).grid(row=2, column=3, sticky="e")

        # Controls
        ctrl = ttk.Frame(root)
        ctrl.pack(fill="x", pady=(10, 4))
        self.btn_start = ttk.Button(ctrl, text="▶ Start Bot", command=self._start_bot)
        self.btn_stop  = ttk.Button(ctrl, text="■ Stop", command=self._stop_bot, state="disabled")
        self.btn_test  = ttk.Button(ctrl, text="Test Match…", command=self._test_match)
        self.btn_start.pack(side="left")
        self.btn_stop.pack(side="left", padx=(8, 0))
        self.btn_test.pack(side="left", padx=(8, 0))

        self.lbl_status = ttk.Label(ctrl, text="Status: idle", style="Status.TLabel")
        self.lbl_status.pack(side="right")

        # Log area
        logf = ttk.LabelFrame(root, text="Log", padding=6)
        logf.pack(fill="both", expand=True)
        self.txt = tk.Text(logf, wrap="word", height=18, state="disabled")
        self.txt.pack(fill="both", expand=True)
        self.txt.tag_configure("mono", font=("Consolas", 10))

        # Footer
        foot = ttk.Frame(root)
        foot.pack(fill="x")
        ttk.Label(foot, text="Tip: Keep ‘Stay logged in’ checked on WhatsApp Web for seamless starts.").pack(anchor="w")

        for i in range(4):
            frm.columnconfigure(i, weight=1)

    def _pick_profile(self):
        p = filedialog.askdirectory(title="Choose Chrome profile directory")
        if p:
            self.var_profile.set(p)

    def _pick_keywords(self):
        p = filedialog.askopenfilename(
            title="Choose keywords.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if p:
            self.var_keywords.set(p)

    def _start_bot(self):
        # Validate inputs
        try:
            group = self.var_group.get().strip()
            if not group:
                raise ValueError("Group name is required.")
            poll = float(self.var_poll.get())
            if poll <= 0:
                raise ValueError("Poll interval must be > 0.")
            profile_dir = Path(self.var_profile.get()).expanduser()
            keywords_path = Path(self.var_keywords.get()).expanduser()
            if not keywords_path.exists():
                raise ValueError(f"keywords.json not found:\n{keywords_path}")
        except Exception as e:
            messagebox.showerror("Invalid settings", str(e))
            return

        cfg = BotConfig(
            group_name=group,
            poll_interval=poll,
            profile_dir=profile_dir,
            keywords_path=keywords_path
        )

        # Prepare queues/state
        self.stop_event.clear()
        self.worker = BotWorker(cfg, self.log_q, self.status_q, self.stop_event)
        self._set_controls_running(True)
        self._append_log(f"Starting bot for group '{cfg.group_name}'…")
        self.worker.start()

    def _stop_bot(self):
        if self.worker and self.worker.is_alive():
            self._append_log("Stopping bot…")
            self.stop_event.set()
        else:
            self._append_log("Bot not running.")
            self._set_controls_running(False)

    def _set_controls_running(self, running: bool):
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")

    def _append_log(self, msg: str):
        self.txt.configure(state="normal")
        self.txt.insert("end", msg + "\n", "mono")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _set_status(self, status: str):
        mapping = {
            "waiting-login": "waiting for login",
            "connecting": "connecting…",
            "running": "running",
            "stopped": "stopped",
            "error": "error",
        }
        text = mapping.get(status, status)
        self.lbl_status.configure(text=f"Status: {text}")

        if status in ("stopped", "error"):
            self._set_controls_running(False)

    def _drain_queues(self):
        # Drain logs
        try:
            while True:
                msg = self.log_q.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        # Drain status
        try:
            while True:
                st = self.status_q.get_nowait()
                self._set_status(st)
        except queue.Empty:
            pass
        self.after(150, self._drain_queues)

    def _test_match(self):
        # Quick tester: lets you type a message and see which reply (if any) would be picked right now.
        dlg = tk.Toplevel(self)
        dlg.title("Test Keyword Match")
        dlg.transient(self)
        dlg.grab_set()
        ttk.Label(dlg, text="Enter a sample incoming message:").pack(anchor="w", padx=12, pady=(12,4))
        txt = tk.Text(dlg, height=4, width=60)
        txt.pack(padx=12, fill="x")
        out = ttk.Label(dlg, text="", foreground="#06a")
        out.pack(anchor="w", padx=12, pady=6)

        def run_test():
            try:
                rules, _ = load_keyword_rules(Path(self.var_keywords.get()).expanduser())
                sample = txt.get("1.0", "end").strip()
                reply = match_keyword(sample, rules)
                if reply:
                    out.configure(text=f"Reply → {reply}")
                else:
                    out.configure(text="No match.")
            except Exception as e:
                out.configure(text=f"Error: {e}")

        btns = ttk.Frame(dlg)
        btns.pack(fill="x", padx=12, pady=(0,12))
        ttk.Button(btns, text="Test", command=run_test).pack(side="left")
        ttk.Button(btns, text="Close", command=dlg.destroy).pack(side="right")

    def destroy(self):
        # Ensure clean shutdown
        try:
            self._stop_bot()
        finally:
            super().destroy()

if __name__ == "__main__":
    App().mainloop()
