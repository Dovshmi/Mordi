# whatsapp_auto_reply.py · continuous keyword reply bot (skip if no match or bot's own reply)
from pathlib import Path
import time, sys, re, random, json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

GROUP_NAME  = "S"
PROFILE_DIR = Path.home() / "selenium_profile"

SEARCH_BOX = ("//div[@role='textbox' and @contenteditable='true' and "
              "(@aria-label='Search input textbox' or @data-tab='3')]")
CHAT_ITEM   = "//span[@title=%s]"
MSG_AREA    = "//footer//div[@role='textbox' and @contenteditable='true']"

BUBBLES_IN_CSS  = "div.message-in span.selectable-text"
BUBBLES_ANY_CSS = "div.copyable-text span.selectable-text"

MEDIA_PLACEHOLDER = "[Media]"
POLL_INTERVAL = 2  # seconds

def _norm(s: str) -> str:
    """Normalize text for safe comparison (trim + casefold)."""
    return s.strip().casefold()

# Load keywords & replies from JSON
def load_keyword_rules(json_path="keywords.json"):
    rules = []
    all_replies_set = set()
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for item in data:
        pattern = re.compile(item["keyword"], re.IGNORECASE)
        replies = item["replies"]
        rules.append((pattern, replies))
        # store normalized versions for matching against incoming messages
        for r in replies:
            all_replies_set.add(_norm(r))
    return rules, all_replies_set

# Load keyword rules and reply set
KEYWORD_RULES, ALL_REPLIES_NORM = load_keyword_rules()

def build_driver() -> webdriver.Chrome:
    PROFILE_DIR.mkdir(exist_ok=True)
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR.resolve()}")
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
        input("⌛ QR code is still displayed. Scan it, then press <Enter>…")

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

def is_bot_reply(msg: str) -> bool:
    """True if msg equals one of our JSON replies (normalized)."""
    if msg == MEDIA_PLACEHOLDER:
        return False
    return _norm(msg) in ALL_REPLIES_NORM

def match_keyword(msg: str) -> str | None:
    if msg == MEDIA_PLACEHOLDER:
        return None
    for pattern, replies in KEYWORD_RULES:
        if pattern.search(msg):
            return random.choice(replies)  # pick a random reply
    return None  # No keyword match

def send_reply(drv, txt):
    box = WebDriverWait(drv, 10).until(EC.element_to_be_clickable((By.XPATH, MSG_AREA)))
    time.sleep(0.6)
    box.send_keys(txt, Keys.ENTER)

def main():
    drv = build_driver()
    drv.get("https://web.whatsapp.com")
    print("➡️  Scan QR code (if needed)…", file=sys.stderr)
    wait_for_login(drv)
    print("✅ Connected.", file=sys.stderr)

    open_chat(drv, GROUP_NAME)
    last_processed = None

    print("🤖 Bot is running. Press Ctrl+C to stop.")
    try:
        while True:
            msg = last_incoming_text(drv)
            if msg != last_processed:
                if is_bot_reply(msg):
                    print(f"⏭️ Last message is one of my replies — skipping: {msg}")
                else:
                    print(f"📥 New message: {msg}")
                    reply_txt = match_keyword(msg)
                    if reply_txt:
                        send_reply(drv, reply_txt)
                        print(f"💬 Reply sent: {reply_txt}")
                    else:
                        print("⏭️ No keyword match — waiting for next message.")
                last_processed = msg
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
    finally:
        drv.quit()

if __name__ == "__main__":
    main()
