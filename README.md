# Mordi v7.4 — WhatsApp Auto‑Reply Bot (GUI)

A Selenium‑powered Python app with a friendly GUI for automatically replying to WhatsApp **group** messages based on keywords (including **Regex** patterns) you control in `keywords.json`. Built for sales teams and ops crews who want quick, consistent replies and simple rule management.

> **OS:** Windows 10/11 • **Python:** 3.11+ / 3.12+ • **Browser:** Chrome • **License:** MIT

---

## 🚀 What’s new in v7.4

- **Schedule Messages** — New “תזמון הודעות” page to create one‑time or repeating sends (יומי/שבועי/חודשי), with a table that shows group, text, repeat, and status. Includes **Send Now** and a quick **Notepad** editor for the message body.
- **Smarter Regex Builder** — Any‑order matching mode, per‑term counts via `term:K` (e.g., `חיים:2`), Hebrew prefix handling (`[והבכלמש]`), and safer tokenization for RTL patterns.
- **Startup page preference** — Choose which page opens first (Bot / Dataset / Schedule / Settings) in `settings.json` or via the Settings UI.
- **Quality of life** — Autosave settings, right‑aligned RTL widgets, recent‑group suggestions, and clearer logs & toasts.

---

## ✨ Core Features

- **Point‑and‑click GUI** to manage rules and replies (no code required)
- **Regex support** for flexible keyword matching (Hebrew/RTL friendly)
- **Randomized replies** (add multiple replies per rule)
- **Self‑reply prevention** (won’t respond to its own messages)
- **Persistent login** using your Chrome user profile
- **Emoji‑friendly** replies (save `keywords.json` as UTF‑8)
- **Packaged app** support (PyInstaller one‑file EXE; optional Inno Setup installer)

---

## 📦 Project Structure

```
.
├─ patch_mordi_builder.py       # v7.4 main app (GUI + Regex Builder + Scheduler)
├─ keywords.json                # Your rules (patterns → replies)
├─ schedules.json               # Saved schedules (one‑time / repeating)
├─ settings.json                # App/user settings
├─ icon.ico                     # App icon (Windows)
├─ setupscript.iss              # Inno Setup script (optional installer)
└─ README.md
```

> Tip: Don’t commit built binaries (`Mordi.exe`, `MordiSetup.exe`). Publish them under **GitHub Releases** instead.

---

## ⚙️ Requirements

- Windows 10/11
- Python 3.11+ (3.12 supported)
- Google Chrome installed
- Python packages: `selenium`, `webdriver-manager`

Install packages:

```powershell
pip install selenium webdriver-manager
```

---

## 🏁 Quick Start

1) **Clone**
```powershell
git clone https://github.com/Dovshmi/mordi.git
cd mordi
```

2) **Install deps**
```powershell
pip install selenium webdriver-manager
```

3) **Run the GUI (v7.4)**
```powershell
python patch_mordi_builder.py
```

4) **First run**
- WhatsApp Web opens in Chrome
- Scan the QR code (only the first time)
- Choose your group and let Mordi monitor messages

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

> **Advanced (v7.4)**: The builder supports **any‑order** matching, **per‑term counts** with `term:K` (e.g., `חיים:2` means the word must appear twice), and **Hebrew prefixes** (ו/ה/ב/כ/ל/מ/ש) as optional tokens.

---

## ⏰ Schedule Messages (New in v7.4)

Open **תזמון הודעות** to create one‑time or repeating schedules.

**Create a schedule**
1. Pick a **Group/Contact**
2. Choose **Date & Time** (defaults to “now + 10 minutes”)
3. Set **Repeat**: *חד פעמי* / *יומי* / *שבועי* / *חודשי*
4. Click **הוסף תזמון**

**Table columns**
- When • Group • Repeat • Text • Status (פעיל/נעצר/נשלח/נכשל)

**Actions**
- **שלח עכשיו** — sends the message immediately (uses a separate Chrome profile so it won’t interrupt the main bot)
- **Notepad‑ערוך** — opens the message body in Notepad for quick editing
- **Pause/Resume** — toggle a schedule’s status

**Storage**
- Schedules persist to `schedules.json` in UTF‑8.

---

## 🛠 Settings

Manage under **הגדרות** (or edit `settings.json`):

- `startup_page`: which page to open at launch (`bot` / `dataset` / `schedule` / `settings`)
- `autosave_enabled` and `autosave_interval_sec`
- `confirm_deletions`, `start_maximized`, `poll_interval_sec`
- `recent_groups`, `group_history` (improves group suggestions)

> Changes made in the UI are saved back to `settings.json` automatically.

---

## 🧪 Packaging to EXE (PyInstaller)

Create a single‑file Windows EXE. Note the **semicolon** in `--add-data` on Windows.

```powershell
pyinstaller `
  --name Mordi `
  --onefile `
  --windowed `
  --icon icon.ico `
  --add-data "keywords.json;." `
  --add-data "settings.json;." `
  patch_mordi_builder.py
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

## 🧷 File Formats

### `schedules.json` (example)

```json
[
  {
    "id": "1756281462187",
    "when": "2025-08-27T11:00",
    "group": "S",
    "text": "Hello",
    "status": "failed",
    "sent_at": "2025-08-27T11:14:04",
    "repeat": "once"
  }
]
```

**Status values**: `"pending" | "paused" | "sent" | "failed"`  
**Repeat values**: `"once" | "daily" | "weekly" | "monthly"`

### `settings.json` (example)

```json
{
  "theme": "light",
  "autosave_enabled": true,
  "autosave_interval_sec": 15,
  "confirm_deletions": true,
  "start_maximized": false,
  "poll_interval_sec": 2,
  "recent_groups": ["S", "נירה"],
  "group_history": ["S", "נירה"],
  "startup_page": "bot"
}
```

---

## 🛟 Troubleshooting

- **ChromeDriver mismatch** → Use `webdriver-manager` (already recommended)
- **Data file not found (EXE)** → Verify `--add-data` paths and `resource_path()` usage
- **Emoji not showing** → Ensure `keywords.json` is saved as UTF‑8 and your system font supports the characters
- **RTL/Hebrew alignment** → Use the RTL‑tuned layouts; the 7.4 builder and scheduler align controls to the right for better Hebrew UX

---

## 🤝 Contributing

PRs are welcome! For larger changes, open an issue first to discuss.

---

## 🔒 Disclaimer

This project automates interactions with **WhatsApp Web**. Use responsibly and follow WhatsApp’s terms and your local laws. You are responsible for how you deploy and use this tool.

---

## 📜 License
Rony Shmidov

[MIT](LICENSE)
