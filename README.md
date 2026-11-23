# Campus Transportation App – Agile Mindset (Problem Statement 12)

A working web application for the Agile Software Development final jury project. It includes the original route-management workflow plus student and driver accounts, bus passes, complaints, emergency alerts and driver administration.

| Required | Where in the app |
|---|---|
| **Bus routes and stops** | 20 routes (R1–R20), each with **8 neighborhood stops plus MIT-ADT College Gate**; one route number = one bus running **both ways** |
| **Schedules and timings** | Departure time for each direction + a timing for every stop in each direction |
| **Bus location via map** | Leaflet + OpenStreetMap route maps, simulated sample positions, and driver GPS tracking shared through SQLite with current coordinates and last-updated time |
| **Admin route / timing update** | Login-protected admin: add / edit / deactivate routes, add / remove / reorder stops, change all timings, control the simulated location |
| **Alert / notification for changes** | Notification with route, change, **old value → new value, reason, time**; bell counter + pop-up alert on open pages |
| **Student / driver accounts** | Student registration, role-based login, profile and password changes; admin-created driver accounts |
| **Student bus pass** | Digital pass with unique QR token and admin verification |
| **Complaints / emergency alerts** | Student complaint tracking, admin responses, targeted in-app emergency alerts |
| **Admin management** | Student route assignment, driver CRUD and availability, delay / cancellation status and alternative-route suggestions |

**Tech:** HTML + CSS + JavaScript · Python **Flask** · **SQLite** · Leaflet/OpenStreetMap · no paid services, no API keys, no GPS hardware.

> Agile documentation (backlog, user stories, sprint plan, test cases, viva questions…) is in **`docs/AGILE_DOCUMENTATION.md`**.

---

## 1. Folder structure

```
campus-transportation-app/
├── app.py                 ← Flask app: URLs, page rendering, background bus simulator
├── services.py            ← business logic: validation, updates, notifications, location status, simulation
├── db.py                  ← database connection, table definitions, sample data (20 routes)
├── init_db.py             ← script to create / reset the database
├── requirements.txt       ← Python packages needed (just Flask)
├── README.md              ← this file
├── database/              ← campus_transport.db is created here automatically
├── templates/             ← HTML pages (student, admin, driver, pass, complaint and login views)
├── static/css/style.css   ← styling (responsive)
├── static/js/app.js       ← auto-refresh, search, tabs, alerts, maps
├── tests/test_app.py      ← 59 automated tests
└── docs/AGILE_DOCUMENTATION.md
```

## 2. What to install (once)

1. **Python 3.10 or newer** – <https://www.python.org/downloads/>. In the installer **tick “Add python.exe to PATH”**.
2. **Visual Studio Code** – <https://code.visualstudio.com/> and its **Python** extension (`Ctrl+Shift+X`).
3. A modern browser. Internet is needed only for the map tiles (see §11).

Check Python: in a terminal run `python --version` (or `py --version`).

## 3. Run it in VS Code (Windows)

