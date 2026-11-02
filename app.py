import os
import json
from datetime import date, timedelta
from urllib.request import urlopen
from urllib.parse import urlencode

import pandas as pd
import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "Crop_recommendation.csv")

# -----------------------------
# Settings (environment variables - Render dashboard me set karein)
#   DATABASE_URL : Neon ki connection string
#   SECRET_KEY   : koi bhi lamba random text
# -----------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")


# -----------------------------
# Database (Neon PostgreSQL)
# -----------------------------
def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor
    )


def init_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable set nahi hai.")

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                full_name VARCHAR(150) NOT NULL,
                email VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL REFERENCES users(id),
                nitrogen DOUBLE PRECISION NOT NULL,
                phosphorus DOUBLE PRECISION NOT NULL,
                potassium DOUBLE PRECISION NOT NULL,
                temperature DOUBLE PRECISION NOT NULL,
                humidity DOUBLE PRECISION NOT NULL,
                ph DOUBLE PRECISION NOT NULL,
                rainfall DOUBLE PRECISION NOT NULL,
                predicted_crop VARCHAR(100) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
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
                    RETURNING id
                    """,
                    (full_name, email, generate_password_hash(password))
                )
                user_id = cur.fetchone()["id"]
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

        except psycopg2.IntegrityError:
            conn.rollback()
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


# Tables app start hote hi automatically ban jati hain.
init_db()

if __name__ == "__main__":
    # Sirf local testing ke liye. Render par gunicorn chalta hai.
    app.run(host="127.0.0.1", port=5000, debug=False)
