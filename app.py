"""团队日计划 — 轻量 Web 应用"""
import json
import mimetypes
import os
import secrets
import uuid
from datetime import date, datetime
from pathlib import Path

from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.utils import secure_filename

from db import DB, init_schema, open_connection, use_postgres

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

SALES_QUOTES = [
    "每一次拒绝，都是离成交更近一步。",
    "销售拼的不是嘴，是持续行动的脚。",
    "今日多打一个电话，明天多一个可能。",
    "先把信任建立好，成交自然水到渠成。",
    "业绩不会陪你演戏，只会奖励真功夫。",
    "把每个线索当机会，而不是当任务。",
    "报价前先问清需求，比急着推销更专业。",
    "跟进要及时，机会不等人。",
    "客户的沉默，往往是在等你的下一次触达。",
    "早计划、早行动，业绩自然来敲门。",
    "专业是最好的话术，靠谱是最强的背书。",
    "今天多跟进一个客户，就离目标更近一步。",
    "销售没有捷径，坚持就是最好的方法。",
    "先帮客户解决问题，再谈合作会更顺利。",
    "把拒绝当成反馈，把反馈变成进步。",
    "每一次拜访，都是在为信任账户充值。",
    "行动治愈焦虑，执行带来结果。",
    "客户需求没摸清之前，别急着推产品。",
    "复盘今天，是为了明天签得更好。",
    "态度决定高度，细节决定成交。",
    "你今天的努力，客户未必立刻看见，但业绩会记住。",
    "销售本质是价值交换，先给予，再收获。",
    "把大目标拆成今日三件事，一步步完成。",
    "比同行多走一步，客户就会多看你一眼。",
    "耐心跟进，是对优质线索最大的尊重。",
    "开口就有机会，不开口永远为零。",
    "用结果证明专业，用服务赢得复购。",
    "今日事今日毕，别让线索在列表里沉睡。",
    "成交是开始，服务才是长久的生意。",
    "越忙越要列计划，有计划才有掌控感。",
    "相信过程，坚持行动，业绩只是时间问题。",
]


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


def _migrate_schema(db):
    if use_postgres():
        db.run("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_at TEXT")
        db.run("ALTER TABLE task_attachments ADD COLUMN IF NOT EXISTS file_data BYTEA")
    else:
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "updated_at" not in cols:
            db.run("ALTER TABLE tasks ADD COLUMN updated_at TEXT")
        att_cols = {r[1] for r in db.conn.execute("PRAGMA table_info(task_attachments)").fetchall()}
        if "file_data" not in att_cols:
            db.run("ALTER TABLE task_attachments ADD COLUMN file_data BLOB")


def ensure_schema():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = open_connection()
    try:
        init_schema(conn)
        _migrate_schema(DB(conn))
        conn.commit()
    finally:
        conn.close()


ensure_schema()


def today_str():
    return date.today().isoformat()


def format_date_display(d):
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{d.year}年{d.month}月{d.day}日 {WEEKDAYS[d.weekday()]}"


def today_display():
    return format_date_display(date.today())


def daily_quote():
    d = date.today()
    idx = (d.year * 366 + d.timetuple().tm_yday) % len(SALES_QUOTES)
    return SALES_QUOTES[idx]


@app.context_processor
def inject_globals():
    return {"daily_quote": daily_quote(), "cfg": load_config()}


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


def get_attachments(db, task_id):
    return db.fetchall(
        "SELECT * FROM task_attachments WHERE task_id = ? ORDER BY id",
        (task_id,),
    )


def tasks_with_attachments(db, plan_id):
    tasks = get_tasks(db, plan_id)
    for t in tasks:
        t["attachments"] = get_attachments(db, t["id"])
    return tasks


def completion_rate(tasks):
    if not tasks:
        return None
    done = sum(1 for t in tasks if t["evening_done"])
    return round(done * 100 / len(tasks))


def get_day_members(db, plan_date):
    rows = db.fetchall(
        "SELECT DISTINCT member_name FROM daily_plans WHERE plan_date = ? ORDER BY member_name",
        (plan_date,),
    )
    return [r["member_name"] for r in rows]


def get_recent_dates(db, days):
    if use_postgres():
        rows = db.fetchall(
            f"""
            SELECT DISTINCT plan_date FROM daily_plans
            WHERE plan_date >= (CURRENT_DATE - INTERVAL '{int(days)} days')::text
            ORDER BY plan_date DESC
            """
        )
    else:
        rows = db.fetchall(
            "SELECT DISTINCT plan_date FROM daily_plans WHERE plan_date >= date('now', ?) ORDER BY plan_date DESC",
            (f"-{int(days)} days",),
        )
    return [r["plan_date"] for r in rows]


