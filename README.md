#Hospital Management System (Flask + Vue CDN)

A complete HMS built with Flask on the backend and Vue 3 (via CDN) on the frontend. This single README consolidates everything: folders, technologies, how and where they’re used, why certain choices were made, and step‑by‑step run instructions for Windows PowerShell.

## 🚀 Highlights

- MPA architecture: server-rendered Jinja pages with small Vue “islands” for interactivity
- Session-based auth (Flask-Login) with role guards (admin/doctor/patient)
- Doctor availability with duration-based slots, per-slot deletion, safe delete-by-date
- Appointment booking, reschedule, cancel; unified Treatment view (Pending/Completed/Rejected)
- CDN-only frontend (no Node/Vite, no axios at runtime); a minimal `window.http` fetch helper is used instead
- Optional Redis + Celery for caching and background jobs

## � Technologies and why we used them

- Flask 3.x — solid Python web framework; Jinja templating for MPAs
- Flask-Login — simple, secure session-based auth; easier than maintaining JWTs for an MPA
- Flask-SQLAlchemy/SQLAlchemy — ORM for clean model definitions and relationships
- SQLite — lightweight embedded DB, created automatically for local/dev use
- Redis (optional) — caching and Celery broker with short timeouts so the app won’t hang if Redis is down
- Celery (optional) — background tasks (reminders/reports/export) without blocking requests
- Vue 3 (CDN) — reactive UI for interactive parts; no build pipeline needed
- Bootstrap 5 + Icons (CDN) — responsive layout and icons with minimal setup

Key design choices:
- No Vite/Node at runtime: everything uses CDNs and a single `frontend/static/main.js` file
- `.vue` SFCs replaced with inline templates + mounts in `main.js` (small, composable components)
- A tiny fetch wrapper `window.http` (axios-like API) replaces axios across the codebase
- `v-cloak` and `{% raw %}...{% endraw %}` used to avoid flicker and Jinja/Vue moustache collisions

## 📁 Folder structure

```
HealthTrackPro/
└─ HealthTrackPro/
   ├─ HOSPITAL_MANAGEMENT_24F2002843/
   │  ├─ backend/
   │  │  ├─ app.py                 # Flask app (config, DB init/seed, auth, blueprints, Redis client)
   │  │  ├─ celery_tasks.py        # (Optional) Celery tasks (reminders/reports/export)
   │  │  ├─ instance/
   │  │  │  └─ hospital.db         # SQLite database (auto-created)
   │  │  ├─ models/
   │  │  │  └─ __init__.py         # SQLAlchemy models & relationships
   │  │  ├─ routes/
   │  │  │  ├─ admin_routes.py     # Admin endpoints & pages
   │  │  │  ├─ doctor_routes.py    # Doctor endpoints & pages
   │  │  │  └─ patient_routes.py   # Patient endpoints & pages
   │  │  └─ templates/
   │  │     ├─ base.html           # Bootstrap + Vue CDN, jsDelivr fallback, window.http helper, global CSS link
   │  │     ├─ index.html, login.html, register.html
   │  │     ├─ admin/              # Admin pages (dashboard, doctors, patients, appointments, profile)
   │  │     ├─ doctor/             # Doctor pages (dashboard, treatment, patients, availability, profile)
   │  │     └─ patient/            # Patient pages (dashboard, appointments, book, history, profile)
   │  └─ frontend/
   │     └─ static/
   │        ├─ main.js             # Central Vue mounts for Admin/Doctor/Patient
   │        └─ style.css           # All custom CSS (sidebar, active link, stat-card, v-cloak, utilities)
   ├─ pyproject.toml
   └─ uv.lock
```

## 🧠 Data models (backend/models/__init__.py)

- User — id, email, password (hashed), role (admin|doctor|patient), name, contact, is_active
  - Flask-Login’s `UserMixin` for session auth; one-to-one with Doctor/Patient (optional)
- Department — id, name, description; one-to-many with Doctor
- Doctor — user_id, department_id, specialization, experience, qualification, is_active
- Patient — user_id, date_of_birth, gender, address, blood_group, emergency_contact
- DoctorAvailability — doctor_id, date, start_time, end_time, is_available, duration_minutes, custom_times
- Appointment — patient_id, doctor_id, date, time, status (Booked|Completed|Cancelled), reason, created_at; one-to-one Treatment
- Treatment — appointment_id, diagnosis, prescription, notes, timestamps

Relationships quick map:
- Department 1 — * Doctor
- User 1 — 1 Doctor (optional) | User 1 — 1 Patient (optional)
- Doctor 1 — * DoctorAvailability | Doctor 1 — * Appointment
- Patient 1 — * Appointment
- Appointment 1 — 1 Treatment (optional until completed)

