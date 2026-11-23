"""
services.py - the "business logic" of the app.

Everything that reads/validates/changes data lives here, so app.py stays small.
Rules used everywhere:
  * Invalid input  -> raise ChangeError("friendly message")  (nothing is saved)
  * Valid input    -> save the change AND its notification(s) inside ONE database
                      transaction ("with conn:"), so they either both happen or neither does.
  * Notifications are only created after a change was validated and saved.

A route has TWO trips on the same bus:
  "from" = College -> Home   (stops in stored order, uses stops.arrival_time, starts routes.departure_time)
  "to"   = Home -> College   (stops reversed,        uses stops.to_time,      starts routes.to_departure_time)
"""
import math
import re
from datetime import date, datetime, timedelta

STALE_AFTER_MINUTES = 5
TIME_FMT = "%Y-%m-%d %H:%M:%S"
SIM_STEP = 0.006                      # how far a simulated bus moves per simulator tick (fraction of the route)
TRIP_LABELS = {"to": "Home → College", "from": "College → Home"}
ROUTE_COLORS = ["#0f8f7e", "#2563eb", "#7c3aed", "#db2777", "#ea580c", "#dc2626", "#16a34a", "#4f46e5"]


class ChangeError(Exception):
    """A problem the user can fix (bad input, not found...). The message is shown on screen."""


# --------------------------------------------------------------------------- time helpers
def now_str():
    return datetime.now().strftime(TIME_FMT)


def parse_dt(value):
    try:
        return datetime.strptime(value, TIME_FMT)
    except (TypeError, ValueError):
        return None


