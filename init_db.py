"""
Initialise (or reset) the demo database.

    python init_db.py           -> create the database and demo data if they do not exist
    python init_db.py --reset   -> DELETE everything and recreate the demo data
"""
import sys

from app import create_app
import db

if __name__ == "__main__":
    reset = "--reset" in sys.argv
    app = create_app(init=False)
    with app.app_context():
        db.init_db(reset=reset)
    print("Database RESET and demo data loaded." if reset else "Database ready.")
    print("Location:", app.config["DATABASE"])
    print(f"Admin login -> username: {db.DEMO_ADMIN_USERNAME}  password: {db.DEMO_ADMIN_PASSWORD}")