## 🔐 Authentication and route guards

- Session-based login with Flask-Login (`login_user`, `logout_user`), 8h session lifetime
- Unauthorized API calls return 401 JSON; page requests redirect to `/login`
- Role checks per blueprint: admin/doctor/patient endpoints require the matching role
- Blocked accounts (`is_active == False`) can’t log in

## 🧭 Key backend endpoints and flows

- Admin
  - Stats: `/admin/stats`
  - Doctor management: `/admin/api/doctors` CRUD, `/admin/api/doctors/<id>/activate`
  - Patients: `/admin/api/patients` (list/search), block/activate
  - Appointments overview: `/admin/api/appointments`
  - Profile get/update: `/admin/api/profile`
- Doctor
  - Stats: `/doctor/stats`
  - Appointments: `/doctor/api/appointments` (includes patient and location), update status
  - Treatment: `POST /doctor/api/treatment` (marks appt Completed)
  - Availability: get/set/delete; slots: `GET /doctor/api/slots?date=YYYY-MM-DD`
  - Slot deletion: `DELETE /doctor/api/slots?date=YYYY-MM-DD&time=HH:MM` (free-only)
  - Delete-by-date guard: `DELETE /doctor/api/availability/by-date?date=YYYY-MM-DD`
  - Patients & history: `/doctor/api/patients`, `/doctor/api/patients/<id>/history`
- Patient
  - Book/reschedule/cancel appointments
  - History and print-friendly view
  - Profile get/update

## 🎨 Frontend runtime (CDN Vue + one JS bundle)

- `templates/base.html`
  - Loads Vue 3 from unpkg with jsDelivr fallback
  - Injects `window.http` (fetch wrapper with axios-like `get/post/put/delete`, includes credentials)
  - Links global CSS `/static/style.css`
- `frontend/static/main.js`
  - Waits briefly for Vue to be available (prevents “Vue is not defined”)
  - Conditionally mounts small Vue apps into specific roots (e.g., `#vue-root`, `#dashboard-app`)
- `frontend/static/style.css`
  - Consolidated styles: sidebar, active link, stat-card, `[v-cloak]`, and small utilities (e.g., `.max-w-320`)

Why no `.vue` files?
- Simpler deployment: no Node/Vite build, fewer moving parts
- Vue is used purely for interactivity; the server-rendered HTML remains intact (sidebars, layout)

## ▶️ Run (Windows PowerShell)

Prereqs: Python 3.11+, Redis optional

1) Create and activate a virtual environment

```powershell
cd 'C:\Users\<you>\Downloads\HealthTrackPro\HealthTrackPro\HOSPITAL_MANAGEMENT_24F2002843'
python -m venv .venv
& .venv\Scripts\Activate.ps1
```

2) Install Python dependencies

```powershell
cd .\backend
pip install flask flask-login flask-sqlalchemy sqlalchemy werkzeug redis celery
```

3) Run Flask

```powershell
& ..\.venv\Scripts\python.exe app.py
# or
$env:FLASK_APP='app.py'; $env:FLASK_ENV='development'
python -m flask run
```

4) Optional: Redis + Celery

```powershell
redis-server   # in another terminal

# Celery worker
python -m celery -A celery_tasks worker --loglevel=info -P solo

# Celery beat (scheduler)
python -m celery -A celery_tasks beat --loglevel=info --detach
```

5) Open the app

Visit http://127.0.0.1:5000/

Default admin (seeded):
- Email: admin@hospital.com
- Password: admin123

## 🧩 Troubleshooting

- “Vue is not defined”
  - Ensure `base.html` loads Vue (CDN) and `/static/main.js` is present on that page; fallback CDN is included
- Blank profile forms
  - Ensure you’re logged in; check `/admin/api/profile` in DevTools Network for 401/403
- Celery exits with code 1
  - Verify Redis is running; start Celery from the `backend` folder with the venv active
- Jinja vs Vue moustaches
  - Wrap heavy client moustaches in `{% raw %} ... {% endraw %}` or embed JSON safely

## ❓ FAQ

- Where is the DB?
  - `backend/instance/hospital.db` (auto-created on first run)
- How is availability turned into slots?
  - By duration (`duration_minutes`) in `/doctor/api/slots` between `start_time` and `end_time`
- Why use sessions over JWTs?
  - Simpler for MPAs (server-rendered pages + cookies), fewer CORS/CSRF concerns
- Where did axios/Vite go?
  - Replaced with a tiny fetch wrapper (`window.http`) and CDN Vue; no Node build needed

---

This document is the single source of truth for the project. If you need deeper details, check the specific files referenced above.

