"""团队日计划 — 轻量 Web 应用"""
import json
import os
import secrets
from datetime import date, datetime, time
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for

from db import DB, get_connection, history_date_filter, init_schema, use_postgres

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_db():
    if "db" not in g:
        g._db_conn = get_connection().__enter__()
        g.db = DB(g._db_conn)
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("_db_conn", None)
    g.pop("db", None)
    if conn is not None:
        try:
            conn.commit()
        except Exception:
            conn.rollback()
        conn.close()


def init_db():
    with get_connection() as conn:
        init_schema(conn)


def today_str():
    return date.today().isoformat()


def parse_hm(hm: str) -> time:
    h, m = map(int, hm.split(":"))
    return time(h, m)


def current_phase(cfg):
    now = datetime.now().time()
    morning = parse_hm(cfg["schedule"]["morning_deadline"])
    noon = parse_hm(cfg["schedule"]["noon_check"])
    evening = parse_hm(cfg["schedule"]["evening_check"])

    if now < morning:
        return "morning"
    if now < noon:
        return "noon"
    if now < evening:
        return "evening"
    return "closed"


def phase_label(phase):
    return {
        "morning": "早间 · 填写计划",
        "noon": "午间 · 确认进度",
        "evening": "晚间 · 确认进度",
        "closed": "今日已截止",
    }.get(phase, phase)


def get_plan(db, member_name, plan_date):
    return db.fetchone(
        "SELECT * FROM daily_plans WHERE member_name = ? AND plan_date = ?",
        (member_name, plan_date),
    )


def get_tasks(db, plan_id):
    return db.fetchall(
        "SELECT * FROM tasks WHERE plan_id = ? ORDER BY sort_order, id",
        (plan_id,),
    )


def completion_rate(tasks, field):
    if not tasks:
        return None
    done = sum(1 for t in tasks if t[field])
    return round(done * 100 / len(tasks))


def member_status(db, member_name, plan_date, cfg):
    plan = get_plan(db, member_name, plan_date)
    phase = current_phase(cfg)

    if not plan:
        missing = "plan" if phase != "morning" else None
        return {
            "member_name": member_name,
            "has_plan": False,
            "noon_done": False,
            "evening_done": False,
            "tasks": [],
            "noon_rate": None,
            "evening_rate": None,
            "missing": missing,
            "alert": phase != "morning",
        }

    tasks = get_tasks(db, plan["id"])
    missing = None
    if phase in ("evening", "closed") and not plan["noon_submitted_at"]:
        missing = "noon"
    if phase == "closed" and not plan["evening_submitted_at"]:
        missing = "evening"

    return {
        "member_name": member_name,
        "has_plan": True,
        "noon_done": bool(plan["noon_submitted_at"]),
        "evening_done": bool(plan["evening_submitted_at"]),
        "tasks": tasks,
        "noon_rate": completion_rate(tasks, "noon_done"),
        "evening_rate": completion_rate(tasks, "evening_done"),
        "missing": missing,
        "alert": missing is not None,
    }


@app.before_request
def _ensure_db():
    init_db()


@app.route("/")
def index():
    cfg = load_config()
    return render_template("index.html", cfg=cfg)


@app.route("/select/<member_name>")
def select_member(member_name):
    cfg = load_config()
    if member_name not in cfg["members"]:
        return redirect(url_for("index"))
    session["member_name"] = member_name
    return redirect(url_for("member_home"))


@app.route("/member")
def member_home():
    cfg = load_config()
    member_name = session.get("member_name")
    if not member_name:
        return redirect(url_for("index"))

    db = get_db()
    plan_date = today_str()
    plan = get_plan(db, member_name, plan_date)
    tasks = get_tasks(db, plan["id"]) if plan else []
    phase = current_phase(cfg)

    return render_template(
        "member.html",
        cfg=cfg,
        member_name=member_name,
        plan=plan,
        tasks=tasks,
        phase=phase,
        phase_label=phase_label(phase),
        plan_date=plan_date,
    )


@app.route("/api/plan", methods=["POST"])
def api_save_plan():
    cfg = load_config()
    member_name = session.get("member_name")
    if not member_name:
        return jsonify({"ok": False, "error": "请先选择姓名"}), 401

    if current_phase(cfg) != "morning":
        return jsonify({"ok": False, "error": "已过早间填写时间（09:00 前）"}), 400

    data = request.get_json(force=True)
    items = [t.strip() for t in data.get("tasks", []) if t and t.strip()]
    if not items:
        return jsonify({"ok": False, "error": "请至少填写一条任务"}), 400

    db = get_db()
    plan_date = today_str()
    now = datetime.now().isoformat(timespec="seconds")

    existing = get_plan(db, member_name, plan_date)
    if existing:
        db.run("DELETE FROM tasks WHERE plan_id = ?", (existing["id"],))
        plan_id = existing["id"]
        db.run(
            "UPDATE daily_plans SET created_at = ?, noon_submitted_at = NULL, evening_submitted_at = NULL WHERE id = ?",
            (now, plan_id),
        )
    else:
        db.run(
            "INSERT INTO daily_plans (member_name, plan_date, created_at) VALUES (?, ?, ?)",
            (member_name, plan_date, now),
        )
        row = db.fetchone(
            "SELECT id FROM daily_plans WHERE member_name = ? AND plan_date = ?",
            (member_name, plan_date),
        )
        plan_id = row["id"]

    for i, content in enumerate(items):
        db.run(
            "INSERT INTO tasks (plan_id, content, sort_order) VALUES (?, ?, ?)",
            (plan_id, content, i),
        )
    g._db_conn.commit()
    return jsonify({"ok": True})


