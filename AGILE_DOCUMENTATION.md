# Agile Jury Documentation – Campus Transportation App (Topic 12)

> **How to read the labels in this document**
> * **[ACTUAL]** – something that really exists in this project (code, files, results of tests that were run).
> * **[SUGGESTED]** – a recommended document/approach you can adopt. It is *not* a claim that you already did it.
> * **[ILLUSTRATIVE]** – example numbers (story points, burndown, assignments) made up to show the format. Replace them with your team's real data before presenting.
>
> Do **not** tell the jury you used Jira, Trello or GitHub, or that you ran a test, unless you really did. Sections 10 and 11 give you the steps so that it becomes true.

---

## 1. Problem statement and proposed solution [ACTUAL – the app implements it]

**Problem.** Students depend on college buses, but route changes, timing changes and bus whereabouts are communicated by word of mouth or scattered messages. Students miss buses, wait without information, and the transport office has no single place to publish changes with a reason.

**Proposed solution.** A web application with two sides:
* **Student dashboard** – search routes, see start, destination, all stops in order with timings, the assigned bus, the bus location with a clear **Current / Stale / Unavailable** status, and **in-app notifications** for every route or schedule change.
* **Admin dashboard** (login protected) – manage routes, stops, timings and the (simulated) bus location. Every change needs a **reason**, is validated, stored together with its **old and new values**, and automatically produces a notification.

**Agile mindset.** We build in small increments (two sprints), keep a prioritised backlog, deliver a working end-to-end slice first (student → admin update → student notification), and inspect/adapt after each sprint.

---

## 2. Product backlog with priorities [ILLUSTRATIVE – priorities/points are examples]

Priority uses MoSCoW (Must / Should / Could / Won’t). Points use the Fibonacci scale (see §5).

| ID | Backlog item | Priority | Points | Sprint |
|---|---|---|---|---|
| PB1 | Database schema + sample data (R1–R3) | Must | 3 | 1 |
| PB2 | Student route list and search (incl. “route not found”) | Must | 5 | 1 |
| PB3 | Route details: start, destination, ordered stops, timings, bus number | Must | 3 | 1 |
| PB4 | Admin login with session protection and hashed password | Must | 5 | 1 |
| PB5 | Bus location view with Current / Stale (>5 min) / Unavailable status, labelled simulated | Must | 8 | 1 |
| PB6 | Responsive, clean UI (student + admin) | Should | 2 | 1 |
| PB7 | Admin: add / edit / deactivate routes | Must | 5 | 2 |
| PB8 | Admin: add / remove / reorder stops, edit stop timings | Must | 5 | 2 |
| PB9 | Notifications on every successful change (old value, new value, reason, time) in one transaction | Must | 8 | 2 |
| PB10 | Input validation + friendly errors (duplicate ID, bad time, missing reason, unauthorised access) | Must | 5 | 2 |
| PB11 | Auto-refresh with JavaScript polling | Should | 2 | 2 |
| PB12 | Automated tests + manual test cases | Must | 3 | 2 |
| PB13 | 20 routes, one route number = one bus running both ways (Home → College and College → Home), 8 stops each with two timings per stop | Must | 5 | 2 |
| PB14 | Moving simulated bus on a map (route line, stops, live simulation) and a live map of all buses | Must | 5 | 2 |
| PB15 | Notification bell, pop-up alerts, filters by type and route | Should | 3 | 2 |
| PB16 | Real GPS integration | Won’t (this release) | – | – |
| PB17 | Email / SMS / push notifications | Could (future) | – | – |
| PB18 | Multiple admin accounts and roles | Could (future) | – | – |

---

## 3. User stories with acceptance criteria [SUGGESTED – matches what the app does]

**US1 – Find a route (PB2)**
*As a student, I want to search for a bus route, so that I can quickly find the one that serves my area.*
Acceptance criteria:
1. Given the dashboard, when I type `R1`, then only R1 is shown (search is not case-sensitive).
2. When I search for `R99`, then I see “Route 'R99' not found” with a hint, and no error page.
3. The search also matches route names and stop names (e.g. `Baner`).

