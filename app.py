import os
import sys
import json
import socket
import configparser
from datetime import date, timedelta
from urllib.request import urlopen
from urllib.parse import urlencode

import pandas as pd
import pymysql
import pymysql.cursors
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "Crop_recommendation.csv")

# -----------------------------
# Settings
# Saari settings config.ini file me hain (DB port, DB password,
# website ka port). Zarurat ho to wahin badlein, app.py nahi.
# Environment variables (DB_HOST, DB_PORT, ...) config.ini se upar chalte hain.
# -----------------------------
_cfg = configparser.ConfigParser(interpolation=None)
_cfg.read(os.path.join(BASE_DIR, "config.ini"), encoding="utf-8")


def _setting(section, key, env_name, default):
    value = os.environ.get(env_name)
    if value is None or value == "":
        value = _cfg.get(section, key, fallback=default)
    return str(value).strip()


# MySQL
DB_HOST = _setting("database", "host", "DB_HOST", "127.0.0.1")
DB_PORT = int(_setting("database", "port", "DB_PORT", "3306"))
DB_USER = _setting("database", "user", "DB_USER", "root")
DB_PASSWORD = _setting("database", "password", "DB_PASSWORD", "")
DB_NAME = _setting("database", "name", "DB_NAME", "crop_recommendation")

# Website (Flask)
APP_HOST = _setting("server", "host", "APP_HOST", "127.0.0.1")
APP_PORT = int(_setting("server", "port", "APP_PORT", "5000"))

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "crop-recommendation-system-local-secret-key"
)


# -----------------------------
# Database (MySQL)
# -----------------------------
def get_db():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False
    )


def resolve_db_port():
    """
    MySQL ka sahi port dhoondhta hai.
    Pehle config.ini wala port try hota hai, phir 3306/3307/3308/3309.
    Jo port par MySQL mil jaye wahi use hota hai.
    """
    global DB_PORT

    candidates = []
    for port in (DB_PORT, 3306, 3307, 3308, 3309):
        if port not in candidates:
            candidates.append(port)

    last_error = None
    for port in candidates:
        try:
            conn = pymysql.connect(
                host=DB_HOST,
                port=port,
                user=DB_USER,
                password=DB_PASSWORD,
                charset="utf8mb4",
                connect_timeout=5
            )
            conn.close()
        except pymysql.err.OperationalError as error:
            code = error.args[0] if error.args else None
            if code == 1045:
                # Server mil gaya par username/password galat hai.
                raise RuntimeError(
                    f"MySQL port {port} par mil gaya, lekin username/password "
                    f"galat hai.\nconfig.ini me [database] user aur password "
                    f"sahi karein. (user = {DB_USER})"
                )
            last_error = error
            continue

        if port != DB_PORT:
            print(f"[INFO] MySQL port {port} par mila "
                  f"(config.ini me {DB_PORT} tha). Port {port} use ho raha hai.")
            print(f"[TIP]  config.ini me port = {port} kar dein.")
        DB_PORT = port
        return port

    raise RuntimeError(
        "MySQL server se connect nahi ho paya "
        f"(host={DB_HOST}, tried ports={candidates}).\n"
        "1) MySQL server chalu hai ya nahi check karein "
        "(XAMPP/MySQL Workbench/Services).\n"
        "2) MySQL ka asli port config.ini me [database] port me likhein.\n"
        f"Detail: {last_error}"
    )


def init_db():
    resolve_db_port()

    # Database na ho to pehle bana do.
    server = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        charset="utf8mb4"
    )
    with server.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    server.commit()
    server.close()

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                full_name VARCHAR(150) NOT NULL,
                email VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                nitrogen DOUBLE NOT NULL,
                phosphorus DOUBLE NOT NULL,
                potassium DOUBLE NOT NULL,
                temperature DOUBLE NOT NULL,
                humidity DOUBLE NOT NULL,
                ph DOUBLE NOT NULL,
                rainfall DOUBLE NOT NULL,
                predicted_crop VARCHAR(100) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
    conn.commit()
    conn.close()


# -----------------------------
# Machine-learning model
# Original CSV is used directly.
# -----------------------------
data = pd.read_csv(DATA_FILE)

X = data.drop(columns=["label"])
y = data["label"]

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.20,
    random_state=42,
    stratify=y
)

model = RandomForestClassifier(
    n_estimators=100,
    max_depth=10,
    random_state=42
)
model.fit(X_train, y_train)


# -----------------------------
# Authentication helper
# -----------------------------
def login_required(view_function):
    from functools import wraps

    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view_function(*args, **kwargs)

    return wrapped_view