1. Unzip `campus-transportation-app.zip` (e.g. to `C:\Projects\campus-transportation-app`).
2. VS Code → **File → Open Folder…** → pick the folder that contains `app.py`.
3. **Terminal → New Terminal**, then:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   python init_db.py --reset
   python app.py
   ```
   (If `python` is not recognised use `py`. If PowerShell blocks activation run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first, or use a Command Prompt terminal.)
4. Open **<http://127.0.0.1:5000>**. Stop with `Ctrl+C`.

Next time: open the folder → `venv\Scripts\activate` → `python app.py`.

## 4. Accounts and logins

| User | Address | How to access |
|---|---|---|
| Student | <http://127.0.0.1:5000/register> | Register with PRN, college email and password, then log in at `/login?role=student` |
| Admin | <http://127.0.0.1:5000/admin/login> | username **`admin`** · password **`Admin@123`** |
| Driver | <http://127.0.0.1:5000/login?role=driver> | Admin creates a driver account from Admin → Drivers; the driver uses the assigned email or Driver ID and temporary password |

Passwords are stored as salted hashes. Students can optionally choose a route during registration; the admin can assign or change a route later from Admin → Students. The admin can create, edit and remove driver accounts and assign drivers to routes.

Forgot-password requests are recorded for administrator review. This demo does not send reset emails; an administrator should verify the student's identity and issue a temporary password through a trusted channel.

## 5. Reset the demo database

Stop the server, then `python init_db.py --reset`. (Do this after unzipping a new version so the new sample data is loaded.)

## 6. Pune-area route profiles: 20 routes, 8 neighborhood stops plus College Gate

* **One route number = one area = one bus that runs both ways.** Route numbers never change.
* The routes use **College Gate – MIT-ADT University** as their origin. Your eight numbered home-to-college stops are shown in the order you provided; College Gate is added as the ninth stop. Every stop has **two timings** and the reverse direction uses the same stops in reverse order.
* Every College → Home trip departs at **4:45 PM**. The Home → College departure is calculated from route duration so the bus reaches MIT-ADT by **8:45 AM**.
* **Bus location:** sample buses use simulated positions. A signed-in driver can start browser GPS tracking for their assigned route; updates are stored in SQLite and polled by student/admin maps. Stop coordinates are approximate.

The stop lists are based on the locations you supplied. The application does not connect to Moovit, PMPML, or another live transit feed. Verify stop coordinates and operating times with MIT-ADT before using these schedules for actual service.

## 7. Demonstration script (what to show the jury)

1. `python init_db.py --reset`, then `python app.py`. Open <http://127.0.0.1:5000> and keep this **student** tab open.
2. **Student checks a route:** click **R1 → “Stops & live bus”**. Show the stops and timings (tabs for Home → College and College → Home), bus BUS-101, the **SIMULATED** label and the map with the route line, stops and the **moving bus**. Also show **🗺 Live map** (all 20 buses) and search a place (`Hadapsar`, `Kharadi`).
3. **Admin changes the timing:** in a second window open **Admin → login** (`admin` / `Admin@123`) → **Edit R1** → change *College → Home departs* from **4:45 PM to 5:15 PM** (keep “shift all stop timings” ticked) → reason `Schedule changed due to traffic.` → **Save changes & notify students**. *(Route changes work the same way: add / remove / reorder / rename stops on that page.)*
4. **Student sees the update and alert:** in the student tab, within ~10 seconds a **pop-up alert** appears, the 🔔 bell shows **1**, R1 shows **5:15 PM** and the notification reads **Old: 4:45 PM → New: 5:15 PM** with the reason. Press **F5** – it persists (stored in the database).
5. **Invalid route:** search **R99** → *“Route 'R99' not found.”* (or open `/routes/R99` → friendly 404 page).
6. **Stale location:** Admin dashboard → **⏱ Stale** on R2 → open R2 as a student → yellow **Stale** warning (“older than 5 minutes”).
7. **Missing location:** Admin dashboard → **✕ Missing** on R3 → open R3 → **“Bus location unavailable.”**
8. Admin dashboard → **▶ Resume live simulation (all buses)** → all buses are Current and moving again.
9. *(Optional)* invalid admin input: empty reason, empty departure time, duplicate route ID `R1` on **Add route** → clear errors, nothing saved, **no** notification.

## 8. Automated tests

With the virtual environment active:
```
python -m unittest discover -s tests -v
```
Each test uses its own temporary database. **Expected:** every line ends with `ok`, then `Ran 59 tests … OK`.

| Test group | What it checks |
|---|---|
| `StudentTests` (7) | route list, **8 neighborhood stops plus the college in both directions**, same bus both ways, search by route/stop, **R99 invalid**, 404 page, HTML-escaping |
| `LocationTests` (7) | Current / **Stale >5 min** / exactly 5 min / **Unavailable (missing)**, SIMULATED label, stale & missing demos, coordinate validation, no notification for location, live API |
| `SimulationTests` (6) | the simulator moves buses along the route and keeps them Current, **frozen buses stay Stale / Unavailable**, resume one / all, wrap-around, inactive routes |
| `AuthTests` (6) | admin pages redirect when logged out, **unauthorised POST changes nothing**, login success / wrong / empty, **hashed password**, logout, CSRF |
| `UpdateAndNotificationTests` (11) | **R1 4:45→5:15 PM workflow**, old/new/reason/time, student sees it and it persists, shift per trip, Home→College departure, missing reason / empty / invalid time, no-change, DB error, **transaction rollback** |
| `NotificationFeatureTests` (3) | notification API (bell/pop-up), type & route filters, day grouping |
| `RouteManagementTests` (11) | add route (both trips + live bus), **duplicate route ID**, many invalid inputs, add / edit / reorder / remove stops, deactivate & reactivate |
| `ExtendedSampleTests` (5) | 20 requested stop sequences with coordinates, shared schedule constraints, every bus simulated, area search, every page renders |
| `HelperTests` (3) | time parsing, formatting, interpolation |

Run one group: `python -m unittest tests.test_app.SimulationTests -v`

## 9. Added account and transport-management features

- Student registration, login, profile editing and password change.
- Driver login and assigned-route dashboard; drivers can submit simulated bus coordinates.
- Admin student management and route assignment.
- Admin driver account creation, editing, availability and deletion.
- Digital student bus pass with a unique QR token; admin can verify the token, including camera scanning in supported browsers.
- Student feedback and complaints with admin status and response management.
- Admin emergency alerts, route-specific delay/cancellation notices and in-app notifications.
- Cancelled-route page with alternative routes that share stops.
- Simulated ETA, clearly labelled as an estimate.
- Admin password-reset request review. No email delivery is configured.

**Important demo limits:** Driver GPS requires browser location permission and a secure context (HTTPS, or localhost). SQLite makes updates available to all app sessions using the same database file; separate server instances must share that database to see the same position. ETA is an approximate demo estimate, not a traffic-aware prediction. QR camera scanning depends on browser support and camera permission; manual token verification remains available.

## 10. How it works (short)

```
Browser ──HTTP──► app.py (URL → function) ──► services.py (validate + rules) ──► SQLite database
   ▲                                                                                  │
   └── HTML / JSON ◄── templates + /api/... ◄──────────────────────────────────────────┘
                              ▲
              background thread in app.py moves the simulated buses every 6 s