**US2 – See stops and timings (PB3)**
*As a student, I want to see all stops with their timings in order, so that I know when to reach my stop.*
1. The page shows start, destination, departure time and the assigned bus number.
2. Stops are listed in route order with a time for each.
3. Times are shown in 12-hour format (e.g. 8:20 AM).

**US3 – See where the bus is (PB5)**
*As a student, I want to see the bus location and how fresh it is, so that I can decide when to leave.*
1. A marker is shown on the map and latitude/longitude plus “last updated” time are displayed.
2. Location older than 5 minutes shows a **Stale** warning; missing coordinates show “Bus location unavailable.”
3. Every location is clearly labelled **SIMULATED – not real GPS**.

**US4 – Admin login (PB4)**
*As an admin, I want to log in securely, so that only authorised staff can change schedules.*
1. Correct username/password opens the admin dashboard; wrong credentials show an error.
2. Opening any `/admin` page without logging in redirects to the login page, and POST requests change nothing.
3. Passwords are stored as hashes, never as plain text.

**US5 – Manage routes and stops (PB7, PB8)**
*As an admin, I want to add, edit, deactivate routes and manage stops, so that the information stays correct.*
1. I can add a route with ID, name, bus, departure time and ≥ 2 stops.
2. I can edit the departure time, add/remove/reorder stops and change stop times.
3. Deactivated routes disappear for students but stay in the database.

**US6 – Notify students about changes (PB9)**
*As a student, I want to be told about route or schedule changes and why, so that I am not surprised.*
1. After an admin saves a change, a notification with the route, description, **old value, new value, reason and time** appears on the student dashboard.
2. The new data is still visible after refreshing the page.
3. A failed or invalid update creates **no** notification.

**US7 – Reliable input (PB10)**
*As an admin, I want clear validation messages, so that I can fix mistakes quickly.*
1. Duplicate route ID, empty/invalid departure time, missing reason, invalid stop data and invalid coordinates are rejected with a clear message.
2. Nothing is saved when validation fails.

**US9 – Moving bus and route map (PB14)**
*As a student, I want to see my bus moving along its route on a map, so that I know how far away it is.*
1. The route page shows the route line, every stop and the bus marker; the bus moves every few seconds.
2. The card says which stop the bus is near and which way it is heading.
3. A live map shows all buses; everything is labelled SIMULATED.

**US10 – Notice changes instantly (PB15)**
*As a student, I want an alert when something changes, so that I do not miss it.*
1. A bell counter and a pop-up appear within about 10 seconds of an admin change.
2. I can filter notifications by type (schedule, stops, bus, routes) and by route.

**US8 – Live updates (PB11)**
*As a student, I want the page to update automatically, so that I do not need to refresh.*
1. Route cards, notifications and location refresh about every 10 seconds without a full reload.
2. If the server cannot be reached, a banner explains it and the old data stays visible.

---

## 4. Example story-point estimates [ILLUSTRATIVE]

| Story | Points | Why (example reasoning) |
|---|---|---|
| US1 Find a route | 5 | Search + empty/invalid states |
| US2 Stops and timings | 3 | Simple read + display |
| US3 Bus location | 8 | Status rules, timestamp logic, map, fallback, labelling |
| US4 Admin login | 5 | Sessions, hashing, access control |
| US5 Manage routes/stops | 10 (PB7 5 + PB8 5) | Many forms and rules (ordering, minimum stops) |
| US6 Notifications | 8 | Old/new values + transaction consistency |
| US7 Validation | 5 | Many edge cases |
| US8 Live updates | 2 | Small JavaScript polling |

Total ≈ 54 points for PB1–PB12 plus 13 points for PB13–PB15 (added after the first demo).

---

## 5. Planning Poker – explanation [SUGGESTED]