def normalize_time(value):
    """'8:30 AM' / '08:30' / '8:30 pm' -> '08:30' (24h). Returns None if invalid."""
    if value is None:
        return None
    match = re.fullmatch(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", value.strip().upper())
    if not match:
        return None
    hour, minute, suffix = int(match.group(1)), int(match.group(2)), match.group(3)
    if minute > 59:
        return None
    if suffix:
        if not 1 <= hour <= 12:
            return None
        hour = (0 if hour == 12 else hour) + (12 if suffix == "PM" else 0)
    elif hour > 23:
        return None
    return f"{hour:02d}:{minute:02d}"


def pretty_time(hhmm):
    """'08:30' -> '8:30 AM'"""
    if not hhmm:
        return "-"
    hour, minute = int(hhmm[:2]), int(hhmm[3:])
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def to_minutes(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def from_minutes(total):
    return f"{total // 60:02d}:{total % 60:02d}"


def _require_time(value, label):
    if value is None or not value.strip():
        raise ChangeError(f"{label} is missing. Please enter a time such as 08:30.")
    result = normalize_time(value)
    if result is None:
        raise ChangeError(f"{label} '{value.strip()}' is not a valid time. Use a format like 08:30 or 8:30 AM.")
    return result


# --------------------------------------------------------------------------- bus location status
def _get(row, key, default=None):
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def location_status(row, now=None):
    """
    Decide how to show a bus location. Returns a dict with status = 'current' | 'stale' | 'unavailable'.
    Rules: missing coordinates (or timestamp) -> unavailable; older than 5 minutes -> stale; otherwise current.
    """
    now = now or datetime.now()
    info = {    "status": "unavailable", "label": "Unavailable", "message": "Bus location unavailable.",
    "latitude": None, "longitude": None, "last_updated": None, "minutes_old": None,
    "simulated": bool(_get(row, "is_simulated", 1)) if row is not None else True,
            "auto": bool(_get(row, "auto_update", 0)) if row is not None else False,
            "is_live": bool(_get(row, "is_live", 0)) if row is not None else False,
            "trip_status": _get(row, "trip_status", "Not Started") if row is not None else "Not Started",
            "trip_started_at": _get(row, "trip_started_at") if row is not None else None}
    if row is None or row["latitude"] is None or row["longitude"] is None:
        return info
    stamp = parse_dt(row["last_updated"])
    if stamp is None:
        return info                      # we cannot tell how old it is -> do not trust it
    age = now - stamp
    minutes_old = max(int(age.total_seconds() // 60), 0)
    info.update(latitude=row["latitude"], longitude=row["longitude"],
                last_updated=row["last_updated"], minutes_old=minutes_old)
    if age > timedelta(minutes=STALE_AFTER_MINUTES):
        info.update(status="stale", label="Stale",
                    message=f"Warning: this location is {minutes_old} minutes old (older than "
                            f"{STALE_AFTER_MINUTES} minutes). The bus may have moved.")
    else:
        info.update(status="current", label="Current",
                    message="Location was updated within the last 5 minutes.")
    return info


def _interpolate(points, fraction):
    """Point at 'fraction' (0..1) along a list of (lat, lon) points joined by straight lines."""
    position = max(0.0, min(1.0, fraction)) * (len(points) - 1)
    i = min(int(position), len(points) - 2)
    t = position - i
    return (round(points[i][0] + (points[i + 1][0] - points[i][0]) * t, 6),
            round(points[i][1] + (points[i + 1][1] - points[i][1]) * t, 6))


def _fraction(progress):
    """progress 0..1 = driving College -> Home, 1..2 = driving back."""
    return progress if progress <= 1 else 2 - progress


# --------------------------------------------------------------------------- reading routes
def _route_row(conn, code):
    return conn.execute("SELECT * FROM routes WHERE UPPER(route_code) = UPPER(?)",
                        ((code or "").strip(),)).fetchone()


def _require_route(conn, code):
    row = _route_row(conn, code)
    if row is None:
        raise ChangeError(f"Route '{code}' was not found.")
    return row


def _stop_rows(conn, route_pk):
    return conn.execute("SELECT * FROM stops WHERE route_id = ? ORDER BY stop_order", (route_pk,)).fetchall()


def trip_view(route, direction):
    """The trip (one direction) of a route as a simple dict: departure + ordered stops with times."""
    if direction == "from":
        seq = [{"name": s["stop_name"], "time": s["arrival_time"]} for s in route["stops"]]
        departure = route["departure_time"]
    else:
        seq = [{"name": s["stop_name"], "time": s["to_time"]} for s in reversed(route["stops"])]
        departure = route["to_departure_time"]
    return {"direction": direction, "label": TRIP_LABELS[direction], "departure": departure, "stops": seq,
            "start": seq[0]["name"] if seq else "-", "end": seq[-1]["name"] if seq else "-",
            "arrives": seq[-1]["time"] if seq else None}


def _geo_points(stops):
    return [(s["stop_name"], s["latitude"], s["longitude"]) for s in stops if s["latitude"] is not None and s["longitude"] is not None]


def _build_route(conn, row):
    route = dict(row)
    route["stops"] = [dict(s) for s in _stop_rows(conn, row["id"])]
    route["start_point"] = route["stops"][0]["stop_name"] if route["stops"] else "-"
    route["destination"] = route["stops"][-1]["stop_name"] if route["stops"] else "-"
    route["area"] = route["destination"]
    route["geo"] = [{"name": n, "lat": la, "lon": lo} for n, la, lo in _geo_points(route["stops"])]
    loc_row = conn.execute("SELECT * FROM bus_locations WHERE route_id = ?", (row["id"],)).fetchone()
    loc = location_status(loc_row)
    loc["near"], loc["heading"] = None, None
    loc["progress"] = loc_row["progress"] if loc_row is not None else None
    if loc_row is not None and loc["auto"] and loc["status"] == "current" and len(route["geo"]) >= 2:
        progress = loc_row["progress"]
        names = [g["name"] for g in route["geo"]]
        loc["near"] = names[round(_fraction(progress) * (len(names) - 1))]
        loc["heading"] = f"towards {names[-1]}" if progress <= 1 else f"towards {names[0]}"
    route["location"] = loc
    route["trips"] = {"to": trip_view(route, "to"), "from": trip_view(route, "from")}
    digits = re.sub(r"\D", "", row["route_code"])
    number = int(digits) if digits else sum(map(ord, row["route_code"]))
    route["color"] = ROUTE_COLORS[number % len(ROUTE_COLORS)]
    return route


def get_routes(conn, query="", include_inactive=False):
    """List routes. 'query' matches route ID, route name or any stop name."""
    sql = "SELECT DISTINCT r.* FROM routes r LEFT JOIN stops s ON s.route_id = r.id WHERE 1 = 1"
    params = []
    if not include_inactive:
        sql += " AND r.is_active = 1"
    query = (query or "").strip()
    if query:
        sql += " AND (r.route_code LIKE ? OR r.name LIKE ? OR s.stop_name LIKE ?)"
        params += [f"%{query}%"] * 3
    sql += " ORDER BY LENGTH(r.route_code), r.route_code"
    return [_build_route(conn, row) for row in conn.execute(sql, params).fetchall()]


def get_route(conn, code):
    row = _route_row(conn, code)
    return _build_route(conn, row) if row else None


def buses_overview(conn):
    """All active buses with their latest simulated position (used by the live map)."""
    buses = []
    for route in get_routes(conn):
        loc = route["location"]
        buses.append({"route": route["route_code"], "name": route["name"], "bus": route["bus_number"], "color": route["color"],
                      "lat": loc["latitude"], "lon": loc["longitude"], "status": loc["status"], "label": loc["label"],
                      "minutes_old": loc["minutes_old"], "near": loc["near"], "heading": loc["heading"],
                      "last_updated": loc["last_updated"], "is_live": loc["is_live"],
                      "trip_status": loc["trip_status"], "trip_started_at": loc["trip_started_at"]})
    return buses


def verify_admin(conn, username, password):
    from werkzeug.security import check_password_hash
    row = conn.execute("SELECT * FROM admins WHERE username = ?", ((username or "").strip(),)).fetchone()
    if row and check_password_hash(row["password_hash"], password or ""):
        return row
    return None


# --------------------------------------------------------------------------- notifications
CATEGORY_TYPES = {
    "schedule": ["Departure time changed", "Stop timing changed"],
    "stops": ["Stop added", "Stop removed", "Stop renamed", "Stop order changed"],
    "bus": ["Bus changed"],
    "routes": ["New route added", "Route name changed", "Route deactivated", "Route reactivated"],
    "emergency": ["Emergency alert", "Bus Delayed", "Bus Cancelled", "Bus Active"],
}


def _day_label(created_at):
    stamp = parse_dt(created_at)
    if not stamp:
        return ""
    if stamp.date() == date.today():
        return "Today"
    if stamp.date() == date.today() - timedelta(days=1):
        return "Yesterday"
    return f"{stamp.day} {stamp:%b %Y}"


def get_notifications(conn, route_code=None, limit=None, category=None, after_id=None):
    sql, params = "SELECT * FROM notifications WHERE 1 = 1", []
    if route_code:
        sql += " AND UPPER(route_code) = UPPER(?)"
        params.append(route_code)
    if category in CATEGORY_TYPES:
        types = CATEGORY_TYPES[category]
        sql += " AND change_type IN (%s)" % ",".join("?" * len(types))
        params += types
    if after_id is not None:
        sql += " AND id > ?"
        params.append(int(after_id))
    sql += " ORDER BY id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    items = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for item in items:
        item["day_label"] = _day_label(item["created_at"])
    return items


def latest_notification_id(conn):
    return conn.execute("SELECT COALESCE(MAX(id), 0) FROM notifications").fetchone()[0]


def _notify(conn, route_pk, route_code, change_type, description, old, new, reason):
    conn.execute(
        "INSERT INTO notifications (route_id, route_code, change_type, description, old_value,"
        " new_value, reason, created_at, audience, audience_route) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'route', ?)",
        (route_pk, route_code, change_type, description, old, new, reason, now_str(), route_code))


# --------------------------------------------------------------------------- input cleaning
def _clean_reason(value):
    reason = (value or "").strip()
    if len(reason) < 5:
        raise ChangeError("A reason is required for every change (at least 5 characters).")
    if len(reason) > 200:
        raise ChangeError("The reason is too long (maximum 200 characters).")
    return reason


def _clean_route_name(value):
    name = " ".join((value or "").split())
    if not 3 <= len(name) <= 60:
        raise ChangeError("Route name must be between 3 and 60 characters.")
    return name


def _clean_bus(value):
    bus = " ".join((value or "").split()).upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9 -]{1,19}", bus):
        raise ChangeError("Bus number must be 2-20 characters (letters, digits, spaces or hyphens), e.g. BUS-104.")
    return bus


def _clean_stop_name(value):
    name = " ".join((value or "").split())
    if not name:
        raise ChangeError("Stop name is missing.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .'&-]{1,49}", name):
        raise ChangeError("Stop name must be 2-50 characters (letters, digits, spaces and . ' & -).")
    return name


def _parse_coordinate(value, label, low, high):
    text = (value or "").strip()
    try:
        number = float(text)
    except ValueError:
        raise ChangeError(f"{label} must be a number (e.g. 18.5975).")
    if not math.isfinite(number) or not low <= number <= high:
        raise ChangeError(f"{label} must be between {low} and {high}.")
    return number


def _check_stops(stops, dep_from, dep_to):
    """stops = [[name, from_time, to_time, lat, lon], ...] in route order (College first)."""
    if len(stops) < 2:
        raise ChangeError("A route needs at least two stops (College and one more).")
    names = [s[0].lower() for s in stops]
    if len(set(names)) != len(names):
        raise ChangeError("Each stop name must be unique within a route.")
    if to_minutes(stops[0][1]) < to_minutes(dep_from):
        raise ChangeError(f"The first stop ({stops[0][0]}, {pretty_time(stops[0][1])}) cannot be earlier "
                          f"than the College → Home departure ({pretty_time(dep_from)}).")
    for prev, cur in zip(stops, stops[1:]):
        if to_minutes(cur[1]) <= to_minutes(prev[1]):
            raise ChangeError(f"College → Home timings must increase along the route: {cur[0]} ({pretty_time(cur[1])}) "
                              f"must be later than {prev[0]} ({pretty_time(prev[1])}).")
    if to_minutes(stops[-1][2]) < to_minutes(dep_to):
        raise ChangeError(f"The Home → College trip starts at {stops[-1][0]}; its time ({pretty_time(stops[-1][2])}) "
                          f"cannot be earlier than the Home → College departure ({pretty_time(dep_to)}).")
    for prev, cur in zip(stops, stops[1:]):
        if to_minutes(prev[2]) <= to_minutes(cur[2]):
            raise ChangeError(f"Home → College timings must increase towards the college: {prev[0]} ({pretty_time(prev[2])}) "
                              f"must be later than {cur[0]} ({pretty_time(cur[2])}). Check the 'Home → College time' box.")


def _mirror(from_times, dep_to):
    """Home -> College times that mirror the College -> Home journey (same travel durations)."""
    last = to_minutes(from_times[-1])
    result = []
    for t in from_times:
        moved = to_minutes(dep_to) + (last - to_minutes(t))
        if moved > 1439:
            raise ChangeError("The Home → College trip would run past midnight. Choose an earlier departure.")
        result.append(from_minutes(moved))
    return result


def _parse_stops_text(text, dep_from, dep_to):
    """Lines like 'Wakad, 08:20' or 'Wakad, 08:20, 18.599, 73.761' (coordinates optional)."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        raise ChangeError("Enter at least two stops (College and one more), one per line, like: Wakad, 08:20")
    named = []
    for number, line in enumerate(lines, start=1):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) not in (2, 4):
            raise ChangeError(f"Stop line {number} ('{line}') must look like: Stop name, HH:MM  (optionally , latitude, longitude)")
        lat = lon = None
        if len(parts) == 4:
            lat = _parse_coordinate(parts[2], f"Latitude on stop line {number}", -90, 90)
            lon = _parse_coordinate(parts[3], f"Longitude on stop line {number}", -180, 180)
        named.append((_clean_stop_name(parts[0]), _require_time(parts[1], f"Time on stop line {number}"), lat, lon))
    if "college" not in named[0][0].lower():
        raise ChangeError("The first stop must be the college (for example: College Gate, 08:00).")
    to_times = _mirror([t for _n, t, _a, _o in named], dep_to)
    stops = [[n, t, to_t, la, lo] for (n, t, la, lo), to_t in zip(named, to_times)]
    _check_stops(stops, dep_from, dep_to)
    return stops


def _sequence(stops):
    return " → ".join(s[0] for s in stops)


def _touch(conn, route_pk):
    conn.execute("UPDATE routes SET updated_at = ? WHERE id = ?", (now_str(), route_pk))


def _rewrite_stops(conn, route_pk, stops):
    conn.execute("DELETE FROM stops WHERE route_id = ?", (route_pk,))
    for order, (name, from_time, to_time, lat, lon) in enumerate(stops, start=1):
        conn.execute("INSERT INTO stops (route_id, stop_order, stop_name, arrival_time, to_time, latitude, longitude)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?)", (route_pk, order, name, from_time, to_time, lat, lon))


def _stops_as_lists(conn, route_pk):
    return [[r["stop_name"], r["arrival_time"], r["to_time"], r["latitude"], r["longitude"]] for r in _stop_rows(conn, route_pk)]


# --------------------------------------------------------------------------- admin: routes
def create_route(conn, form):
    code = (form.get("route_id") or "").strip().upper()
    if not code:
        raise ChangeError("Route ID is missing. Use something like R21.")
    if not re.fullmatch(r"[A-Z][A-Z0-9]{0,9}", code):
        raise ChangeError("Route ID must start with a letter and contain only letters and digits (max 10), e.g. R21.")
    if _route_row(conn, code):
        raise ChangeError(f"Route ID {code} already exists. Please choose a different route ID.")
    name = _clean_route_name(form.get("name"))
    bus = _clean_bus(form.get("bus_number"))
    dep_from = _require_time(form.get("departure_time"), "Departure time (College → Home)")
    dep_to = _require_time(form.get("to_departure_time"), "Departure time (Home → College)")
    stops = _parse_stops_text(form.get("stops_text"), dep_from, dep_to)
    reason = _clean_reason(form.get("reason"))
    lat = lon = stamp = None                         # starting location of the (simulated) bus
    auto = 0
    if (form.get("latitude") or "").strip() or (form.get("longitude") or "").strip():
        lat = _parse_coordinate(form.get("latitude"), "Latitude", -90, 90)
        lon = _parse_coordinate(form.get("longitude"), "Longitude", -180, 180)
        stamp = now_str()
    elif all(s[3] is not None and s[4] is not None for s in stops):
        lat, lon, stamp, auto = stops[0][3], stops[0][4], now_str(), 1      # live simulation starts at the college
    try:
        with conn:                                   # ONE transaction: route + stops + location + notification
            pk = conn.execute(
                "INSERT INTO routes (route_code, name, bus_number, departure_time, to_departure_time,"
                " is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (code, name, bus, dep_from, dep_to, now_str(), now_str())).lastrowid
            _rewrite_stops(conn, pk, stops)
            conn.execute("INSERT INTO bus_locations (route_id, latitude, longitude, last_updated, is_simulated, auto_update, progress)"
                         " VALUES (?, ?, ?, ?, 1, ?, 0)", (pk, lat, lon, stamp, auto))
            _notify(conn, pk, code, "New route added",
                    f"New route {code} ({name}) was added: {_sequence(stops)}.",
                    None, f"Home → College {pretty_time(dep_to)} · College → Home {pretty_time(dep_from)}", reason)
    except Exception as exc:
        if exc.__class__.__name__ == "IntegrityError":
            raise ChangeError(f"Route ID {code} already exists. Please choose a different route ID.")
        raise
    return f"Route {code} was added successfully."


def update_route_details(conn, code, form):
    route = _require_route(conn, code)
    name = _clean_route_name(form.get("name"))
    bus = _clean_bus(form.get("bus_number"))
    dep_from = _require_time(form.get("departure_time"), "Departure time (College → Home)")
    dep_to = (_require_time(form.get("to_departure_time"), "Departure time (Home → College)")
              if "to_departure_time" in form else route["to_departure_time"])
    reason = _clean_reason(form.get("reason"))
    shift = form.get("shift_stops") == "on"
    stops = _stops_as_lists(conn, route["id"])
    new_stops = [list(s) for s in stops]
    changes = []                                     # (change_type, description, old, new)

    if dep_from != route["departure_time"]:
        delta = to_minutes(dep_from) - to_minutes(route["departure_time"])
        if shift:
            for s in new_stops:
                moved = to_minutes(s[1]) + delta
                if not 0 <= moved <= 1439:
                    raise ChangeError("Shifting would move a stop past midnight. Edit stop times manually instead.")
                s[1] = from_minutes(moved)
            note = f" (all College → Home stop timings moved by {delta:+d} min)"
        else:
            if to_minutes(dep_from) > to_minutes(stops[0][1]):
                raise ChangeError(f"The new departure time cannot be later than the first stop's time "
                                  f"({pretty_time(stops[0][1])}). Tick 'shift all stop timings' or edit the stops first.")
            note = ""
        changes.append(("Departure time changed", f"College → Home departure time changed{note}.",
                        pretty_time(route["departure_time"]), pretty_time(dep_from)))
    if dep_to != route["to_departure_time"]:
        delta = to_minutes(dep_to) - to_minutes(route["to_departure_time"])
        if shift:
            for s in new_stops:
                moved = to_minutes(s[2]) + delta
                if not 0 <= moved <= 1439:
                    raise ChangeError("Shifting would move a stop past midnight. Edit stop times manually instead.")
                s[2] = from_minutes(moved)
            note = f" (all Home → College stop timings moved by {delta:+d} min)"
        else:
            if to_minutes(dep_to) > to_minutes(stops[-1][2]):
                raise ChangeError(f"The new Home → College departure cannot be later than the first stop's time "
                                  f"({pretty_time(stops[-1][2])}). Tick 'shift all stop timings' or edit the stops first.")
            note = ""
        changes.append(("Departure time changed", f"Home → College departure time changed{note}.",
                        pretty_time(route["to_departure_time"]), pretty_time(dep_to)))
    if name != route["name"]:
        changes.append(("Route name changed", "Route name changed.", route["name"], name))
    if bus != route["bus_number"]:
        changes.append(("Bus changed", "Assigned bus changed.", route["bus_number"], bus))
    if not changes:
        raise ChangeError("No changes were made - the values are the same as before.")
    _check_stops(new_stops, dep_from, dep_to)

    with conn:
        conn.execute("UPDATE routes SET name = ?, bus_number = ?, departure_time = ?, to_departure_time = ?,"
                     " updated_at = ? WHERE id = ?", (name, bus, dep_from, dep_to, now_str(), route["id"]))
        if new_stops != stops:
            _rewrite_stops(conn, route["id"], new_stops)
        for change_type, description, old, new in changes:
            _notify(conn, route["id"], route["route_code"], change_type, description, old, new, reason)
    return f"Route {route['route_code']} updated. Students were notified ({len(changes)} notification(s))."


def set_route_active(conn, code, active, form):
    route = _require_route(conn, code)
    reason = _clean_reason(form.get("reason"))
    if bool(route["is_active"]) == active:
        raise ChangeError(f"Route {route['route_code']} is already {'active' if active else 'inactive'}.")
    with conn:
        conn.execute("UPDATE routes SET is_active = ?, updated_at = ? WHERE id = ?",
                     (1 if active else 0, now_str(), route["id"]))
        _notify(conn, route["id"], route["route_code"],
                "Route reactivated" if active else "Route deactivated",
                f"Route {route['route_code']} is now {'running again' if active else 'not running'}.",
                "Inactive" if active else "Active", "Active" if active else "Inactive", reason)
    return f"Route {route['route_code']} {'reactivated' if active else 'deactivated'}."


# --------------------------------------------------------------------------- admin: stops
def add_stop(conn, code, form):
    route = _require_route(conn, code)
    stops = _stops_as_lists(conn, route["id"])
    name = _clean_stop_name(form.get("stop_name"))
    from_time = _require_time(form.get("arrival_time"), "Stop time (College → Home)")
    position_text = (form.get("position") or "").strip()
    try:
        position = int(position_text) if position_text else len(stops) + 1
    except ValueError:
        raise ChangeError("Position must be a whole number.")
    if not 2 <= position <= len(stops) + 1:
        raise ChangeError(f"Position must be between 2 and {len(stops) + 1} (position 1 is the college).")
    if (form.get("to_time") or "").strip():
        to_time = _require_time(form.get("to_time"), "Stop time (Home → College)")
    else:                                            # mirror of the College -> Home journey
        last_from = (from_time if position == len(stops) + 1 else stops[-1][1])
        moved = to_minutes(route["to_departure_time"]) + (to_minutes(last_from) - to_minutes(from_time))
        to_time = from_minutes(min(moved, 1439))
    lat = lon = None
    if (form.get("latitude") or "").strip() or (form.get("longitude") or "").strip():
        lat = _parse_coordinate(form.get("latitude"), "Latitude", -90, 90)
        lon = _parse_coordinate(form.get("longitude"), "Longitude", -180, 180)
    reason = _clean_reason(form.get("reason"))
    new_stops = stops[:position - 1] + [[name, from_time, to_time, lat, lon]] + stops[position - 1:]
    _check_stops(new_stops, route["departure_time"], route["to_departure_time"])
    with conn:
        _rewrite_stops(conn, route["id"], new_stops)
        _touch(conn, route["id"])
        _notify(conn, route["id"], route["route_code"], "Stop added",
                f"Stop '{name}' was added at position {position}.",
                _sequence(stops), _sequence(new_stops), reason)
    return f"Stop '{name}' added to {route['route_code']}."


def update_stop(conn, code, stop_id, form):
    route = _require_route(conn, code)
    rows = _stop_rows(conn, route["id"])
    index = next((i for i, r in enumerate(rows) if r["id"] == stop_id), None)
    if index is None:
        raise ChangeError("That stop no longer exists. Please reload the page.")
    name = _clean_stop_name(form.get("stop_name"))
    from_time = _require_time(form.get("arrival_time"), "Stop time (College → Home)")
    to_text = (form.get("to_time") or "").strip()
    to_time = _require_time(to_text, "Stop time (Home → College)") if to_text else rows[index]["to_time"]
    reason = _clean_reason(form.get("reason"))
    old = rows[index]
    stops = [[r["stop_name"], r["arrival_time"], r["to_time"], r["latitude"], r["longitude"]] for r in rows]
    stops[index][:3] = [name, from_time, to_time]
    changes = []
    if from_time != old["arrival_time"]:
        changes.append(("Stop timing changed", f"Timing for stop '{name}' (College → Home) changed.",
                        pretty_time(old["arrival_time"]), pretty_time(from_time)))
    if to_time != old["to_time"]:
        changes.append(("Stop timing changed", f"Timing for stop '{name}' (Home → College) changed.",
                        pretty_time(old["to_time"]), pretty_time(to_time)))
    if name != old["stop_name"]:
        changes.append(("Stop renamed", "A stop was renamed.", old["stop_name"], name))
    if not changes:
        raise ChangeError("No changes were made - the values are the same as before.")
    _check_stops(stops, route["departure_time"], route["to_departure_time"])
    with conn:
        conn.execute("UPDATE stops SET stop_name = ?, arrival_time = ?, to_time = ? WHERE id = ?",
                     (name, from_time, to_time, stop_id))
        _touch(conn, route["id"])
        for change_type, description, o, n in changes:
            _notify(conn, route["id"], route["route_code"], change_type, description, o, n, reason)
    return f"Stop '{name}' updated. Students were notified."


def move_stop(conn, code, stop_id, direction, form):
    """Reorder: the stop NAME (and its map position) moves; the time slots stay so times stay in order."""
    route = _require_route(conn, code)
    rows = _stop_rows(conn, route["id"])
    index = next((i for i, r in enumerate(rows) if r["id"] == stop_id), None)
    if index is None:
        raise ChangeError("That stop no longer exists. Please reload the page.")
    other = index - 1 if direction == "up" else index + 1 if direction == "down" else None
    if other is None:
        raise ChangeError("Direction must be 'up' or 'down'.")
    if not 0 <= other < len(rows):
        raise ChangeError("That stop is already at the " + ("start" if direction == "up" else "end") + " of the route.")
    reason = _clean_reason(form.get("reason"))
    old_names = [r["stop_name"] for r in rows]
    new_names = list(old_names)
    new_names[index], new_names[other] = new_names[other], new_names[index]
    with conn:
        for i, j in ((index, other), (other, index)):
            conn.execute("UPDATE stops SET stop_name = ?, latitude = ?, longitude = ? WHERE id = ?",
                         (rows[j]["stop_name"], rows[j]["latitude"], rows[j]["longitude"], rows[i]["id"]))
        _touch(conn, route["id"])
        _notify(conn, route["id"], route["route_code"], "Stop order changed",
                f"The order of stops changed ('{old_names[index]}' moved {direction}).",
                " → ".join(old_names), " → ".join(new_names), reason)
    return "Stop order updated."


def delete_stop(conn, code, stop_id, form):
    route = _require_route(conn, code)
    rows = _stop_rows(conn, route["id"])
    target = next((r for r in rows if r["id"] == stop_id), None)
    if target is None:
        raise ChangeError("That stop no longer exists. Please reload the page.")
    if len(rows) <= 2:
        raise ChangeError("A route must keep at least two stops, so this stop cannot be removed.")
    reason = _clean_reason(form.get("reason"))
    old_stops = _stops_as_lists(conn, route["id"])
    new_stops = [s for r, s in zip(rows, old_stops) if r["id"] != stop_id]
    with conn:
        _rewrite_stops(conn, route["id"], new_stops)
        _touch(conn, route["id"])
        _notify(conn, route["id"], route["route_code"], "Stop removed",
                f"Stop '{target['stop_name']}' ({pretty_time(target['arrival_time'])}) was removed from the route.",
                _sequence(old_stops), _sequence(new_stops), reason)
    return f"Stop '{target['stop_name']}' removed."


# --------------------------------------------------------------------------- bus location (SIMULATED)
def _parse_admin_datetime(value):
    text = (value or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ChangeError("Last-updated timestamp is not a valid date and time.")


def _route_points(conn, route_pk):
    return [(la, lo) for _n, la, lo in _geo_points(_stop_rows(conn, route_pk))]


def set_location(conn, code, form):
    """
    Admin control of the SIMULATED bus location. (No notification: only route/stop/timing changes notify.)
    save / make_stale / clear  -> the bus is frozen (auto_update = 0), so you can demo Stale / Unavailable
    refresh                    -> only sets the timestamp to now
    resume                     -> the demo simulator moves the bus again (auto_update = 1)
    """
    route = _require_route(conn, code)
    action = form.get("action", "save")
    current = conn.execute("SELECT * FROM bus_locations WHERE route_id = ?", (route["id"],)).fetchone()
    progress = current["progress"] if current is not None else 0
    auto = current["auto_update"] if current is not None else 0
    if action == "clear":
        lat = lon = stamp = None
        auto = 0
        message = f"Location of {route['route_code']} cleared - students will see 'Bus location unavailable.'"
    elif action in ("refresh", "make_stale"):
        if current is None or current["latitude"] is None or current["longitude"] is None:
            raise ChangeError("This route has no coordinates yet. Enter latitude and longitude first.")
        lat, lon = current["latitude"], current["longitude"]
        if action == "refresh":
            stamp = now_str()
            message = f"Location time of {route['route_code']} set to now (status: Current)."
        else:
            stamp = (datetime.now() - timedelta(minutes=10)).strftime(TIME_FMT)
            auto = 0
            message = f"Location time of {route['route_code']} set to 10 minutes ago (status: Stale). Live simulation paused for this bus."
    elif action == "resume":
        points = _route_points(conn, route["id"])
        if len(points) < 2:
            raise ChangeError("This route needs at least two stops with coordinates for the live simulation.")
        lat, lon = _interpolate(points, _fraction(progress))
        stamp, auto = now_str(), 1
        message = f"Live simulation resumed for {route['route_code']} - the bus is moving again."
    elif action == "save":
        if not (form.get("latitude") or "").strip() and not (form.get("longitude") or "").strip():
            raise ChangeError("Latitude and longitude are missing. Enter both, or use 'Clear location'.")
        lat = _parse_coordinate(form.get("latitude"), "Latitude", -90, 90)
        lon = _parse_coordinate(form.get("longitude"), "Longitude", -180, 180)
        if (form.get("last_updated") or "").strip():
            when = _parse_admin_datetime(form.get("last_updated"))
            if when > datetime.now() + timedelta(minutes=1):
                raise ChangeError("Last-updated time cannot be in the future.")
        else:
            when = datetime.now()
        stamp, auto = when.strftime(TIME_FMT), 0
        message = f"Simulated location of {route['route_code']} saved (live simulation paused for this bus)."
    else:
        raise ChangeError("Unknown location action.")
    with conn:
        conn.execute(
            "INSERT INTO bus_locations (route_id, latitude, longitude, last_updated, is_simulated, auto_update, progress, is_live, trip_status)"
            " VALUES (?, ?, ?, ?, 1, ?, ?, 0, 'Not Started') ON CONFLICT(route_id) DO UPDATE SET latitude = excluded.latitude,"
            " longitude = excluded.longitude, last_updated = excluded.last_updated, auto_update = excluded.auto_update,"
            " is_simulated = 1, is_live = 0, trip_status = CASE WHEN bus_locations.is_live = 1 THEN 'Trip Ended' ELSE 'Not Started' END,"
            " trip_started_at = NULL",
            (route["id"], lat, lon, stamp, auto, progress))
    return message


def update_driver_trip(conn, code, form):
    """Persist a driver's real GPS trip state and latest coordinates."""
    route = _require_route(conn, code)
    action = form.get("action", "")
    current = conn.execute("SELECT * FROM bus_locations WHERE route_id = ?", (route["id"],)).fetchone()

    if action in ("start", "update"):
        if action == "update" and (current is None or not current["is_live"]):
            raise ChangeError("Location sharing is not active. Start a trip before sending updates.")
        lat = _parse_coordinate(form.get("latitude"), "Latitude", -90, 90)
        lon = _parse_coordinate(form.get("longitude"), "Longitude", -180, 180)
        stamp = now_str()
        started = stamp if action == "start" else current["trip_started_at"]
        with conn:
            conn.execute(
                "INSERT INTO bus_locations (route_id, latitude, longitude, last_updated, is_simulated, auto_update, "
                "progress, is_live, trip_status, trip_started_at) VALUES (?, ?, ?, ?, 0, 0, 0, 1, 'In Progress', ?) "
                "ON CONFLICT(route_id) DO UPDATE SET latitude=excluded.latitude, longitude=excluded.longitude, "
                "last_updated=excluded.last_updated, is_simulated=0, auto_update=0, is_live=1, "
                "trip_status='In Progress', trip_started_at=excluded.trip_started_at",
                (route["id"], lat, lon, stamp, started))
        return {"message": "Location sharing is active.", "last_updated": stamp,
                "trip_started_at": started, "latitude": lat, "longitude": lon}

    if action == "stop":
        if current is None:
            raise ChangeError("This bus does not have a recorded location to stop.")
        with conn:
            conn.execute(
                "UPDATE bus_locations SET is_live=0, auto_update=0, trip_status='Trip Ended' WHERE route_id=?",
                (route["id"],))
        return {"message": "Trip ended. Location sharing has stopped.",
                "last_updated": current["last_updated"],
                "trip_started_at": current["trip_started_at"],
                "latitude": current["latitude"], "longitude": current["longitude"]}

    raise ChangeError("Unknown trip action.")


def simulate_step(conn, step=SIM_STEP):
    """
    One tick of the DEMO simulator: every bus with auto_update = 1 moves a little along its route and gets a
    fresh timestamp. Called every few seconds by a background thread in app.py (and by tests).
    """
    rows = conn.execute("SELECT b.route_id, b.progress FROM bus_locations b JOIN routes r ON r.id = b.route_id"
                        " WHERE b.auto_update = 1 AND b.is_live = 0 AND r.is_active = 1").fetchall()
    moved, stamp = 0, now_str()
    with conn:
        for row in rows:
            points = _route_points(conn, row["route_id"])
            if len(points) < 2:
                continue
            progress = (row["progress"] + step) % 2
            lat, lon = _interpolate(points, _fraction(progress))
            conn.execute("UPDATE bus_locations SET latitude = ?, longitude = ?, last_updated = ?, progress = ? WHERE route_id = ?",
                         (lat, lon, stamp, progress, row["route_id"]))
            moved += 1
    return moved


def resume_all_simulation(conn):
    """Admin button: every bus that has stop coordinates goes live again (auto_update = 1, time = now)."""
    stamp, count = now_str(), 0
    with conn:
        for row in conn.execute("SELECT route_id, progress FROM bus_locations WHERE is_live = 0").fetchall():
            points = _route_points(conn, row["route_id"])
            if len(points) < 2:
                continue
            lat, lon = _interpolate(points, _fraction(row["progress"]))
            conn.execute("UPDATE bus_locations SET latitude = ?, longitude = ?, last_updated = ?, auto_update = 1,"
                         " is_simulated = 1, is_live = 0, trip_status = 'Not Started', trip_started_at = NULL"
                         " WHERE route_id = ?", (lat, lon, stamp, row["route_id"]))
            count += 1
    if not count:
        raise ChangeError("No route has stop coordinates for the live simulation.")
    return f"Live simulation resumed for {count} buses - all are Current again."
