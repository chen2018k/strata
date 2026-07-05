"""
智塔 Strata 后台 — 全流程测试脚本

测试覆盖:
  1. 用户注册 (正常 + 边界校验)
  2. 用户登录 (正常 + 错误密码)
  3. 策略保存 (多策略族)
  4. 回测结果保存 (完整 VBT 指标)
  5. 账户概览 (策略数/回测数/最近活动)
  6. 数据查询与删除
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime

BASE_URL = "http://localhost:5000"
OUTPUT_DIR = Path(__file__).resolve().parent / "test_results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PASS = 0
FAIL = 0
RESULTS: list[dict] = []


# ── HTTP 工具 ───────────────────────────────────────────────

def request(method: str, path: str, data: dict | None = None, cookies: str | None = None) -> tuple[int, dict]:
    """发送 JSON API 请求，返回 (status_code, response_json, cookie_header)。"""
    # URL 编码中文路径
    encoded_path = urllib.request.quote(path, safe="/?=&")
    url = f"{BASE_URL}{encoded_path}"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if cookies:
        headers["Cookie"] = cookies

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            cookie_header = resp.headers.get("Set-Cookie", "")
            return resp.status, json.loads(resp.read().decode("utf-8")), cookie_header
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8")), ""


def test(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    status = "✅ PASS" if condition else "❌ FAIL"
    if condition:
        PASS += 1
    else:
        FAIL += 1
    RESULTS.append({"name": name, "status": status, "detail": detail, "passed": condition})
    print(f"  {status} | {name}")
    if detail:
        print(f"         {detail}")


# ── 测试执行 ────────────────────────────────────────────────

def run_tests():
    global PASS, FAIL
    PASS = FAIL = 0
    RESULTS.clear()

    print("=" * 60)
    print("  智塔 Strata 后台 — 全流程测试")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ════════════════════════════════════════════════════════
    # 1. 健康检查
    # ════════════════════════════════════════════════════════
    print("\n── 1. 健康检查 ──")
    code, resp, _ = request("GET", "/api/health")
    test("服务可达", code == 200 and resp.get("status") == "ok", str(resp))

    # ════════════════════════════════════════════════════════
    # 2. 用户注册
    # ════════════════════════════════════════════════════════
    print("\n── 2. 用户注册 ──")

    # 2a. 正常注册
    code, resp, _ = request("POST", "/api/auth/register", {
        "username": "testuser",
        "email": "test@strata.dev",
        "password": "test123456",
    })
    test("注册新用户", code == 201 and resp.get("user", {}).get("username") == "testuser",
         f"status={code}, username={resp.get('user', {}).get('username')}")

    # 2b. 重复用户名
    code, resp, _ = request("POST", "/api/auth/register", {
        "username": "testuser",
        "email": "other@strata.dev",
        "password": "test123456",
    })
    test("拒绝重复用户名", code == 400 and "已被注册" in resp.get("error", ""),
         str(resp.get("error", "")))

    # 2c. 缺少必填字段
    code, resp, _ = request("POST", "/api/auth/register", {
        "username": "ab",
        "email": "bad",
        "password": "12",
    })
    test("拒绝无效输入", code == 400,
         f"status={code}")

    # 2d. 第二个用户
    code, resp, _ = request("POST", "/api/auth/register", {
        "username": "user2",
        "email": "user2@strata.dev",
        "password": "password123",
    })
    test("注册第二个用户", code == 201, f"user_id={resp.get('user', {}).get('id')}")

    # ════════════════════════════════════════════════════════
    # 3. 用户登录
    # ════════════════════════════════════════════════════════
    print("\n── 3. 用户登录 ──")

    # 3a. 正常登录
    code, resp, cookie = request("POST", "/api/auth/login", {
        "username": "testuser",
        "password": "test123456",
    })
    session_cookie = cookie
    test("正常登录", code == 200 and resp.get("user", {}).get("username") == "testuser",
         f"session={session_cookie[:40]}...")

    # 3b. 错误密码
    code, resp, _ = request("POST", "/api/auth/login", {
        "username": "testuser",
        "password": "wrongpassword",
    })
    test("拒绝错误密码", code == 401, str(resp.get("error", "")))

    # 3c. 获取当前用户
    code, resp, _ = request("GET", "/api/auth/me", cookies=session_cookie)
    test("获取当前用户", code == 200 and resp.get("user", {}).get("username") == "testuser",
         f"email={resp.get('user', {}).get('email')}")

    # ════════════════════════════════════════════════════════
    # 4. 策略保存
    # ════════════════════════════════════════════════════════
    print("\n── 4. 策略保存 ──")

    strategy_payloads = [
        {
            "name": "沪深300趋势跟踪策略",
            "family": "趋势跟踪",
            "risk_profile": "均衡",
            "symbol_code": "510300",
            "symbol_name": "沪深300ETF",
            "benchmark_code": "510300",
            "window": "近3年",
            "enhanced": True,
            "engine": "native",
            "factor_blend": {
                "base_factor": {"id": "trend_ma_20_60", "name": "20/60日均线趋势"},
                "user_factor": {"hypothesis": "订单增加驱动价格上行"},
                "user_weight": 0.35,
            },
            "notes": "基于铜矿需求增加的一手观察",
        },
        {
            "name": "创业板均值回归策略",
            "family": "均值回归",
            "risk_profile": "保守",
            "symbol_code": "159915",
            "symbol_name": "创业板ETF",
            "window": "近1年",
            "enhanced": True,
            "engine": "native",
            "notes": "超跌反弹策略，低仓位控制风险",
        },
        {
            "name": "科创50 VBT基准线策略",
            "family": "趋势跟踪",
            "risk_profile": "进取",
            "symbol_code": "588000",
            "symbol_name": "科创50ETF",
            "benchmark_code": "510300",
            "window": "近6个月",
            "enhanced": True,
            "engine": "vbt",
            "factor_blend": {
                "base_factor": {"id": "benchmark_relative_zscore", "name": "基准线Z-score"},
                "user_factor": {"hypothesis": "科创相对沪深300持续走强"},
                "user_weight": 0.30,
            },
        },
        {
            "name": "多策略投票稳健版",
            "family": "多策略投票",
            "risk_profile": "均衡",
            "symbol_code": "510500",
            "symbol_name": "中证500ETF",
            "window": "全部",
            "enhanced": True,
            "engine": "native",
        },
    ]

    saved_strategies = []
    for i, payload in enumerate(strategy_payloads):
        code, resp, _ = request("POST", "/api/strategies", data=payload, cookies=session_cookie)
        ok = code == 201
        test(f"保存策略 #{i+1}: {payload['name']}", ok,
             f"id={resp.get('strategy', {}).get('id')}, family={payload['family']}")
        if ok:
            saved_strategies.append(resp["strategy"])

    # 列出所有策略
    code, resp, _ = request("GET", "/api/strategies", cookies=session_cookie)
    test("列出策略列表", code == 200 and resp.get("total") == 4,
         f"total={resp.get('total')}, per_page={resp.get('per_page')}")

    # 按家族筛选
    code, resp, _ = request("GET", "/api/strategies?family=趋势跟踪", cookies=session_cookie)
    test("按家族筛选", code == 200 and resp.get("total", 0) >= 2,
         f"趋势跟踪数量={resp.get('total')}")

    # 未登录拒绝
    code, resp, _ = request("GET", "/api/strategies")
    test("未登录拒绝访问", code == 401, str(resp.get("error", "")))

    # ════════════════════════════════════════════════════════
    # 5. 回测结果保存
    # ════════════════════════════════════════════════════════
    print("\n── 5. 回测结果保存 ──")

    backtest_payloads = [
        {
            "total_return": 0.0569,
            "benchmark_return": 0.3219,
            "excess_return": -0.2650,
            "max_drawdown": -0.0679,
            "sharpe_ratio": 0.60,
            "win_rate": 0.50,
            "trade_count": 3,
            "holding_ratio": 0.58,
            "data_start": "2025-06-18",
            "data_end": "2026-07-01",
            "data_rows": 252,
            "extra_metrics": {"engine": "vbt", "mode": "csv"},
        },
        {
            "total_return": 0.1225,
            "benchmark_return": 0.3219,
            "excess_return": -0.1994,
            "max_drawdown": -0.0325,
            "sharpe_ratio": 1.91,
            "win_rate": 1.00,
            "trade_count": 5,
            "holding_ratio": 0.18,
            "data_start": "2025-06-18",
            "data_end": "2026-07-01",
            "data_rows": 252,
            "extra_metrics": {"engine": "vbt", "family": "布林带反转"},
        },
        {
            "total_return": -0.0173,
            "benchmark_return": 0.3219,
            "excess_return": -0.3392,
            "max_drawdown": -0.0709,
            "sharpe_ratio": -0.19,
            "win_rate": 0.0,
            "trade_count": 2,
            "holding_ratio": 0.02,
            "data_start": "2025-06-18",
            "data_end": "2026-07-01",
            "data_rows": 252,
            "extra_metrics": {"engine": "vbt", "factor_type": "external_rsi"},
        },
    ]

    strategy_ids = [s["id"] for s in saved_strategies]
    for i, payload in enumerate(backtest_payloads):
        sid = strategy_ids[min(i, len(strategy_ids) - 1)]
        code, resp, _ = request("POST", f"/api/strategies/{sid}/results", data=payload, cookies=session_cookie)
        ok = code == 201
        test(f"保存回测结果 #{i+1} (策略ID={sid})", ok,
             f"return={payload['total_return']:.2%}, sharpe={payload['sharpe_ratio']:.2f}")
        if not ok:
            print(f"         ERROR: {resp}")

    # 查询回测结果
    sid = strategy_ids[0]
    code, resp, _ = request("GET", f"/api/strategies/{sid}/results", cookies=session_cookie)
    test("查询回测结果列表", code == 200 and len(resp.get("results", [])) > 0,
         f"strategy_id={sid}, count={len(resp.get('results', []))}")

    # ════════════════════════════════════════════════════════
    # 6. 账户概览
    # ════════════════════════════════════════════════════════
    print("\n── 6. 账户概览 ──")

    code, resp, _ = request("GET", "/api/account/summary", cookies=session_cookie)
    test("策略总数正确", resp.get("strategy_count") == 4,
         f"strategies={resp.get('strategy_count')}")
    test("回测结果总数正确", resp.get("result_count", 0) >= 3,
         f"results={resp.get('result_count')}")
    test("最近策略列表", len(resp.get("recent_strategies", [])) == 4,
         f"recent={len(resp.get('recent_strategies', []))}")

    # ════════════════════════════════════════════════════════
    # 7. 数据隔离 (多用户)
    # ════════════════════════════════════════════════════════
    print("\n── 7. 数据隔离 ──")

    # user2 登录
    code, resp, cookie2 = request("POST", "/api/auth/login", {
        "username": "user2", "password": "password123",
    })
    test("user2 登录成功", code == 200)

    # user2 看不到 testuser 的策略
    code, resp, _ = request("GET", "/api/strategies", cookies=cookie2)
    test("user2 看不到 testuser 的数据", resp.get("total") == 0,
         f"total={resp.get('total')} (预期 0)")

    # user2 保存自己的策略
    code, resp, _ = request("POST", "/api/strategies", data={
        "name": "user2 的独立策略",
        "family": "趋势跟踪",
        "risk_profile": "均衡",
        "symbol_code": "600519",
        "symbol_name": "贵州茅台",
    }, cookies=cookie2)
    test("user2 保存自己的策略", code == 201,
         f"id={resp.get('strategy', {}).get('id')}")

    # testuser 看不到 user2 的策略
    code, resp, _ = request("GET", "/api/strategies", cookies=session_cookie)
    test("testuser 看不到 user2 的数据", resp.get("total") == 4,
         f"total={resp.get('total')} (预期 4，只有自己的)")

    # ════════════════════════════════════════════════════════
    # 8. 策略删除
    # ════════════════════════════════════════════════════════
    print("\n── 8. 策略删除 ──")

    code, resp, _ = request("DELETE", f"/api/strategies/{strategy_ids[-1]}", cookies=session_cookie)
    test("删除策略", code == 200, str(resp.get("message", "")))

    code, resp, _ = request("GET", "/api/strategies", cookies=session_cookie)
    test("删除后总数减少", resp.get("total") == 3,
         f"total={resp.get('total')} (预期 3)")

    # ════════════════════════════════════════════════════════
    # 汇总
    # ════════════════════════════════════════════════════════
    print()
    print("=" * 60)
    total = PASS + FAIL
    print(f"  测试完成: {total} 项  |  ✅ 通过: {PASS}  |  ❌ 失败: {FAIL}")
    if FAIL == 0:
        print("  🎉 全部通过！")
    else:
        print(f"  ⚠ 有 {FAIL} 项失败，请检查")
    print("=" * 60)

    return PASS, FAIL


def save_results():
    """保存测试结果到 OUTPUT_DIR。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON 格式
    report = {
        "test_time": datetime.now().isoformat(),
        "total": PASS + FAIL,
        "passed": PASS,
        "failed": FAIL,
        "all_passed": FAIL == 0,
        "results": RESULTS,
    }
    json_path = OUTPUT_DIR / f"test_report_{timestamp}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[已保存] JSON → {json_path}")

    # Markdown 格式
    md_lines = [
        f"# 智塔 Strata 后台测试报告",
        f"",
        f"**测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**数据库**: SQLite (instance/strata.db)",
        f"**总计**: {PASS + FAIL} 项 | ✅ {PASS} 通过 | ❌ {FAIL} 失败",
        f"",
        f"## 测试结果",
        f"",
        f"| # | 测试项 | 结果 | 详情 |",
        f"|---|--------|------|------|",
    ]
    for i, r in enumerate(RESULTS, 1):
        md_lines.append(f"| {i} | {r['name']} | {r['status']} | {r.get('detail', '')} |")

    md_lines.extend([
        "",
        "## 数据库模型",
        "",
        "| 表 | 说明 |",
        "|---|------|",
        "| users | 用户账户 (username, email, password_hash) |",
        "| strategies | 策略信息 (name, family, risk, symbol, engine, factor_blend) |",
        "| backtest_results | 回测收益数据 (return, sharpe, max_dd, win_rate, trades...) |",
        "",
        "## API 端点",
        "",
        "| 方法 | 路径 | 说明 |",
        "|------|------|------|",
        "| POST | /api/auth/register | 用户注册 |",
        "| POST | /api/auth/login | 用户登录 |",
        "| POST | /api/auth/logout | 退出登录 |",
        "| GET | /api/auth/me | 当前用户信息 |",
        "| GET | /api/strategies | 策略列表 (支持 ?family= & ?page=) |",
        "| POST | /api/strategies | 保存策略 |",
        "| GET | /api/strategies/:id | 策略详情 |",
        "| DELETE | /api/strategies/:id | 删除策略 |",
        "| GET | /api/strategies/:id/results | 回测结果列表 |",
        "| POST | /api/strategies/:id/results | 保存回测结果 |",
        "| GET | /api/account/summary | 账户概览 |",
        "| GET | /api/health | 健康检查 |",
    ])

    md_path = OUTPUT_DIR / f"test_report_{timestamp}.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[已保存] Markdown → {md_path}")

    # 简短摘要
    summary_path = OUTPUT_DIR / "LATEST_SUMMARY.txt"
    summary_path.write_text(
        f"最新测试: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"结果: {PASS} 通过 / {FAIL} 失败 / {PASS + FAIL} 总计\n"
        f"{'ALL PASSED' if FAIL == 0 else 'SOME FAILED'}\n",
        encoding="utf-8",
    )
    print(f"[已保存] 摘要 → {summary_path}")


if __name__ == "__main__":
    # 等待服务启动
    print("[等待] 确保 Flask 服务已启动在 http://localhost:5000 ...")
    for i in range(5):
        try:
            code, _, _ = request("GET", "/api/health")
            if code == 200:
                break
        except Exception:
            pass
        print(f"  等待中... ({i+1}/5)")
        time.sleep(2)
    else:
        print("[错误] 无法连接到 Flask 服务。请先启动: python app.py")
        sys.exit(1)

    # 通过 API 重置数据库，得到干净测试环境
    print("[清理] 通过 API 重置数据库...")
    code, resp, _ = request("POST", "/api/admin/reset-db")
    if code == 200:
        print(f"  数据库已重置: {resp.get('message')}")
    else:
        print(f"  重置失败: {resp}")

    run_tests()
    save_results()