Planning Poker is a team estimation game that reduces anchoring and encourages discussion.

1. The Product Owner reads a user story and answers questions.
2. Every developer privately picks a card from the scale **1, 2, 3, 5, 8, 13** (Fibonacci – the gaps grow because bigger items are less certain). “?” means “I do not understand” and “☕” means “I need a break”.
3. Everyone reveals the cards at the same time.
4. If the numbers differ (e.g. 3 and 8), the lowest and highest estimator explain their reasoning (maybe one forgot the validation work, the other knew a library already exists).
5. Re-vote until the team roughly agrees; that number is the story’s **story points** (relative size: effort + complexity + uncertainty, *not* hours).
6. Use a reference story (e.g. “US2 = 3”) to compare others against it.

*Free tools:* planningpoker.com, Scrum Poker Cards mobile apps, or paper cards.
*Example round:* US3 “Bus location” – votes 5, 8, 8, 13, 8. The person who voted 13 mentioned the stale-time rules and the map fallback; after discussion everyone voted 8.

---

## 6. Two-sprint plan [ILLUSTRATIVE – replace names and dates with your team’s]

Assumptions: 2-week sprints, team velocity ≈ 26–28 points, five team members (Member A–E). Roles: Product Owner, Scrum Master, 3 developers (everybody codes and tests).

### Sprint 1 – “Student can find a route and see the bus” (Goal: read-only student journey + admin login)

| Backlog item | Task | Assigned to | Est. (h) |
|---|---|---|---|
| PB1 | Design tables, write `db.py`, sample data | Member A | 6 |
| PB2 | Route list page, search, empty state | Member B | 8 |
| PB3 | Route details page with ordered stops | Member B | 5 |
| PB4 | Login/logout, session, password hashing, route protection | Member C | 8 |
| PB5 | Location status function (Current/Stale/Unavailable) + tests | Member D | 8 |
| PB5 | Leaflet map + offline fallback | Member D | 5 |
| PB6 | `style.css`, base layout, responsive checks | Member E | 8 |
| – | Sprint review demo + retrospective | Whole team | 2 |

### Sprint 2 – “Admin changes routes and students are notified” (Goal: complete end-to-end workflow)

| Backlog item | Task | Assigned to | Est. (h) |
|---|---|---|---|
| PB7 | Add / edit / deactivate route forms | Member A | 8 |
| PB8 | Stop add/remove/reorder + time rules | Member C | 10 |
| PB9 | Notifications table, create inside same transaction, student panel | Member B | 10 |
| PB10 | Validation rules + error messages | Member D | 8 |
| PB11 | Polling script (`app.js`) | Member E | 4 |
| PB12 | Automated tests + manual test cases + README | Member E + D | 8 |
| – | Jury rehearsal, bug fixing, retrospective | Whole team | 4 |

**Ceremonies [SUGGESTED]:** Sprint Planning (1–2 h), Daily Scrum (15 min), Sprint Review (demo to the guide), Sprint Retrospective (what went well / to improve / actions).

---

## 7. Definition of Done [SUGGESTED]

A backlog item is **Done** when:
1. Code is written, runs without errors and is committed to the repository with a clear message.
2. Acceptance criteria of the story are met and demonstrated.
3. Input is validated and errors show friendly messages (no crashes / stack traces).
4. Automated tests for the item exist and pass (`python -m unittest discover -s tests -v`).
5. Manual test cases for the item are executed and recorded.
6. The UI works on laptop and mobile width.
7. A teammate reviewed the code (peer review / pull request).
8. README / documentation is updated.
9. The Product Owner accepted it in the Sprint Review.

---

## 8. Sprint burndown [ILLUSTRATIVE – sample progress, not real data]

**Sprint 1** – committed 26 points, 10 working days.

| Day | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Ideal remaining | 26 | 23.4 | 20.8 | 18.2 | 15.6 | 13 | 10.4 | 7.8 | 5.2 | 2.6 | 0 |
| Actual remaining (sample) | 26 | 26 | 23 | 23 | 18 | 15 | 15 | 10 | 8 | 3 | 0 |

