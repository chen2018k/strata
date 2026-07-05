"""
智塔 Strata 后台 — Flask 后端

功能:
  1. 用户注册/登录 (Flask-Login + bcrypt + 邮箱验证码)
  2. 回测记录 CRUD + 模拟实盘运行
  3. SPA 前端页面

启动: python app.py  →  http://localhost:5800
"""

from __future__ import annotations

import json, os, random, re, time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(ROOT / "templates"))
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "strata-dev-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{ROOT / 'instance' / 'strata.db'}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
CORS(app, supports_credentials=True)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
(ROOT / "instance").mkdir(parents=True, exist_ok=True)
(ROOT / "templates").mkdir(parents=True, exist_ok=True)

# ── 验证码存储 ────────────────────────────────────────────
_verification_codes: dict[str, dict] = {}
CODE_EXPIRE = 300

def store_code(target: str) -> str:
    code = f"{random.randint(100000, 999999)}"
    _verification_codes[target] = {"code": code, "expires": time.time() + CODE_EXPIRE, "attempts": 0}
    print(f"\n  [验证码] {target} -> {code}\n")
    return code

def verify_code(target: str, code: str) -> tuple[bool, str]:
    r = _verification_codes.get(target)
    if not r: return False, "请先获取验证码"
    if time.time() > r["expires"]: _verification_codes.pop(target, None); return False, "验证码已过期"
    if r["attempts"] >= 5: _verification_codes.pop(target, None); return False, "尝试次数过多"
    r["attempts"] += 1
    if r["code"] != str(code).strip(): return False, "验证码错误"
    _verification_codes.pop(target, None)
    return True, "ok"

def is_valid_email(e: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", e))

# ── 模型 ──────────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(30), default="")
    password_hash = db.Column(db.String(256), nullable=False)
    email_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    records = db.relationship("Record", back_populates="user", lazy="dynamic", cascade="all, delete-orphan")
    def set_password(self, p): self.password_hash = generate_password_hash(p)
    def check_password(self, p): return check_password_hash(self.password_hash, p)
    def to_dict(self):
        return {"id": self.id, "username": self.username, "email": self.email, "phone": self.phone,
                "email_verified": self.email_verified, "created_at": self.created_at.isoformat(),
                "record_count": self.records.count()}

class Record(db.Model):
    """回测记录"""
    __tablename__ = "records"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    symbol_name = db.Column(db.String(100), nullable=False)
    family = db.Column(db.String(50), nullable=False)
    risk = db.Column(db.String(20), default="均衡")
    engine = db.Column(db.String(20), default="native")
    window = db.Column(db.String(20), default="近3年")
    total_return = db.Column(db.Float, default=0.0)
    sharpe = db.Column(db.Float, default=0.0)
    max_dd = db.Column(db.Float, default=0.0)
    win_rate = db.Column(db.Float, default=0.0)
    trade_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="completed")  # completed / running / stopped
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notes = db.Column(db.Text, default="")

    user = db.relationship("User", back_populates="records")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "symbol": self.symbol,
                "symbol_name": self.symbol_name, "family": self.family, "risk": self.risk,
                "engine": self.engine, "window": self.window, "total_return": self.total_return,
                "sharpe": self.sharpe, "max_dd": self.max_dd, "win_rate": self.win_rate,
                "trade_count": self.trade_count, "status": self.status,
                "created_at": self.created_at.strftime("%Y-%m-%d %H:%M"),
                "notes": self.notes}

