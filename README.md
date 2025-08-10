# WhatsApp Auto-Reply Bot 🤖💬

A Selenium-powered Python bot that automatically replies to WhatsApp group messages based on **keywords** stored in a JSON file.  
Designed for continuous monitoring — perfect for sales tracking, team updates, or automated responses.

---

## ✨ Features
- **Custom keyword detection** — Keywords and replies are stored in a simple `keywords.json`.
- **Randomized replies** — Multiple replies per keyword for variety.
- **Self-reply prevention** — Bot won’t respond to its own previous messages.
- **Persistent login** — Uses Chrome’s user profile to keep you logged in.
- **Media detection** — Ignores media messages unless specifically matched.
- **Regex matching** — Supports flexible keyword patterns.

---

## 📂 Project Structure
```
whatsapp-auto-reply-bot/
│
├── whatsapp_auto_reply.py   # Main bot script
├── keywords.json            # Keywords & replies config
└── README.md                # Project documentation
```

---

## ⚙️ Installation

1. **Clone the repository**
```bash
git clone https://github.com/your-username/whatsapp-auto-reply-bot.git
cd whatsapp-auto-reply-bot
```

2. **Install dependencies**
```bash
pip install selenium
```

3. **Download ChromeDriver**
- Ensure the version matches your Chrome browser.
- [Download ChromeDriver here](https://googlechromelabs.github.io/chrome-for-testing/).

4. **Set up your keywords**
- Edit `keywords.json` to add or modify keyword-reply pairs.

Example:
```json
[
    {
        "keyword": "cyber\\+",
        "replies": [
            "Nice Cyber+ sale! Logged.",
            "Cyber+ recorded. Great job!"
        ]
    }
]
```

---

## 🚀 Usage

Run the bot:
```bash
python whatsapp_auto_reply.py
```

Steps:
1. On first run, scan the WhatsApp Web QR code.
2. Bot will open the configured group.
3. Messages are monitored every 2 seconds.
4. If a message matches a keyword, a random reply is sent.

---

## 🛡️ Safety & Notes
- **Do not** spam groups — follow WhatsApp’s fair use rules.
- Keep keywords relevant to your use case.
- Regex allows advanced matching (`\\s*` for spaces, `\\b` for word boundaries).
- Tested on Windows 10, Chrome 139+, Python 3.12.

---

## 💡 Example Keywords

Current `keywords.json` includes:
```json
[
    {
        "keyword": "cyber\\+",
        "replies": [
            "Nice Cyber+ sale! Logged. ",
            "Cyber+ recorded. Great job! ",
            "Cyber+ noted. Keep them coming. "
        ]
    },
    {
        "keyword": "\\bbe\\b",
        "replies": [
            "Great BE sale! Added to the tally. ",
            "BE locked in. Nice close! ",
            "BE counted. Keep pushing! "
        ]
    },
    {
        "keyword": "be\\s*fiber",
        "replies": [
            "BE Fiber sale! Logged and ready. ",
            "Great BE Fiber close! Well done. ",
            "BE Fiber recorded — keep going strong! "
        ]
    },
    {
        "keyword": "battary",
        "replies": [
            "Battery sale noted. Keep charging ahead! ",
            "Battery recorded — nice work! ",
            "Battery logged in the system. Great job! "
        ]
    },
    {
        "keyword": "upgrade",
        "replies": [
            "Upgrade sale locked — excellent work! ",
            "Upgrade recorded. Keep it up! ",
            "Upgrade logged. Fantastic push! "
        ]
    }
]
```

---

## 📜 License
MIT License — feel free to use, modify, and share.
