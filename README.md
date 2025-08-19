# Mordi — WhatsApp Auto‑Reply Bot (GUI)

A Selenium‑powered Python app with a friendly GUI for automatically replying to WhatsApp **group** messages based on keywords (including **Regex** patterns) you control in `keywords.json`. Built for sales teams and ops crews who want quick, consistent replies and simple rule management.

> **OS:** Windows 10/11 • **Python:** 3.11+ / 3.12+ • **Browser:** Chrome • **License:** MIT

---

## ✨ Features

* **Point‑and‑click GUI** to manage rules and replies (no code required)
* **Regex support** for flexible keyword matching (Hebrew/RTL friendly)
* **Randomized replies** (add multiple replies per rule)
* **Self‑reply prevention** (won’t respond to its own messages)
* **Persistent login** using your Chrome user profile
* **Emoji‑friendly** replies (save `keywords.json` as UTF‑8)
* **Packaged app** support (PyInstaller one‑file EXE; optional Inno Setup installer)

---

## 📦 Project Structure

```
.
├─ mordi_gui2_updated.py        # Main GUI entry (run this)
├─ mordi_gui2_pro_settings.py   # Previous GUI variant
├─ mordi_gui2_pro_settings_rtl_notepad_v2.py  # RTL/Notepad variant
├─ patch_mordi_builder.py       # Regex builder / helpers
├─ keywords.json                # Your rules (patterns → replies)
├─ settings.json                # App/user settings (optional)
├─ icon.ico                     # App icon (Windows)
├─ setupscript.iss              # Inno Setup script (optional installer)
└─ README.md
```

> ⚠️ **Tip:** Don’t commit built binaries (`Mordi.exe`, `MordiSetup.exe`). Publish them under **GitHub Releases** instead.

---

## ⚙️ Requirements

* Windows 10/11
* Python 3.11+ (3.12 supported)
* Google Chrome installed
* Python packages: `selenium`, `webdriver-manager`

Install packages:

```powershell
pip install selenium webdriver-manager
```

---

## 🚀 Quick Start (from source)

1. **Clone**

```powershell
git clone https://github.com/Dovshmi/mordi.git
cd mordi
```

2. **Install deps**

```powershell
pip install selenium webdriver-manager
```

3. **Run the GUI**

```powershell
python mordi_gui2_updated.py
```

4. **First run**

* WhatsApp Web opens in Chrome
* Scan the QR code (only the first time)
* Choose your group and let Mordi monitor messages

---

## 🧩 Configure Rules (`keywords.json`)

Each rule has a **pattern** (string; plain text or Regex) and a list of **replies**. Replies are chosen at random.

```jsonc
[
  {
    "keyword": "cyber\\+",        // Regex: matches "cyber+"
    "replies": [
      "Nice Cyber+ sale! Logged.",
      "Cyber+ recorded. Great job!"
    ]
  },
  {
    "keyword": "\\bbe\\b",        // word-boundary example
    "replies": [
      "Great BE sale! Added to the tally.",
      "BE locked in. Nice close!"
    ]
  },
  {
    "keyword": "be\\s*fiber",     // allows optional spaces
    "replies": [
      "BE Fiber recorded — keep going strong!"
    ]
  }
]
```

**Notes**

* Save the file as **UTF‑8** to keep Hebrew and emoji intact
* Use `\b` for whole words, `\s*` for optional spaces, and character classes as needed
* Start simple; you can always refine patterns later

---

## 🧠 Selenium/Driver Setup (automatic)

This project recommends `webdriver-manager` so you **don’t** have to manually download ChromeDriver.

```python
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

def make_driver(user_data_dir=None):
    opts = Options()
    if user_data_dir:
        opts.add_argument(f"--user-data-dir={user_data_dir}")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()),
                            options=opts)
```

---

## 🧪 Running as a packaged app (PyInstaller)

Create a single‑file Windows EXE. Note the **semicolon** in `--add-data` on Windows.

```powershell
pyinstaller `
  --name Mordi `
  --onefile `
  --windowed `
  --icon icon.ico `
  --add-data "keywords.json;." `
  --add-data "settings.json;." `
  mordi_gui2_updated.py
```

**Resource loading inside Python** (works in source & EXE):

```python
import os, sys

def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

ICON_PATH = resource_path("icon.ico")
KEYWORDS_PATH = resource_path("keywords.json")
```

> After building, run `dist/Mordi.exe`.

---

## 📀 Optional: Installer (Inno Setup)

If you want a click‑through installer:

1. Build `Mordi.exe` with PyInstaller
2. Open `setupscript.iss` in **Inno Setup**
3. Set `AppName`, `AppVersion`, `SetupIconFile`, and point to your EXE
4. Build the installer to produce `MordiSetup.exe`

---

## 🛠 Troubleshooting

* **ChromeDriver mismatch** → Use `webdriver-manager` (already recommended above)
* **“Data file not found” in EXE** → Verify `--add-data` paths and `resource_path()` usage
* **Emoji not showing** → Ensure `keywords.json` is saved as UTF‑8 and your system font supports the characters
* **RTL/Hebrew alignment** → Use the RTL‑tuned GUI variant if you prefer (`mordi_gui2_pro_settings_rtl_notepad_v2.py`)

---

## 🤝 Contributing

Pull requests are welcome! For a larger change, please open an issue first to discuss what you’d like to add.

---

## 🔒 Disclaimer

This project automates interactions with **WhatsApp Web**. Use responsibly and follow WhatsApp’s terms and your local laws. You are responsible for how you deploy and use this tool.

---

## 📜 License

[MIT](LICENSE)