```
Points
26 |*.
24 | ** .
22 |   *.  .
20 |    ..  .          * = actual (sample)   . = ideal
18 |     *   .
16 |      .   .
14 |      *    .
12 |        .   .
10 |         *   *.
 8 |            .  *.
 4 |              .   .
 2 |                *   .
 0 +--+--+--+--+--+--+--+--+--+--+--> day
    0  1  2  3  4  5  6  7  8  9  10
```
*Reading it:* actual stays above ideal in the middle (the map fallback took longer than planned) but the team catches up by day 10.

**Sprint 2** – committed 28 points.

| Day | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Ideal remaining | 28 | 25.2 | 22.4 | 19.6 | 16.8 | 14 | 11.2 | 8.4 | 5.6 | 2.8 | 0 |
| Actual remaining (sample) | 28 | 28 | 25 | 25 | 20 | 17 | 17 | 12 | 8 | 5 | 0 |

To make a real chart: copy these two rows into Excel/Google Sheets → Insert → Line chart, and update the “actual” row every day after the Daily Scrum.

---

## 9. Manual test cases [SUGGESTED – “Actual result” columns are for YOU to fill after executing]

Start from a clean database: `python init_db.py --reset`, then `python app.py`. If more than 5 minutes passed since reset, press “▶ Resume live simulation (all buses)” on the Admin dashboard first.

| ID | Type | Steps | Expected result | Actual result / Pass? |
|---|---|---|---|---|
| TC1 | Positive | Open `/`, click R1 → “View stops & bus location” | Stops College Gate, Wakad, Hinjawadi in order with times; bus BUS-101; location card says SIMULATED | |
| TC2 | Positive | Admin login with `admin` / `Admin@123` | Admin dashboard opens with success message | |
| TC3 | Positive (main workflow) | Admin → Edit R1 → departure 08:30, reason “Schedule changed due to traffic.” → Save. Open student dashboard, then press F5 | R1 shows 8:30 AM; notification shows Old 8:00 AM → New 8:30 AM + reason + time; still there after F5 | |
| TC4 | Negative | Search `R99` on the student page | Message “Route 'R99' not found.”; no crash | |
| TC5 | Negative | Admin login with a wrong password | “Invalid username or password.”; not logged in | |
| TC6 | Negative | Not logged in: open `/admin` directly | Redirected to login page with a message | |
| TC7 | Negative | Admin → + Add route with ID `R1` | “Route ID R1 already exists…”; no route added; no notification | |
| TC8 | Negative | Edit R1, clear the departure time, give a reason, Save | “Departure time is missing…”; data unchanged; no notification | |
| TC9 | Negative | Edit R1, change time but leave reason empty | “A reason is required…”; no change; no notification | |
| TC10 | Exceptional | Admin dashboard → “⏱ Stale” on R4, then open R4 as a student | Yellow “Stale” badge and warning that location is older than 5 minutes | |
| TC11 | Exceptional | Admin dashboard → “✕ Missing” on R5, then open R5 as a student | “Bus location unavailable.”; no marker | |
| TC12 | Exceptional | Admin → Edit R1 → location: enter latitude `123` → Save location | Error “Latitude must be between -90 and 90”; location unchanged | |
| TC13 | Exceptional | Open the student page, stop the server (Ctrl+C), wait ~15 s | Red banner “Cannot reach the server…”; old data stays visible | |
| TC15 | Positive | Student opens R4 (Wagholi Line) and checks both tabs | 8 stops from Wagholi (via Kharadi, Hadapsar…) to College Gate and the reverse, with timings | |
| TC16 | Positive | Watch the bus marker on R1’s map for 30 s | Marker moves along the route; “near <stop>” text changes; status Current | |
| TC17 | Positive | Keep a student tab open, change R1 in Admin | Pop-up alert and bell count within ~10 s | |
| TC14 | Positive | Admin → Edit R1 → add stop “Dange Chowk” 8:30 at position 3, with a reason | Stop appears in position 3; notification “Stop added” with old/new sequence | |

