"""团队日计划 — 轻量 Web 应用"""
import json
import os
import secrets
from datetime import date, datetime, time
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for

from db import DB, history_date_filter, init_schema, open_connection, use_postgres

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_db():
    if "db" not in g:
        g._db_conn = open_connection()
        g.db = DB(g._db_conn)
    return g.db


@app.teardown_appcontext
def close_db(exc):
    conn = g.pop("_db_conn", None)
    g.pop("db", None)
    if conn is not None:
        try:
            if exc is None:
                conn.commit()
            else:
                conn.rollback()
        except Exception:
            pass
        finally:
            conn.close()


def ensure_schema():
    conn = open_connection()
    try:
        init_schema(conn)
        conn.commit()
    finally:
        conn.close()


ensure_schema()


def today_str():
    return date.today().isoformat()


def today_display():
    d = date.today()
    return f"{d.year}年{d.month}月{d.day}日 {WEEKDAYS[d.weekday()]}"


def parse_hm(hm: str) -> time:
    h, m = map(int, hm.split(":"))
    return time(h, m)


def current_phase(cfg):
    """planning：白天填计划 | evening：晚上更新完成情况"""
    now = datetime.now().time()
    evening = parse_hm(cfg["schedule"]["evening_check"])
    if now >= evening:
        return "evening"
    return "planning"


def phase_label(phase):
    return {
        "planning": "填写今日工作计划",
        "evening": "更新任务完成情况",
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


def completion_rate(tasks, field="evening_done"):
    if not tasks:
        return None
    done = sum(1 for t in tasks if t[field])
    return round(done * 100 / len(tasks))


def get_today_members(db, plan_date):
    rows = db.fetchall(
        "SELECT DISTINCT member_name FROM daily_plans WHERE plan_date = ? ORDER BY member_name",
        (plan_date,),
    )
    return [r["member_name"] for r in rows]


def member_status(db, member_name, plan_date, cfg):
    plan = get_plan(db, member_name, plan_date)
    phase = current_phase(cfg)

    if not plan:
        return {
            "member_name": member_name,
            "has_plan": False,
            "evening_done": False,
            "tasks": [],
            "evening_rate": None,
            "missing": "plan" if phase == "evening" else None,
            "alert": phase == "evening",
        }

    tasks = get_tasks(db, plan["id"])
    missing = None
    if phase == "evening" and not plan["evening_submitted_at"]:
        missing = "evening"

    return {
        "member_name": member_name,
        "has_plan": True,
        "evening_done": bool(plan["evening_submitted_at"]),
        "tasks": tasks,
        "evening_rate": completion_rate(tasks),
        "missing": missing,
        "alert": missing is not None,
    }



@app.route("/")
def index():
    cfg = load_config()
    member_name = session.get("member_name")
    if member_name:
        return redirect(url_for("member_home"))
    return render_template(
        "index.html",
        cfg=cfg,
        plan_date=today_str(),
        date_display=today_display(),
        error=request.args.get("error"),
    )


@app.route("/join", methods=["POST"])
def join():
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("index", error="请输入您的姓名"))
    if len(name) > 20:
        return redirect(url_for("index", error="姓名不超过 20 个字"))
    session["member_name"] = name
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
        date_display=today_display(),
        evening_time=cfg["schedule"]["evening_check"],
    )


@app.route("/api/plan", methods=["POST"])
def api_save_plan():
    member_name = session.get("member_name")
    if not member_name:
        return jsonify({"ok": False, "error": "请先输入姓名"}), 401

    if current_phase(load_config()) == "evening" and get_plan(get_db(), member_name, today_str()):
        existing = get_plan(get_db(), member_name, today_str())
        if existing and existing.get("evening_submitted_at"):
            return jsonify({"ok": False, "error": "晚间确认已提交，无法修改计划"}), 400

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
        if not existing.get("evening_submitted_at"):
            db.run(
                "UPDATE daily_plans SET created_at = ? WHERE id = ?",
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
        return jsonify({"ok": False, "error": "请先输入姓名"}), 401

    if current_phase(cfg) != "evening":
        return jsonify({"ok": False, "error": f"请在 {cfg['schedule']['evening_check']} 后再更新完成情况"}), 400

    data = request.get_json(force=True)
    task_status = data.get("tasks", {})

    db = get_db()
    plan_date = today_str()
    plan = get_plan(db, member_name, plan_date)
    if not plan:
        return jsonify({"ok": False, "error": "请先填写今日工作计划"}), 400

    tasks = get_tasks(db, plan["id"])
    for t in tasks:
        done = 1 if task_status.get(str(t["id"]), False) else 0
        db.run("UPDATE tasks SET evening_done = ? WHERE id = ?", (done, t["id"]))

    db.run(
        "UPDATE daily_plans SET evening_submitted_at = ? WHERE id = ?",
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

    members = get_today_members(db, plan_date)
    statuses = [member_status(db, m, plan_date, cfg) for m in members]
    submitted = len([s for s in statuses if s["has_plan"]])
    evening_ok = sum(1 for s in statuses if s["evening_done"])
    alerts = [s for s in statuses if s["alert"]]

    return render_template(
        "manager.html",
        cfg=cfg,
        plan_date=plan_date,
        date_display=today_display(),
        phase=phase,
        phase_label=phase_label(phase),
        statuses=statuses,
        submitted=submitted,
        evening_ok=evening_ok,
        alerts=alerts,
        evening_time=cfg["schedule"]["evening_check"],
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
               SUM(t.evening_done) AS evening_done,
               dp.evening_submitted_at
        FROM daily_plans dp
        LEFT JOIN tasks t ON t.plan_id = dp.id
        WHERE {date_filter}
        GROUP BY dp.plan_date, dp.member_name, dp.evening_submitted_at
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
                "evening_rate": er,
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