# -----------------------------
# Sign Up
# -----------------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if "user_id" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not full_name or not email or not password:
            flash("Please fill all fields.", "error")
            return render_template("signup.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("signup.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("signup.html")

        conn = get_db()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (full_name, email, password_hash)
                    VALUES (%s, %s, %s)
                    """,
                    (full_name, email, generate_password_hash(password))
                )
                user_id = cur.lastrowid
            conn.commit()

            session.clear()
            session["user_id"] = user_id
            session["full_name"] = full_name
            session["email"] = email

            flash(
                f"Account created successfully. Your User ID is {user_id}.",
                "success"
            )
            return redirect(url_for("index"))

        except pymysql.err.IntegrityError:
            flash("This email is already registered. Please log in.", "error")
            return render_template("signup.html")

        finally:
            conn.close()

    return render_template("signup.html")


# -----------------------------
# Login
# -----------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE email = %s",
                (email,)
            )
            user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["full_name"] = user["full_name"]
            session["email"] = user["email"]
            return redirect(url_for("index"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


# -----------------------------
# Logout
# -----------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -----------------------------
# Prediction page
# -----------------------------
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    prediction = None
    submitted = {}

    if request.method == "POST":
        try:
            values = {
                "N": float(request.form["N"]),
                "P": float(request.form["P"]),
                "K": float(request.form["K"]),
                "temperature": float(request.form["temperature"]),
                "humidity": float(request.form["humidity"]),
                "ph": float(request.form["ph"]),
                "rainfall": float(request.form["rainfall"])
            }

            input_data = pd.DataFrame(
                [[
                    values["N"],
                    values["P"],
                    values["K"],
                    values["temperature"],
                    values["humidity"],
                    values["ph"],
                    values["rainfall"]
                ]],
                columns=[
                    "N", "P", "K",
                    "temperature", "humidity",
                    "ph", "rainfall"
                ]
            )

            prediction = str(model.predict(input_data)[0])
            submitted = values

            # Save this prediction against the logged-in user's ID.
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO predictions (
                        user_id, nitrogen, phosphorus, potassium,
                        temperature, humidity, ph, rainfall, predicted_crop
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session["user_id"],
                        values["N"],
                        values["P"],
                        values["K"],
                        values["temperature"],
                        values["humidity"],
                        values["ph"],
                        values["rainfall"],
                        prediction
                    )
                )
            conn.commit()
            conn.close()

        except (KeyError, ValueError):
            flash("Please enter valid values in all fields.", "error")

    return render_template(
        "index.html",
        prediction=prediction,
        submitted=submitted
    )


# -----------------------------
# Prediction history for logged-in user
# -----------------------------
@app.route("/history")
@login_required
def history():
    conn = get_db()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id, nitrogen, phosphorus, potassium,
                temperature, humidity, ph, rainfall,
                predicted_crop, created_at
            FROM predictions
            WHERE user_id = %s
            ORDER BY id DESC
            """,
            (session["user_id"],)
        )
        rows = cur.fetchall()

    conn.close()

    return render_template("history.html", predictions=rows)


# -----------------------------
# Automatic weather
#
# Temperature + Humidity:
# current weather at detected location.
#
# Rainfall:
# total rain from the last 365 completed days.
# -----------------------------
@app.route("/get_weather", methods=["GET"])
@login_required
def get_weather():
    try:
        latitude = float(request.args["latitude"])
        longitude = float(request.args["longitude"])

        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Invalid location.")

        # Current temperature and humidity.
        current_params = urlencode({
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m",
            "timezone": "auto"
        })

        current_url = (
            "https://api.open-meteo.com/v1/forecast?"
            + current_params
        )

        with urlopen(current_url, timeout=15) as response:
            current_weather = json.loads(
                response.read().decode("utf-8")
            )

        current = current_weather.get("current", {})
        temperature = current.get("temperature_2m")
        humidity = current.get("relative_humidity_2m")

        if temperature is None or humidity is None:
            raise ValueError("Current temperature/humidity not available.")

        # Last 365 completed days for rainfall.
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=364)

        rain_params = urlencode({
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": "rain_sum",
            "timezone": "auto"
        })

        rain_url = (
            "https://archive-api.open-meteo.com/v1/archive?"
            + rain_params
        )

        with urlopen(rain_url, timeout=20) as response:
            rain_weather = json.loads(
                response.read().decode("utf-8")
            )

        rain_values = rain_weather.get("daily", {}).get("rain_sum", [])
        rainfall = sum(float(value or 0) for value in rain_values)

        return jsonify({
            "success": True,
            "temperature": round(float(temperature), 2),
            "humidity": round(float(humidity), 2),
            "rainfall": round(float(rainfall), 2)
        })

    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


def find_free_port(host, preferred, tries=50):
    """Preferred port busy ho to agla khaali port dhoondh leta hai."""
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"Port {preferred} ke baad koi khaali port nahi mila.")


# Create the database automatically when the app starts.
try:
    init_db()
except RuntimeError as error:
    print("\n[ERROR] " + str(error) + "\n")
    sys.exit(1)

if __name__ == "__main__":
    port = find_free_port(APP_HOST, APP_PORT)
    if port != APP_PORT:
        print(f"[INFO] Port {APP_PORT} busy hai, isliye port {port} use ho raha hai.")

    print("\n==============================================")
    print(f" Browser me kholein: http://127.0.0.1:{port}")
    print(f" MySQL: {DB_HOST}:{DB_PORT}  (database: {DB_NAME})")
    print("==============================================\n")

    # use_reloader=False: debug mode me app do baar start hone se bachata hai.
    app.run(host=APP_HOST, port=port, debug=True, use_reloader=False)
