"""
db.py - everything about the SQLite database:
  * how to connect
  * the table definitions (schema)
  * the demo/sample data (seed)

The database file is created automatically the first time the app runs.

MODEL IN ONE PARAGRAPH: one route number (R1, R2...) = one area = ONE bus that runs BOTH ways.
  stops are stored in order College -> Home area.
  trip "from" = College -> Home : uses stops.arrival_time,  starts at routes.departure_time
  trip "to"   = Home -> College : uses stops.to_time (stops in reverse), starts at routes.to_departure_time
Every stop has (approximate) coordinates, so the SIMULATED bus can move along the route on the map.
"""
import os
import sqlite3
from datetime import datetime

from flask import current_app, g
from werkzeug.security import generate_password_hash

TIME_FMT = "%Y-%m-%d %H:%M:%S"

# Demo admin account (documented in README.md). Only the HASH is stored in the DB.
DEMO_ADMIN_USERNAME = "admin"
DEMO_ADMIN_PASSWORD = "Admin@123"

SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

-- One row per route. "id" is the internal key, "route_code" is what people see (R1, R2...).
CREATE TABLE IF NOT EXISTS routes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    route_code        TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    bus_number        TEXT NOT NULL,
    departure_time    TEXT NOT NULL CHECK (departure_time    GLOB '[0-2][0-9]:[0-5][0-9]'),  -- College -> Home
    to_departure_time TEXT NOT NULL CHECK (to_departure_time GLOB '[0-2][0-9]:[0-5][0-9]'),  -- Home -> College
    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

-- Stops in order College (1) -> Home area (last). Two timings per stop, one for each direction.
CREATE TABLE IF NOT EXISTS stops (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id     INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    stop_order   INTEGER NOT NULL CHECK (stop_order >= 1),
    stop_name    TEXT NOT NULL,
    arrival_time TEXT NOT NULL CHECK (arrival_time GLOB '[0-2][0-9]:[0-5][0-9]'),  -- College -> Home trip
    to_time      TEXT NOT NULL CHECK (to_time      GLOB '[0-2][0-9]:[0-5][0-9]'),  -- Home -> College trip
    latitude     REAL CHECK (latitude  IS NULL OR latitude  BETWEEN -90  AND 90),
    longitude    REAL CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180),
    UNIQUE (route_id, stop_order)
);

-- Latest (simulated) position of the bus of each route. NULL coordinates = missing location.
--   auto_update = 1 : the demo simulator keeps moving the bus along its route (status stays Current)
--   auto_update = 0 : the bus is "frozen" (admin set it manually, e.g. to demo Stale / Unavailable)
--   progress        : 0..1 = driving College -> Home, 1..2 = driving back (position = interpolation along the stops)
CREATE TABLE IF NOT EXISTS bus_locations (
    route_id     INTEGER PRIMARY KEY REFERENCES routes(id) ON DELETE CASCADE,
    latitude     REAL CHECK (latitude  IS NULL OR latitude  BETWEEN -90  AND 90),
    longitude    REAL CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180),
    last_updated TEXT,
    is_simulated INTEGER NOT NULL DEFAULT 1,
    auto_update  INTEGER NOT NULL DEFAULT 1 CHECK (auto_update IN (0, 1)),
    progress     REAL NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress < 2),
    is_live      INTEGER NOT NULL DEFAULT 0 CHECK (is_live IN (0, 1)),
    trip_status  TEXT NOT NULL DEFAULT 'Not Started',
    trip_started_at TEXT
);