@app.route("/api/checkin", methods=["POST"])
def api_checkin():
    cfg = load_config()
    member_name = session.get("member_name")
    if not member_name:
        return jsonify({"ok": False, "error": "请先选择姓名"}), 401

    phase = current_phase(cfg)
    if phase not in ("noon", "evening"):
        return jsonify({"ok": False, "error": "当前不在确认时段"}), 400

    data = request.get_json(force=True)
    task_status = data.get("tasks", {})
    check_field = "noon_done" if phase == "noon" else "evening_done"
    time_field = "noon_submitted_at" if phase == "noon" else "evening_submitted_at"

    db = get_db()
    plan_date = today_str()
    plan = get_plan(db, member_name, plan_date)
    if not plan:
        return jsonify({"ok": False, "error": "请先填写今日计划"}), 400

    tasks = get_tasks(db, plan["id"])
    for t in tasks:
        done = 1 if task_status.get(str(t["id"]), False) else 0
        db.run(f"UPDATE tasks SET {check_field} = ? WHERE id = ?", (done, t["id"]))

    db.run(
        f"UPDATE daily_plans SET {time_field} = ? WHERE id = ?",
        (datetime.now().isoformat(timespec="seconds"), plan["id"]),
    )
    g._db_conn.commit()
    return jsonify({"ok": True})


@app.route("/manager")
def manager_login():
    return render_template("manager_login.html")


@app.route("/manager/auth", methods=["POST"])
def manager_auth():
    cfg = load_config()
    pin = request.form.get("pin", "")
    if pin == cfg.get("manager_pin", "8888"):
        session["manager"] = True
        return redirect(url_for("manager_dashboard"))
    return render_template("manager_login.html", error="PIN 错误")


@app.route("/manager/dashboard")
def manager_dashboard():
    if not session.get("manager"):
        return redirect(url_for("manager_login"))

    cfg = load_config()
    db = get_db()
    plan_date = today_str()
    phase = current_phase(cfg)

    statuses = [member_status(db, m, plan_date, cfg) for m in cfg["members"]]
    submitted = sum(1 for s in statuses if s["has_plan"])
    noon_ok = sum(1 for s in statuses if s["noon_done"])
    evening_ok = sum(1 for s in statuses if s["evening_done"])
    alerts = [s for s in statuses if s["alert"]]

    return render_template(
        "manager.html",
        cfg=cfg,
        plan_date=plan_date,
        phase=phase,
        phase_label=phase_label(phase),
        statuses=statuses,
        submitted=submitted,
        total=len(cfg["members"]),
        noon_ok=noon_ok,
        evening_ok=evening_ok,
        alerts=alerts,
    )


@app.route("/manager/history")
def manager_history():
    if not session.get("manager"):
        return redirect(url_for("manager_login"))

    cfg = load_config()
    db = get_db()
    days = int(request.args.get("days", 7))
    date_filter = history_date_filter(days)
    rows = db.fetchall(
        f"""
        SELECT dp.plan_date, dp.member_name,
               COUNT(t.id) AS task_count,
               SUM(t.noon_done) AS noon_done,
               SUM(t.evening_done) AS evening_done,
               dp.noon_submitted_at, dp.evening_submitted_at
        FROM daily_plans dp
        LEFT JOIN tasks t ON t.plan_id = dp.id
        WHERE {date_filter}
        GROUP BY dp.plan_date, dp.member_name, dp.noon_submitted_at, dp.evening_submitted_at
        ORDER BY dp.plan_date DESC, dp.member_name
        """
    )

    by_date = {}
    for r in rows:
        d = r["plan_date"]
        if d not in by_date:
            by_date[d] = {"date": d, "members": [], "plan_count": 0, "avg_evening": []}
        tc = r["task_count"] or 0
        er = round((r["evening_done"] or 0) * 100 / tc) if tc else 0
        by_date[d]["members"].append(
            {
                "name": r["member_name"],
                "tasks": tc,
                "noon_rate": round((r["noon_done"] or 0) * 100 / tc) if tc else 0,
                "evening_rate": er,
                "noon_ok": bool(r["noon_submitted_at"]),
                "evening_ok": bool(r["evening_submitted_at"]),
            }
        )
        by_date[d]["plan_count"] += 1
        by_date[d]["avg_evening"].append(er)

    history = []
    for d in sorted(by_date.keys(), reverse=True):
        item = by_date[d]
        avg = round(sum(item["avg_evening"]) / len(item["avg_evening"])) if item["avg_evening"] else 0
        history.append(
            {
                "date": item["date"],
                "plan_count": item["plan_count"],
                "total_members": len(cfg["members"]),
                "avg_evening": avg,
                "members": item["members"],
            }
        )

    return render_template(
        "manager_history.html",
        cfg=cfg,
        history=history,
        days=days,
    )


@app.route("/health")
def health():
    return jsonify({"ok": True, "db": "postgres" if use_postgres() else "sqlite"})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