def member_status(db, member_name, plan_date):
    plan = get_plan(db, member_name, plan_date)
    if not plan:
        return {
            "member_name": member_name,
            "has_plan": False,
            "updated": False,
            "tasks": [],
            "evening_rate": None,
        }
    tasks = tasks_with_attachments(db, plan["id"])
    has_progress = bool(plan.get("evening_submitted_at")) or any(t["evening_done"] for t in tasks)
    return {
        "member_name": member_name,
        "has_plan": True,
        "updated": has_progress,
        "tasks": tasks,
        "evening_rate": completion_rate(tasks),
    }


def build_daily_report(db, plan_date):
    statuses = [member_status(db, m, plan_date) for m in get_day_members(db, plan_date)]
    rates = [s["evening_rate"] for s in statuses if s["evening_rate"] is not None]
    return {
        "date": plan_date,
        "date_display": format_date_display(plan_date),
        "is_today": plan_date == today_str(),
        "submitted": len(statuses),
        "updated_ok": sum(1 for s in statuses if s["updated"]),
        "avg_rate": round(sum(rates) / len(rates)) if rates else 0,
        "statuses": statuses,
    }


def get_daily_reports(db, days=7, specific_date=None):
    if specific_date:
        return [build_daily_report(db, specific_date)]
    return [build_daily_report(db, d) for d in get_recent_dates(db, days)]


def delete_task_files(db, task_ids):
    if not task_ids:
        return
    placeholders = ",".join("?" * len(task_ids))
    rows = db.fetchall(
        f"SELECT stored_name FROM task_attachments WHERE task_id IN ({placeholders})",
        tuple(task_ids),
    )
    for r in rows:
        path = UPLOAD_DIR / r["stored_name"]
        if path.exists():
            path.unlink(missing_ok=True)


