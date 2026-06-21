"""
db_setup.py — run this ONCE to create burnoutshield.db
=========================================================
- Creates employees / users / assessments tables
- Migrates every employee from final.csv into the employees table
- Generates a username (= Employee_ID) and a random password for every
  employee, stores only a salted hash in the DB, and writes the plaintext
  pairs to credentials_export.csv (ONE TIME — distribute then delete it)
- Creates one HR admin account the same way

Run: python db_setup.py
"""

import sqlite3
import pandas as pd
from auth_utils import generate_password, hash_password

DB_PATH = "burnoutshield.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY,
    employee_name TEXT NOT NULL,
    department TEXT,
    age_group TEXT,
    gender TEXT,
    work_experience INTEGER,
    working_hours_per_day INTEGER,
    meetings_per_week INTEGER,
    late_night_work_frequency INTEGER,
    ai_job_displacement_fear INTEGER,
    supervisor_support INTEGER,
    salary_satisfaction INTEGER,
    work_life_balance INTEGER,
    stress_level INTEGER,
    sleep_quality INTEGER,
    job_satisfaction INTEGER,
    burnout_symptoms INTEGER,
    depression_risk INTEGER,
    burnout_stage TEXT,
    date_added TEXT,
    year_month TEXT
);

CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('HR','Employee')),
    employee_id TEXT,
    must_change_password INTEGER DEFAULT 1,
    FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    age_group TEXT, gender TEXT,
    work_experience INTEGER, working_hours_per_day INTEGER,
    meetings_per_week INTEGER, late_night_work_frequency INTEGER,
    ai_job_displacement_fear INTEGER, supervisor_support INTEGER,
    salary_satisfaction INTEGER, work_life_balance INTEGER,
    stress_level INTEGER, sleep_quality INTEGER,
    job_satisfaction INTEGER, burnout_symptoms INTEGER,
    predicted_risk INTEGER, burnout_stage TEXT, confidence REAL,
    FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
);
"""


def burnout_stage_label(score: int) -> str:
    if score <= 2:
        return "Mild"
    elif score == 3:
        return "Moderate"
    return "Severe"


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript(SCHEMA)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM employees")
    if cur.fetchone()[0] > 0:
        print(f"{DB_PATH} already has employee data — skipping migration.")
        print("Delete burnoutshield.db first if you want to rebuild from scratch.")
        conn.close()
        return

    df = pd.read_csv("final.csv")
    df["Depression_Risk"] = df["Depression_Risk"].replace(3, 2)
    df["Burnout_Stage"] = df["Burnout_Symptoms"].apply(burnout_stage_label)
    df["Date"] = pd.to_datetime(df["Date"])
    df["Year_Month"] = df["Date"].dt.to_period("M").astype(str)

    credentials_rows = []

    for _, row in df.iterrows():
        cur.execute("""
            INSERT OR REPLACE INTO employees (
                employee_id, employee_name, department, age_group, gender,
                work_experience, working_hours_per_day, meetings_per_week,
                late_night_work_frequency, ai_job_displacement_fear,
                supervisor_support, salary_satisfaction, work_life_balance,
                stress_level, sleep_quality, job_satisfaction, burnout_symptoms,
                depression_risk, burnout_stage, date_added, year_month
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            row["Employee_ID"], row["Employee_Name"], row["Department"],
            row["Age_Group"], row["Gender"], int(row["Work_Experience"]),
            int(row["Working_Hours_Per_Day"]), int(row["Meetings_Per_Week"]),
            int(row["Late_Night_Work_Frequency"]), int(row["AI_Job_Displacement_Fear"]),
            int(row["Supervisor_Support"]), int(row["Salary_Satisfaction"]),
            int(row["Work_Life_Balance"]), int(row["Stress_Level"]),
            int(row["Sleep_Quality"]), int(row["Job_Satisfaction"]),
            int(row["Burnout_Symptoms"]), int(row["Depression_Risk"]),
            row["Burnout_Stage"], str(row["Date"].date()), row["Year_Month"]
        ))

        username = row["Employee_ID"]
        password = generate_password()
        salt, pwd_hash = hash_password(password)
        cur.execute("""
            INSERT OR REPLACE INTO users
                (username, salt, password_hash, role, employee_id, must_change_password)
            VALUES (?,?,?,?,?,1)
        """, (username, salt, pwd_hash, "Employee", row["Employee_ID"]))

        credentials_rows.append({
            "username": username, "password": password,
            "role": "Employee", "name": row["Employee_Name"]
        })

    # One HR admin account
    hr_password = generate_password()
    salt, pwd_hash = hash_password(hr_password)
    cur.execute("""
        INSERT OR REPLACE INTO users
            (username, salt, password_hash, role, employee_id, must_change_password)
        VALUES (?,?,?,?,NULL,1)
    """, ("hr_admin", salt, pwd_hash, "HR"))
    credentials_rows.append({"username": "hr_admin", "password": hr_password,
                              "role": "HR", "name": "HR Admin"})

    conn.commit()
    conn.close()

    cred_df = pd.DataFrame(credentials_rows)
    cred_df.to_csv("credentials_export.csv", index=False)

    print(f"✅ Database created: {DB_PATH}")
    print(f"✅ {len(df)} employees migrated, each with a generated login.")
    print("✅ Plaintext credentials written to credentials_export.csv")
    print()
    print("⚠️  IMPORTANT: credentials_export.csv is the ONLY place the plaintext")
    print("    passwords exist — the database only stores salted hashes. Distribute")
    print("    this file securely (or print individual rows) then delete it.")
    print()
    print(f"HR login -> username: hr_admin   password: {hr_password}")
    print("Every account is forced to set a new password on first login.")


if __name__ == "__main__":
    main()
