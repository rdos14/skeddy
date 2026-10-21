<div align="center">

# 🧠 Skeddy

**A natural-language reminder bot for Telegram.**

Talk to it the way you'd talk to a person — in Uzbek or English — and Skeddy
figures out *what* to remind you and *when*, including complex recurring
schedules like “the first Monday of every month at 9 AM.”

[![CI](https://github.com/robotic0/Skeddy/actions/workflows/ci.yml/badge.svg)](https://github.com/robotic0/Skeddy/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![aiogram 3.x](https://img.shields.io/badge/aiogram-3.x-2481cc.svg)](https://docs.aiogram.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

</div>

---

## ✨ What makes Skeddy different

Most reminder bots force you to learn a rigid command syntax. Skeddy reads
**conversational language** and extracts the timing itself:

> *«Har oyning birinchi dushanbasida ertalab soat 9 da server jurnallarini tekshirishni eslat»*
>
> → 🔁 `har oyning 1- dushanbasida 09:00 da` — a recurring monthly job.

```
"ertaga soat 9 da shifokorga qo'ng'iroq qil"   → one-off, tomorrow 09:00
"har kuni 22:00 da suv ich"                     → daily at 22:00
"har dushanba 10:00 da hisobot"                 → weekly, Mondays 10:00
"har 15 daqiqada holatni tekshir"               → every 15 minutes
"30 daqiqadan keyin choynakni o'chir"           → one-off, +30 min
"every monday at 18:30 water the plants"        → weekly, Mondays 18:30
```

## 🧩 How the NLP engine works

Skeddy uses a **rule-based, bilingual grammar** — fast, deterministic and
fully offline (no external API calls, no API keys). The pipeline lives in
[`app/nlp`](app/nlp):

1. **`patterns.py`** — the lexicon: weekdays, ordinals, time units and day
   periods in both Uzbek and English, plus the compiled regexes.
2. **`parser.py`** — extracts the time-of-day, detects the recurrence type
   (interval · daily · weekly · monthly Nth-weekday · one-off), and strips the
   temporal tokens to leave a clean reminder message.
3. **`recurrence.py`** — a backend-agnostic `Schedule` value object that
   serialises to JSON (for storage) and converts to an APScheduler trigger.

The trickiest case — *“Nth weekday of every month”* — is expressed as a cron
rule by ANDing a day-of-month range with a day-of-week:

| Phrase | Cron |
|---|---|
| 1st Monday | `day="1-7", day_of_week="mon"` |
| 3rd Friday | `day="15-21", day_of_week="fri"` |
| last Friday | `day="22-31", day_of_week="fri"` |

## 🏗️ Architecture

```
bot.py                     # entry point: bot + dispatcher + scheduler
│
└── app/
    ├── config.py          # environment-driven configuration
    ├── nlp/               # the natural-language engine (patterns, parser, recurrence)
    ├── database/          # async SQLAlchemy engine, models, repositories
    ├── handlers/          # aiogram routers (start, reminders)
    ├── keyboards/         # inline keyboards + callback factories
    ├── services/          # APScheduler-based reminder scheduler
    ├── middlewares/        # per-update DB session injection
    └── utils/             # logging setup
```

**Tech stack:** [aiogram 3.x](https://docs.aiogram.dev/) · [APScheduler](https://apscheduler.readthedocs.io/) · [SQLAlchemy 2.0 (async)](https://www.sqlalchemy.org/) · SQLite / PostgreSQL.

Reminders are **persisted**, so every active reminder is reloaded and
re-registered on startup — nothing is lost across restarts.

## 🚀 Quick start

```bash
git clone https://github.com/robotic0/Skeddy.git
cd Skeddy

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # add your BOT_TOKEN
python bot.py
```

Get a token from [@BotFather](https://t.me/BotFather), paste it into `.env`,
and message your bot.

## 🐳 Run with Docker

```bash
cp .env.example .env               # add your BOT_TOKEN
docker compose up -d --build
```

The SQLite database is persisted to `./data` on the host.

## 💬 Usage

| Command | Description |
|---|---|
| *(any message)* | Create a reminder from natural language |
| `/list` | Show your active reminders (with delete buttons) |
| `/timezone Asia/Tashkent` | Set your timezone (per user) |
| `/help` | Full grammar reference |
| `/start` | Welcome + examples |

### Supported grammar

- **One-off:** `ertaga …`, `bugun …`, `in 30 minutes …`, `2 soatdan keyin …`,
  `27.09 soat 15:30 da …`, `2026-10-01 …`, day-first `27/10/2026 09:00 …`,
  `Saturday at 9:00 AM …`, or just a bare time (`soat 9 da …`).
- **Recurring:** `har kuni …`, `har <weekday> …`, `har soatda …`,
  `har N daqiqa/soat/kun/hafta …`, `har oyning <ordinal> <weekday>sida …`.
- **Day periods:** `ertalab` (09:00), `tush` (12:00), `kechqurun` (19:00),
  `kechasi` (22:00) — used when no explicit time is given.

Numeric dates are always day-first (`DD/MM/YYYY`, `DD/MM/YY`, `DD-MM-YY`);
two-digit years explicitly mean `20YY`, and `MM/DD` is rejected. Date-only
requests ask for a clock rather than guessing one. Numbered multiline pastes
receive a per-line preview and require explicit confirmation. See
[`DATETIME_PARSER.md`](DATETIME_PARSER.md) for the analysis and pending-draft APIs.

## 🧪 Development

```bash
pip install -e ".[dev]"

ruff check .      # lint
pytest -q         # the parser is covered by an extensive test suite
```

The entire NLP engine is unit-tested in [`tests/test_parser.py`](tests/test_parser.py)
with no network access required.

## 🗺️ Roadmap

- [ ] Snooze / postpone actions on the notification itself
- [ ] Timezone auto-detection from the user's location
- [ ] Natural-language editing (“move that to 10 AM”)
- [ ] Month/date names (`5-oktabr`, `October 5th`)
- [ ] Reminder categories and search

## 📄 License

Distributed under the [MIT License](LICENSE).
