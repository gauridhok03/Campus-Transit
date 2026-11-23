"""
app.py - the Flask web application (URLs / "routes" and page rendering).

Run it with:   python app.py      then open   http://127.0.0.1:5000
"""
import hmac
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

from flask import (Flask, current_app, flash, jsonify, redirect, render_template, request,
                   session, url_for)

import db
import services
from services import ChangeError

POPULAR_AREAS = ["Wagholi", "Hadapsar", "Kharadi", "Baner", "Wakad", "Kothrud", "Katraj", "Pimpri"]
SIM_INTERVAL_SECONDS = 6


def create_app(test_config=None, init=True):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "demo-secret-key-change-me"),
        DATABASE=os.path.join(app.root_path, "database", "campus_transport.db"),
        CSRF_ENABLED=True,
        FULL_SAMPLE=True,
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(db.close_db)
    if init:
        with app.app_context():
            db.init_db()          # creates the database + demo data on the first run

    # ------------------------------------------------------------------ template helpers
    def pretty_dt(value):
        stamp = services.parse_dt(value)
        if not stamp:
            return "-"
        return f"{stamp.day} {stamp:%b %Y}, {stamp.hour % 12 or 12}:{stamp:%M} {'AM' if stamp.hour < 12 else 'PM'}"

    def time_ago(value):
        stamp = services.parse_dt(value)
        if not stamp:
            return ""
        seconds = int((datetime.now() - stamp).total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{seconds // 60} min ago"
        if seconds < 86400:
            return f"{seconds // 3600} h ago"
        return f"{seconds // 86400} days ago"

    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    app.jinja_env.filters.update(pretty_time=services.pretty_time, pretty_dt=pretty_dt, time_ago=time_ago)
    app.jinja_env.globals.update(csrf_token=csrf_token, trip_labels=services.TRIP_LABELS)

    # ------------------------------------------------------------------ security / cache
    @app.before_request
    def check_csrf():
        """Every POST form must carry the secret token (protects against forged requests)."""
        if request.method == "POST" and current_app.config["CSRF_ENABLED"]:
            sent = request.form.get("csrf_token", "")
            expected = session.get("_csrf", "")
            if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
                flash("Your session expired or the form was invalid. Please try again.", "error")
                return redirect(url_for("admin_login") if request.path.startswith("/admin") else url_for("student_dashboard"))

    @app.after_request
    def no_cache(response):
        if not request.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("admin_id"):
                flash("Please log in as admin to access that page.", "error")
                return redirect(url_for("admin_login"))
            return view(*args, **kwargs)
        return wrapped

    def student_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("student_id"):
                flash("Please log in as a student to access that page.", "error")
                return redirect(url_for("user_login", role="student"))
            return view(*args, **kwargs)
        return wrapped

    def driver_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("driver_id"):
                flash("Please log in as a driver to access that page.", "error")
                return redirect(url_for("user_login", role="driver"))
            return view(*args, **kwargs)
        return wrapped

    def create_notification(conn, route_code, change_type, description, reason, audience="all"):
        route = conn.execute("SELECT id FROM routes WHERE route_code = ?", (route_code or "",)).fetchone()
        with conn:
            conn.execute(
                "INSERT INTO notifications (route_id, route_code, change_type, description, old_value, new_value, reason, created_at, audience, audience_route) "
                "VALUES (?, ?, ?, ?, '', '', ?, ?, ?, ?)",
                (route["id"] if route else None, route_code or "ALL", change_type, description,
                 reason, datetime.now().strftime(services.TIME_FMT), "route" if audience == "route" else "all",
                 route_code if audience == "route" else None))

    def for_current_student(items):
        if not session.get("student_id"):
            return items
        student = db.get_db().execute("SELECT r.route_code FROM students s LEFT JOIN routes r ON r.id=s.route_id WHERE s.id=?",
                                      (session["student_id"],)).fetchone()
        assigned = student["route_code"] if student else None
        return [n for n in items if not n.get("audience_route") or n.get("audience_route") == assigned]

    def run_change(action, back_url, *args):
        """Run an admin change safely: show success / error messages, never crash."""
        try:
            flash(action(db.get_db(), *args), "success")
        except ChangeError as error:
            flash(str(error), "error")
        except sqlite3.Error:
            current_app.logger.exception("Database error during change")
            flash("A database error occurred. Nothing was saved - please try again.", "error")
        return redirect(back_url)

    def error_page(code, title, message):
        return render_template("error.html", code=code, title=title, message=message), code

    # ================================================================== STUDENT PAGES
    @app.route("/")
    def student_dashboard():
        # First-time visitors see the role selection portal. Authenticated users
        # are sent to the workspace that matches their account role.
        if session.get("admin_id"):
            return redirect(url_for("admin_dashboard"))
        if session.get("driver_id"):
            return redirect(url_for("driver_dashboard"))
        if not session.get("student_id"):
            return render_template("auth_portal.html", unauthenticated_portal=True)
        query = request.args.get("q", "").strip()[:30]
        conn = db.get_db()
        everything = services.get_routes(conn)
        stats = {"routes": len(everything),
                 "stops": len({s["stop_name"] for r in everything for s in r["stops"]}),
                 "live": sum(1 for r in everything if r["location"]["status"] == "current")}
        current_student = conn.execute("SELECT * FROM students WHERE id = ?", (session.get("student_id"),)).fetchone() if session.get("student_id") else None
        current_student = dict(current_student) if current_student else None
        notifs = services.get_notifications(conn, limit=5)
        if current_student and current_student.get("route_id"):
            assigned = conn.execute("SELECT route_code FROM routes WHERE id = ?", (current_student["route_id"],)).fetchone()
            assigned_code = assigned["route_code"] if assigned else None
            notifs = [n for n in notifs if not n.get("audience_route") or n.get("audience_route") == assigned_code]
        return render_template("student_dashboard.html", q=query, stats=stats, popular=POPULAR_AREAS,
                               routes=services.get_routes(conn, query), student=current_student,
                               notifications=notifs)

    @app.route("/routes/<route_id>")
    def route_details(route_id):
        conn = db.get_db()
        route = services.get_route(conn, route_id)
        if route is None:
            return error_page(404, "Route not found",
                              f"No route with ID '{route_id[:20]}' exists. Try R1, R2 or R3.")
        if not route["is_active"]:
            alternatives = []
            stop_names = [s["stop_name"].lower() for s in route["stops"]]
            for candidate in services.get_routes(conn):
                if candidate["route_code"] != route["route_code"]:
                    overlap = [s["stop_name"] for s in candidate["stops"] if s["stop_name"].lower() in stop_names]
                    if overlap:
                        alternatives.append({"route": candidate, "overlap": overlap})
            return render_template("route_cancelled.html", route=route, alternatives=alternatives)
        route_notifs = services.get_notifications(conn, route["route_code"], 20)
        eta_minutes = max(1, round(20 * (1 - (route["location"].get("progress", 0) % 1)))) if route["location"]["status"] == "current" else None
        assigned_driver = conn.execute("SELECT full_name, driver_code, mobile, is_available FROM drivers WHERE route_id=? ORDER BY id LIMIT 1",
                                       (route["id"],)).fetchone()
        selected_route = False
        if session.get("student_id"):
            selected = conn.execute("SELECT route_id FROM students WHERE id=?", (session["student_id"],)).fetchone()
            selected_route = bool(selected and selected["route_id"] == route["id"])
        return render_template("route_details.html", route=route, eta_minutes=eta_minutes,
                               driver=assigned_driver, notifications=route_notifs,
                               selected_route=selected_route)

    @app.route("/routes/<route_code>/select", methods=["POST"])
    @student_required
    def select_student_route(route_code):
        conn = db.get_db()
        route = conn.execute("SELECT id, route_code, is_active FROM routes WHERE route_code=?", (route_code.upper(),)).fetchone()
        if not route or not route["is_active"]:
            flash("That route is unavailable. Please choose an active route.", "error")
            return redirect(url_for("student_dashboard"))
        conn.execute("UPDATE students SET route_id=? WHERE id=?", (route["id"], session["student_id"]))
        conn.commit()
        flash(f"Route {route['route_code']} has been added to your student profile.", "success")
        return redirect(url_for("route_details", route_id=route["route_code"]))

    @app.route("/live")
    def live_map():
        return render_template("live_map.html", buses=services.buses_overview(db.get_db()))

    @app.route("/api/buses")
    def api_buses():
        """JSON used by the live map: latest simulated position + status of every bus."""
        return jsonify(buses=services.buses_overview(db.get_db()))

    # ---- notifications -------------------------------------------------------------------------
    @app.route("/notifications")
    def notifications_page():
        route_filter = request.args.get("route", "").strip()[:10]
        category = request.args.get("type", "")
        category = category if category in services.CATEGORY_TYPES else ""
        conn = db.get_db()
        return render_template("notifications.html", route_filter=route_filter, category=category,
                               routes=services.get_routes(conn, include_inactive=True),
                               notifications=for_current_student(services.get_notifications(conn, route_filter or None, 100, category or None)),
                               latest_id=services.latest_notification_id(conn))

    @app.route("/api/notifications/summary")
    def notifications_summary():
        """Tiny JSON used by the bell icon and the pop-up alerts."""
        conn = db.get_db()
        after = request.args.get("after", type=int)
        latest = services.latest_notification_id(conn)
        new_items = for_current_student(services.get_notifications(conn, after_id=after, limit=50)) if after is not None else []
        return jsonify(latest_id=latest, new_count=len(new_items),
                       items=[{"id": n["id"], "route": n["route_code"], "type": n["change_type"],
                               "text": n["description"], "old": n["old_value"], "new": n["new_value"]}
                              for n in new_items[:3]])

    # ---- small HTML fragments used by JavaScript polling (auto-refresh without reloading) ----
    @app.route("/partials/routes")
    def partial_routes():
        query = request.args.get("q", "").strip()[:30]
        return render_template("_route_cards.html", q=query, routes=services.get_routes(db.get_db(), query))

    @app.route("/partials/notifications")
    def partial_notifications():
        route_code = request.args.get("route", "").strip()[:10]
        category = request.args.get("type", "")
        limit = min(max(request.args.get("limit", 5, type=int), 1), 100)
        return render_template("_notification_list.html", grouped=request.args.get("grouped") == "1",
                               notifications=for_current_student(services.get_notifications(db.get_db(), route_code or None, limit,
                                                                        category if category in services.CATEGORY_TYPES else None)))

    NOTICE = '<div class="alert alert-warning">This route is no longer available.</div>'

    def _active_route(route_id):
        route = services.get_route(db.get_db(), route_id)
        return route if route and route["is_active"] else None

    @app.route("/partials/route/<route_id>/info")
    def partial_route_info(route_id):
        route = _active_route(route_id)
        return render_template("_route_info.html", route=route) if route else NOTICE

    @app.route("/partials/route/<route_id>/location")
    def partial_route_location(route_id):
        route = _active_route(route_id)
        return render_template("_location_card.html", route=route) if route else NOTICE

    # ================================================================== ADMIN PAGES
    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if session.get("admin_id"):
            return redirect(url_for("admin_dashboard"))
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            if not username.strip() or not password:
                flash("Please enter both username and password.", "error")
                return render_template("admin_login.html", username=username), 400
            admin = services.verify_admin(db.get_db(), username, password)
            if admin is None:
                flash("Invalid username or password.", "error")
                return render_template("admin_login.html", username=username), 401
            session.clear()
            if request.form.get("remember_me"):
                session.permanent = True
            session["admin_id"], session["admin_name"] = admin["id"], admin["username"]
            flash(f"Welcome, {admin['username']}!", "success")
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html", username="")

    @app.route("/admin/logout", methods=["POST"])
    def admin_logout():
        session.pop("admin_id", None)
        session.pop("admin_name", None)
        flash("You have been logged out.", "success")
        return redirect(url_for("admin_login"))

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        conn = db.get_db()
        routes = services.get_routes(conn, include_inactive=True)
        stats = {"active": sum(1 for r in routes if r["is_active"]),
                 "inactive": sum(1 for r in routes if not r["is_active"]),
                 "live": sum(1 for r in routes if r["is_active"] and r["location"]["status"] == "current"),
                 "stale": sum(1 for r in routes if r["is_active"] and r["location"]["status"] == "stale"),
                 "unavailable": sum(1 for r in routes if r["is_active"] and r["location"]["status"] == "unavailable"),
                 "notifications": len(services.get_notifications(conn)),
                 "students": conn.execute("SELECT COUNT(*) FROM students").fetchone()[0],
                 "drivers": conn.execute("SELECT COUNT(*) FROM drivers").fetchone()[0],
                 "complaints": conn.execute("SELECT COUNT(*) FROM complaints WHERE status != 'Resolved'").fetchone()[0],
                 "buses": conn.execute("SELECT COUNT(*) FROM routes").fetchone()[0],
                 "cancelled": conn.execute("SELECT COUNT(*) FROM routes WHERE is_active=0").fetchone()[0]}
        return render_template("admin_dashboard.html", routes=routes, stats=stats,
                               notifications=services.get_notifications(conn, limit=6))

    @app.route("/admin/routes/new", methods=["GET", "POST"])
    @admin_required
    def admin_route_new():
        if request.method == "POST":
            try:
                message = services.create_route(db.get_db(), request.form)
                flash(message, "success")
                return redirect(url_for("admin_dashboard"))
            except ChangeError as error:
                flash(str(error), "error")
            except sqlite3.Error:
                current_app.logger.exception("Database error while creating route")
                flash("A database error occurred. The route was not saved.", "error")
            return render_template("admin_route_form.html", form=request.form), 400
        return render_template("admin_route_form.html", form={})

    @app.route("/admin/routes/<route_id>")
    @admin_required
    def admin_route_edit(route_id):
        route = services.get_route(db.get_db(), route_id)
        if route is None:
            flash(f"Route '{route_id[:20]}' was not found.", "error")
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_route_edit.html", route=route)

    def back(route_id):
        return url_for("admin_route_edit", route_id=route_id)

    @app.route("/admin/routes/<route_id>/details", methods=["POST"])
    @admin_required
    def admin_route_details(route_id):
        return run_change(services.update_route_details, back(route_id), route_id, request.form)

    @app.route("/admin/routes/<route_id>/status", methods=["POST"])
    @admin_required
    def admin_route_status(route_id):
        active = request.form.get("active") == "1"
        return run_change(services.set_route_active, back(route_id), route_id, active, request.form)

    @app.route("/admin/routes/<route_id>/stops/add", methods=["POST"])
    @admin_required
    def admin_stop_add(route_id):
        return run_change(services.add_stop, back(route_id), route_id, request.form)

    @app.route("/admin/routes/<route_id>/stops/<int:stop_id>/update", methods=["POST"])
    @admin_required
    def admin_stop_update(route_id, stop_id):
        return run_change(services.update_stop, back(route_id), route_id, stop_id, request.form)

    @app.route("/admin/routes/<route_id>/stops/<int:stop_id>/move/<direction>", methods=["POST"])
    @admin_required
    def admin_stop_move(route_id, stop_id, direction):
        return run_change(services.move_stop, back(route_id), route_id, stop_id, direction, request.form)

    @app.route("/admin/routes/<route_id>/stops/<int:stop_id>/delete", methods=["POST"])
    @admin_required
    def admin_stop_delete(route_id, stop_id):
        return run_change(services.delete_stop, back(route_id), route_id, stop_id, request.form)

    @app.route("/admin/locations/resume-all", methods=["POST"])
    @admin_required
    def admin_resume_all():
        return run_change(services.resume_all_simulation, url_for("admin_dashboard"))

    @app.route("/admin/routes/<route_id>/location", methods=["POST"])
    @admin_required
    def admin_location(route_id):
        target = request.form.get("next") or back(route_id)
        if not target.startswith("/admin"):
            target = back(route_id)
        return run_change(services.set_location, target, route_id, request.form)


    # ================================================================== STUDENT / DRIVER ACCOUNTS
    @app.route("/register", methods=["GET", "POST"])
    def student_register():
        if request.method == "POST":
            form = request.form
            full_name = " ".join(form.get("full_name", "").split())
            prn = form.get("prn", "").strip().upper()
            email = form.get("email", "").strip().lower()
            mobile = form.get("mobile", "").strip()
            department = form.get("department", "").strip()
            year = form.get("year", "").strip()
            division = form.get("division", "").strip()
            password = form.get("password", "")
            confirm = form.get("confirm_password", "")
            route_code = form.get("route_code", "").strip().upper()
            route = db.get_db().execute("SELECT id FROM routes WHERE route_code = ? AND is_active = 1", (route_code,)).fetchone() if route_code else None
            if not all([full_name, prn, email, mobile, department, year, division, password]):
                flash("Please complete all required fields.", "error")
            elif "@" not in email or len(password) < 8 or password != confirm:
                flash("Enter a valid email, use at least 8 password characters and make sure passwords match.", "error")
            elif route_code and not route:
                flash("Please select a valid active bus route.", "error")
            else:
                try:
                    conn = db.get_db()
                    stamp = datetime.now().strftime(services.TIME_FMT)
                    cur = conn.execute(
                        "INSERT INTO students (full_name, prn, email, mobile, department, year, division, password_hash, route_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (full_name, prn, email, mobile, department, year, division, generate_password_hash(password), route["id"] if route else None, stamp))
                    student_id = cur.lastrowid
                    token = secrets.token_urlsafe(32)
                    valid_until = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
                    conn.execute("INSERT INTO bus_passes (student_id, token, valid_until, created_at) VALUES (?, ?, ?, ?)",
                                 (student_id, token, valid_until, stamp))
                    conn.commit()
                    flash("Registration successful. Please log in.", "success")
                    return redirect(url_for("user_login", role="student"))
                except sqlite3.IntegrityError:
                    flash("That PRN or email is already registered.", "error")
            return render_template("register.html", form=form, routes=services.get_routes(db.get_db()))
        return render_template("register.html", form={}, routes=services.get_routes(db.get_db()))

    @app.route("/login", methods=["GET", "POST"])
    def user_login():
        role = request.args.get("role", request.form.get("role", "student")).lower()
        if role not in ("student", "driver"):
            role = "student"
        if request.method == "POST":
            identifier = request.form.get("identifier", "").strip()
            password = request.form.get("password", "")
            table = "students" if role == "student" else "drivers"
            row = db.get_db().execute(f"SELECT * FROM {table} WHERE email = ? OR " +
                                      ("prn = ?" if role == "student" else "driver_code = ?"),
                                      (identifier.lower(), identifier.upper())).fetchone()
            if row and check_password_hash(row["password_hash"], password) and (role != "driver" or row["is_available"]):
                session.clear()
                if request.form.get("remember_me"):
                    session.permanent = True
                if role == "student":
                    session["student_id"] = row["id"]
                    session["student_name"] = row["full_name"]
                else:
                    session["driver_id"] = row["id"]
                    session["driver_name"] = row["full_name"]
                flash(f"Welcome, {row['full_name']}!", "success")
                return redirect(url_for("student_dashboard" if role == "student" else "driver_dashboard"))
            flash("Invalid login details. Please try again.", "error")
        return render_template("user_login.html", role=role)

    @app.route("/logout", methods=["POST"])
    def user_logout():
        session.pop("student_id", None); session.pop("student_name", None)
        session.pop("driver_id", None); session.pop("driver_name", None)
        flash("You have been logged out.", "success")
        return redirect(url_for("student_dashboard"))

    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            if email:
                db.get_db().execute("INSERT INTO password_reset_requests (email, created_at) VALUES (?, ?)",
                                    (email, datetime.now().strftime(services.TIME_FMT)))
                db.get_db().commit()
            flash("If the account exists, a reset request has been recorded. Please contact the transport administrator to verify your identity.", "success")
            return redirect(url_for("user_login", role="student"))
        return render_template("forgot_password.html")

    @app.route("/profile", methods=["GET", "POST"])
    @student_required
    def student_profile():
        conn = db.get_db()
        student = conn.execute("SELECT s.*, r.route_code FROM students s LEFT JOIN routes r ON r.id=s.route_id WHERE s.id=?",
                               (session["student_id"],)).fetchone()
        if request.method == "POST":
            full_name = " ".join(request.form.get("full_name", "").split())
            mobile = request.form.get("mobile", "").strip()
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            if not full_name or not mobile:
                flash("Name and mobile number are required.", "error")
            elif new_password and (not check_password_hash(student["password_hash"], current_password) or len(new_password) < 8 or new_password != confirm_password):
                flash("To change password, enter your current password and matching new password (at least 8 characters).", "error")
            else:
                if new_password:
                    conn.execute("UPDATE students SET full_name=?, mobile=?, password_hash=? WHERE id=?",
                                 (full_name, mobile, generate_password_hash(new_password), session["student_id"]))
                else:
                    conn.execute("UPDATE students SET full_name=?, mobile=? WHERE id=?", (full_name, mobile, session["student_id"]))
                conn.commit()
                session["student_name"] = full_name
                flash("Profile updated.", "success")
                return redirect(url_for("student_profile"))
        return render_template("profile.html", student=student)

    @app.route("/bus-pass")
    @student_required
    def student_bus_pass():
        conn = db.get_db()
        student = conn.execute("SELECT s.*, r.route_code, r.bus_number, r.name AS route_name, p.token, p.valid_until "
                               "FROM students s LEFT JOIN routes r ON r.id=s.route_id LEFT JOIN bus_passes p ON p.student_id=s.id "
                               "WHERE s.id=?", (session["student_id"],)).fetchone()
        return render_template("bus_pass.html", student=student)

    @app.route("/verify-pass", methods=["GET", "POST"])
    @admin_required
    def verify_bus_pass():
        result = None
        if request.method == "POST":
            token = request.form.get("token", "").strip()
            result = db.get_db().execute("SELECT p.valid_until, s.full_name, s.prn, r.route_code FROM bus_passes p "
                                         "JOIN students s ON s.id=p.student_id LEFT JOIN routes r ON r.id=s.route_id WHERE p.token=?",
                                         (token,)).fetchone()
            if result:
                result = dict(result)
                result["valid"] = result["valid_until"] >= datetime.now().strftime("%Y-%m-%d")
            else:
                result = {"valid": False}
        return render_template("verify_pass.html", result=result)

    @app.route("/complaints", methods=["GET", "POST"])
    @student_required
    def student_complaints():
        conn = db.get_db()
        if request.method == "POST":
            category = request.form.get("category", "").strip()
            description = request.form.get("description", "").strip()
            allowed = {"Bus delay", "Driver behaviour", "Overcrowding", "Missed stop", "Other"}
            if category not in allowed or not 10 <= len(description) <= 1000:
                flash("Choose a category and enter a description of at least 10 characters.", "error")
            else:
                stamp = datetime.now().strftime(services.TIME_FMT)
                conn.execute("INSERT INTO complaints (student_id, category, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                             (session["student_id"], category, description, stamp, stamp))
                conn.commit()
                flash("Your complaint has been submitted.", "success")
                return redirect(url_for("student_complaints"))
        complaints = conn.execute("SELECT * FROM complaints WHERE student_id=? ORDER BY id DESC", (session["student_id"],)).fetchall()
        return render_template("complaints.html", complaints=complaints)

    @app.route("/driver")
    @driver_required
    def driver_dashboard():
        conn = db.get_db()
        driver = conn.execute("SELECT d.*, r.route_code, r.name AS route_name, r.bus_number, r.departure_time, r.to_departure_time "
                              "FROM drivers d LEFT JOIN routes r ON r.id=d.route_id WHERE d.id=?", (session["driver_id"],)).fetchone()
        route = services.get_route(conn, driver["route_code"]) if driver and driver["route_code"] else None
        return render_template("driver_dashboard.html", driver=driver, route=route)

    @app.route("/driver/location", methods=["POST"])
    @driver_required
    def driver_location_update():
        conn = db.get_db()
        driver = conn.execute("SELECT d.driver_code, r.route_code FROM drivers d LEFT JOIN routes r ON r.id=d.route_id WHERE d.id=?",
                              (session["driver_id"],)).fetchone()
        if not driver or not driver["route_code"]:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(error="No bus route is assigned to your account."), 400
            flash("No bus route is assigned to your account.", "error")
            return redirect(url_for("driver_dashboard"))
        try:
            action = request.form.get("action", "")
            if action in ("start", "update", "stop"):
                result = services.update_driver_trip(conn, driver["route_code"], request.form)
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify(result)
                flash(result["message"], "success")
            else:
                msg = services.set_location(conn, driver["route_code"], request.form)
                flash(msg, "success")
        except ChangeError as error:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(error=str(error)), 400
            flash(str(error), "error")
        return redirect(url_for("driver_dashboard"))

    # ================================================================== ADMIN EXTRA MANAGEMENT
    @app.route("/admin/students", methods=["GET", "POST"])
    @admin_required
    def admin_students():
        conn = db.get_db()
        if request.method == "POST":
            student_id = request.form.get("student_id", type=int)
            route_code = request.form.get("route_code", "").strip().upper()
            route = conn.execute("SELECT id FROM routes WHERE route_code=?", (route_code,)).fetchone() if route_code else None
            if route_code and not route:
                flash("Selected route does not exist.", "error")
            else:
                conn.execute("UPDATE students SET route_id=? WHERE id=?", (route["id"] if route else None, student_id))
                conn.commit()
                flash("Student route assignment updated.", "success")
                return redirect(url_for("admin_students"))
        students = conn.execute("SELECT s.*, r.route_code FROM students s LEFT JOIN routes r ON r.id=s.route_id ORDER BY s.full_name").fetchall()
        return render_template("admin_students.html", students=students, routes=services.get_routes(conn, include_inactive=True))

    @app.route("/admin/students/<int:student_id>/delete", methods=["POST"])
    @admin_required
    def admin_student_delete(student_id):
        conn = db.get_db()
        conn.execute("DELETE FROM students WHERE id=?", (student_id,))
        conn.commit()
        flash("Student account deleted.", "success")
        return redirect(url_for("admin_students"))

    @app.route("/admin/drivers", methods=["GET", "POST"])
    @admin_required
    def admin_drivers():
        conn = db.get_db()
        if request.method == "POST":
            code = request.form.get("driver_code", "").strip().upper()
            name = request.form.get("full_name", "").strip()
            email = request.form.get("email", "").strip().lower()
            mobile = request.form.get("mobile", "").strip()
            password = request.form.get("password", "")
            route_code = request.form.get("route_code", "").strip().upper()
            route = conn.execute("SELECT id FROM routes WHERE route_code=?", (route_code,)).fetchone() if route_code else None
            try:
                if request.form.get("action") == "update":
                    driver_id = request.form.get("driver_id", type=int)
                    if not all([code, name, email, mobile]) or (route_code and not route):
                        flash("Complete all driver details and select a valid route.", "error")
                    else:
                        conn.execute("UPDATE drivers SET driver_code=?, full_name=?, email=?, mobile=?, route_id=?, is_available=? WHERE id=?",
                                     (code, name, email, mobile, route["id"] if route else None,
                                      1 if request.form.get("is_available") == "1" else 0, driver_id))
                        if password:
                            if len(password) < 8:
                                raise ValueError("Password must contain at least 8 characters.")
                            conn.execute("UPDATE drivers SET password_hash=? WHERE id=?", (generate_password_hash(password), driver_id))
                        conn.commit()
                        flash("Driver details updated.", "success")
                elif not all([code, name, email, mobile]) or len(password) < 8 or (route_code and not route):
                    flash("Complete all fields, use a password of at least 8 characters and select a valid route.", "error")
                else:
                    conn.execute("INSERT INTO drivers (driver_code, full_name, email, mobile, password_hash, route_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                 (code, name, email, mobile, generate_password_hash(password), route["id"] if route else None,
                                  datetime.now().strftime(services.TIME_FMT)))
                    conn.commit()
                    flash("Driver account created.", "success")
            except (sqlite3.IntegrityError, ValueError) as error:
                flash("Driver details could not be saved: " + str(error), "error")
        drivers = conn.execute("SELECT d.*, r.route_code FROM drivers d LEFT JOIN routes r ON r.id=d.route_id ORDER BY d.id DESC").fetchall()
        return render_template("admin_drivers.html", drivers=drivers, routes=services.get_routes(conn, include_inactive=True))

    @app.route("/admin/drivers/<int:driver_id>/delete", methods=["POST"])
    @admin_required
    def admin_driver_delete(driver_id):
        conn = db.get_db()
        conn.execute("DELETE FROM drivers WHERE id=?", (driver_id,))
        conn.commit()
        flash("Driver record deleted.", "success")
        return redirect(url_for("admin_drivers"))

    @app.route("/admin/complaints", methods=["GET", "POST"])
    @admin_required
    def admin_complaints():
        conn = db.get_db()
        if request.method == "POST":
            complaint_id = request.form.get("complaint_id", type=int)
            status = request.form.get("status", "Pending")
            response_text = request.form.get("admin_response", "").strip()
            if status not in ("Pending", "In progress", "Resolved"):
                flash("Invalid complaint status.", "error")
            else:
                conn.execute("UPDATE complaints SET status=?, admin_response=?, updated_at=? WHERE id=?",
                             (status, response_text, datetime.now().strftime(services.TIME_FMT), complaint_id))
                conn.commit()
                flash("Complaint updated.", "success")
                return redirect(url_for("admin_complaints"))
        complaints = conn.execute("SELECT c.*, s.full_name, s.prn FROM complaints c JOIN students s ON s.id=c.student_id ORDER BY c.id DESC").fetchall()
        return render_template("admin_complaints.html", complaints=complaints)

    @app.route("/admin/password-resets", methods=["GET", "POST"])
    @admin_required
    def admin_password_resets():
        conn = db.get_db()
        if request.method == "POST":
            request_id = request.form.get("request_id", type=int)
            new_password = request.form.get("new_password", "")
            reset = conn.execute("SELECT * FROM password_reset_requests WHERE id=?", (request_id,)).fetchone()
            if not reset or len(new_password) < 8:
                flash("Select a valid request and enter a password of at least 8 characters.", "error")
            else:
                student = conn.execute("SELECT id FROM students WHERE email=?", (reset["email"],)).fetchone()
                if student:
                    conn.execute("UPDATE students SET password_hash=? WHERE id=?", (generate_password_hash(new_password), student["id"]))
                conn.execute("UPDATE password_reset_requests SET status='Completed' WHERE id=?", (request_id,))
                conn.commit()
                flash("Password reset request processed. Share the temporary password securely with the student.", "success")
                return redirect(url_for("admin_password_resets"))
        requests_list = conn.execute("SELECT * FROM password_reset_requests ORDER BY id DESC").fetchall()
        return render_template("admin_password_resets.html", requests=requests_list)

    @app.route("/admin/alerts", methods=["GET", "POST"])
    @admin_required
    def admin_alerts():
        conn = db.get_db()
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            message = request.form.get("message", "").strip()
            route_code = request.form.get("route_code", "").strip().upper()
            if not title or len(message) < 5:
                flash("Enter an alert title and a message of at least 5 characters.", "error")
            elif route_code and not conn.execute("SELECT 1 FROM routes WHERE route_code=?", (route_code,)).fetchone():
                flash("Selected route does not exist.", "error")
            else:
                create_notification(conn, route_code, "Emergency alert", f"{title}: {message}", "Emergency announcement", "route" if route_code else "all")
                flash("Emergency alert published.", "success")
                return redirect(url_for("admin_alerts"))
        return render_template("admin_alerts.html", routes=services.get_routes(conn, include_inactive=True))

    @app.route("/admin/routes/<route_id>/service-status", methods=["POST"])
    @admin_required
    def admin_service_status(route_id):
        conn = db.get_db()
        route = conn.execute("SELECT * FROM routes WHERE route_code=?", (route_id.upper(),)).fetchone()
        if not route:
            flash("Route not found.", "error")
            return redirect(url_for("admin_dashboard"))
        status = request.form.get("status", "")
        reason = request.form.get("reason", "").strip()
        if status not in ("Delayed", "Cancelled", "Active") or len(reason) < 5:
            flash("Choose a valid service status and provide a reason.", "error")
        else:
            with conn:
                if status == "Cancelled":
                    conn.execute("UPDATE routes SET is_active=0, service_status='Cancelled', status_reason=?, updated_at=? WHERE id=?",
                                 (reason, datetime.now().strftime(services.TIME_FMT), route["id"]))
                elif status == "Active":
                    conn.execute("UPDATE routes SET is_active=1, service_status='Active', status_reason=?, updated_at=? WHERE id=?",
                                 (reason, datetime.now().strftime(services.TIME_FMT), route["id"]))
                else:
                    conn.execute("UPDATE routes SET service_status=?, status_reason=?, updated_at=? WHERE id=?",
                                 (status, reason, datetime.now().strftime(services.TIME_FMT), route["id"]))
                create_notification(conn, route_id.upper(), "Bus " + status, f"{route['bus_number']} is {status.lower()}: {reason}", reason, "route")
            flash(f"{route['bus_number']} marked {status.lower()} and students notified.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/eta")
    @admin_required
    def admin_eta_placeholder():
        return redirect(url_for("admin_dashboard"))

    # ================================================================== ERRORS
    @app.errorhandler(404)
    def not_found(_e):
        return error_page(404, "Page not found", "The page you asked for does not exist.")

    @app.errorhandler(405)
    def not_allowed(_e):
        return error_page(405, "Not allowed", "That action is not allowed on this page.")

    @app.errorhandler(Exception)
    def unexpected(error):
        from werkzeug.exceptions import HTTPException
        if isinstance(error, HTTPException):
            return error_page(error.code, error.name, error.description)
        current_app.logger.exception("Unexpected error")
        return error_page(500, "Something went wrong",
                          "An unexpected error occurred. Nothing was lost - please go back and try again.")

    return app


def start_simulator(app, interval=SIM_INTERVAL_SECONDS):
    """
    DEMO ONLY: a background thread that moves every 'live' simulated bus a little along its route every few
    seconds. This is how the app shows a moving bus without any GPS hardware. Buses that the admin froze
    (Stale / Unavailable demos) are not moved.
    """
    def loop():
        while True:
            time.sleep(interval)
            try:
                conn = db.connect(app.config["DATABASE"])
                try:
                    services.simulate_step(conn)
                finally:
                    conn.close()
            except sqlite3.Error:
                app.logger.exception("Simulator tick failed")
    thread = threading.Thread(target=loop, name="bus-simulator", daemon=True)
    thread.start()
    return thread


if __name__ == "__main__":
    application = create_app()
    start_simulator(application)
    application.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