---

## 10. Jira or Trello setup instructions [SUGGESTED]

**Trello (simplest)**
1. Go to trello.com → sign up (free) → **Create board** → name it “Campus Transportation App”.
2. Create lists: `Product Backlog`, `Sprint 1 Backlog`, `Sprint 2 Backlog`, `In Progress`, `In Review / Testing`, `Done`.
3. Add one card per backlog item (PB1…PB12). In the card: description = user story, checklist = acceptance criteria, label = priority (Must/Should/Could), and add story points in the card title, e.g. `[8] PB5 Bus location status`.
4. Add team members → assign cards. Add due dates for each sprint end.
5. At Sprint Planning drag cards from `Product Backlog` to the sprint list. During the sprint move cards left to right.
6. Take screenshots at the sprint start and end – these are your evidence for the jury.

**Jira**
1. Go to atlassian.com → **Jira Software** (free plan) → create a project using the **Scrum** template, name “Campus Transportation App” (key `CTA`).
2. Backlog tab → create issues (type *Story*) for each backlog item; fill story points and acceptance criteria in the description.
3. **Create sprint** → drag issues into Sprint 1 → set dates → **Start sprint**.
4. Use the board (To Do / In Progress / Done); at the end click **Complete sprint**.
5. Reports → **Burndown Chart** gives a real burndown chart. Invite teammates via Project settings → People.

---

## 11. GitHub repository setup and commit examples [SUGGESTED]

1. Create an account at github.com and install **Git for Windows** (git-scm.com). In VS Code the **Source Control** panel (`Ctrl+Shift+G`) can do all of this.
2. Create a **new repository** on GitHub (name `campus-transportation-app`, private or public, no README).
3. In the VS Code terminal inside the project folder:
```
git init
git config user.name "Your Name"
git config user.email "you@example.com"
```
4. Create a file named `.gitignore` containing:
```
venv/
__pycache__/
*.pyc
database/*.db
```
5. First commit and push:
```
git add .
git commit -m "feat: initial Flask project with SQLite schema and sample data"
git branch -M main
git remote add origin https://github.com/<your-username>/campus-transportation-app.git
git push -u origin main
```
6. Working style: one **branch per user story** (`git checkout -b feature/US3-bus-location`), open a **Pull Request**, a teammate reviews, then merge.
7. Add teammates: repository → Settings → Collaborators.

**Example commit messages (one per task):**
```
feat: add routes, stops, bus_locations and notifications tables
feat: student dashboard with route search and not-found message
feat: route details page with ordered stops and timings
feat: admin login with session and hashed password
feat: location status Current/Stale/Unavailable with 5-minute rule
feat: create notification with old/new value and reason in one transaction
fix: reject duplicate route ID case-insensitively
fix: show friendly message when database update fails
test: add unit tests for stale and missing bus location
style: make dashboard responsive for mobile
docs: add README setup steps for Windows and VS Code
```

---

## 12. Suggested architecture and data flow [ACTUAL – describes this code]

```
┌────────────┐  HTTP   ┌─────────────────────────── Flask server ───────────────────────────┐
│  Browser   │────────►│ app.py  (routes/URLs, login check, CSRF, error pages)              │
│ HTML/CSS/JS│◄────────│    │                                                               │
└────────────┘  HTML   │    ▼                                                               │
   ▲   │  fetch()      │ services.py (validation, business rules, notifications, status)    │
   │   └─every 10 s───►│    │                                                               │
   │      /partials/*  │    ▼                                                               │
   │                   │ db.py ──► SQLite file  database/campus_transport.db                │
   │                   └────────────────────────────────────────────────────────────────────┘
   └── templates/*.html (Jinja) build the pages; static/ holds CSS and JS
```