# ── 种子数据 ──────────────────────────────────────────────
MOCK_RECORDS = [
    {"name": "沪深300 趋势跟踪 · 均衡增强", "symbol": "510300", "symbol_name": "沪深300ETF",
     "family": "趋势跟踪", "risk": "均衡", "engine": "native", "window": "近3年",
     "total_return": 0.0824, "sharpe": 0.72, "max_dd": -0.124, "win_rate": 0.48, "trade_count": 12,
     "notes": "20/60日均线金叉入场，风控增强版回测验证通过"},
    {"name": "创业板 均值回归 · 保守", "symbol": "159915", "symbol_name": "创业板ETF",
     "family": "均值回归", "risk": "保守", "engine": "native", "window": "近1年",
     "total_return": 0.153, "sharpe": 1.45, "max_dd": -0.065, "win_rate": 0.62, "trade_count": 8,
     "notes": "RSI<30入场，超跌修复策略，低仓位控制风险"},
    {"name": "科创50 基准线策略 · VBT", "symbol": "588000", "symbol_name": "科创50ETF",
     "family": "趋势跟踪", "risk": "进取", "engine": "vbt", "window": "近6个月",
     "total_return": 0.221, "sharpe": 1.91, "max_dd": -0.089, "win_rate": 0.55, "trade_count": 6,
     "notes": "相对沪深300基准的Z-score偏离策略，VBT加速回测"},
    {"name": "中证500 多策略投票 · 稳健", "symbol": "510500", "symbol_name": "中证500ETF",
     "family": "多策略投票", "risk": "均衡", "engine": "vbt", "window": "全部",
     "total_return": 0.056, "sharpe": 0.38, "max_dd": -0.145, "win_rate": 0.41, "trade_count": 18,
     "notes": "趋势/RSI/布林带三信号确认，降低单一信号误判"},
    {"name": "贵州茅台 外部因子 · 库存拐点", "symbol": "600519", "symbol_name": "贵州茅台",
     "family": "基础模板", "risk": "均衡", "engine": "vbt", "window": "近3年",
     "total_return": -0.032, "sharpe": -0.21, "max_dd": -0.198, "win_rate": 0.35, "trade_count": 4,
     "notes": "基于渠道库存数据的外部因子注入，待优化因子阈值"},
    {"name": "平安银行 布林带反转 · 进取", "symbol": "000001", "symbol_name": "平安银行",
     "family": "布林带反转", "risk": "进取", "engine": "native", "window": "近1年",
     "total_return": 0.047, "sharpe": 0.55, "max_dd": -0.073, "win_rate": 0.44, "trade_count": 22,
     "notes": "跌破布林下轨入场，回到中轨出场，高换手策略"},
    {"name": "宁德时代 趋势跟踪 · 进取", "symbol": "300750", "symbol_name": "宁德时代",
     "family": "趋势跟踪", "risk": "进取", "engine": "native", "window": "近3年",
     "total_return": 0.182, "sharpe": 0.88, "max_dd": -0.215, "win_rate": 0.51, "trade_count": 9,
     "notes": "新能源赛道趋势策略，高弹性高波动"},
]

def seed_records(user_id: int):
    if Record.query.filter_by(user_id=user_id).count() > 0: return
    for m in MOCK_RECORDS:
        db.session.add(Record(user_id=user_id, status="completed", created_at=datetime.now(timezone.utc), **m))
    db.session.commit()

# ── Auth helpers ───────────────────────────────────────────
@login_manager.user_loader
def load_user(uid): return db.session.get(User, int(uid))
def api_login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not current_user.is_authenticated: return jsonify({"error": "未登录"}), 401
        return f(*a, **kw)
    return dec

# ── 页面 ───────────────────────────────────────────────────
@app.route("/")
def index(): return render_template("index.html")

# ── Auth ───────────────────────────────────────────────────
@app.route("/api/auth/send-code", methods=["POST"])
def send_code():
    d = request.get_json(silent=True) or {}
    t = (d.get("target") or "").strip()
    if not t: return jsonify({"error": "请输入邮箱或手机号"}), 400
    is_e = "@" in t
    if is_e and not is_valid_email(t): return jsonify({"error": "邮箱格式不正确"}), 400
    if is_e and User.query.filter_by(email=t).first(): return jsonify({"error": "该邮箱已被注册"}), 409
    code = store_code(t)
    return jsonify({"message": f"验证码已发送", "code_hint": code, "expires_in": CODE_EXPIRE})

