# JobScout

A field book for finding work in Marrakech. 283 employers pulled from public
Google listings, scored on reputation and on the gaps worth a phone call, then
tracked from first contact through to an offer — with templated email, Gemini
drafting, an admin panel and a built-in presentation.

Python end to end: one Flask process serving server-rendered auth pages and a
Dash + Plotly dashboard behind a login guard.

---

## Run it

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

cp .env.example .env            # then edit — see Configuration
python app.py
```

Open <http://127.0.0.1:8050>. **The first account you create becomes the
administrator**, so sign up before anyone else does.

Nothing in `.env` is required to boot. Without a `GEMINI_API_KEY` the AI
buttons are disabled and everything else works; email defaults to a dry run that
records messages without delivering them.

---

## What is in it

| Page | What it does |
|---|---|
| **Overview** | Directory totals, your own tracking funnel, sector breakdown, the website gap, score distribution, and reputation plotted against review volume |
| **Directory** | All 283 employers — search, filter by sector, filter to no-website or priority or tracked-only, sort on any column, expand a row for contact details and actions |
| **Tracking** | A seven-stage board (Scouted → Closed) over the employers you track, with contact details and notes per record |
| **Contact** | Compose from a template or have Gemini draft it, fill placeholders from the record, preview exactly what will be sent, send and log it |
| **Assistant** | Ask Gemini about the directory; it answers from live aggregates and is told to name the missing figure rather than guess |
| **Deck** | A nine-slide presentation of the project, generated from the database so the numbers are never stale |
| **Admin** | Accounts and roles, delivery and AI health, a test send, re-score and re-import, and the audit trail |

### The opportunity score

Each employer carries one mark from 0 to 9, computed in a single vectorised
NumPy pass and **stored on the row with an index**, so the directory sorts and
pages in SQL rather than in Python. Four signals, weighted (all four weights are
configurable, then re-score from the admin panel):

| Signal | Default weight | Why it counts |
|---|---|---|
| Public rating | 0.35 | how well regarded they are; unrated scores 0 rather than being read as zero stars |
| Review weight | 0.25 | log-scaled, so a 4.3 with 900 reviews outranks a lone 5.0 |
| Website gap | 0.25 | nothing to send people to is an obvious, nameable thing to offer |
| Reachability | 0.15 | a phone number on file means you can get through today |

Bands: **0–4** low signal · **5–6** worth a look · **7–9** priority.

---

## Configuration

Every setting is an environment variable, read once at boot. `.env.example`
documents all of them; the ones that matter most:

| Variable | Default | Notes |
|---|---|---|
| `JOBSCOUT_SECRET_KEY` | *random* | **Set this.** Without it a new key is generated each boot, so every restart signs everyone out |
| `JOBSCOUT_HTTPS` | `0` | Set to `1` behind TLS so the session cookie is marked `Secure` |
| `JOBSCOUT_ALLOW_SIGNUP` | `1` | Close open signup once your accounts exist |
| `JOBSCOUT_INVITE_CODE` | — | If set, required on every signup after the first |
| `GEMINI_API_KEY` | — | Enables the AI features ([aistudio.google.com/apikey](https://aistudio.google.com/apikey)); `GOOGLE_API_KEY` is read as a fallback |
| `JOBSCOUT_AI_MODEL` | `gemini-2.5-pro` | |
| `JOBSCOUT_MAIL_DRY_RUN` | `1` | **On by default.** Messages are logged with status `simulated` and never delivered |
| `JOBSCOUT_MAIL_DAILY_CAP` | `60` | Per account, enforced before the socket opens |
| `JOBSCOUT_W_*` | see above | Scoring weights |

### Sending real email

1. Fill in `JOBSCOUT_SMTP_HOST`, `JOBSCOUT_SMTP_PORT`, `JOBSCOUT_SMTP_USER`,
   `JOBSCOUT_SMTP_PASSWORD` and `JOBSCOUT_MAIL_FROM`.
2. Restart, then use **Admin → Delivery → Send test** while the dry run is still
   on — it tells you whether the settings are even plausible.
3. Only then set `JOBSCOUT_MAIL_DRY_RUN=0`.

Template placeholders, filled from the employer's own record:
`{name}` `{sector}` `{address}` `{phone}` `{website}` `{rating}` `{reviews}`
`{score}` `{contact_name}` `{sender_name}` `{city}`

---

## Layout

```
app.py                  entry point; builds the Flask server and mounts Dash
config.py               every setting, environment-driven
data/employers.json     the seed dataset (283 records)
jobscout/
  db.py                 schema, connection handling, seeding, re-scoring
  repo.py               every query the pages are allowed to make
  scoring.py            the vectorised 0–9 score
  ai.py                 Gemini: draft an email, write a brief, answer a question
  mailer.py             rendering, validation, SMTP, the daily cap
  auth.py               login / signup / logout, CSRF, throttling, guards
  charts.py             every Plotly figure, light and dark
  ui.py                 shared layout vocabulary
  dashboard.py          the Dash shell, router and theme
  pages/                overview, directory, tracking, contact, assistant, deck, admin
  templates/            Jinja pages for auth
  static/theme.css      the design system
