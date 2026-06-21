

import os
import sqlite3
from datetime import datetime

import streamlit as st
import joblib
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from auth_utils import generate_password, hash_password, verify_password

st.set_page_config(page_title="BurnoutShield", layout="wide", page_icon="🧠")

DB_PATH = "burnoutshield.db"
if not os.path.exists(DB_PATH):
    import db_setup
    db_setup.main()
# ----------------------------------------------------------------------------
# Styling
# ----------------------------------------------------------------------------
st.markdown("""
<style>
    .bs-header {
        background: linear-gradient(90deg, #1f2937 0%, #312e81 100%);
        padding: 28px 32px; border-radius: 14px; margin-bottom: 24px;
    }
    .bs-header h1 { margin: 0; font-size: 30px; }
    .bs-header p { margin: 4px 0 0 0; opacity: 0.75; }
    div[data-testid="stMetric"] {
        background: #161b22; border: 1px solid #2d333b;
        border-radius: 10px; padding: 10px 14px;
    }
</style>
""", unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# DB helpers
# ----------------------------------------------------------------------------
def get_conn():
    return sqlite3.connect(DB_PATH)


def fetch_user(username: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT username, salt, password_hash, role, employee_id, must_change_password "
        "FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "username": row[0], "salt": row[1], "password_hash": row[2],
        "role": row[3], "employee_id": row[4], "must_change_password": bool(row[5]),
    }


def reset_password(username: str, new_password: str):
    salt, pwd_hash = hash_password(new_password)
    conn = get_conn()
    conn.execute(
        "UPDATE users SET salt=?, password_hash=?, must_change_password=0 WHERE username=?",
        (salt, pwd_hash, username)
    )
    conn.commit()
    conn.close()


def next_employee_id(cur) -> str:
    last = cur.execute("SELECT employee_id FROM employees ORDER BY employee_id DESC LIMIT 1").fetchone()
    n = int(last[0].replace("EMP", "")) + 1 if last else 1
    return f"EMP{n:04d}"


def create_employee(name: str, department: str, age_group: str, gender: str):
    """HR adds a new hire. Survey fields stay NULL until the employee logs in
    and completes their own self-assessment."""
    conn = get_conn()
    cur = conn.cursor()
    emp_id = next_employee_id(cur)
    cur.execute(
        "INSERT INTO employees (employee_id, employee_name, department, age_group, gender, date_added) "
        "VALUES (?,?,?,?,?,?)",
        (emp_id, name, department, age_group, gender, datetime.now().strftime("%Y-%m-%d"))
    )
    username = emp_id
    password = generate_password()
    salt, pwd_hash = hash_password(password)
    cur.execute(
        "INSERT INTO users (username, salt, password_hash, role, employee_id, must_change_password) "
        "VALUES (?,?,?,?,?,1)",
        (username, salt, pwd_hash, "Employee", emp_id)
    )
    conn.commit()
    conn.close()
    return emp_id, username, password


def get_employee_name(employee_id: str) -> str:
    conn = get_conn()
    row = conn.execute("SELECT employee_name FROM employees WHERE employee_id=?", (employee_id,)).fetchone()
    conn.close()
    return row[0] if row else employee_id


def save_assessment(employee_id: str, age_group_label: str, gender_label: str, answers: dict,
                     predicted_risk: int, burnout_stage: str, confidence: float):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now()
    cur.execute("""
        UPDATE employees SET
            age_group=?, gender=?, work_experience=?, working_hours_per_day=?,
            meetings_per_week=?, late_night_work_frequency=?, ai_job_displacement_fear=?,
            supervisor_support=?, salary_satisfaction=?, work_life_balance=?,
            stress_level=?, sleep_quality=?, job_satisfaction=?, burnout_symptoms=?,
            depression_risk=?, burnout_stage=?, year_month=?
        WHERE employee_id=?
    """, (
        age_group_label, gender_label, answers["Work_Experience"], answers["Working_Hours_Per_Day"],
        answers["Meetings_Per_Week"], answers["Late_Night_Work_Frequency"], answers["AI_Job_Displacement_Fear"],
        answers["Supervisor_Support"], answers["Salary_Satisfaction"], answers["Work_Life_Balance"],
        answers["Stress_Level"], answers["Sleep_Quality"], answers["Job_Satisfaction"], answers["Burnout_Symptoms"],
        predicted_risk, burnout_stage, now.strftime("%Y-%m"), employee_id
    ))
    cur.execute("""
        INSERT INTO assessments (
            employee_id, submitted_at, age_group, gender, work_experience, working_hours_per_day,
            meetings_per_week, late_night_work_frequency, ai_job_displacement_fear, supervisor_support,
            salary_satisfaction, work_life_balance, stress_level, sleep_quality, job_satisfaction,
            burnout_symptoms, predicted_risk, burnout_stage, confidence
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        employee_id, now.isoformat(), age_group_label, gender_label,
        answers["Work_Experience"], answers["Working_Hours_Per_Day"], answers["Meetings_Per_Week"],
        answers["Late_Night_Work_Frequency"], answers["AI_Job_Displacement_Fear"], answers["Supervisor_Support"],
        answers["Salary_Satisfaction"], answers["Work_Life_Balance"], answers["Stress_Level"],
        answers["Sleep_Quality"], answers["Job_Satisfaction"], answers["Burnout_Symptoms"],
        predicted_risk, burnout_stage, confidence
    ))
    conn.commit()
    conn.close()


_COLUMN_RENAME = {
    "employee_id": "Employee_ID", "employee_name": "Employee_Name", "department": "Department",
    "age_group": "Age_Group", "gender": "Gender", "work_experience": "Work_Experience",
    "working_hours_per_day": "Working_Hours_Per_Day", "meetings_per_week": "Meetings_Per_Week",
    "late_night_work_frequency": "Late_Night_Work_Frequency", "ai_job_displacement_fear": "AI_Job_Displacement_Fear",
    "supervisor_support": "Supervisor_Support", "salary_satisfaction": "Salary_Satisfaction",
    "work_life_balance": "Work_Life_Balance", "stress_level": "Stress_Level", "sleep_quality": "Sleep_Quality",
    "job_satisfaction": "Job_Satisfaction", "burnout_symptoms": "Burnout_Symptoms",
    "depression_risk": "Depression_Risk", "burnout_stage": "Burnout_Stage",
    "date_added": "Date", "year_month": "Year_Month",
}


def load_employees_df(assessed_only: bool = True) -> pd.DataFrame:
    conn = get_conn()
    query = "SELECT * FROM employees"
    if assessed_only:
        query += " WHERE depression_risk IS NOT NULL"
    data = pd.read_sql_query(query, conn)
    conn.close()
    data = data.rename(columns=_COLUMN_RENAME)
    if not data.empty:
        data["Depression_Risk"] = data["Depression_Risk"].astype(int)
    return data


# ----------------------------------------------------------------------------
# Model artifacts (cached — these never change at runtime)
# ----------------------------------------------------------------------------
@st.cache_resource
def load_model_artifacts():
    model = joblib.load("burnoutshield_model.pkl")
    age_encoder = joblib.load("age_encoder.pkl")
    gender_encoder = joblib.load("gender_encoder.pkl")
    return model, age_encoder, gender_encoder


model, age_encoder, gender_encoder = load_model_artifacts()

FEATURE_ORDER = [
    "Age_Group", "Gender", "Work_Experience", "Working_Hours_Per_Day",
    "Meetings_Per_Week", "Late_Night_Work_Frequency", "AI_Job_Displacement_Fear",
    "Supervisor_Support", "Salary_Satisfaction", "Work_Life_Balance",
    "Stress_Level", "Sleep_Quality", "Job_Satisfaction", "Burnout_Symptoms",
]

RISK_LABEL = {0: "🟢 Low Risk", 1: "🟡 Medium Risk", 2: "🔴 High Risk"}
RISK_COLOR = {0: "#22c55e", 1: "#eab308", 2: "#ef4444"}


def burnout_stage_label(score: int) -> str:
    if score <= 2:
        return "Mild"
    elif score == 3:
        return "Moderate"
    return "Severe"


def recommendations_for(risk_code: int):
    if risk_code == 2:
        return ["Reduce overtime / late-night work", "Improve sleep quality",
                "Recommend counseling support", "Flag for manager check-in"]
    elif risk_code == 1:
        return ["Monitor stress level over next few weeks", "Encourage better work-life balance"]
    return ["Maintain current healthy habits"]


# ----------------------------------------------------------------------------
# Session state / auth
# ----------------------------------------------------------------------------
defaults = {
    "stage": "login", "logged_in": False, "role": None,
    "emp_id": None, "emp_name": None,
    "pending_username": None, "pending_role": None, "pending_emp_id": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


def logout():
    for k, v in defaults.items():
        st.session_state[k] = v
    st.rerun()


def login_page():
    st.markdown(
        '<div class="bs-header"><h1>🧠 BurnoutShield</h1>'
        '<p>Employee depression & burnout risk monitoring platform</p></div>',
        unsafe_allow_html=True
    )
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        with st.form("login_form"):
            username = st.text_input("Username").strip()
            password = st.text_input("Password", type="password")
            go_btn = st.form_submit_button("Login", use_container_width=True)

        if go_btn:
            user = fetch_user(username)
            if user is None or not verify_password(password, user["salt"], user["password_hash"]):
                st.error("Invalid username or password.")
            elif user["must_change_password"]:
                st.session_state.stage = "password_reset"
                st.session_state.pending_username = user["username"]
                st.session_state.pending_role = user["role"]
                st.session_state.pending_emp_id = user["employee_id"]
                st.rerun()
            else:
                st.session_state.logged_in = True
                st.session_state.role = user["role"]
                st.session_state.emp_id = user["employee_id"]
                if user["role"] == "Employee":
                    st.session_state.emp_name = get_employee_name(user["employee_id"])
                st.session_state.stage = "app"
                st.rerun()


def password_reset_page():
    st.markdown(
        '<div class="bs-header"><h1>🔑 Set a New Password</h1>'
        '<p>First-time login — choose a new password to continue</p></div>',
        unsafe_allow_html=True
    )
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        with st.form("reset_form"):
            p1 = st.text_input("New password", type="password")
            p2 = st.text_input("Confirm new password", type="password")
            submit = st.form_submit_button("Set Password & Continue", use_container_width=True)

        if submit:
            if len(p1) < 8:
                st.error("Password must be at least 8 characters.")
            elif p1 != p2:
                st.error("Passwords don't match.")
            else:
                reset_password(st.session_state.pending_username, p1)
                st.session_state.logged_in = True
                st.session_state.role = st.session_state.pending_role
                st.session_state.emp_id = st.session_state.pending_emp_id
                if st.session_state.role == "Employee":
                    st.session_state.emp_name = get_employee_name(st.session_state.pending_emp_id)
                st.session_state.stage = "app"
                st.rerun()

        if st.button("← Back to login"):
            st.session_state.stage = "login"
            st.rerun()


# ----------------------------------------------------------------------------
# HR VIEW
# ----------------------------------------------------------------------------
def hr_view():
    st.sidebar.title("📊 HR Navigation")
    page = st.sidebar.radio(
        "Select Dashboard",
        ["Overview", "Department Analytics", "Employee Lookup", "Trends", "Add Employee"]
    )
    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Logout"):
        logout()

    df = load_employees_df(assessed_only=True)
    pending_df = load_employees_df(assessed_only=False)
    pending_count = pending_df["Depression_Risk"].isna().sum() if not pending_df.empty else 0

    if df.empty:
        st.title("📊 Executive Overview")
        st.info("No assessed employees yet.")
        return

    total_emp = len(df)
    high_risk = len(df[df["Depression_Risk"] == 2])
    medium_risk = len(df[df["Depression_Risk"] == 1])
    low_risk = len(df[df["Depression_Risk"] == 0])

    # ---------------- Overview ----------------
    if page == "Overview":
        st.title("📊 Executive Overview")

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Employees", total_emp)
        c2.metric("🔴 High Risk", high_risk)
        c3.metric("🟡 Medium Risk", medium_risk)
        c4.metric("🟢 Low Risk", low_risk)
        c5.metric("🆕 Pending First Assessment", int(pending_count))

        left, right = st.columns(2)
        with left:
            risk_df = df["Depression_Risk"].value_counts().reset_index()
            risk_df.columns = ["Risk", "Count"]
            risk_df["Risk"] = risk_df["Risk"].map(RISK_LABEL)
            fig = px.pie(risk_df, values="Count", names="Risk", hole=0.5,
                         title="Employee Risk Distribution", color="Risk",
                         color_discrete_map={RISK_LABEL[i]: RISK_COLOR[i] for i in RISK_COLOR})
            st.plotly_chart(fig, use_container_width=True)
        with right:
            org_risk = round((high_risk / total_emp) * 100, 2)
            fig = go.Figure(go.Indicator(
                mode="gauge+number", value=org_risk,
                title={'text': 'Organization Risk Index'},
                gauge={'axis': {'range': [0, 100]},
                       'steps': [{'range': [0, 30], 'color': '#1e3a2f'},
                                 {'range': [30, 60], 'color': '#3a3520'},
                                 {'range': [60, 100], 'color': '#3a1e1e'}],
                       'bar': {'color': RISK_COLOR[2] if org_risk > 60 else
                               RISK_COLOR[1] if org_risk > 30 else RISK_COLOR[0]}}
            ))
            st.plotly_chart(fig, use_container_width=True)

    # ---------------- Department Analytics ----------------
    elif page == "Department Analytics":
        st.title("🏢 Department Analytics")
        dept_selected = st.selectbox("Department", sorted(df["Department"].dropna().unique()))
        dept_df = df[df["Department"] == dept_selected]

        c1, c2, c3 = st.columns(3)
        c1.metric("Employees", len(dept_df))
        c2.metric("High Risk", len(dept_df[dept_df["Depression_Risk"] == 2]))
        c3.metric("Avg. Stress Level", round(dept_df["Stress_Level"].mean(), 2))

        g1, g2 = st.columns(2)
        with g1:
            risk_by_dept = pd.crosstab(df["Department"], df["Depression_Risk"])
            risk_by_dept.columns = [RISK_LABEL[c] for c in risk_by_dept.columns]
            fig = px.bar(risk_by_dept, barmode="group", title="Risk by Department",
                         color_discrete_map={RISK_LABEL[i]: RISK_COLOR[i] for i in RISK_COLOR})
            st.plotly_chart(fig, use_container_width=True)
        with g2:
            avg_stress = df.groupby("Department")["Stress_Level"].mean().round(2).reset_index()
            fig = px.bar(avg_stress, x="Department", y="Stress_Level",
                         title="Average Stress Level by Department", range_y=[0, 5])
            st.plotly_chart(fig, use_container_width=True)

        stage_by_dept = pd.crosstab(df["Department"], df["Burnout_Stage"])
        stage_by_dept = stage_by_dept[[c for c in ["Mild", "Moderate", "Severe"] if c in stage_by_dept.columns]]
        fig = px.bar(stage_by_dept, barmode="stack", title="Burnout Stage by Department",
                     color_discrete_map={"Mild": "#22c55e", "Moderate": "#eab308", "Severe": "#ef4444"})
        st.plotly_chart(fig, use_container_width=True)

        st.subheader(f"All Employees — {dept_selected}")
        st.dataframe(
            dept_df[["Employee_ID", "Employee_Name", "Stress_Level", "Burnout_Stage", "Depression_Risk"]]
            .assign(Depression_Risk=lambda d: d["Depression_Risk"].map(RISK_LABEL))
            .rename(columns={"Depression_Risk": "Risk Level"}),
            use_container_width=True, hide_index=True
        )

    # ---------------- Employee Lookup ----------------
    elif page == "Employee Lookup":
        st.title("🔍 Employee Lookup")
        employee = st.selectbox("Search Employee", sorted(df["Employee_Name"]))
        emp = df[df["Employee_Name"] == employee].iloc[0]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Employee ID", emp["Employee_ID"])
        c2.metric("Department", emp["Department"])
        c3.metric("Risk Level", RISK_LABEL[emp["Depression_Risk"]])
        c4.metric("Burnout Stage", emp["Burnout_Stage"])

        risk_score = emp["Stress_Level"] * 10 + emp["Burnout_Symptoms"] * 10
        fig = go.Figure(go.Indicator(
            mode="gauge+number", value=risk_score,
            title={'text': 'Risk Score'}, gauge={'axis': {'range': [0, 100]}}
        ))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Recommendations")
        for r in recommendations_for(emp["Depression_Risk"]):
            st.write(f"• {r}")

        if pending_count > 0:
            st.markdown("---")
            with st.expander(f"🆕 {int(pending_count)} employee(s) waiting on their first self-assessment"):
                st.dataframe(
                    pending_df[pending_df["Depression_Risk"].isna()][["Employee_ID", "Employee_Name", "Department"]],
                    use_container_width=True, hide_index=True
                )

    # ---------------- Trends ----------------
    elif page == "Trends":
        st.title("📈 Trend Dashboard")
        monthly = pd.crosstab(df["Year_Month"], df["Depression_Risk"]).sort_index()
        monthly.columns = [RISK_LABEL[c] for c in monthly.columns]

        fig = px.line(monthly, markers=True, title="Monthly Depression Trend")
        st.plotly_chart(fig, use_container_width=True)

        fig = px.area(monthly, title="Burnout Growth Trend")
        st.plotly_chart(fig, use_container_width=True)

    # ---------------- Add Employee ----------------
    elif page == "Add Employee":
        st.title("➕ Add New Employee")
        st.caption("Creates the employee record + a login. They'll complete their own "
                    "self-assessment the first time they log in.")

        existing_depts = sorted(df["Department"].dropna().unique()) if not df.empty else \
            ["Finance", "HR", "IT", "Marketing", "Operations", "Sales", "Support"]

        with st.form("add_employee_form"):
            name = st.text_input("Full Name")
            department = st.selectbox("Department", existing_depts)
            age_group = st.selectbox("Age Group", list(age_encoder.classes_))
            gender = st.selectbox("Gender", list(gender_encoder.classes_))
            submit = st.form_submit_button("Create Employee", use_container_width=True)

        if submit:
            if not name.strip():
                st.error("Name is required.")
            else:
                emp_id, username, password = create_employee(name.strip(), department, age_group, gender)
                st.success(f"Employee **{name}** created as **{emp_id}**.")
                st.code(f"Username: {username}\nTemporary password: {password}", language=None)
                st.warning("This password is shown only once — copy it now and share it securely "
                           "with the employee. They'll be required to set their own password on first login.")


# ----------------------------------------------------------------------------
# EMPLOYEE VIEW — self-assessment + live model prediction
# ----------------------------------------------------------------------------
def employee_view():
    if st.sidebar.button("🚪 Logout"):
        logout()

    st.markdown(
        f'<div class="bs-header"><h1>🧍 Welcome, {st.session_state.emp_name}</h1>'
        f'<p>Employee ID: {st.session_state.emp_id} — answer the questions below for your personal risk check</p></div>',
        unsafe_allow_html=True
    )

    st.subheader("Self-Assessment")
    with st.form("predict_form"):
        c1, c2 = st.columns(2)
        with c1:
            age_group = st.selectbox("Age Group", list(age_encoder.classes_))
            gender = st.selectbox("Gender", list(gender_encoder.classes_))
            work_experience = st.slider("Work Experience Level (1=Entry, 5=Highly Experienced)", 1, 5, 3)
            working_hours = st.slider("Working Hours Per Day (1=Few, 5=Many)", 1, 5, 3)
            meetings = st.slider("Meetings Per Week (1=Few, 5=Many)", 1, 5, 3)
            late_night = st.slider("Late-Night Work Frequency (1=Never, 5=Always)", 1, 5, 3)
            ai_fear = st.slider("AI Job-Displacement Fear (1=None, 5=Extreme)", 1, 5, 3)
        with c2:
            supervisor_support = st.slider("Supervisor Support (1=Poor, 5=Excellent)", 1, 5, 3)
            salary_satisfaction = st.slider("Salary Satisfaction (1=Low, 5=High)", 1, 5, 3)
            wlb = st.slider("Work-Life Balance (1=Poor, 5=Excellent)", 1, 5, 3)
            stress_level = st.slider("Stress Level (1=Low, 5=High)", 1, 5, 3)
            sleep_quality = st.slider("Sleep Quality (1=Poor, 5=Excellent)", 1, 5, 3)
            job_satisfaction = st.slider("Job Satisfaction (1=Low, 5=High)", 1, 5, 3)
            burnout_symptoms = st.slider("Burnout Symptoms (1=None, 5=Severe)", 1, 5, 3)

        submitted = st.form_submit_button("🔮 Predict My Risk", use_container_width=True)

    if submitted:
        answers = {
            "Work_Experience": work_experience, "Working_Hours_Per_Day": working_hours,
            "Meetings_Per_Week": meetings, "Late_Night_Work_Frequency": late_night,
            "AI_Job_Displacement_Fear": ai_fear, "Supervisor_Support": supervisor_support,
            "Salary_Satisfaction": salary_satisfaction, "Work_Life_Balance": wlb,
            "Stress_Level": stress_level, "Sleep_Quality": sleep_quality,
            "Job_Satisfaction": job_satisfaction, "Burnout_Symptoms": burnout_symptoms,
        }
        input_df = pd.DataFrame([{
            "Age_Group": age_encoder.transform([age_group])[0],
            "Gender": gender_encoder.transform([gender])[0],
            **answers,
        }])[FEATURE_ORDER]

        pred = int(model.predict(input_df)[0])
        proba = model.predict_proba(input_df)[0]
        stage = burnout_stage_label(burnout_symptoms)

        save_assessment(st.session_state.emp_id, age_group, gender, answers,
                         pred, stage, float(proba[pred]))

        st.markdown("---")
        st.subheader("Your Result")
        st.caption("Saved to your record.")

        r1, r2, r3 = st.columns(3)
        r1.metric("Depression Risk", RISK_LABEL[pred])
        r2.metric("Burnout Stage", stage)
        r3.metric("Confidence", f"{proba[pred]*100:.1f}%")

        g1, g2 = st.columns(2)
        with g1:
            risk_score = stress_level * 10 + burnout_symptoms * 10
            fig = go.Figure(go.Indicator(
                mode="gauge+number", value=risk_score,
                title={'text': 'Your Risk Score'}, gauge={'axis': {'range': [0, 100]}, 'bar': {'color': RISK_COLOR[pred]}}
            ))
            st.plotly_chart(fig, use_container_width=True)
        with g2:
            proba_df = pd.DataFrame({
                "Risk Level": [RISK_LABEL[0], RISK_LABEL[1], RISK_LABEL[2]], "Probability": proba
            })
            fig = px.bar(proba_df, x="Risk Level", y="Probability", title="Model Confidence by Class",
                         color="Risk Level", color_discrete_map={RISK_LABEL[i]: RISK_COLOR[i] for i in RISK_COLOR})
            st.plotly_chart(fig, use_container_width=True)

        profile_df = pd.DataFrame({
            "Factor": ["Stress", "Sleep Quality", "Work-Life Balance", "Job Satisfaction",
                       "Supervisor Support", "Burnout Symptoms"],
            "Your Score": [stress_level, sleep_quality, wlb, job_satisfaction, supervisor_support, burnout_symptoms]
        })
        fig = px.bar(profile_df, x="Factor", y="Your Score", title="Your Wellbeing Profile", range_y=[0, 5])
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Recommendations for You")
        for r in recommendations_for(pred):
            st.write(f"• {r}")


# ----------------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------------
if st.session_state.stage == "login":
    login_page()
elif st.session_state.stage == "password_reset":
    password_reset_page()
elif st.session_state.role == "HR":
    hr_view()
else:
    employee_view()