@app.route("/api/auth/verify-and-register", methods=["POST"])
def verify_and_register():
    d = request.get_json(silent=True) or {}
    target = (d.get("target") or "").strip()
    code = (d.get("code") or "").strip()
    uname = (d.get("username") or "").strip()
    pw = (d.get("password") or "").strip()
    if not uname or len(uname)<2: return jsonify({"error":"用户名至少2个字符"}),400
    if not pw or len(pw)<6: return jsonify({"error":"密码至少6个字符"}),400
    is_e = "@" in target
    if is_e and User.query.filter_by(email=target).first(): return jsonify({"error":"邮箱已被注册"}),409
    ok, msg = verify_code(target, code)
    if not ok: return jsonify({"error": msg}), 400
    u = User(username=uname, email=target if is_e else f"phone_{target}@strata.local",
             phone=target if not is_e else "", email_verified=True)
    u.set_password(pw); db.session.add(u); db.session.commit()
    seed_records(u.id)
    login_user(u, remember=True)
    return jsonify({"message":"注册成功","user":u.to_dict()}),201

@app.route("/api/auth/login", methods=["POST"])
def login():
    d = request.get_json(silent=True) or {}
    uname, pw = (d.get("username") or "").strip(), (d.get("password") or "").strip()
    u = User.query.filter_by(email=uname).first() if "@" in uname else User.query.filter_by(username=uname).first()
    if not u or not u.check_password(pw): return jsonify({"error":"用户名或密码错误"}),401
    login_user(u, remember=True)
    return jsonify({"message":"登录成功","user":u.to_dict()})

@app.route("/api/auth/logout", methods=["POST"])
@api_login_required
def logout(): logout_user(); return jsonify({"message":"已退出"})

@app.route("/api/auth/me")
@api_login_required
def me(): return jsonify({"user": current_user.to_dict()})

@app.route("/api/health")
def health(): return jsonify({"status":"ok"})

# ── 回测记录 CRUD ──────────────────────────────────────────
@app.route("/api/records")
@api_login_required
def list_records():
    seed_records(current_user.id)
    records = current_user.records.order_by(Record.created_at.desc()).all()
    return jsonify({"records": [r.to_dict() for r in records]})

@app.route("/api/records/<int:rid>", methods=["GET"])
@api_login_required
def get_record(rid):
    r = db.session.get(Record, rid)
    if not r or r.user_id != current_user.id: return jsonify({"error":"记录不存在"}),404
    return jsonify({"record": r.to_dict()})

@app.route("/api/records/<int:rid>", methods=["PUT"])
@api_login_required
def update_record(rid):
    r = db.session.get(Record, rid)
    if not r or r.user_id != current_user.id: return jsonify({"error":"记录不存在"}),404
    d = request.get_json(silent=True) or {}
    if d.get("name"): r.name = d["name"]
    if d.get("notes"): r.notes = d["notes"]
    db.session.commit()
    return jsonify({"message":"已更新","record":r.to_dict()})

@app.route("/api/records/<int:rid>", methods=["DELETE"])
@api_login_required
def delete_record(rid):
    r = db.session.get(Record, rid)
    if not r or r.user_id != current_user.id: return jsonify({"error":"记录不存在"}),404
    db.session.delete(r); db.session.commit()
    return jsonify({"message":"已删除"})

@app.route("/api/records/<int:rid>/run", methods=["POST"])
@api_login_required
def run_record(rid):
    """模拟实盘运行：将状态改为 running，2 秒后自动恢复 completed"""
    r = db.session.get(Record, rid)
    if not r or r.user_id != current_user.id: return jsonify({"error":"记录不存在"}),404
    r.status = "running"; db.session.commit()
    # 模拟异步：延迟恢复
    def _restore():
        time.sleep(2)
        with app.app_context():
            rec = db.session.get(Record, rid)
            if rec and rec.status == "running": rec.status = "completed"; db.session.commit()
    import threading; threading.Thread(target=_restore, daemon=True).start()
    return jsonify({"message":"已启动实盘运行","record":r.to_dict()})

# ── 启动 ───────────────────────────────────────────────────
def init_db():
    with app.app_context(): db.create_all()

if __name__ == "__main__":
    init_db()
    print("\n  智塔 Strata 后台 → http://localhost:5200\n")
    app.run(debug=False, host="0.0.0.0", port=5200)