def save_attachment(db, task_id, file_storage):
    ext = Path(file_storage.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError("仅支持 PNG、JPG、GIF、WebP 图片")
    data = file_storage.read()
    if len(data) > MAX_FILE_SIZE:
        raise ValueError("单张图片不超过 5MB")
    stored = f"{uuid.uuid4().hex}{ext}"
    db.run(
        "INSERT INTO task_attachments (task_id, stored_name, original_name, created_at, file_data) VALUES (?, ?, ?, ?, ?)",
        (
            task_id,
            stored,
            secure_filename(file_storage.filename or stored),
            datetime.now().isoformat(timespec="seconds"),
            data,
        ),
    )


def _verify_task_owner(db, task_id, member_name):
    task = db.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if not task:
        return None, (jsonify({"ok": False, "error": "任务不存在"}), 404)
    plan = get_plan(db, member_name, today_str())
    if not plan or task["plan_id"] != plan["id"]:
        return None, (jsonify({"ok": False, "error": "无权操作"}), 403)
    return task, None


@app.route("/")
def index():
    if session.get("member_name"):
        return redirect(url_for("member_home"))
    return render_template("index.html", cfg=load_config(), date_display=today_display(), error=request.args.get("error"))


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
    member_name = session.get("member_name")
    if not member_name:
        return redirect(url_for("index"))
    db = get_db()
    plan_date = today_str()
    plan = get_plan(db, member_name, plan_date)
    tasks = tasks_with_attachments(db, plan["id"]) if plan else []
    return render_template(
        "member.html",
        cfg=load_config(),
        member_name=member_name,
        plan=plan,
        tasks=tasks,
        plan_date=plan_date,
        date_display=today_display(),
    )


@app.route("/api/plan", methods=["POST"])
def api_save_plan():
    member_name = session.get("member_name")
    if not member_name:
        return jsonify({"ok": False, "error": "请先输入姓名"}), 401
    data = request.get_json(force=True)
    items = [t.strip() for t in data.get("tasks", []) if t and t.strip()]
    if not items:
        return jsonify({"ok": False, "error": "请至少填写一条任务"}), 400
    db = get_db()
    plan_date = today_str()
    now = datetime.now().isoformat(timespec="seconds")
    existing = get_plan(db, member_name, plan_date)
    if existing:
        old_tasks = get_tasks(db, existing["id"])
        delete_task_files(db, [t["id"] for t in old_tasks])
        db.run("DELETE FROM tasks WHERE plan_id = ?", (existing["id"],))
        plan_id = existing["id"]
        db.run("UPDATE daily_plans SET created_at = ? WHERE id = ?", (now, plan_id))
    else:
        db.run("INSERT INTO daily_plans (member_name, plan_date, created_at) VALUES (?, ?, ?)", (member_name, plan_date, now))
        plan_id = db.fetchone("SELECT id FROM daily_plans WHERE member_name = ? AND plan_date = ?", (member_name, plan_date))["id"]
    for i, content in enumerate(items):
        db.run("INSERT INTO tasks (plan_id, content, sort_order) VALUES (?, ?, ?)", (plan_id, content, i))
    g._db_conn.commit()
    return jsonify({"ok": True})


@app.route("/api/task/<int:task_id>/submit", methods=["POST"])
def api_submit_task(task_id):
    member_name = session.get("member_name")
    if not member_name:
        return jsonify({"ok": False, "error": "请先输入姓名"}), 401
    db = get_db()
    task, err = _verify_task_owner(db, task_id, member_name)
    if err:
        return err
    plan = get_plan(db, member_name, today_str())
    done = request.form.get("done", "0") in ("1", "true", "True")
    now = datetime.now().isoformat(timespec="seconds")
    for key in request.files:
        for f in request.files.getlist(key):
            if f and f.filename:
                try:
                    save_attachment(db, task_id, f)
                except ValueError as e:
                    return jsonify({"ok": False, "error": str(e)}), 400
    db.run("UPDATE tasks SET evening_done = ?, updated_at = ? WHERE id = ?", (1 if done else 0, now, task_id))
    db.run("UPDATE daily_plans SET evening_submitted_at = ? WHERE id = ?", (now, plan["id"]))
    g._db_conn.commit()
    return jsonify({"ok": True, "done": done, "updated_at": now})


@app.route("/api/attachment/<int:att_id>", methods=["DELETE"])
def api_delete_attachment(att_id):
    member_name = session.get("member_name")
    if not member_name:
        return jsonify({"ok": False, "error": "请先登录"}), 401
    db = get_db()
    att = db.fetchone("SELECT * FROM task_attachments WHERE id = ?", (att_id,))
    if not att:
        return jsonify({"ok": False, "error": "附件不存在"}), 404
    task = db.fetchone("SELECT * FROM tasks WHERE id = ?", (att["task_id"],))
    plan = get_plan(db, member_name, today_str())
    if not plan or task["plan_id"] != plan["id"]:
        return jsonify({"ok": False, "error": "无权删除"}), 403
    path = UPLOAD_DIR / att["stored_name"]
    if path.exists():
        path.unlink(missing_ok=True)
    db.run("DELETE FROM task_attachments WHERE id = ?", (att_id,))
    g._db_conn.commit()
    return jsonify({"ok": True})


@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    if ".." in filename:
        abort(404)
    if not (session.get("member_name") or session.get("manager")):
        abort(403)
    db = get_db()
    att = db.fetchone("SELECT * FROM task_attachments WHERE stored_name = ?", (filename,))
    if not att:
        abort(404)
    data = att.get("file_data")
    if data is None:
        path = UPLOAD_DIR / filename
        if path.exists():
            return send_from_directory(UPLOAD_DIR, filename)
        abort(404)
    if isinstance(data, memoryview):
        data = data.tobytes()
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return Response(data, mimetype=mime)


@app.route("/manager")
def manager_login():
    return render_template("manager_login.html")


@app.route("/manager/auth", methods=["POST"])
def manager_auth():
    cfg = load_config()
    if request.form.get("pin", "") == cfg.get("manager_pin", "8888"):
        session["manager"] = True
        return redirect(url_for("manager_dashboard"))
    return render_template("manager_login.html", error="PIN 错误")


@app.route("/manager/dashboard")
def manager_dashboard():
    if not session.get("manager"):
        return redirect(url_for("manager_login"))
    db = get_db()
    days = int(request.args.get("days", 7))
    specific_date = request.args.get("date")
    if specific_date:
        try:
            date.fromisoformat(specific_date)
        except ValueError:
            specific_date = None
    return render_template(
        "manager.html",
        cfg=load_config(),
        daily_reports=get_daily_reports(db, days=days, specific_date=specific_date),
        days=days,
        selected_date=specific_date,
    )


@app.route("/manager/history")
def manager_history():
    return redirect(url_for("manager_dashboard", days=request.args.get("days", 30)))


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