```
* **Admin changes a route/timing** → `services.update_route_details()` validates → ONE transaction: update `routes` (+ `stops`) **and** insert into `notifications` → commit. If anything fails nothing is saved and no notification exists.
* **Student pages** read the database; `app.js` re-requests small HTML fragments every 10 s and a tiny JSON (`/api/notifications/summary`) for the bell and pop-ups.
* **Location status** (`services.location_status`): missing coordinates → *Unavailable*; older than 5 minutes → *Stale*; otherwise *Current*. Driver tracking state, trip status, coordinates, and timestamps are persisted in `bus_locations`.
* **Simulated live bus:** sample buses have `auto_update` and `progress` columns. The simulator moves them along their stops and stores a fresh timestamp. Saving a position, “Make 10 min old” or “Clear” **freezes** that bus; “Resume live simulation” moves it again. It does not move a bus during driver GPS tracking.
* **Driver GPS:** Start Live Location requests the browser's GPS permission and uses `watchPosition`; each coordinate is saved to SQLite. Student route maps, the all-bus live map, and the admin route table read the same persisted location. Stop Trip calls `clearWatch()` and marks the trip ended so no later driver position is accepted.
* **Browser storage:** `localStorage` is used only for notification read-state in the browser; it is not used for bus positions because it cannot share updates between driver, student, and admin sessions. Shared positions are stored in the app's SQLite database.

Tables: `admins`, `routes`, `stops` (FK → routes, with coordinates), `bus_locations` (FK → routes), `notifications` (FK → routes). Foreign keys are enforced.

## 11. What is real and what is simulated

| Real (implemented) | Simulated / demo only |
|---|---|
| Flask + SQLite app, sessions, hashed password, CSRF token; optional real browser GPS shared from the driver | Sample buses use simulated positions and approximate sample data |
| Routes, stops, timings for both directions with validation | Route names, timings, bus numbers and stop coordinates are **sample data** |
| Add / edit / deactivate routes, reorder stops, change timings | The admin account is a **demo** account |
| Notifications with old/new value, reason, time (one transaction), bell, pop-ups | Notifications are **in-app only** (no email/SMS/push) |
| Current / Stale / Unavailable logic, driver GPS updates, and moving buses on maps | GPS requires device permission and an HTTPS/localhost browser context |
| 59 automated tests | |

## 12. Map note

The map uses **Leaflet** and **OpenStreetMap** tiles from the internet (no key). Offline, the map area shows a short message and the latitude/longitude card still works (the “coordinate-based view”). Everything else works offline.

## 13. Troubleshooting

| Problem | Fix |
|---|---|
| `'python' is not recognized` | Re-install Python with **Add python.exe to PATH**, or use `py`. Restart VS Code. |
| `venv\Scripts\activate` blocked | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` or use a Command Prompt terminal. |
| `ModuleNotFoundError: No module named 'flask'` | Activate the venv (`(venv)` in the prompt) then `pip install -r requirements.txt`. |
| `Address already in use` | Close the other server (`Ctrl+C`) or change `port=5000` at the bottom of `app.py`. |
| Old data / old routes | `python init_db.py --reset`, then `Ctrl+F5` in the browser. |
| “Your session expired or the form was invalid” | The server was restarted while a page was open. Reload and try again. |
| `database is locked` | Run only one server. |
| Driver GPS does not start | Allow location permission and use HTTPS or localhost. The simulator runs only with `python app.py` (not with `flask run`). |
| Map grey / missing | No internet or blocked CDN; coordinates are still shown. |
| Wrong Python in VS Code | `Ctrl+Shift+P` → **Python: Select Interpreter** → the one in `.\venv`. |

## 14. Admin pages

| Address | Purpose |
|---|---|
| `/admin/login` | Log in |
| `/admin` | Dashboard: stats, all routes with timings and live coordinates, **⏱ Stale / ✕ Missing** demo buttons, **▶ Resume live simulation**, change history |
| `/admin/routes/new` | Add a route (stops one per line: `Name, HH:MM` or `Name, HH:MM, lat, lon`) |
| `/admin/routes/<ID>` | Edit name / bus / both departure times, stops and their timings, simulated location, deactivate / reactivate |

**Reordering note:** moving a stop up/down moves its name and map position; the time slots stay where they are so timings remain in order. Edit the times afterwards if needed.