```

Routes: `/` → `/login`, then `/signup`, `/logout`, `/healthz`, and the dashboard
under `/app/`.

---

## Notes on the build

**Where it came from.** This replaces a single 744-line `index.html` that held
the data inline, scored each row in a JavaScript loop, and kept its watchlist in
`localStorage`. The styling is carried over deliberately — same paper-and-rust
palette, same Fraunces/Source Sans pairing, same ledger table and score chips —
so it still reads as the same product.

**A data bug the port surfaced.** Two distinct businesses share one Google place
id in the original export (*MEGACOMSYS* / *Evolution Technology* and *Riad
Palais Sebban* / *Amanjena*). The old page rendered both but treated them as one
when starring; keying a database on that id would have silently dropped a row.
The seed file suffixes the second occurrence (`...-2`), so all 283 survive. The
conversion was checked field by field against `matcher_data.js` — zero
mismatches. That file is the original source and is no longer read at runtime;
delete it whenever you like.

**Performance.** Scores are computed once in NumPy and stored on an indexed
column. The read-mostly employer table is held as a single cached DataFrame, so
filtering and sorting on every keystroke is a vectorised mask rather than a
round trip. SQLite runs in WAL mode, so the dashboard reads while a send writes.

**Charts.** Both palettes were checked with a validator — lightness band, chroma
floor, colour-blind separation, normal-vision floor and contrast against the
chart surface — in light *and* dark, rather than eyeballed. Dark mode is its own
selected set of steps, not a flip of the light one. Categorical series also
carry a second encoding (marker shape), so identity never rests on colour alone.

**Security posture.** scrypt password hashing; a per-session CSRF token on both
forms; per-IP and per-email throttling; session rotation on login; uniform error
text so the form never reveals whether an address is registered; every admin
callback re-checks the role server-side; the Dash callback endpoint returns 401
to anyone not signed in; and URLs from the dataset are filtered so a
`javascript:` or `data:` value can never become a link.

**Known limits.** The login throttle is in-process, so behind multiple workers
it should move to Redis or the database. `app.py` runs Flask's development
server — put it behind `gunicorn app:server` (or `waitress-serve`) in
production, and behind a proxy, add `ProxyFix` so `request.remote_addr` stays
honest.

---

## Tests

Run both from the repository root, each against a throwaway database — they
create accounts, so never point them at a real one:

```bash
JOBSCOUT_DB=data/t.sqlite3 python tests/smoke.py   && rm -f data/t.sqlite3*
JOBSCOUT_DB=data/t.sqlite3 python tests/cb.py      && rm -f data/t.sqlite3*
```

On Windows PowerShell: `$env:JOBSCOUT_DB="data/t.sqlite3"; python tests/smoke.py`

* `tests/smoke.py` — 95 checks: the auth flow (including CSRF rejection and weak
  passwords), every page render in both themes, all nine deck slides, the data
  layer, the mailer, every chart including empty-frame cases, URL safety,
  scoring behaviour and the admin guards.
* `tests/cb.py` — 90 checks: every Dash callback driven over real HTTP —
  filter and sort combinations, pattern-matching fan-outs, deep links,
  privilege-escalation attempts and anonymous access.

Both pass in full. Each expects a *fresh* database, since the first signup is
what makes an administrator.

---

Compiled from public Google listings. For internal use.