-- Change history. Each successful admin change adds rows here (shown to students).
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id    INTEGER REFERENCES routes(id) ON DELETE SET NULL,
    route_code  TEXT NOT NULL,
    change_type TEXT NOT NULL,
    description TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    prn TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    mobile TEXT NOT NULL,
    department TEXT NOT NULL,
    year TEXT NOT NULL,
    division TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    route_id INTEGER REFERENCES routes(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_code TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    mobile TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    route_id INTEGER REFERENCES routes(id) ON DELETE SET NULL,
    is_available INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS complaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending',
    admin_response TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bus_passes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL UNIQUE REFERENCES students(id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    valid_until TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS password_reset_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending'
);
"""

# Approximate coordinates of Pune stops (lat, lon); verify them before operating real service.
COLLEGE_GATE = "College Gate - MIT-ADT University"
PLACES = {
    COLLEGE_GATE: (18.4770, 74.0230), "College Gate": (18.4770, 74.0230),
    "Shivajinagar": (18.5308, 73.8475), "University Circle": (18.5525, 73.8236),
    "Aundh": (18.5580, 73.8075), "Baner": (18.5590, 73.7868), "Balewadi": (18.5770, 73.7787),
    "Balewadi High Street": (18.5710, 73.7790), "Wakad": (18.5990, 73.7610), "Hinjawadi Phase 1": (18.5925, 73.7390),
    "Hinjawadi": (18.5810, 73.7280), "Pashan": (18.5416, 73.7900), "Sanewadi": (18.5545, 73.8140),
    "Medipoint": (18.5603, 73.8036), "Law College Road": (18.5167, 73.8310), "Erandwane": (18.5088, 73.8310),
    "Karve Nagar": (18.4935, 73.8205), "Kothrud": (18.5074, 73.8077), "Paud Road": (18.5063, 73.8140),
    "Bhusari Colony": (18.5040, 73.7960), "Deccan": (18.5167, 73.8409), "Pune Station": (18.5286, 73.8744),
    "Camp": (18.5139, 73.8808), "Hadapsar": (18.5089, 73.9259), "Magarpatta": (18.5143, 73.9286),
    "Kharadi": (18.5515, 73.9400), "Kesnand Phata": (18.5750, 73.9700), "Wagholi": (18.5800, 73.9800),
    "Khadki": (18.5645, 73.8394), "Dapodi": (18.5780, 73.8350), "Kasarwadi": (18.6080, 73.8160),
    "Pimpri": (18.6279, 73.7997), "Chinchwad": (18.6425, 73.7945), "Akurdi": (18.6480, 73.7750),
    "Phugewadi": (18.5985, 73.8230), "Bhosari": (18.6420, 73.8440), "Pradhikaran": (18.6525, 73.7790),
    "Nigdi": (18.6580, 73.7700), "Sus Road": (18.5450, 73.7750), "Chandni Chowk": (18.5230, 73.7770),
    "Bavdhan Khurd": (18.5170, 73.7790), "Bavdhan": (18.5120, 73.7830), "Yerwada": (18.5530, 73.8870),
    "Kalyani Nagar": (18.5460, 73.9040), "Viman Nagar": (18.5679, 73.9143), "Nagar Road": (18.5600, 73.9250),
    "EON IT Park": (18.5520, 73.9370), "Ghorpadi": (18.5290, 73.8970), "Fatima Nagar": (18.5190, 73.8990),
    "Mundhwa": (18.5330, 73.9170), "Keshav Nagar": (18.5240, 73.9330), "Koregaon Park": (18.5362, 73.8937),
    "Swargate": (18.5018, 73.8636), "Market Yard": (18.4870, 73.8680), "Dhankawadi": (18.4735, 73.8580),
    "Bibwewadi": (18.4750, 73.8610), "Balaji Nagar": (18.4650, 73.8550), "Katraj": (18.4575, 73.8677),
    "Bharati Vidyapeeth": (18.4570, 73.8560), "Ambegaon": (18.4500, 73.8420), "Narhe": (18.4590, 73.8150),
    "Karve Road": (18.5040, 73.8230), "Warje": (18.4837, 73.8002), "Anand Nagar": (18.4790, 73.8200),
    "Vadgaon Budruk": (18.4700, 73.8230), "Sinhagad Road": (18.4620, 73.8100), "Wanowrie": (18.4950, 73.8970),
    "Salunke Vihar": (18.4880, 73.8920), "NIBM Road": (18.4780, 73.8970), "Kondhwa Khurd": (18.4700, 73.8930),
    "Kondhwa": (18.4650, 73.8930), "Sangvi": (18.5793, 73.8084), "Pimple Gurav": (18.5900, 73.8100),
    "Rahatani": (18.5990, 73.7960), "Kunal Icon Road": (18.5920, 73.7870), "Pimple Saudagar": (18.5983, 73.7967),
    "Pisoli": (18.4620, 73.9100), "Undri": (18.4600, 73.9000), "Sarasbaug": (18.5000, 73.8550),
    "Dandekar Bridge": (18.4960, 73.8420), "Dhayari Phata": (18.4470, 73.8090), "Dhayari": (18.4450, 73.8000),
    "Mahalunge": (18.5650, 73.7570), "Tathawade": (18.6190, 73.7560), "Ravet": (18.6480, 73.7350),
    "Kalas": (18.5750, 73.9000), "Vishrantwadi": (18.5800, 73.8780), "Dighi": (18.6040, 73.8690), "Moshi": (18.6700, 73.8500),
    "Hinjawadi Phase 2": (18.5900, 73.7180), "Hinjawadi Phase 3": (18.5861, 73.6873),
    "Hinjawadi Shivaji Chowk": (18.5890, 73.7350), "Wakad Bridge": (18.6000, 73.7540),
    "Wakad Phata": (18.5990, 73.7630), "Baner Phata": (18.5680, 73.7930),
    "Balewadi Phata": (18.5680, 73.7770), "Bremen Chowk": (18.5600, 73.8070),
    "Parihar Chowk": (18.5580, 73.8130), "Kothrud Depot": (18.5060, 73.8090),
    "Vanaz": (18.5070, 73.7890), "Ideal Colony": (18.5070, 73.8240),
    "Nal Stop": (18.5090, 73.8320), "Paud Phata": (18.5090, 73.8230),
    "Deccan Gymkhana": (18.5167, 73.8409), "BJS College": (18.5810, 73.9820),
    "Wagheshwar Temple": (18.5740, 73.9690), "Ubale Nagar": (18.5630, 73.9680),
    "Kharadi Bypass": (18.5510, 73.9450), "Mundhwa Chowk": (18.5320, 73.9210),
    "Magarpatta City": (18.5143, 73.9286), "Noble Hospital": (18.4950, 73.9330),
    "Chinchwad Station": (18.6290, 73.7990), "Pimpri Chowk": (18.6230, 73.8060),
    "Vallabh Nagar": (18.6160, 73.8130), "Nashik Phata": (18.6090, 73.8200),
    "Bhakti Shakti Chowk": (18.6590, 73.7660), "Hadapsar Gadital": (18.5003, 73.9393),
    "Pashan Circle": (18.5390, 73.8050), "Chandan Nagar": (18.5550, 73.9250),
    "Ramwadi": (18.5620, 73.9210), "Bund Garden": (18.5360, 73.8810),
    "Shewalewadi": (18.4810, 73.9510), "Manjari": (18.4830, 73.9870),
    "Loni Gaon Phata": (18.4850, 74.0120), "Katraj Chowk": (18.4575, 73.8677),
    "Padmavati": (18.4890, 73.8560), "Warje Malwadi": (18.4840, 73.7970),
    "Salunkhe Vihar": (18.4880, 73.8920), "Jagtap Dairy": (18.5920, 73.7880),
    "Navi Sangvi": (18.5770, 73.8220), "Sangvi Phata": (18.5710, 73.8130),
    "Mohammadwadi": (18.4740, 73.9100), "Manik Baug": (18.4660, 73.8200),
    "Ambegaon Budruk": (18.4500, 73.8420), "Navale Bridge": (18.4600, 73.8200),
    "Balewadi Stadium": (18.5670, 73.7680), "Kiwale": (18.6550, 73.7240),
    "Punawale": (18.6270, 73.7480), "Bhumkar Chowk": (18.6120, 73.7510),
    "Dange Chowk": (18.6060, 73.7580),
    "Yerawada": (18.5530, 73.8870),
}

# route_code, name, bus, stops [(place, minutes after leaving College Gate)]
# Stops are stored College -> Home; reverse each user-provided Home -> College list.
ROUTES = [
    ("R1", "Hinjawadi Express", "BUS-101",
     [(COLLEGE_GATE, 0), ("University Circle", 42), ("Baner Phata", 50), ("Wakad Phata", 58), ("Wakad Bridge", 66), ("Hinjawadi Shivaji Chowk", 74), ("Hinjawadi Phase 1", 88), ("Hinjawadi Phase 2", 102), ("Hinjawadi Phase 3", 118)]),
    ("R2", "Baner-Aundh Line", "BUS-102",
     [(COLLEGE_GATE, 0), ("Swargate", 20), ("Shivajinagar", 35), ("University Circle", 48), ("Parihar Chowk", 55), ("Bremen Chowk", 62), ("Aundh", 70), ("Balewadi Phata", 82), ("Baner", 92)]),
    ("R3", "Kothrud-Deccan Line", "BUS-103",
     [(COLLEGE_GATE, 0), ("Market Yard", 18), ("Swargate", 30), ("Deccan Gymkhana", 44), ("Paud Phata", 55), ("Nal Stop", 62), ("Ideal Colony", 70), ("Vanaz", 78), ("Kothrud Depot", 88)]),
    ("R4", "Wagholi Line", "BUS-104",
     [(COLLEGE_GATE, 0), ("Noble Hospital", 12), ("Magarpatta City", 24), ("Mundhwa Chowk", 34), ("Kharadi Bypass", 44), ("Ubale Nagar", 52), ("Wagheshwar Temple", 60), ("Kesnand Phata", 70), ("BJS College", 78)]),
    ("R5", "Pimpri-Chinchwad Line", "BUS-105",
     [(COLLEGE_GATE, 0), ("Khadki", 30), ("Dapodi", 42), ("Phugewadi", 52), ("Kasarwadi", 62), ("Nashik Phata", 72), ("Vallabh Nagar", 80), ("Pimpri Chowk", 90), ("Chinchwad Station", 100)]),
    ("R6", "Nigdi Line", "BUS-106",
     [(COLLEGE_GATE, 0), ("Shivajinagar", 28), ("Khadki", 40), ("Dapodi", 50), ("Pimpri", 58), ("Chinchwad Station", 68), ("Akurdi", 80), ("Bhakti Shakti Chowk", 92), ("Nigdi", 102)]),
    ("R7", "Bavdhan-Pashan Line", "BUS-107",
     [(COLLEGE_GATE, 0), ("Hadapsar Gadital", 14), ("Swargate", 30), ("Deccan Gymkhana", 42), ("University Circle", 55), ("Pashan Circle", 62), ("Pashan", 72), ("Chandni Chowk", 80), ("Bavdhan", 90)]),
    ("R8", "Kharadi-Viman Nagar Line", "BUS-108",
     [(COLLEGE_GATE, 0), ("Hadapsar Gadital", 15), ("Camp", 28), ("Bund Garden", 38), ("Yerawada", 46), ("Ramwadi", 54), ("Viman Nagar", 62), ("Chandan Nagar", 72), ("Kharadi", 82)]),
    ("R9", "Hadapsar-Magarpatta Line", "BUS-109",
     [(COLLEGE_GATE, 0), ("Loni Gaon Phata", 12), ("Manjari", 20), ("Shewalewadi", 28), ("Hadapsar Gadital", 36), ("Noble Hospital", 44), ("Magarpatta City", 50), ("Mundhwa Chowk", 62), ("Keshav Nagar", 74)]),
    ("R10", "Katraj-Swargate Line", "BUS-110",
     [(COLLEGE_GATE, 0), ("Hadapsar Gadital", 14), ("Fatima Nagar", 24), ("Swargate", 34), ("Padmavati", 44), ("Dhankawadi", 54), ("Balaji Nagar", 65), ("Bharati Vidyapeeth", 75), ("Katraj Chowk", 85)]),
    ("R11", "Sinhagad Road-Warje Line", "BUS-111",
     [(COLLEGE_GATE, 0), ("Hadapsar Gadital", 12), ("Swargate", 22), ("Deccan Gymkhana", 32), ("Karve Nagar", 42), ("Warje Malwadi", 52), ("Anand Nagar", 60), ("Vadgaon Budruk", 70), ("Dhayari Phata", 80)]),
    ("R12", "Kondhwa-NIBM Line", "BUS-112",
     [(COLLEGE_GATE, 0), ("Loni Gaon Phata", 10), ("Manjari", 20), ("Hadapsar Gadital", 30), ("Fatima Nagar", 38), ("Wanowrie", 45), ("Salunkhe Vihar", 52), ("NIBM Road", 60), ("Kondhwa Khurd", 70)]),
    ("R13", "Pimple Saudagar-Sangvi Line", "BUS-113",
     [(COLLEGE_GATE, 0), ("Shivajinagar", 30), ("University Circle", 40), ("Aundh", 50), ("Sangvi Phata", 60), ("Navi Sangvi", 70), ("Pimple Gurav", 80), ("Jagtap Dairy", 90), ("Pimple Saudagar", 100)]),
    ("R14", "Undri-Wanowrie Line", "BUS-114",
     [(COLLEGE_GATE, 0), ("Hadapsar Gadital", 10), ("Fatima Nagar", 20), ("Wanowrie", 30), ("Salunkhe Vihar", 38), ("NIBM Road", 47), ("Mohammadwadi", 55), ("Pisoli", 62), ("Undri", 70)]),
    ("R15", "Dhayari-Sinhagad Road Line", "BUS-115",
     [(COLLEGE_GATE, 0), ("Hadapsar Gadital", 15), ("Swargate", 26), ("Dandekar Bridge", 38), ("Manik Baug", 48), ("Anand Nagar", 58), ("Vadgaon Budruk", 68), ("Dhayari Phata", 78), ("Dhayari", 88)]),
    ("R16", "Katraj-Ambegaon Line", "BUS-116",
     [(COLLEGE_GATE, 0), ("Swargate", 18), ("Padmavati", 30), ("Balaji Nagar", 40), ("Dhankawadi", 50), ("Katraj Chowk", 60), ("Navale Bridge", 70), ("Ambegaon Budruk", 80), ("Narhe", 90)]),
    ("R17", "Baner-Balewadi Line", "BUS-117",
     [(COLLEGE_GATE, 0), ("Swargate", 24), ("Shivajinagar", 38), ("University Circle", 52), ("Pashan", 64), ("Baner", 76), ("Balewadi Phata", 88), ("Balewadi Stadium", 100), ("Mahalunge", 112)]),
    ("R18", "Koregaon Park-Magarpatta Line", "BUS-118",
     [(COLLEGE_GATE, 0), ("Noble Hospital", 12), ("Magarpatta City", 24), ("Mundhwa Chowk", 34), ("Ghorpadi", 44), ("Camp", 56), ("Pune Station", 66), ("Bund Garden", 75), ("Koregaon Park", 84)]),
    ("R19", "Ravet-Tathawade Line", "BUS-119",
     [(COLLEGE_GATE, 0), ("Wakad Phata", 25), ("Dange Chowk", 40), ("Bhumkar Chowk", 55), ("Wakad", 65), ("Tathawade", 75), ("Punawale", 85), ("Kiwale", 95), ("Ravet", 108)]),
    ("R20", "Vishrantwadi-Moshi Line", "BUS-120",
     [(COLLEGE_GATE, 0), ("Hadapsar Gadital", 15), ("Yerawada", 30), ("Kalas", 42), ("Vishrantwadi", 52), ("Dapodi", 64), ("Nashik Phata", 76), ("Bhosari", 88), ("Moshi", 100)]),
]
BASIC_ROUTES = 3        # R1-R3 only (used by the automated tests)
COLLEGE_TO_HOME_DEPARTURE = "16:45"
HOME_TO_COLLEGE_ARRIVAL = "08:45"


def _add_minutes(hhmm, minutes):
    total = int(hhmm[:2]) * 60 + int(hhmm[3:]) + minutes
    return f"{total // 60:02d}:{total % 60:02d}"


def connect(path):
    """Open a connection. Rows behave like dictionaries; foreign keys are enforced."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """One connection per web request (stored in Flask's 'g')."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(reset=False):
    """Create tables (if missing) and add demo data (if empty). reset=True wipes everything first."""
    conn = connect(current_app.config["DATABASE"])
    try:
        if reset:
            for table in ("password_reset_requests", "bus_passes", "complaints", "drivers", "students", "bookings", "notifications", "bus_locations", "stops", "routes", "admins"):
                conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(SCHEMA)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(notifications)").fetchall()}
        if "audience" not in columns:
            conn.execute("ALTER TABLE notifications ADD COLUMN audience TEXT NOT NULL DEFAULT 'all'")
        if "audience_route" not in columns:
            conn.execute("ALTER TABLE notifications ADD COLUMN audience_route TEXT")
        route_columns = {row[1] for row in conn.execute("PRAGMA table_info(routes)").fetchall()}
        if "service_status" not in route_columns:
            conn.execute("ALTER TABLE routes ADD COLUMN service_status TEXT NOT NULL DEFAULT 'Active'")
        if "status_reason" not in route_columns:
            conn.execute("ALTER TABLE routes ADD COLUMN status_reason TEXT")
        location_columns = {row[1] for row in conn.execute("PRAGMA table_info(bus_locations)").fetchall()}
        if "is_live" not in location_columns:
            conn.execute("ALTER TABLE bus_locations ADD COLUMN is_live INTEGER NOT NULL DEFAULT 0")
        if "trip_status" not in location_columns:
            conn.execute("ALTER TABLE bus_locations ADD COLUMN trip_status TEXT NOT NULL DEFAULT 'Not Started'")
        if "trip_started_at" not in location_columns:
            conn.execute("ALTER TABLE bus_locations ADD COLUMN trip_started_at TEXT")
        conn.execute(
            "UPDATE stops SET stop_name = ? WHERE lower(stop_name) LIKE 'college gate%'",
            (COLLEGE_GATE,),
        )
        seed(conn, full=current_app.config.get("FULL_SAMPLE", True))
        conn.commit()
    finally:
        conn.close()


def seed(conn, full=True):
    """full=True: 20 routes. full=False: only R1-R3 (used by tests). Every bus starts Current and 'live'."""
    stamp = datetime.now().strftime(TIME_FMT)

    if conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
        conn.execute("INSERT INTO admins (username, password_hash, created_at) VALUES (?, ?, ?)",
                     (DEMO_ADMIN_USERNAME, generate_password_hash(DEMO_ADMIN_PASSWORD), stamp))

    if conn.execute("SELECT COUNT(*) FROM routes").fetchone()[0] != 0:
        return
    for index, (code, name, bus, stops) in enumerate(ROUTES if full else ROUTES[:BASIC_ROUTES]):
        dep_from = COLLEGE_TO_HOME_DEPARTURE
        dep_to = _add_minutes(HOME_TO_COLLEGE_ARRIVAL, -stops[-1][1])
        pk = conn.execute(
            "INSERT INTO routes (route_code, name, bus_number, departure_time, to_departure_time,"
            " is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (code, name, bus, dep_from, dep_to, stamp, stamp)).lastrowid
        total = stops[-1][1]
        points = []
        for order, (place, offset) in enumerate(stops, start=1):
            lat, lon = PLACES[place]
            points.append((lat, lon))
            conn.execute("INSERT INTO stops (route_id, stop_order, stop_name, arrival_time, to_time, latitude, longitude)"
                         " VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (pk, order, place, _add_minutes(dep_from, offset), _add_minutes(dep_to, total - offset), lat, lon))
        # start each bus at a different place along its route so the live map looks natural
        progress = round((index * 0.37) % 2, 3)
        fraction = progress if progress <= 1 else 2 - progress
        position = fraction * (len(points) - 1)
        i = min(int(position), len(points) - 2)
        t = position - i
        lat = points[i][0] + (points[i + 1][0] - points[i][0]) * t
        lon = points[i][1] + (points[i + 1][1] - points[i][1]) * t
        conn.execute("INSERT INTO bus_locations (route_id, latitude, longitude, last_updated, is_simulated, auto_update, progress)"
                     " VALUES (?, ?, ?, ?, 1, 1, ?)", (pk, round(lat, 6), round(lon, 6), stamp, progress))