**Data flow – “admin changes departure time”**
1. Admin submits the form → `POST /admin/routes/R1/details` (`app.py`).
2. `app.py` checks the session (logged in?) and the CSRF token.
3. `services.update_route_details()` validates name, bus, time, reason; compares with old values.
4. **One database transaction:** update `routes` (and shift `stops`) + insert into `notifications` (old, new, reason, timestamp). If anything fails → rollback → nothing saved, no notification.
5. The admin is redirected back with a success (or error) message.
6. A student’s browser requests `/partials/routes` and `/partials/notifications` every 10 s (or on refresh), the server reads the database and returns HTML; `app.js` swaps it into the page.

**Why this structure:** each file has one job (routes / rules / database), which keeps it beginner-friendly and easy to test.

---

## 13. Likely challenges and solutions

| Challenge | Solution used / suggested |
|---|---|
| No real GPS hardware | Simulated coordinates entered by the admin, clearly labelled; status logic works the same with real data later |
| Keeping route change and notification consistent | One SQLite transaction (`with conn:`); tested by forcing a failure |
| Stale data confusing students | 5-minute rule → Stale warning; missing → Unavailable |
| Reordering stops without breaking times | Move the stop *name* while time slots stay in order; timings must strictly increase |
| Bad input | Central validation in `services.py`; `novalidate` forms so the server messages are demonstrated |
| Unauthorised access | Session check on every admin URL + CSRF token on every POST |
| Updating pages without reload | Polling small HTML fragments every 10 s |
| Map needs internet | Offline fallback showing coordinates |
| Team coordination | Backlog, sprint board, branches and pull requests |
| Beginner setup problems | README troubleshooting table, reset script, tests with temporary databases |

---

## 14. Short jury demonstration script (about 6–8 minutes) [SUGGESTED]

1. **(30 s) Problem + solution** – §1 in two sentences; mention Scrum with two sprints.
2. **(60 s) Student view** – dashboard → R1 → stops, timings, bus BUS-101, map, **SIMULATED** label.
3. **(30 s) Errors** – search `R99` → friendly message. Open R2 → **Stale** warning. Open R3 → **“Bus location unavailable.”**
4. **(30 s) Security** – try `/admin` while logged out → redirected. Log in as admin.
5. **(90 s) Main workflow** – Edit R1: 08:00 → 08:30, reason “Schedule changed due to traffic.” → Save → switch to student tab → new time + notification (old, new, reason, time) → press F5 → still there.
6. **(30 s) Validation** – submit an empty reason or duplicate route ID `R1` → error, no notification.
7. **(45 s) Quality** – show terminal: `python -m unittest discover -s tests -v` → all tests `ok` (run it live **only** on your laptop, and report what you really see).
8. **(60 s) Agile evidence** – show your real Jira/Trello board, sprint plan, burndown (state clearly if it is sample data), GitHub commits.
9. **(30 s) Limits and future work** – simulated location, in-app notifications only; future: real GPS, push/SMS, multiple admins.

---

## 15. Possible viva questions and simple answers

