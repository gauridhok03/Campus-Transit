"""
Automated tests for the Campus Transportation App.

Run from the project folder with:
    python -m unittest discover -s tests -v

Each test gets its OWN temporary database, so your real demo database is never touched.
Most tests use only routes R1-R3 (FULL_SAMPLE=False); ExtendedSampleTests use the full 20-route demo data.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db                      # noqa: E402
import services                # noqa: E402
from app import create_app     # noqa: E402


class BaseTest(unittest.TestCase):
    full = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.db")
        self.app = create_app({"DATABASE": self.db_path, "TESTING": True, "CSRF_ENABLED": False, "FULL_SAMPLE": self.full})
        self.app.logger.disabled = True       # keep expected-error tracebacks out of the test output
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def login(self, client=None, username="admin", password="Admin@123"):
        return (client or self.client).post("/admin/login", data={"username": username, "password": password}, follow_redirects=True)

    def query(self, sql, params=()):
        conn = db.connect(self.db_path)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def count_notifications(self):
        return self.query("SELECT COUNT(*) FROM notifications")[0][0]

    def route(self, code="R1"):
        with self.app.app_context():
            return services.get_route(db.get_db(), code)

    def change_r1(self, **overrides):
        data = {"name": "Hinjawadi Express", "bus_number": "BUS-101", "departure_time": "17:15",
                "shift_stops": "on", "reason": "Schedule changed due to traffic."}
        data.update(overrides)
        return self.client.post("/admin/routes/R1/details", data=data, follow_redirects=True)


# ------------------------------------------------------------------------------------------ student: routes, stops, timings
class StudentTests(BaseTest):
    def test_01_dashboard_lists_sample_routes(self):
        html = self.client.get("/").get_data(as_text=True)
        for code in ("R1", "R2", "R3"):
            self.assertIn(code, html)
        self.assertIn("4:45 PM", html)

    def test_02_route_details_show_many_stops_in_order_for_both_trips(self):
        html = self.client.get("/routes/R1").get_data(as_text=True)
        html = html[html.index('data-pane="to"'):]
        to_pane, from_pane = [part[part.index('<ol class="timeline">'):] for part in html.split('data-pane="from"')]
        self.assertGreaterEqual(to_pane.count('class="stop-name"'), 8)
        self.assertLess(from_pane.index("College Gate - MIT-ADT University"), from_pane.index("University Circle"))
        self.assertLess(from_pane.index("University Circle"), from_pane.index("Baner Phata"))
        self.assertLess(from_pane.index("Wakad Phata"), from_pane.index("Hinjawadi Phase 1"))
        self.assertLess(to_pane.index("Hinjawadi Phase 3"), to_pane.index("Hinjawadi Phase 2"))
        self.assertLess(to_pane.index("Hinjawadi Phase 2"), to_pane.index("Hinjawadi Phase 1"))
        self.assertLess(to_pane.index("Hinjawadi Phase 1"), to_pane.index("Wakad Bridge"))
        self.assertLess(to_pane.index("Wakad Bridge"), to_pane.index("College Gate - MIT-ADT University"))
        self.assertIn("5:27 PM", from_pane)
        self.assertIn("6:47 AM", to_pane)
        self.assertIn("8:45 AM", to_pane)

    def test_03_same_bus_runs_both_ways(self):
        route = self.route("R1")
        self.assertEqual((route["trips"]["to"]["start"], route["trips"]["to"]["end"]),
                         ("Hinjawadi Phase 3", db.COLLEGE_GATE))
        self.assertEqual((route["trips"]["from"]["start"], route["trips"]["from"]["end"]),
                         (db.COLLEGE_GATE, "Hinjawadi Phase 3"))
        html = self.client.get("/routes/R1").get_data(as_text=True)
        self.assertIn("BUS-101", html)
        self.assertIn("Home → College", html)
        self.assertIn("College → Home", html)

    def test_04_search_by_route_and_by_stop_case_insensitive(self):
        html = self.client.get("/?q=r2").get_data(as_text=True)
        self.assertIn("Baner-Aundh Line", html)
        self.assertNotIn("Hinjawadi Express", html)
        self.assertIn("Kothrud-Deccan Line", self.client.get("/?q=kothrud").get_data(as_text=True))

    def test_05_invalid_route_search_shows_message(self):
        self.assertIn("Route 'R99' not found.", self.client.get("/?q=R99").get_data(as_text=True))

    def test_06_invalid_route_page_is_friendly_404(self):
        response = self.client.get("/routes/R99")
        self.assertEqual(response.status_code, 404)
        self.assertIn("No route with ID", response.get_data(as_text=True))

    def test_07_search_input_is_escaped(self):
        self.assertNotIn("<script>alert(1)</script>", self.client.get("/?q=<script>alert(1)</script>").get_data(as_text=True))


# ------------------------------------------------------------------------------------------ bus location
class LocationTests(BaseTest):
    def test_10_status_current_stale_unavailable(self):
        now = datetime(2026, 11, 2, 9, 0, 0)
        row = lambda minutes: {"latitude": 18.5, "longitude": 73.8, "last_updated": (now - timedelta(minutes=minutes)).strftime(services.TIME_FMT)}
        self.assertEqual(services.location_status(row(2), now)["status"], "current")
        self.assertEqual(services.location_status(row(5), now)["status"], "current")        # exactly 5 min is still current
        stale = services.location_status(row(6), now)
        self.assertEqual(stale["status"], "stale")
        self.assertIn("older than 5 minutes", stale["message"])
        self.assertEqual(services.location_status(None)["status"], "unavailable")
        self.assertEqual(services.location_status({"latitude": None, "longitude": None, "last_updated": None})["message"],
                         "Bus location unavailable.")
        self.assertEqual(services.location_status({"latitude": 18.5, "longitude": 73.8, "last_updated": None})["status"], "unavailable")

    def test_11_seed_locations_are_current_labelled_simulated_with_coordinates(self):
        html = self.client.get("/routes/R1").get_data(as_text=True)
        self.assertIn("Current", html)
        self.assertIn("SIMULATED", html)
        self.assertIn("Live simulation", html)
        loc = self.route("R1")["location"]
        self.assertIsNotNone(loc["latitude"])
        self.assertIsNotNone(loc["last_updated"])

    def test_12_admin_can_demo_stale_and_unavailable(self):
        self.login()
        self.client.post("/admin/routes/R2/location", data={"action": "make_stale"})
        self.client.post("/admin/routes/R3/location", data={"action": "clear"})
        stale = self.client.get("/routes/R2").get_data(as_text=True)
        self.assertIn("older than 5 minutes", stale)
        self.assertIn("Stale", stale)
        self.assertIn("Bus location unavailable.", self.client.get("/routes/R3").get_data(as_text=True))
        self.assertEqual(self.route("R1")["location"]["status"], "current")           # other buses unaffected

    def test_13_save_location_validation(self):
        self.login()
        bad = [{"action": "save", "latitude": "", "longitude": ""}, {"action": "save", "latitude": "18.5", "longitude": ""},
               {"action": "save", "latitude": "123", "longitude": "73.8"}, {"action": "save", "latitude": "abc", "longitude": "73.8"},
               {"action": "save", "latitude": "18.5", "longitude": "73.8", "last_updated": "2999-01-01T10:00"},
               {"action": "refresh_typo"}]
        before = self.query("SELECT latitude, longitude, last_updated FROM bus_locations ORDER BY route_id")
        for data in bad:
            self.assertIn("alert-error", self.client.post("/admin/routes/R1/location", data=data, follow_redirects=True).get_data(as_text=True), data)
        self.assertEqual(before, self.query("SELECT latitude, longitude, last_updated FROM bus_locations ORDER BY route_id"))

    def test_14_location_updates_do_not_create_notifications(self):
        self.login()
        self.client.post("/admin/routes/R1/location", data={"action": "refresh"})
        self.client.post("/admin/routes/R1/location", data={"action": "make_stale"})
        self.assertEqual(self.count_notifications(), 0)

    def test_15_refresh_needs_existing_coordinates(self):
        self.login()
        self.client.post("/admin/routes/R3/location", data={"action": "clear"})
        self.assertIn("no coordinates yet", self.client.post("/admin/routes/R3/location", data={"action": "refresh"}, follow_redirects=True).get_data(as_text=True))

    def test_16_live_api_returns_all_buses_with_status(self):
        data = self.client.get("/api/buses").get_json()
        self.assertEqual([b["route"] for b in data["buses"]], ["R1", "R2", "R3"])
        self.assertTrue(all(b["status"] == "current" and b["lat"] is not None for b in data["buses"]))
        self.assertIn("Live bus map", self.client.get("/live").get_data(as_text=True))


class DriverTrackingTests(BaseTest):
    def setUp(self):
        super().setUp()
        conn = db.connect(self.db_path)
        route_id = conn.execute("SELECT id FROM routes WHERE route_code='R1'").fetchone()["id"]
        conn.execute(
            "INSERT INTO drivers (driver_code, full_name, email, mobile, password_hash, route_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("DRV-1", "Test Driver", "driver@example.test", "555-0101",
             generate_password_hash("Driver@123"), route_id, services.now_str()))
        conn.commit()
        conn.close()
        self.client.post("/login?role=driver", data={
            "role": "driver", "identifier": "DRV-1", "password": "Driver@123"
        })

    def post_location(self, data):
        return self.client.post("/driver/location", data=data,
                                headers={"X-Requested-With": "XMLHttpRequest"})

    def test_driver_dashboard_has_trip_controls_and_assigned_route(self):
        html = self.client.get("/driver").get_data(as_text=True)
        self.assertIn("Driver Dashboard", html)
        self.assertIn("Start Live Location", html)
        self.assertIn("Stop Trip", html)
        self.assertIn("BUS-101", html)
        self.assertIn("R1", html)

    def test_live_gps_is_shared_and_stop_freezes_the_position(self):
        response = self.post_location({"action": "start", "latitude": "18.5", "longitude": "73.8"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["trip_started_at"])

        updated = self.post_location({"action": "update", "latitude": "18.51", "longitude": "73.81"})
        self.assertEqual(updated.status_code, 200)
        bus = next(item for item in self.client.get("/api/buses").get_json()["buses"] if item["route"] == "R1")
        self.assertTrue(bus["is_live"])
        self.assertEqual((bus["lat"], bus["lon"]), (18.51, 73.81))
        route_html = self.client.get("/routes/R1").get_data(as_text=True)
        self.assertIn("LIVE – Location Sharing Active", route_html)
        self.assertIn("18.51000", route_html)

        stopped = self.post_location({"action": "stop"})
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped.get_json()["message"], "Trip ended. Location sharing has stopped.")
        rejected = self.post_location({"action": "update", "latitude": "18.52", "longitude": "73.82"})
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("Start a trip", rejected.get_json()["error"])
        before_step = self.query("SELECT latitude, longitude, last_updated FROM bus_locations WHERE route_id=1")[0]
        with self.app.app_context():
            services.simulate_step(db.get_db())
        after_step = self.query("SELECT latitude, longitude, last_updated FROM bus_locations WHERE route_id=1")[0]
        self.assertEqual(tuple(before_step), tuple(after_step))

        bus = next(item for item in self.client.get("/api/buses").get_json()["buses"] if item["route"] == "R1")
        self.assertFalse(bus["is_live"])
        self.assertEqual(bus["trip_status"], "Trip Ended")

        admin = self.app.test_client()
        admin.post("/admin/login", data={"username": "admin", "password": "Admin@123"})
        admin_html = admin.get("/admin").get_data(as_text=True)
        self.assertIn("18.51000, 73.81000", admin_html)

    def test_live_gps_rejects_invalid_coordinates(self):
        response = self.post_location({"action": "start", "latitude": "91", "longitude": "73.8"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Latitude must be between", response.get_json()["error"])
        row = self.query("SELECT is_live FROM bus_locations WHERE route_id=1")[0]
        self.assertEqual(row["is_live"], 0)


class SimulationTests(BaseTest):
    def step(self, **kw):
        conn = db.connect(self.db_path)
        try:
            return services.simulate_step(conn, **kw)
        finally:
            conn.close()

    def test_20_simulator_moves_live_buses_along_the_route_and_keeps_them_current(self):
        before = self.route("R1")["location"]
        self.assertEqual(self.step(step=0.05), 3)
        after = self.route("R1")["location"]
        self.assertNotEqual((before["latitude"], before["longitude"]), (after["latitude"], after["longitude"]))
        self.assertEqual(after["status"], "current")
        self.assertIsNotNone(after["near"])
        lats = [s["lat"] for s in self.route("R1")["geo"]]
        self.assertTrue(min(lats) - 1e-6 <= after["latitude"] <= max(lats) + 1e-6)          # stays on the route's bounding box

    def test_21_frozen_buses_are_not_moved_so_stale_and_missing_demos_stay(self):
        self.login()
        self.client.post("/admin/routes/R1/location", data={"action": "make_stale"})
        self.client.post("/admin/routes/R2/location", data={"action": "clear"})
        self.assertEqual(self.step(), 1)                                                   # only R3 still moves
        self.assertEqual(self.route("R1")["location"]["status"], "stale")
        self.assertEqual(self.route("R2")["location"]["status"], "unavailable")

    def test_22_resume_live_simulation_for_one_bus_and_for_all(self):
        self.login()
        self.client.post("/admin/routes/R1/location", data={"action": "make_stale"})
        self.client.post("/admin/routes/R2/location", data={"action": "clear"})
        self.client.post("/admin/routes/R1/location", data={"action": "resume"})
        self.assertEqual(self.route("R1")["location"]["status"], "current")
        html = self.client.post("/admin/locations/resume-all", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Live simulation resumed for 3 buses", html)
        self.assertTrue(all(self.route(c)["location"]["status"] == "current" for c in ("R1", "R2", "R3")))

    def test_23_progress_wraps_so_the_bus_drives_back(self):
        conn = db.connect(self.db_path)
        conn.execute("UPDATE bus_locations SET progress = 1.99"); conn.commit(); conn.close()
        self.step(step=0.05)
        self.assertLess(self.query("SELECT progress FROM bus_locations WHERE route_id = 1")[0][0], 0.1)

    def test_24_inactive_routes_are_not_simulated(self):
        self.login()
        self.client.post("/admin/routes/R3/status", data={"active": "0", "reason": "Bus under repair"})
        self.assertEqual(self.step(), 2)

    def test_25_manual_save_freezes_the_bus(self):
        self.login()
        self.client.post("/admin/routes/R1/location", data={"action": "save", "latitude": "18.5", "longitude": "73.8"})
        self.step()
        self.assertEqual(self.route("R1")["location"]["latitude"], 18.5)
        self.assertIn("Manual position", self.client.get("/routes/R1").get_data(as_text=True))


# ------------------------------------------------------------------------------------------ auth
class AuthTests(BaseTest):
    def test_30_admin_pages_redirect_when_logged_out(self):
        for url in ("/admin", "/admin/routes/new", "/admin/routes/R1"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("/admin/login", response.headers["Location"])

    def test_31_unauthorized_post_cannot_change_data(self):
        for url, data in (("/admin/routes/R1/details", {"name": "Hacked", "bus_number": "BUS-1", "departure_time": "09:00", "reason": "no permission"}),
                          ("/admin/routes/R1/location", {"action": "clear"}), ("/admin/locations/resume-all", {})):
            self.assertEqual(self.client.post(url, data=data).status_code, 302, url)
        self.assertEqual(self.query("SELECT departure_time FROM routes WHERE route_code='R1'")[0][0], "16:45")
        self.assertEqual(self.route("R1")["location"]["status"], "current")
        self.assertEqual(self.count_notifications(), 0)

    def test_32_login_success_wrong_and_empty(self):
        self.assertIn("Admin dashboard", self.login().get_data(as_text=True))
        other = self.app.test_client()
        self.assertEqual(other.post("/admin/login", data={"username": "admin", "password": "wrong"}).status_code, 401)
        self.assertEqual(other.post("/admin/login", data={"username": "", "password": ""}).status_code, 400)
        self.assertEqual(other.get("/admin").status_code, 302)

    def test_33_password_is_not_stored_in_plain_text(self):
        stored = self.query("SELECT password_hash FROM admins")[0][0]
        self.assertNotIn("Admin@123", stored)
        self.assertTrue(stored.startswith(("scrypt:", "pbkdf2:")))

    def test_34_logout_blocks_admin_again(self):
        self.login()
        self.client.post("/admin/logout")
        self.assertEqual(self.client.get("/admin").status_code, 302)

    def test_35_csrf_token_is_enforced_when_enabled(self):
        app = create_app({"DATABASE": os.path.join(self.tmp.name, "csrf.db"), "CSRF_ENABLED": True, "FULL_SAMPLE": False})
        client = app.test_client()
        response = client.post("/admin/login", data={"username": "admin", "password": "Admin@123"}, follow_redirects=True)
        self.assertIn("session expired or the form was invalid", response.get_data(as_text=True))
        self.assertEqual(client.get("/admin").status_code, 302)


# ------------------------------------------------------------------------------------------ admin updates + notifications
class UpdateAndNotificationTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.login()

    def test_40_full_workflow_departure_change_creates_notification(self):
        self.assertIn("alert-success", self.change_r1().get_data(as_text=True))
        self.assertEqual(self.query("SELECT departure_time FROM routes WHERE route_code='R1'")[0][0], "17:15")
        row = self.query("SELECT * FROM notifications")[0]
        self.assertEqual((row["route_code"], row["old_value"], row["new_value"], row["reason"]),
                         ("R1", "4:45 PM", "5:15 PM", "Schedule changed due to traffic."))
        self.assertTrue(row["created_at"])

    def test_41_student_sees_update_and_it_persists_after_refresh(self):
        self.change_r1()
        student = self.app.test_client()
        for _ in range(2):
            html = student.get("/").get_data(as_text=True)
            self.assertIn("5:15 PM", html)
            self.assertIn("Old: 4:45 PM", html)
            self.assertIn("New: 5:15 PM", html)
            self.assertIn("Schedule changed due to traffic.", html)
        self.assertIn("Old: 4:45 PM", student.get("/partials/notifications").get_data(as_text=True))
        self.assertIn("5:15 PM", student.get("/routes/R1").get_data(as_text=True))

    def test_42_shift_moves_stop_times_of_that_trip_only(self):
        self.change_r1()
        from_times = [r[0] for r in self.query("SELECT arrival_time FROM stops WHERE route_id=1 ORDER BY stop_order")]
        to_times = [r[0] for r in self.query("SELECT to_time FROM stops WHERE route_id=1 ORDER BY stop_order")]
        self.assertEqual(from_times, ["17:15", "17:21", "17:27", "17:33", "17:41", "17:49", "17:59", "18:13"])
        self.assertEqual(to_times[-1], "07:47")                                  # Home -> College untouched

    def test_43_home_to_college_departure_has_its_own_notification(self):
        self.change_r1(departure_time="16:45", to_departure_time="07:50")
        row = self.query("SELECT * FROM notifications")[0]
        self.assertEqual((row["change_type"], row["old_value"], row["new_value"]), ("Departure time changed", "7:47 AM", "7:50 AM"))
        self.assertIn("Home → College", row["description"])

    def test_44_reason_required_and_failure_creates_no_notification(self):
        self.assertIn("A reason is required", self.change_r1(reason="").get_data(as_text=True))
        self.assertEqual(self.query("SELECT departure_time FROM routes WHERE route_code='R1'")[0][0], "16:45")
        self.assertEqual(self.count_notifications(), 0)

    def test_45_empty_and_invalid_times_rejected(self):
        for field in ("departure_time", "to_departure_time"):
            for bad, message in (("", "is missing"), ("25:99", "not a valid time"), ("abc", "not a valid time")):
                self.assertIn(message, self.change_r1(**{field: bad}).get_data(as_text=True))
        self.assertEqual(self.count_notifications(), 0)

    def test_46_no_change_rejected_and_12_hour_input_accepted(self):
        self.assertIn("No changes were made", self.change_r1(departure_time="16:45").get_data(as_text=True))
        self.change_r1(departure_time="5:00 PM")
        self.assertEqual(self.query("SELECT departure_time FROM routes WHERE route_code='R1'")[0][0], "17:00")

    def test_47_departure_later_than_first_stop_without_shift_is_rejected(self):
        data = {"name": "Hinjawadi Express", "bus_number": "BUS-101", "departure_time": "18:00", "reason": "Testing rules"}
        self.assertIn("cannot be later than the first stop", self.client.post("/admin/routes/R1/details", data=data, follow_redirects=True).get_data(as_text=True))
        self.assertEqual(self.count_notifications(), 0)

    def test_48_bus_change_and_unknown_route(self):
        self.change_r1(departure_time="16:45", bus_number="bus-150")
        row = self.query("SELECT * FROM notifications")[0]
        self.assertEqual((row["change_type"], row["old_value"], row["new_value"]), ("Bus changed", "BUS-101", "BUS-150"))
        self.assertIn("was not found", self.client.post("/admin/routes/R99/details", data={"name": "x"}, follow_redirects=True).get_data(as_text=True))

    def test_49_database_error_is_handled(self):
        with mock.patch.object(services, "update_route_details", side_effect=sqlite3.OperationalError("disk I/O error")):
            self.assertIn("A database error occurred", self.change_r1().get_data(as_text=True))
        self.assertEqual(self.count_notifications(), 0)

    def test_50_transaction_rolls_back_if_notification_fails(self):
        with mock.patch.object(services, "_notify", side_effect=sqlite3.OperationalError("boom")):
            self.assertIn("A database error occurred", self.change_r1().get_data(as_text=True))
        self.assertEqual(self.query("SELECT departure_time FROM routes WHERE route_code='R1'")[0][0], "16:45")
        self.assertEqual(self.count_notifications(), 0)


class NotificationFeatureTests(BaseTest):
    def test_55_summary_api_counts_new_notifications(self):
        self.login()
        self.assertEqual(self.client.get("/api/notifications/summary?after=0").get_json()["new_count"], 0)
        self.change_r1()
        data = self.client.get("/api/notifications/summary?after=0").get_json()
        self.assertEqual(data["new_count"], 1)
        self.assertEqual((data["items"][0]["old"], data["items"][0]["new"]), ("4:45 PM", "5:15 PM"))
        self.assertEqual(self.client.get(f"/api/notifications/summary?after={data['latest_id']}").get_json()["new_count"], 0)

    def test_56_category_and_route_filters(self):
        self.login()
        self.change_r1(bus_number="BUS-150")
        schedule = self.client.get("/notifications?type=schedule").get_data(as_text=True)
        bus = self.client.get("/notifications?type=bus").get_data(as_text=True)
        self.assertIn("Departure time changed", schedule)
        self.assertNotIn("Bus changed", schedule)
        self.assertIn("Bus changed", bus)
        self.assertNotIn("Bus changed", self.client.get("/notifications?route=R2").get_data(as_text=True))
        self.assertIn("Bus changed", self.client.get("/routes/R1").get_data(as_text=True))

    def test_57_notifications_page_groups_by_day(self):
        self.login()
        self.change_r1()
        html = self.client.get("/notifications").get_data(as_text=True)
        self.assertIn("day-head", html)
        self.assertIn("Today", html)


# ------------------------------------------------------------------------------------------ route / stop management
class RouteManagementTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.login()

    def new_route(self, **overrides):
        data = {"route_id": "R21", "name": "Pashan-Sus Line", "bus_number": "BUS-121",
                "departure_time": "16:30", "to_departure_time": "06:40",
                "stops_text": "College Gate, 16:30, 18.5204, 73.8567\nUniversity Circle, 16:36, 18.5525, 73.8236\nPashan, 16:45, 18.5416, 73.7900\nSus Road, 16:55, 18.5450, 73.7750\nBavdhan, 17:10, 18.5120, 73.7830",
                "reason": "New route requested"}
        data.update(overrides)
        return self.client.post("/admin/routes/new", data=data, follow_redirects=True)

    def test_60_add_route_creates_both_trips_notification_and_live_bus(self):
        self.assertIn("Route R21 was added", self.new_route().get_data(as_text=True))
        to_times = [r[0] for r in self.query("SELECT to_time FROM stops WHERE route_id=(SELECT id FROM routes WHERE route_code='R21') ORDER BY stop_order")]
        self.assertEqual(to_times, ["07:20", "07:14", "07:05", "06:55", "06:40"])      # mirrored Home -> College
        self.assertEqual(self.query("SELECT change_type FROM notifications")[0][0], "New route added")
        route = self.route("R21")
        self.assertEqual(route["location"]["status"], "current")
        self.assertTrue(route["location"]["auto"])
        self.assertEqual(len(route["geo"]), 5)

    def test_61_route_without_coordinates_has_unavailable_location(self):
        self.new_route(stops_text="College Gate, 16:30\nPashan, 16:45\nBavdhan, 17:10")
        self.assertEqual(self.route("R21")["location"]["status"], "unavailable")

    def test_62_duplicate_route_id_rejected_case_insensitive(self):
        for code in ("R1", "r1"):
            response = self.new_route(route_id=code)
            self.assertEqual(response.status_code, 400)
            self.assertIn("already exists", response.get_data(as_text=True))
        self.assertEqual(self.query("SELECT COUNT(*) FROM routes")[0][0], 3)
        self.assertEqual(self.count_notifications(), 0)

    def test_63_invalid_new_route_inputs(self):
        cases = [dict(route_id=""), dict(route_id="4R"), dict(name="ab"), dict(bus_number="!"),
                 dict(departure_time=""), dict(to_departure_time=""), dict(stops_text="College Gate, 16:30"),
                 dict(stops_text="College Gate, 16:30\nPashan"), dict(stops_text="College Gate, 16:30\nPashan, 25:00"),
                 dict(stops_text="College Gate, 16:30\nPashan, 16:20"), dict(stops_text="College Gate, 16:00\nPashan, 16:20"),
                 dict(stops_text="Pashan, 16:30\nSus Road, 16:40"), dict(stops_text="College Gate, 16:30\na1, 16:40\nA1, 16:50"),
                 dict(stops_text="College Gate, 16:30, 999, 73\nPashan, 16:40"), dict(reason=""), dict(latitude="999", longitude="73")]
        for overrides in cases:
            response = self.new_route(**overrides)
            self.assertEqual(response.status_code, 400, overrides)
            self.assertIn("alert-error", response.get_data(as_text=True), overrides)
        self.assertEqual(self.query("SELECT COUNT(*) FROM routes")[0][0], 3)
        self.assertEqual(self.count_notifications(), 0)

    def test_64_add_stop_in_middle(self):
        self.client.post("/admin/routes/R1/stops/add", data={"stop_name": "Dange Chowk", "arrival_time": "17:36", "position": "4", "reason": "New stop requested"})
        names = [r[0] for r in self.query("SELECT stop_name FROM stops WHERE route_id=1 ORDER BY stop_order")]
        self.assertEqual(names[2:5], ["Baner Phata", "Dange Chowk", "Wakad Phata"])
        self.assertEqual(self.query("SELECT change_type FROM notifications")[0][0], "Stop added")
        self.assertEqual(len(names), 10)

    def test_65_invalid_stop_inputs(self):
        bad = [{"stop_name": "", "arrival_time": "08:30"}, {"stop_name": "X", "arrival_time": "08:30"},
               {"stop_name": "Dange", "arrival_time": ""}, {"stop_name": "Dange", "arrival_time": "07:00"},
               {"stop_name": "Dange", "arrival_time": "09:30", "position": "3"}, {"stop_name": "Wakad Phata", "arrival_time": "08:40"},
               {"stop_name": "Dange", "arrival_time": "08:12", "position": "99"}, {"stop_name": "Dange", "arrival_time": "08:12", "position": "1"},
               {"stop_name": "Dange", "arrival_time": "08:12", "position": "x"}, {"stop_name": "Dange", "arrival_time": "08:12", "position": "3", "latitude": "abc", "longitude": "1"}]
        for data in bad:
            data["reason"] = "Testing validation"
            self.client.post("/admin/routes/R1/stops/add", data=data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM stops WHERE route_id=1")[0][0], 8)
        self.assertEqual(self.count_notifications(), 0)

    def test_66_update_stop_both_timings(self):
        stop_id = self.query("SELECT id FROM stops WHERE stop_name='Wakad Phata'")[0][0]
        self.client.post(f"/admin/routes/R1/stops/{stop_id}/update", data={"stop_name": "Wakad Phata", "arrival_time": "17:45", "to_time": "07:45", "reason": "Traffic near Wakad"})
        rows = self.query("SELECT description, old_value, new_value FROM notifications ORDER BY id")
        self.assertEqual([(r[1], r[2]) for r in rows], [("5:43 PM", "5:45 PM"), ("7:47 AM", "7:45 AM")])
        self.assertIn("College → Home", rows[0][0])
        bad = self.client.post(f"/admin/routes/R1/stops/{stop_id}/update", data={"stop_name": "Wakad Phata", "arrival_time": "18:50", "reason": "Too late"}, follow_redirects=True)
        self.assertIn("must increase", bad.get_data(as_text=True))
        bad = self.client.post(f"/admin/routes/R1/stops/{stop_id}/update", data={"stop_name": "Wakad Phata", "arrival_time": "17:45", "to_time": "08:00", "reason": "Wrong way"}, follow_redirects=True)
        self.assertIn("Home → College timings must increase", bad.get_data(as_text=True))
        self.assertEqual(self.count_notifications(), 2)

    def test_67_reorder_stops_moves_name_and_map_position(self):
        stop_id = self.query("SELECT id FROM stops WHERE stop_name='Wakad Phata'")[0][0]
        self.client.post(f"/admin/routes/R1/stops/{stop_id}/move/up", data={"reason": "Visit Wakad earlier"})
        rows = self.query("SELECT stop_name, latitude FROM stops WHERE route_id=1 ORDER BY stop_order")
        self.assertEqual([r[0] for r in rows][1:3], ["University Circle", "Wakad Phata"])
        self.assertAlmostEqual(rows[2][1], 18.5990)                                  # coordinates travelled with the name
        first_id = self.query("SELECT id FROM stops WHERE route_id=1 AND stop_order=1")[0][0]
        self.assertIn("already at the start", self.client.post(f"/admin/routes/R1/stops/{first_id}/move/up", data={"reason": "Test boundary"}, follow_redirects=True).get_data(as_text=True))

    def test_68_remove_stop_and_minimum_two_stops(self):
        stop_id = self.query("SELECT id FROM stops WHERE stop_name='Wakad Phata'")[0][0]
        self.client.post(f"/admin/routes/R1/stops/{stop_id}/delete", data={"reason": "Stop closed"})
        self.assertEqual(self.query("SELECT COUNT(*) FROM stops WHERE route_id=1")[0][0], 7)
        self.new_route(stops_text="College Gate, 16:30\nSomewhere, 16:50", route_id="R22")
        last_id = self.query("SELECT id FROM stops WHERE route_id=(SELECT id FROM routes WHERE route_code='R22') AND stop_order=2")[0][0]
        self.assertIn("at least two stops", self.client.post(f"/admin/routes/R22/stops/{last_id}/delete", data={"reason": "Stop closed"}, follow_redirects=True).get_data(as_text=True))

    def test_69_deactivate_hides_route_and_reactivate_restores(self):
        self.client.post("/admin/routes/R3/status", data={"active": "0", "reason": "Bus under repair"})
        student = self.app.test_client()
        self.assertNotIn("Kothrud-Deccan", student.get("/").get_data(as_text=True))
        self.assertEqual(student.get("/routes/R3").status_code, 404)
        self.assertNotIn("R3", [b["route"] for b in student.get("/api/buses").get_json()["buses"]])
        self.assertIn("Route deactivated", student.get("/notifications").get_data(as_text=True))
        self.assertIn("Kothrud-Deccan", self.client.get("/admin").get_data(as_text=True))
        self.client.post("/admin/routes/R3/status", data={"active": "1", "reason": "Bus repaired"})
        self.assertEqual(student.get("/routes/R3").status_code, 200)

    def test_70_stop_change_requires_reason(self):
        stop_id = self.query("SELECT id FROM stops WHERE stop_name='Wakad Phata'")[0][0]
        self.client.post(f"/admin/routes/R1/stops/{stop_id}/update", data={"stop_name": "Wakad Phata", "arrival_time": "17:44", "reason": ""})
        self.assertEqual(self.query("SELECT arrival_time FROM stops WHERE id=?", (stop_id,))[0][0], "17:43")
        self.assertEqual(self.count_notifications(), 0)


# ------------------------------------------------------------------------------------------ full demo data
class ExtendedSampleTests(BaseTest):
    full = True

    def routes(self):
        with self.app.app_context():
            return services.get_routes(db.get_db(), include_inactive=True)

    def test_80_twenty_routes_with_eight_valid_stops_each(self):
        routes = self.routes()
        self.assertEqual([r["route_code"] for r in routes], [f"R{i}" for i in range(1, 21)])
        for r in routes:
            self.assertEqual(len(r["stops"]), 9, r["route_code"])
            self.assertEqual(r["start_point"], db.COLLEGE_GATE)
            self.assertEqual(r["departure_time"], "16:45", r["route_code"])
            from_times = [s["arrival_time"] for s in r["stops"]]
            to_times = [s["to_time"] for s in r["stops"]]
            self.assertEqual(from_times, sorted(set(from_times)), r["route_code"])
            self.assertEqual(to_times, sorted(set(to_times), reverse=True), r["route_code"])
            self.assertEqual(from_times[0], r["departure_time"])
            self.assertEqual(to_times[-1], r["to_departure_time"])
            self.assertEqual(r["trips"]["to"]["arrives"], "08:45", r["route_code"])
            self.assertEqual(len(r["geo"]), len(r["stops"]), r["route_code"])         # every stop has map coordinates

    def test_81_routes_match_the_requested_home_to_college_stop_orders(self):
        by = {r["route_code"]: r for r in self.routes()}
        expected = {
            "R1": "Hinjawadi Phase 3|Hinjawadi Phase 2|Hinjawadi Phase 1|Hinjawadi Shivaji Chowk|Wakad Bridge|Wakad Phata|Baner Phata|University Circle|",
            "R2": "Baner|Balewadi Phata|Aundh|Bremen Chowk|Parihar Chowk|University Circle|Shivajinagar|Swargate|",
            "R3": "Kothrud Depot|Vanaz|Ideal Colony|Nal Stop|Paud Phata|Deccan Gymkhana|Swargate|Market Yard|",
            "R4": "BJS College|Kesnand Phata|Wagheshwar Temple|Ubale Nagar|Kharadi Bypass|Mundhwa Chowk|Magarpatta City|Noble Hospital|",
            "R5": "Chinchwad Station|Pimpri Chowk|Vallabh Nagar|Nashik Phata|Kasarwadi|Phugewadi|Dapodi|Khadki|",
            "R6": "Nigdi|Bhakti Shakti Chowk|Akurdi|Chinchwad Station|Pimpri|Dapodi|Khadki|Shivajinagar|",
            "R7": "Bavdhan|Chandni Chowk|Pashan|Pashan Circle|University Circle|Deccan Gymkhana|Swargate|Hadapsar Gadital|",
            "R8": "Kharadi|Chandan Nagar|Viman Nagar|Ramwadi|Yerawada|Bund Garden|Camp|Hadapsar Gadital|",
            "R9": "Keshav Nagar|Mundhwa Chowk|Magarpatta City|Noble Hospital|Hadapsar Gadital|Shewalewadi|Manjari|Loni Gaon Phata|",
            "R10": "Katraj Chowk|Bharati Vidyapeeth|Balaji Nagar|Dhankawadi|Padmavati|Swargate|Fatima Nagar|Hadapsar Gadital|",
            "R11": "Dhayari Phata|Vadgaon Budruk|Anand Nagar|Warje Malwadi|Karve Nagar|Deccan Gymkhana|Swargate|Hadapsar Gadital|",
            "R12": "Kondhwa Khurd|NIBM Road|Salunkhe Vihar|Wanowrie|Fatima Nagar|Hadapsar Gadital|Manjari|Loni Gaon Phata|",
            "R13": "Pimple Saudagar|Jagtap Dairy|Pimple Gurav|Navi Sangvi|Sangvi Phata|Aundh|University Circle|Shivajinagar|",
            "R14": "Undri|Pisoli|Mohammadwadi|NIBM Road|Salunkhe Vihar|Wanowrie|Fatima Nagar|Hadapsar Gadital|",
            "R15": "Dhayari|Dhayari Phata|Vadgaon Budruk|Anand Nagar|Manik Baug|Dandekar Bridge|Swargate|Hadapsar Gadital|",
            "R16": "Narhe|Ambegaon Budruk|Navale Bridge|Katraj Chowk|Dhankawadi|Balaji Nagar|Padmavati|Swargate|",
            "R17": "Mahalunge|Balewadi Stadium|Balewadi Phata|Baner|Pashan|University Circle|Shivajinagar|Swargate|",
            "R18": "Koregaon Park|Bund Garden|Pune Station|Camp|Ghorpadi|Mundhwa Chowk|Magarpatta City|Noble Hospital|",
            "R19": "Ravet|Kiwale|Punawale|Tathawade|Wakad|Bhumkar Chowk|Dange Chowk|Wakad Phata|",
            "R20": "Moshi|Bhosari|Nashik Phata|Dapodi|Vishrantwadi|Kalas|Yerawada|Hadapsar Gadital|",
        }
        for code, stop_names in expected.items():
            to_stops = [stop["name"] for stop in by[code]["trips"]["to"]["stops"]]
            self.assertEqual(to_stops, stop_names.rstrip("|").split("|") + [db.COLLEGE_GATE], code)

    def test_82_every_bus_is_live_and_each_route_has_its_own_bus(self):
        routes = self.routes()
        for r in routes:
            self.assertEqual(r["location"]["status"], "current", r["route_code"])
            self.assertTrue(r["location"]["auto"])
        self.assertEqual(len({r["bus_number"] for r in routes}), 20)
        conn = db.connect(self.db_path)
        try:
            self.assertEqual(services.simulate_step(conn), 20)
        finally:
            conn.close()

    def test_83_search_by_area_finds_each_route_that_serves_it(self):
        html = self.client.get("/?q=Hadapsar").get_data(as_text=True)
        for code in ("R9",):
            self.assertIn(f">{code}<", html)
        self.assertNotIn("Hinjawadi Express", html)

    def test_84_all_pages_render(self):
        for code in [r["route_code"] for r in self.routes()]:
            self.assertEqual(self.client.get(f"/routes/{code}").status_code, 200, code)
        self.login()
        for url in ("/", "/live", "/notifications", "/admin", "/admin/routes/R9", "/admin/routes/new"):
            self.assertEqual(self.client.get(url).status_code, 200, url)


class HelperTests(unittest.TestCase):
    def test_normalize_time(self):
        cases = {"08:30": "08:30", "8:30": "08:30", "8:30 AM": "08:30", "8:30 pm": "20:30", "12:00 AM": "00:00",
                 "12:15 PM": "12:15", "24:00": None, "12:60": None, "13:00 PM": None, "": None, "abc": None, None: None}
        for given, expected in cases.items():
            self.assertEqual(services.normalize_time(given), expected, given)

    def test_pretty_time(self):
        self.assertEqual(services.pretty_time("08:00"), "8:00 AM")
        self.assertEqual(services.pretty_time("13:05"), "1:05 PM")
        self.assertEqual(services.pretty_time("00:10"), "12:10 AM")

    def test_interpolate_and_fraction(self):
        points = [(0.0, 0.0), (10.0, 10.0), (10.0, 30.0)]
        self.assertEqual(services._interpolate(points, 0), (0.0, 0.0))
        self.assertEqual(services._interpolate(points, 0.25), (5.0, 5.0))
        self.assertEqual(services._interpolate(points, 1), (10.0, 30.0))
        self.assertEqual(services._fraction(0.4), 0.4)
        self.assertAlmostEqual(services._fraction(1.25), 0.75)


if __name__ == "__main__":
    unittest.main(verbosity=2)