1. **What is Agile?** A way of building software in short cycles with continuous feedback, delivering working software early instead of one big delivery at the end.
2. **Why Scrum for this project?** Fixed-length sprints, clear roles, and regular reviews fit a college project with deadlines.
3. **Who is the Product Owner / Scrum Master / Developer?** PO decides priorities and accepts work; Scrum Master removes obstacles and guides the process; developers build and test.
4. **What is a product backlog and a sprint backlog?** The backlog is the ordered list of everything wanted; the sprint backlog is the part chosen for the current sprint with its tasks.
5. **What is a user story?** “As a <user>, I want <goal>, so that <benefit>” plus acceptance criteria.
6. **What are story points and Planning Poker?** Relative size units (effort + complexity + uncertainty); Planning Poker is a card game where the team votes at the same time and discusses differences.
7. **What is velocity?** Story points the team completes per sprint; used to plan the next sprint.
8. **What is a burndown chart?** Remaining work versus time; shows if the sprint is on track.
9. **What is Definition of Done?** A shared checklist (§7) that must be true before an item is called finished.
10. **Why Flask and SQLite?** Both are simple, free and need no server setup – suitable for beginners and demos. SQLite is a file database.
11. **How do notifications work?** When the admin saves a valid change, the app stores the old value, new value, reason and time in a `notifications` table in the same transaction; student pages read and display it.
12. **What is a database transaction and why use it?** A group of operations that all succeed or all fail. Without it we could save a route change but lose its notification.
13. **How is the admin page protected?** Session login, hashed password (never stored in plain text), a check on every admin URL, and a CSRF token on forms.
14. **How do you decide Current, Stale, Unavailable?** No coordinates (or no timestamp) → Unavailable; last update older than 5 minutes → Stale; otherwise Current.
15. **Is the bus location real?** No. It is simulated and labelled so; an admin enters it. A real system would receive GPS from devices.
16. **How does the page update without refresh?** JavaScript polling: every 10 seconds `app.js` asks the server for fresh HTML fragments and replaces them.
17. **How did you test?** Automated tests with Python `unittest` (temporary database, Flask test client) plus manual test cases with positive, negative and exceptional cases. *(Only say this if you actually ran them.)*
18. **What would you improve next?** Real GPS, email/SMS/push, multiple admin roles, real route data, deployment.
19. **What is the difference between Agile and Waterfall?** Waterfall finishes each phase once in sequence; Agile repeats short cycles and accepts changing requirements.
20. **What did you learn from the retrospective?** *(Answer from your own real retrospective.)*

---

## 16. Which features are simulated and which are implemented

**Implemented [ACTUAL]** – runs with real code and a real SQLite database (also: both-direction trips on one bus, 20 routes with 8 stops each, a moving simulated bus on a map, bell/pop-up notifications):
student dashboard, route search, route details with ordered stops/timings/bus, Current/Stale/Unavailable logic with timestamps, admin session login with hashed password, add/edit/deactivate routes, add/remove/reorder stops, edit timings, reason for every change, validation (duplicate IDs, invalid times, invalid stops, invalid coordinates, missing reason), old/new-value notifications created in the same transaction, polling auto-refresh, friendly error pages, CSRF token, 59 automated tests.

**Simulated / sample [ACTUAL – and clearly labelled in the app]**:
bus coordinates (entered manually), all route names/timings/bus numbers, the demo admin account.

**Not implemented [honest limits]**: real GPS or live vehicle feed, email/SMS/push notifications, multiple admin users/roles or password change, deployment to the internet, brute-force login throttling, per-student accounts.

**Evidence status**

| Item | Status |
|---|---|
| Application code and database | **Actual** – delivered in this project |
| Automated tests | **Actual result in the build environment:** 59 tests, all passed (Python 3.12, Flask 3.1). *You* must run them on your laptop and report your own result. |
| Jira / Trello board, GitHub repository, real burndown, Planning Poker sessions | **Not done yet** – only instructions are given; do them before claiming them |
| Sprint plan, burndown numbers, story points, task assignments | **Illustrative** – replace with your team’s data |


---

## 14. Account and transport-management extensions [ACTUAL – added in the enhanced code]

The enhanced code now also includes:
- Student registration/login, profile editing and password changes.
- Driver login and a driver dashboard; driver accounts are created by the admin.
- Admin student route assignment and driver management.
- Digital bus passes with unique QR tokens and admin verification.
- Student feedback/complaints with admin responses and status tracking.
- Emergency, delay and cancellation in-app notifications.
- Cancelled-route page with shared-stop alternative route suggestions.
- Admin password-reset request review (manual process; no email service is configured).

**Demo limitations:** bus location and ETA remain simulated. QR code rendering uses a browser-side library; camera scanning depends on browser support and permissions. In-app notifications do not send SMS, email or push messages.
