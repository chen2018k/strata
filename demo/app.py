from __future__ import annotations

import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from agent_runtime import OpenAICompatibleClient, has_llm_env
from backtest_bridge import (
    VALID_FAMILIES,
    VALID_RISKS,
    VALID_WINDOWS,
    BacktestSpec,
    analyze_backtest_result,
    propose_backtest_spec,
    run_backtest_from_spec,
    summarize_result_for_user,
)
from factor_library import factor_blend_payload
from dev_shortcuts import apply_dev_shortcut
from interview_agent import (
    InterviewQuestion,
    InterviewTemplate,
    StrategyPrototype,
    generate_strategy_prototype,
    load_templates,
    next_question,
    run_interview_turn,
)
from strategyforge import load_symbols, format_pct


st.set_page_config(page_title="智塔 Strata", page_icon="ST", layout="wide")

APP_COPY_VERSION = "clean-css-v1"

APP_DIR = Path(__file__).resolve().parent
CSS_PATH = APP_DIR / "assets" / "strata.css"
ASSISTANT_AVATAR = str(APP_DIR / "assets" / "avatar_assistant.svg")
USER_AVATAR = str(APP_DIR / "assets" / "avatar_user.svg")
DEMO_ACCOUNT = {"username": "123", "email": "123@strata.local", "password": "123123"}
st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def authenticate_user(identity: str, password: str) -> dict | None:
    key = identity.strip().lower()
    if key == DEMO_ACCOUNT["username"] and password == DEMO_ACCOUNT["password"]:
        return DEMO_ACCOUNT
    users = st.session_state.get("auth_users", {})
    user = users.get(key)
    if user is None:
        user = next((item for item in users.values() if item.get("username", "").lower() == key), None)
    if not user or user.get("password") != password:
        return None
    return user


def session_defaults(template: InterviewTemplate) -> None:
    if st.session_state.get("copy_version") != APP_COPY_VERSION:
        st.session_state.answers = {}
        st.session_state.messages = [{"role": "assistant", "content": template.opening_message}]
        st.session_state.prototype = None
        st.session_state.last_template_id = template.id
        st.session_state.copy_version = APP_COPY_VERSION
        st.session_state.pending_user_input = None
        st.session_state.follow_up_questions = []
        st.session_state.follow_up_answers = {}
        st.session_state.follow_up_index = 0
        st.session_state.backtest_ready = False
        st.session_state.show_backtest_controls = False
        st.session_state.backtest_spec = None
        st.session_state.backtest_result = None
        st.session_state.suggestion_cache = {}
        st.session_state.awaiting_strategy_confirmation = False
        st.session_state.pending_strategy_creation = False
        st.session_state.backtest_transition = False
        st.session_state.transition_started_at = None
        st.session_state.interview_archive = []
        st.session_state.live_signal = None
        st.session_state.account_profile = {"name": "访客", "email": "", "plan": "本地 Demo"}
        st.session_state.auth_user = None
        st.session_state.auth_users = {}
        st.session_state.saved_strategies = []
        st.session_state.auth_prompt = False
        st.session_state.account_dashboard = False
        st.session_state.landing_auth_mode = None
        st.session_state.live_dashboard = False
        st.session_state.live_strategy = None
        st.session_state.account_dialog = None
        st.session_state.started = False
        st.session_state.current_view = "landing"
    st.session_state.setdefault("template_id", template.id)
    st.session_state.setdefault("answers", {})
    st.session_state.setdefault("messages", [{"role": "assistant", "content": template.opening_message}])
    st.session_state.setdefault("prototype", None)
    st.session_state.setdefault("last_template_id", template.id)
    st.session_state.setdefault("copy_version", APP_COPY_VERSION)
    st.session_state.setdefault("pending_user_input", None)
    st.session_state.setdefault("follow_up_questions", [])
    st.session_state.setdefault("follow_up_answers", {})
    st.session_state.setdefault("follow_up_index", 0)
    st.session_state.setdefault("backtest_ready", False)
    st.session_state.setdefault("show_backtest_controls", False)
    st.session_state.setdefault("backtest_spec", None)
    st.session_state.setdefault("backtest_result", None)
    st.session_state.setdefault("suggestion_cache", {})
    st.session_state.setdefault("awaiting_strategy_confirmation", False)
    st.session_state.setdefault("pending_strategy_creation", False)
    st.session_state.setdefault("backtest_transition", False)
    st.session_state.setdefault("transition_started_at", None)
    st.session_state.setdefault("interview_archive", [])
    st.session_state.setdefault("live_signal", None)
    st.session_state.setdefault("account_profile", {"name": "访客", "email": "", "plan": "本地 Demo"})
    st.session_state.setdefault("auth_user", None)
    st.session_state.setdefault("auth_users", {})
    st.session_state.setdefault("saved_strategies", [])
    st.session_state.setdefault("auth_prompt", False)
    st.session_state.setdefault("account_dashboard", False)
    st.session_state.setdefault("landing_auth_mode", None)
    st.session_state.setdefault("live_dashboard", False)
    st.session_state.setdefault("live_strategy", None)
    st.session_state.setdefault("account_dialog", None)
    st.session_state.setdefault("started", False)
    st.session_state.setdefault("current_view", "landing")


def reset_session(template: InterviewTemplate) -> None:
    st.session_state.answers = {}
    st.session_state.messages = [{"role": "assistant", "content": template.opening_message}]
    st.session_state.prototype = None
    st.session_state.last_template_id = template.id
    st.session_state.copy_version = APP_COPY_VERSION
    st.session_state.pending_user_input = None
    st.session_state.follow_up_questions = []
    st.session_state.follow_up_answers = {}
    st.session_state.follow_up_index = 0
    st.session_state.backtest_ready = False
    st.session_state.show_backtest_controls = False
    st.session_state.backtest_spec = None
    st.session_state.backtest_result = None
    st.session_state.suggestion_cache = {}
    st.session_state.awaiting_strategy_confirmation = False
    st.session_state.pending_strategy_creation = False
    st.session_state.backtest_transition = False
    st.session_state.transition_started_at = None
    st.session_state.interview_archive = []
    st.session_state.live_signal = None
    st.session_state.account_profile = {"name": "访客", "email": "", "plan": "本地 Demo"}
    st.session_state.started = True
    st.session_state.current_view = "chat"


def progress_state(template: InterviewTemplate, answers: dict[str, str], prototype) -> tuple[int, str]:
    answered = len([question for question in template.questions if question.id in answers])
    if prototype is not None:
        return 3, "策略雏形"
    if answered >= len(template.questions):
        return 2, "生成雏形"
    if answered > 0:
        return 1, "采访中"
    return 0, "准备采访"


def render_steps(active_index: int) -> None:
    labels = ["1. 选择脚本", "2. 对话采访", "3. 生成雏形", "4. 后续验证"]
    parts = ['<div class="stepbar">']
    for idx, label in enumerate(labels):
        cls = "active" if idx == active_index else "done" if idx < active_index else ""
        parts.append(f'<div class="step {cls}">{label}</div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def question_message(question: InterviewQuestion) -> str:
    return question.prompt


def render_workflow_rail(active_index: int) -> None:
    steps = [
        ("01", "对话", "提取观察"),
        ("02", "策略", "形成雏形"),
        ("03", "回测", "历史验证"),
        ("04", "部署", "接口预留"),
    ]
    parts = ['<aside class="workflow-rail" aria-label="策略流程进度">']
    for idx, (number, title, caption) in enumerate(steps):
        cls = "is-active" if idx == active_index else "is-done" if idx < active_index else ""
        parts.append(
            f'<div class="workflow-step {cls}">'
            f'<span class="workflow-index">{number}</span>'
            f'<strong>{title}</strong>'
            f'<em>{caption}</em>'
            f"</div>"
        )
    parts.append("</aside>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def append_next_question(template: InterviewTemplate) -> None:
    question = next_question(template, st.session_state.answers)
    if question is not None:
        st.session_state.messages.append({"role": "assistant", "content": question_message(question)})


def render_prototype(prototype) -> None:
    st.markdown('<div class="prototype-card">', unsafe_allow_html=True)
    st.subheader(prototype.title)
    st.markdown(f"**一手观察总结**  \n{prototype.observation_summary}")
    st.markdown(f"**策略因子假设**  \n{prototype.factor_hypothesis}")
    st.markdown(f"**朴素策略雏形**  \n{prototype.naive_strategy}")
    st.markdown(f"**标的范围**  \n{prototype.target_universe}")
    st.markdown("**标准量化模块**")
    st.markdown(" ".join(f'<span class="pill">{item}</span>' for item in prototype.standard_modules), unsafe_allow_html=True)
    st.markdown("**风控补全**")
    st.markdown(" ".join(f'<span class="pill">{item}</span>' for item in prototype.risk_controls), unsafe_allow_html=True)
    st.markdown(f"**验证计划**  \n{prototype.validation_plan}")
    if prototype.missing_info:
        st.markdown("**仍需补充**")
        for item in prototype.missing_info:
            st.markdown(f"- {item}")
    st.markdown("</div>", unsafe_allow_html=True)


def prototype_message(prototype) -> str:
    modules = "、".join(str(item) for item in getattr(prototype, "standard_modules", ()) if str(item).strip())
    risks = "、".join(str(item) for item in getattr(prototype, "risk_controls", ()) if str(item).strip())
    return (
        f"我先把你的策略雏形整理出来：\n\n"
        f"### {getattr(prototype, 'title', '策略雏形')}\n\n"
        f"**一手观察**\n\n{getattr(prototype, 'observation_summary', '已经收到你的观察。')}\n\n"
        f"**策略因子假设**\n\n{getattr(prototype, 'factor_hypothesis', '这条观察可能成为可继续验证的策略因子。')}\n\n"
        f"**朴素交易逻辑**\n\n{getattr(prototype, 'naive_strategy', '先验证观察是否持续，再进入回测。')}\n\n"
        f"**候选标的范围**\n\n{getattr(prototype, 'target_universe', '待确认')}\n\n"
        f"**建议补全的标准量化模块**\n\n{modules}\n\n"
        f"**基础风控**\n\n{risks}\n\n"
        f"**后续验证计划**\n\n{getattr(prototype, 'validation_plan', '进入历史数据回测，观察收益、回撤和稳定性。')}"
    )


def normalize_follow_up_questions(prototype: StrategyPrototype | None) -> list[str]:
    if prototype is None:
        return []

    raw_questions = getattr(prototype, "follow_up_questions", ()) or ()
    raw_missing = getattr(prototype, "missing_info", ()) or ()
    normalized: list[str] = []

    for item in list(raw_questions) + [f"关于{item}，你能补充一个更具体的说法吗？" for item in raw_missing]:
        if isinstance(item, dict):
            text = item.get("question") or item.get("prompt") or item.get("text") or item.get("title")
        else:
            text = item
        text = str(text or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized[:4]


def generate_and_append_prototype(template: InterviewTemplate, answers: dict[str, str]) -> None:
    llm = OpenAICompatibleClient.from_env() if has_llm_env() else None
    try:
        prototype = generate_strategy_prototype(template, answers, llm=llm)
    except Exception as exc:
        prototype = generate_strategy_prototype(template, answers, llm=None)
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": f"模型接口暂时没有跑通，我先用本地规则生成一个可讨论的版本。错误信息：{exc}",
            }
        )
    st.session_state.prototype = prototype
    st.session_state.messages.append({"role": "assistant", "content": prototype_message(prototype)})


def begin_follow_up_or_backtest(prototype: StrategyPrototype) -> None:
    questions = normalize_follow_up_questions(prototype)
    st.session_state.follow_up_questions = questions
    st.session_state.follow_up_index = 0
    st.session_state.follow_up_answers = {}
    st.session_state.backtest_result = None
    st.session_state.backtest_spec = None
    if questions:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": "这版雏形可以先成立。但是还有几个问题需要再和你确认，我会一个一个问。",
            }
        )
        st.session_state.messages.append({"role": "assistant", "content": questions[0]})
        st.session_state.backtest_ready = False
    else:
        st.session_state.messages.append(
            {"role": "assistant", "content": "这版策略已经可以进入历史回测。你可以先跑一轮结果，再决定要不要继续调整。"}
        )
        st.session_state.backtest_ready = True


def handle_follow_up_answer(template: InterviewTemplate, answers: dict[str, str], user_text: str) -> None:
    questions = [str(item).strip() for item in (st.session_state.get("follow_up_questions") or []) if str(item).strip()]
    index = int(st.session_state.get("follow_up_index") or 0)
    if not questions or index >= len(questions):
        st.session_state.follow_up_questions = []
        st.session_state.follow_up_index = 0
        st.session_state.backtest_ready = True
        st.session_state.messages.append(
            {"role": "assistant", "content": "这条策略雏形已经可以先进入历史回测。我们先看一轮结果，再决定要不要继续补充。"}
        )
        return

    if index < len(questions):
        key = f"follow_up_{index + 1}"
        st.session_state.follow_up_answers[key] = {"question": questions[index], "answer": user_text}
        answers[key] = f"{questions[index]}：{user_text}"

    next_index = index + 1
    st.session_state.follow_up_index = next_index
    if next_index < len(questions):
        st.session_state.messages.append({"role": "assistant", "content": "收到，我先把这条补充记进策略里。"})
        st.session_state.messages.append({"role": "assistant", "content": f"下一个我想确认：\n\n{questions[next_index]}"})
        return

    llm = OpenAICompatibleClient.from_env() if has_llm_env() else None
    try:
        refined = generate_strategy_prototype(template, answers, llm=llm)
    except Exception:
        refined = generate_strategy_prototype(template, answers, llm=None)
    st.session_state.prototype = refined
    st.session_state.messages.append({"role": "assistant", "content": "收到，追问信息已经补齐。我把它合进策略雏形里。"})
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": "现在这条策略已经可以进入历史回测。\n\n" + prototype_message(refined),
        }
    )
    st.session_state.backtest_ready = True
    st.session_state.show_backtest_controls = False
    st.session_state.follow_up_questions = []
    st.session_state.follow_up_index = 0
    st.session_state.backtest_result = None
    st.session_state.backtest_spec = None


def scroll_to_latest() -> None:
    components.html(
        """
        <script>
          setTimeout(() => {
            const doc = window.parent.document;
            const anchor = doc.getElementById("chat-scroll-anchor");
            if (anchor) {
              anchor.scrollIntoView({ behavior: "smooth", block: "end" });
            }
          }, 80);
        </script>
        """,
        height=0,
    )


def render_thinking() -> None:
    st.markdown(
        """
        <div class="thinking-bubble" aria-label="正在思考">
          <span></span><span></span><span></span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def submit_user_text(text: str, template: InterviewTemplate) -> None:
    cleaned = text.strip()
    if not cleaned:
        return
    if cleaned in {"重新开始", "重来", "/reset"}:
        reset_session(template)
        st.rerun()

    st.session_state.awaiting_strategy_confirmation = False
    st.session_state.messages.append({"role": "user", "content": cleaned})
    st.session_state.pending_user_input = cleaned
    st.session_state.current_view = "chat"
    st.rerun()


def latest_assistant_prompt() -> str:
    for message in reversed(st.session_state.get("messages", [])):
        if message.get("role") == "assistant":
            return str(message.get("content") or "")
    return ""


def current_follow_up_prompt() -> str:
    questions = [str(item).strip() for item in (st.session_state.get("follow_up_questions") or []) if str(item).strip()]
    index = int(st.session_state.get("follow_up_index") or 0)
    if questions and index < len(questions):
        return questions[index]
    return ""


def _short_option(text: object) -> str:
    value = str(text or "").strip()
    for prefix in ("-", "•", "1.", "2.", "3.", "4.", "选项", "回答"):
        value = value.removeprefix(prefix).strip()
    value = value.replace("。", "").replace("，", " ").replace("、", " ")
    return value[:7].strip()


def _normalize_suggestions(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    normalized: list[str] = []
    for item in items:
        value = _short_option(item)
        if value and value not in normalized:
            normalized.append(value)
        if len(normalized) == 4:
            break
    return normalized


def fallback_suggestions_for(prompt: str) -> list[str]:
    text = prompt.lower()
    if any(keyword in text for keyword in ["来源", "看到", "确定", "数据", "哪里"]):
        return ["客户订单", "渠道反馈", "公开数据", "还要确认"]
    if any(keyword in text for keyword in ["行业", "订单", "库存", "价格", "供需", "渠道", "变化"]):
        return ["订单增加", "库存偏低", "价格上调", "需求更强"]
    if any(keyword in text for keyword in ["标的", "股票", "etf", "范围", "资产"]):
        return ["行业ETF", "龙头公司", "上游资源", "先不确定"]
    if any(keyword in text for keyword in ["风险", "回撤", "仓位", "亏损", "止损"]):
        return ["偏保守", "均衡", "能承受波动", "小仓位试"]
    if any(keyword in text for keyword in ["时间", "周期", "多久", "窗口", "回测"]):
        return ["近3个月", "近6个月", "近1年", "完整周期"]
    if any(keyword in text for keyword in ["量化", "定义", "指标", "阈值", "分位"]):
        return ["历史分位", "同比变化", "环比变化", "均线趋势"]
    return ["订单增加", "库存偏低", "价格变化", "继续问我"]


def suggested_answers_for(prompt: str) -> list[str]:
    prompt = str(prompt or "").strip()
    if not prompt:
        return []

    cache = st.session_state.setdefault("suggestion_cache", {})
    recent_messages = st.session_state.get("messages", [])[-8:]
    cache_key = str(abs(hash((prompt, tuple((m.get("role"), m.get("content")) for m in recent_messages)))))
    if cache_key in cache:
        return cache[cache_key]

    llm = OpenAICompatibleClient.from_env() if has_llm_env() else None
    if llm is None:
        return []

    llm.timeout = 20
    history = "\n".join(
        f"{message.get('role', '')}: {str(message.get('content', ''))[:180]}"
        for message in recent_messages
    )
    try:
        payload = llm.complete_json(
            "你是智塔 Strata 的策略采访助手。你只负责生成用户下一步可以点击的简短回答选项。",
            (
                "根据当前问题和最近对话，生成 4 个建议回答。\n"
                "要求：\n"
                "1. 只返回 JSON：{\"answers\":[\"...\",\"...\",\"...\",\"...\"]}。\n"
                "2. 每个答案 3 到 7 个汉字，必须简洁、自然、像用户会直接点击的回答。\n"
                "3. 必须贴合当前问题，不能泛泛重复“订单增加、库存偏低、价格变化”。\n"
                "4. 四个答案要覆盖不同方向，例如数据来源、时间窗口、强弱程度、标的范围、风险偏好等。\n"
                "5. 不要解释，不要标点，不要编号。\n\n"
                f"当前问题：{prompt}\n\n"
                f"最近对话：\n{history}"
            ),
        )
        suggestions = _normalize_suggestions(payload.get("answers"))
    except Exception:
        return []

    if len(suggestions) < 4:
        return []

    cache[cache_key] = suggestions[:4]
    return cache[cache_key]

def determine_current_prompt() -> str:
    """根据当前状态，确定要展示建议按钮的上下文 prompt。"""
    # 追问优先
    follow_up = current_follow_up_prompt()
    if follow_up:
        return follow_up
    # 其次是最新的 assistant 消息
    return latest_assistant_prompt()


def render_fixed_composer(template: InterviewTemplate, current_view: str, pending_user_input: str | None) -> None:
    if current_view != "chat":
        return

    prompt = determine_current_prompt()
    has_user_message = any(message.get("role") == "user" for message in st.session_state.get("messages", []))
    placeholder = "" if has_user_message else "开始和小塔聊聊你的想法或行业观察吧"
    user_text = st.chat_input(placeholder, key="fixed_chat_input")
    if user_text:
        submit_user_text(user_text, template)
    st.markdown('<div class="fixed-suggestions-anchor"></div>', unsafe_allow_html=True)
    suggestions = [] if st.session_state.get("awaiting_strategy_confirmation") else suggested_answers_for(prompt)[:4] if prompt and not pending_user_input else []
    if suggestions:
        clicked_suggestion = None
        key_base = abs(hash(prompt))
        columns = st.columns(len(suggestions))
        for index, suggestion in enumerate(suggestions):
            with columns[index]:
                if st.button(
                    suggestion,
                    key=f"fixed_quick_{key_base}_{index}",
                    type="secondary",
                    use_container_width=True,
                ):
                    clicked_suggestion = suggestion
        if clicked_suggestion:
            submit_user_text(clicked_suggestion, template)


def render_strategy_confirmation_actions(template: InterviewTemplate, answers: dict[str, str]) -> None:
    if not st.session_state.get("awaiting_strategy_confirmation"):
        return

    left, right = st.columns([1, 1])
    with left:
        if st.button("创建策略雏形", key="create_strategy_prototype", type="primary", use_container_width=True):
            st.session_state.awaiting_strategy_confirmation = False
            st.session_state.pending_strategy_creation = True
            st.rerun()
    with right:
        if st.button("再聊聊", key="continue_strategy_interview", type="secondary", use_container_width=True):
            st.session_state.awaiting_strategy_confirmation = False
            st.session_state.backtest_ready = False
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": "可以，我们再补充一点。你想再聊哪一块：新的行业观察、数据来源、风险条件，还是具体标的范围？",
                }
            )
            st.rerun()

def render_inline_followup_input(template: InterviewTemplate) -> None:
    with st.form("strategy_followup_form", clear_on_submit=True):
        user_text = st.text_input(
            "继续补充",
            key="strategy_followup_text",
            placeholder="在这里补充你的回答",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("提交回答", type="primary", use_container_width=True)
        if submitted and user_text:
            submit_user_text(user_text, template)


def render_suggestions(prompt: str, template: InterviewTemplate) -> None:
    """已弃用：保留兼容，实际建议已移到输入框上方。"""
    pass


def render_landing_page() -> None:
    st.markdown(
        """
        <main class="landing-page">
          <nav class="landing-nav">
            <div class="landing-brand"><span class="landing-mark"></span><span>智塔 Strata</span></div>
            <div class="landing-auth-actions-slot"></div>
          </nav>
          <section class="landing-hero">
            <div class="landing-kicker">把你的一手观察，变成可测试的交易策略</div>
            <h1><span>让小塔开始</span><span>构建你的策略</span></h1>
            <p>你只需要说出行业、订单、库存、价格或供需变化。小塔会一步步追问，把朴素判断整理成策略雏形，再进入回测。</p>
            <div class="landing-cta-slot">
              <a class="landing-start-link" href="?start=1" target="_self">开始使用</a>
            </div>
          </section>
          <section class="landing-steps">
            <article class="landing-step"><span>1</span><strong>采访观察</strong><p>先聊你最近看到的确定变化，不需要先写策略。</p></article>
            <article class="landing-step"><span>2</span><strong>形成雏形</strong><p>把行业经验补全为因子、标的范围和风险条件。</p></article>
            <article class="landing-step"><span>3</span><strong>进入验证</strong><p>用确定性的回测接口检查收益、回撤和稳定性。</p></article>
          </section>
        </main>
        """,
        unsafe_allow_html=True,
    )


def render_landing_auth_buttons() -> None:
    left, right = st.columns([1, 1])
    with left:
        if st.button("\u767b\u5f55", key="landing_login_action", use_container_width=True):
            st.session_state.landing_auth_mode = "login"
            st.rerun()
    with right:
        if st.button("\u6ce8\u518c", key="landing_register_action", use_container_width=True):
            st.session_state.landing_auth_mode = "register"
            st.rerun()


def _format_summary_table(summary):
    display = summary.copy()
    for column in ["累计收益", "基准收益", "超额收益", "最大回撤", "胜率", "持仓天数占比"]:
        if column in display.columns:
            display[column] = display[column].map(lambda value: format_pct(float(value)))
    if "夏普比率" in display.columns:
        display["夏普比率"] = display["夏普比率"].map(lambda value: f"{float(value):.2f}")
    return display





def start_backtest_transition() -> None:
    st.session_state.interview_archive = list(st.session_state.get("messages", []))
    st.session_state.messages = []
    st.session_state.pending_user_input = None
    st.session_state.suggestion_cache = {}
    st.session_state.awaiting_strategy_confirmation = False
    st.session_state.pending_strategy_creation = False
    st.session_state.show_backtest_controls = True
    st.session_state.backtest_transition = True
    st.session_state.transition_started_at = time.time()
    st.session_state.current_view = "transition"


def render_backtest_transition(template: InterviewTemplate, answers: dict[str, str]) -> None:
    started_at = st.session_state.get("transition_started_at") or time.time()
    elapsed = time.time() - float(started_at)
    spec_ready = st.session_state.get("backtest_spec") is not None
    progress = 1.0 if spec_ready else min(0.94, elapsed / 1.4)
    progress_pct = int(progress * 100)
    st.markdown(
        f"""
        <section class="stage-page transition-stage">
          <div class="transition-card">
            <span>Backtest loading</span>
            <h2>\u6b63\u5728\u51c6\u5907\u56de\u6d4b</h2>
            <div class="transition-progress" aria-label="backtest loading">
              <i style="width: {progress_pct}%"></i>
            </div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    if elapsed < 1.4:
        time.sleep(0.18)
        st.rerun()
    if st.session_state.get("backtest_spec") is None and st.session_state.get("prototype") is not None:
        try:
            llm = OpenAICompatibleClient.from_env() if has_llm_env() else None
            st.session_state.backtest_spec = propose_backtest_spec(st.session_state.prototype, answers, llm=llm)
        except Exception:
            st.session_state.backtest_spec = BacktestSpec(
                symbol_code="510500",
                benchmark_code="510300",
                family=VALID_FAMILIES[1],
                risk_profile=VALID_RISKS[1],
                enhanced=True,
                window=VALID_WINDOWS[2],
                base_factor_id="rsi_reversal",
                user_factor_weight=0.2,
            )
        time.sleep(0.18)
        st.rerun()
    st.session_state.backtest_transition = False
    st.session_state.transition_started_at = None
    st.session_state.current_view = "backtest"
    st.rerun()


def save_current_strategy(prototype, spec: BacktestSpec, result: dict) -> dict:
    summary = result["summary"]
    best = summary.iloc[0]
    saved = {
        "title": getattr(prototype, "title", "策略雏形"),
        "description": getattr(prototype, "summary", "") or getattr(prototype, "user_factor", ""),
        "symbol": spec.symbol_code,
        "benchmark": spec.benchmark_code,
        "family": spec.family,
        "risk_profile": spec.risk_profile,
        "window": spec.window,
        "best_variant": str(best["方案"]) if "方案" in best.index else str(best.iloc[0]),
        "total_return": float(best["累计收益"]) if "累计收益" in best.index else 0.0,
        "max_drawdown": float(best["最大回撤"]) if "最大回撤" in best.index else 0.0,
        "sharpe": float(best["夏普比率"]) if "夏普比率" in best.index else 0.0,
        "owner": (st.session_state.get("auth_user") or {}).get("email", ""),
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "live_status": "saved",
    }
    st.session_state.saved_strategies = [saved, *list(st.session_state.get("saved_strategies", []))]
    return saved


def continue_chat_after_backtest(template: InterviewTemplate) -> None:
    restart_interview_from_first_question(template)
    st.session_state.auth_prompt = False


def restart_interview_from_first_question(template: InterviewTemplate) -> None:
    auth_user = st.session_state.get("auth_user")
    auth_users = st.session_state.get("auth_users", {})
    saved_strategies = st.session_state.get("saved_strategies", [])
    account_profile = st.session_state.get("account_profile", {"name": "访客", "email": "", "plan": "本地 Demo"})
    reset_session(template)
    st.session_state.auth_user = auth_user
    st.session_state.auth_users = auth_users
    st.session_state.saved_strategies = saved_strategies
    st.session_state.account_profile = account_profile
    st.session_state.account_dashboard = False


@st.dialog("登录或注册")
def render_auth_save_prompt(prototype, spec: BacktestSpec, result: dict) -> None:
    st.caption("登录或注册后，这次回测结果会保存到你的策略记录里。")
    login_tab, register_tab = st.tabs(["登录", "注册"])

    with login_tab:
        with st.form("strategy_save_login_form"):
            identity = st.text_input("用户名 / 邮箱", key="login_identity")
            password = st.text_input("密码", type="password", key="login_password")
            submitted = st.form_submit_button("登录并保存", use_container_width=True)
        if submitted:
            user = authenticate_user(identity, password)
            if not user or user.get("password") != password:
                st.error("用户名或密码错误。")
            else:
                st.session_state.auth_user = {"name": user["username"], "email": user["email"]}
                st.session_state.account_profile = {"name": user["username"], "email": user["email"], "plan": "本地 Demo"}
                save_current_strategy(prototype, spec, result)
                st.session_state.auth_prompt = False
                st.session_state.account_dashboard = True
                st.session_state.show_backtest_controls = False
                st.success("已保存到当前账号。")
                st.rerun()

    with register_tab:
        with st.form("strategy_save_register_form"):
            username = st.text_input("用户名", key="register_username")
            email = st.text_input("邮箱", key="register_email")
            password = st.text_input("密码", type="password", key="register_password")
            submitted = st.form_submit_button("注册并保存", use_container_width=True)
        if submitted:
            clean_email = email.strip().lower()
            clean_username = username.strip() or clean_email.split("@")[0]
            if not clean_email or not password:
                st.error("请填写邮箱和密码。")
            elif clean_email in st.session_state.auth_users:
                st.error("这个邮箱已经注册。")
            else:
                st.session_state.auth_users[clean_email] = {
                    "username": clean_username,
                    "email": clean_email,
                    "password": password,
                }
                st.session_state.auth_user = {"name": clean_username, "email": clean_email}
                st.session_state.account_profile = {"name": clean_username, "email": clean_email, "plan": "本地 Demo"}
                save_current_strategy(prototype, spec, result)
                st.session_state.auth_prompt = False
                st.session_state.account_dashboard = True
                st.session_state.show_backtest_controls = False
                st.success("注册完成，策略已保存。")
                st.rerun()

    if st.button("暂不保存", key="dismiss_auth_prompt", use_container_width=True):
        st.session_state.auth_prompt = False
        st.rerun()


def render_post_backtest_actions(template: InterviewTemplate, prototype, spec: BacktestSpec, result: dict) -> None:
    st.markdown('<div class="post-backtest-actions-marker"></div>', unsafe_allow_html=True)
    left, right = st.columns(2)
    with left:
        if st.button("\u4fdd\u5b58\u8be5\u7b56\u7565", key="save_backtested_strategy", use_container_width=True):
            if st.session_state.get("auth_user"):
                save_current_strategy(prototype, spec, result)
                st.session_state.account_dashboard = True
                st.session_state.show_backtest_controls = False
                st.success("\u5df2\u4fdd\u5b58\u5230\u5f53\u524d\u8d26\u53f7\u3002")
                st.rerun()
            else:
                st.session_state.auth_prompt = True
                st.rerun()
    with right:
        if st.button("\u518d\u804a\u804a", key="continue_chat_refine_strategy", use_container_width=True):
            continue_chat_after_backtest(template)
            st.rerun()
    if st.session_state.get("auth_prompt"):
        render_auth_save_prompt(prototype, spec, result)




@st.dialog("\u767b\u5f55\u6216\u6ce8\u518c")
def render_landing_auth_prompt() -> None:
    mode = st.session_state.get("landing_auth_mode") or "login"
    login_tab, register_tab = st.tabs(["\u767b\u5f55", "\u6ce8\u518c"])

    with login_tab:
        with st.form("landing_login_form"):
            identity = st.text_input("\u7528\u6237\u540d / \u90ae\u7bb1", key="landing_login_identity")
            password = st.text_input("\u5bc6\u7801", type="password", key="landing_login_password")
            submitted = st.form_submit_button("\u767b\u5f55", use_container_width=True)
        if submitted:
            user = authenticate_user(identity, password)
            if not user:
                st.error("\u7528\u6237\u540d\u6216\u5bc6\u7801\u9519\u8bef\u3002")
            else:
                st.session_state.auth_user = {"name": user["username"], "email": user["email"]}
                st.session_state.account_profile = {"name": user["username"], "email": user["email"], "plan": "\u672c\u5730 Demo"}
                st.session_state.started = True
                st.session_state.account_dashboard = True
                st.session_state.live_dashboard = False
                st.session_state.current_view = "account"
                st.session_state.landing_auth_mode = None
                st.rerun()

    with register_tab:
        with st.form("landing_register_form"):
            username = st.text_input("\u7528\u6237\u540d", key="landing_register_username")
            email = st.text_input("\u90ae\u7bb1", key="landing_register_email")
            password = st.text_input("\u5bc6\u7801", type="password", key="landing_register_password")
            submitted = st.form_submit_button("\u6ce8\u518c", use_container_width=True)
        if submitted:
            clean_email = email.strip().lower()
            clean_username = username.strip() or clean_email.split("@")[0]
            if not clean_email or not password:
                st.error("\u8bf7\u586b\u5199\u90ae\u7bb1\u548c\u5bc6\u7801\u3002")
            elif clean_email in st.session_state.auth_users:
                st.error("\u8fd9\u4e2a\u90ae\u7bb1\u5df2\u7ecf\u6ce8\u518c\u3002")
            else:
                st.session_state.auth_users[clean_email] = {
                    "username": clean_username,
                    "email": clean_email,
                    "password": password,
                }
                st.session_state.auth_user = {"name": clean_username, "email": clean_email}
                st.session_state.account_profile = {"name": clean_username, "email": clean_email, "plan": "\u672c\u5730 Demo"}
                st.session_state.started = True
                st.session_state.account_dashboard = True
                st.session_state.live_dashboard = False
                st.session_state.current_view = "account"
                st.session_state.landing_auth_mode = None
                st.rerun()

    if mode == "register":
        st.caption("\u53ef\u76f4\u63a5\u5207\u5230\u6ce8\u518c\u9875\u7b7e\u5b8c\u6210\u521b\u5efa\u8d26\u53f7\u3002")


def find_saved_strategy(record_id: str) -> dict | None:
    for item in st.session_state.get("saved_strategies", []):
        if item.get("record_id") == record_id:
            return item
    return None


@st.dialog("\u7f16\u8f91\u7b56\u7565")
def render_record_edit_dialog(record_id: str) -> None:
    item = find_saved_strategy(record_id)
    if item is None:
        st.warning("\u8fd9\u6761\u7b56\u7565\u8bb0\u5f55\u5df2\u4e0d\u5b58\u5728\u3002")
        if st.button("\u5173\u95ed", key=f"close_missing_edit_{record_id}", use_container_width=True):
            st.session_state.account_dialog = None
            st.rerun()
        return

    with st.form(f"record_edit_form_{record_id}"):
        new_title = st.text_input(
            "\u7b56\u7565\u540d\u79f0",
            value=str(item.get("title") or "\u672a\u547d\u540d\u7b56\u7565"),
            key=f"record_title_{record_id}",
        )
        new_description = st.text_area(
            "\u7b56\u7565\u7b80\u4ecb",
            value=str(item.get("description") or item.get("user_factor") or ""),
            key=f"record_description_{record_id}",
            height=96,
        )
        saved_edit = st.form_submit_button("\u4fdd\u5b58\u4fee\u6539", use_container_width=True)

    if saved_edit:
        item["title"] = new_title.strip() or item.get("title") or "\u672a\u547d\u540d\u7b56\u7565"
        item["description"] = new_description.strip()
        st.session_state.account_dialog = None
        st.rerun()

    if st.button("\u53d6\u6d88", key=f"cancel_edit_{record_id}", use_container_width=True):
        st.session_state.account_dialog = None
        st.rerun()


@st.dialog("\u5220\u9664\u7b56\u7565")
def render_record_delete_dialog(record_id: str) -> None:
    item = find_saved_strategy(record_id)
    title = (item or {}).get("title") or "\u8fd9\u6761\u7b56\u7565"
    st.markdown(f"\u786e\u8ba4\u5220\u9664\u300c{title}\u300d\u5417\uff1f\u5220\u9664\u540e\u4e0d\u4f1a\u5728\u5f53\u524d\u672c\u5730\u8d26\u6237\u8bb0\u5f55\u4e2d\u663e\u793a\u3002")
    cancel_col, delete_col = st.columns([1, 1])
    with cancel_col:
        if st.button("\u53d6\u6d88", key=f"cancel_delete_{record_id}", use_container_width=True):
            st.session_state.account_dialog = None
            st.rerun()
    with delete_col:
        if st.button("\u786e\u8ba4\u5220\u9664", key=f"confirm_delete_{record_id}", use_container_width=True):
            st.session_state.saved_strategies = [
                record for record in st.session_state.get("saved_strategies", []) if record.get("record_id") != record_id
            ]
            st.session_state.account_dialog = None
            st.rerun()



def render_account_panel() -> None:
    profile = st.session_state.get("account_profile") or {"name": "\u8bbf\u5ba2", "email": "", "plan": "\u672c\u5730 Demo"}
    user = st.session_state.get("auth_user")
    owner = (user or {}).get("email", "")
    saved = [item for item in list(st.session_state.get("saved_strategies", [])) if not owner or item.get("owner") == owner]
    display_name = (user or {}).get("name") or profile.get("name") or "\u8bbf\u5ba2"
    display_email = (user or {}).get("email") or profile.get("email") or ""
    initial = (display_name or "S").strip()[:1].upper()
    running_count = len([item for item in saved if item.get("live_status") == "running"])

    st.markdown(
        f'''
        <div class="account-dashboard-marker"></div>
        <section class="account-dashboard">
          <div class="account-card account-overview-card">
            <div class="account-user account-user-main">
              <div class="account-avatar">{initial}</div>
              <div>
                <strong>{display_name}</strong>
                <span>{display_email or "\u672a\u7ed1\u5b9a\u90ae\u7bb1"}</span>
              </div>
            </div>
            <div class="account-overview-meta">
              <div><b>{len(saved)}</b><span>\u7b56\u7565</span></div>
              <div><b>{running_count}</b><span>\u8fd0\u884c\u4e2d</span></div>
              <div class="account-status"><i></i><span>\u5df2\u767b\u5f55</span></div>
            </div>
          </div>
        </section>
        ''',
        unsafe_allow_html=True,
    )

    left, right = st.columns([1, 1])
    with left:
        if st.button("\u9000\u51fa\u767b\u5f55", key="logout_account", use_container_width=True):
            st.session_state.auth_user = None
            st.session_state.account_profile = {"name": "\u8bbf\u5ba2", "email": "", "plan": "\u672c\u5730 Demo"}
            st.session_state.account_dashboard = False
            st.session_state.live_dashboard = False
            st.session_state.current_view = "chat"
            st.rerun()
    with right:
        if st.button("\u7ee7\u7eed\u7b56\u7565\u5bf9\u8bdd", key="account_back_to_chat", use_container_width=True):
            st.session_state.account_dashboard = False
            st.session_state.current_view = "chat"
            st.rerun()

    st.markdown(
        f'<div class="account-section-title"><h3>\u7b56\u7565\u8bb0\u5f55</h3><span>{len(saved)} \u6761\u8bb0\u5f55</span></div>',
        unsafe_allow_html=True,
    )
    if not saved:
        st.markdown(
            '<div class="account-empty">\u8fd8\u6ca1\u6709\u4fdd\u5b58\u7b56\u7565\u3002\u5b8c\u6210\u4e00\u6b21\u56de\u6d4b\u540e\uff0c\u70b9\u51fb\u4fdd\u5b58\u5373\u53ef\u51fa\u73b0\u5728\u8fd9\u91cc\u3002</div>',
            unsafe_allow_html=True,
        )
        return

    for index, item in enumerate(saved, start=1):
        item.setdefault("record_id", f"record_{int(time.time() * 1000)}_{index}")
        total_return = float(item.get("total_return", 0) or 0)
        max_drawdown = float(item.get("max_drawdown", 0) or 0)
        sharpe = float(item.get("sharpe", 0) or 0)
        title = item.get("title") or f"\u7b56\u7565 {index}"
        description = item.get("description") or item.get("user_factor") or ""
        benchmark = item.get("benchmark") or "-"
        best_variant = item.get("best_variant") or item.get("family") or "-"
        ret_class = "pos" if total_return >= 0 else "neg"
        status = item.get("live_status") or "saved"
        status_label = "\u8fd0\u884c\u4e2d" if status == "running" else "\u5df2\u4fdd\u5b58"
        status_class = "running" if status == "running" else "completed"
        st.markdown(
            f'''
            <article class="account-record-card {status_class}">
              <div class="record-topline">
                <strong>{title}</strong>
                <span class="record-status {status_class}">{status_label}</span>
              </div>
              <p class="record-description">{description or "\u6682\u65e0\u7b80\u4ecb"}</p>
              <div class="record-tags">
                <span>\u6807\u7684 {item.get("symbol", "-")}</span>
                <span>\u57fa\u51c6 {benchmark}</span>
                <span>{best_variant}</span>
                <span>{item.get("risk_profile", "-")}</span>
              </div>
              <div class="record-metrics">
                <div><span>\u6536\u76ca</span><b class="{ret_class}">{format_pct(total_return)}</b></div>
                <div><span>\u56de\u64a4</span><b>{format_pct(max_drawdown)}</b></div>
                <div><span>\u590f\u666e</span><b>{sharpe:.2f}</b></div>
              </div>
            </article>
            ''',
            unsafe_allow_html=True,
        )
        edit_col, live_col, delete_col = st.columns([1, 1, 1])
        record_key = item["record_id"]
        with edit_col:
            if st.button("\u25e7 \u7f16\u8f91", key=f"record_edit_{record_key}", use_container_width=True):
                st.session_state.account_dialog = {"kind": "edit", "record_id": record_key}
                st.rerun()
        with live_col:
            live_label = "\u25b6 \u63a5\u5165\u5b9e\u76d8" if status != "running" else "\u25cf \u8fd0\u884c\u4e2d"
            if st.button(live_label, key=f"live_connect_{record_key}", use_container_width=True):
                item["live_status"] = "running"
                st.session_state.live_strategy = item
                st.session_state.live_dashboard = True
                st.session_state.account_dashboard = False
                st.session_state.current_view = "live"
                st.rerun()
        with delete_col:
            if st.button("\u2715 \u5220\u9664", key=f"record_delete_{record_key}", use_container_width=True):
                st.session_state.account_dialog = {"kind": "delete", "record_id": record_key}
                st.rerun()

    dialog = st.session_state.get("account_dialog")
    if dialog and dialog.get("kind") == "edit":
        render_record_edit_dialog(dialog.get("record_id", ""))
    elif dialog and dialog.get("kind") == "delete":
        render_record_delete_dialog(dialog.get("record_id", ""))


def render_live_trading_panel() -> None:
    strategy = st.session_state.get("live_strategy") or {}
    title = strategy.get("title") or "\u672a\u547d\u540d\u7b56\u7565"
    st.markdown(
        f'''
        <div class="live-dashboard-marker"></div>
        <section class="live-dashboard">
          <div class="live-hero-card">
            <span>Live Trading Workspace</span>
            <h2>\u5b9e\u76d8\u8fd0\u884c\u754c\u9762\u6b63\u5728\u65bd\u5de5</h2>
            <p>\u5f53\u524d\u7b56\u7565\uff1a{title}\u3002\u8fd9\u91cc\u4f1a\u4fdd\u7559\u5238\u5546\u3001\u884c\u60c5\u3001\u8d26\u6237\u6743\u9650\u3001\u4e0b\u5355\u548c\u98ce\u63a7\u63a5\u53e3\u3002</p>
          </div>
        </section>
        ''',
        unsafe_allow_html=True,
    )
    st.markdown("### \u5b9e\u76d8\u63a5\u5165\u53c2\u6570")
    left, right = st.columns(2)
    with left:
        st.selectbox("\u8fd0\u884c\u73af\u5883", ["Paper Trading / \u6a21\u62df\u76d8", "Live Trading / \u5b9e\u76d8"], key="live_env_mode")
        st.selectbox("\u5238\u5546\u63a5\u53e3", ["IBKR", "Alpaca", "QuantConnect", "\u672c\u5730\u5238\u5546\u7f51\u5173"], key="live_broker_provider")
        st.text_input("Broker API Base URL", value="BROKER_API_BASE_URL", key="live_broker_url")
        st.text_input("Account ID", value="ACCOUNT_ID", key="live_account_id")
    with right:
        st.selectbox("\u884c\u60c5\u6e90", ["Broker Market Data", "Eastmoney", "Tushare", "Local Realtime Feed"], key="live_data_provider")
        st.text_input("Market Data API URL", value="MARKET_DATA_API_URL", key="live_market_url")
        st.text_input("API Key / OAuth Token", value="\u540e\u7eed\u63a5\u5165\u5bc6\u94a5\u7ba1\u7406", key="live_api_key")
        st.text_input("Webhook / Callback URL", value="STRATA_LIVE_CALLBACK_URL", key="live_callback_url")

    st.markdown("### \u98ce\u63a7\u4e0e\u4e0b\u5355\u8bbe\u7f6e")
    a, b, c = st.columns(3)
    with a:
        st.selectbox("\u8ba2\u5355\u7c7b\u578b", ["Market", "Limit", "Stop", "Stop Limit"], key="live_order_type")
    with b:
        st.slider("\u5355\u7b56\u7565\u6700\u5927\u4ed3\u4f4d", 0.0, 1.0, 0.25, 0.05, key="live_max_position")
    with c:
        st.slider("\u5355\u65e5\u6700\u5927\u4e8f\u635f", 0.0, 0.2, 0.03, 0.01, key="live_daily_loss")
    if st.button("\u56de\u5230\u8d26\u6237 Dashboard", key="live_back_account", use_container_width=True):
        st.session_state.live_dashboard = False
        st.session_state.account_dashboard = True
        st.session_state.current_view = "account"
        st.rerun()


def render_live_validation_panel(spec: BacktestSpec, result: dict | None) -> None:
    st.markdown("#### \u5b9e\u76d8 / \u7eb8\u9762\u9a8c\u8bc1\u63a5\u53e3")
    left, right, third = st.columns(3)
    with left:
        data_mode = st.selectbox("\u884c\u60c5\u6e90", ["\u672c\u5730 CSV", "Eastmoney", "\u5238\u5546\u63a5\u53e3\u5360\u4f4d"], key="live_data_mode")
    with right:
        current_position = st.slider("\u5f53\u524d\u4ed3\u4f4d", 0.0, 1.0, 0.0, 0.05, key="live_current_position")
    with third:
        auto_guard = st.checkbox("\u542f\u7528\u98ce\u63a7\u786e\u8ba4", value=True, key="live_auto_guard")

    if st.button("\u751f\u6210\u7eb8\u9762\u4fe1\u53f7", key="generate_live_signal", use_container_width=True):
        risk_target = {"\u4fdd\u5b88": 0.35, "\u5747\u8861": 0.55, "\u8fdb\u53d6": 0.75}.get(str(spec.risk_profile), 0.55)
        target_position = risk_target if spec.enhanced else max(0.0, risk_target - 0.15)
        delta = target_position - current_position
        action = "\u4fdd\u6301" if abs(delta) < 0.03 else "\u52a0\u4ed3" if delta > 0 else "\u51cf\u4ed3"
        st.session_state.live_signal = {"data_mode": data_mode, "target_position": target_position, "current_position": current_position, "action": action, "guard": auto_guard}

    signal = st.session_state.get("live_signal")
    if signal:
        a, b, c = st.columns(3)
        a.metric("\u5efa\u8bae\u52a8\u4f5c", signal["action"])
        b.metric("\u76ee\u6807\u4ed3\u4f4d", format_pct(float(signal["target_position"])))
        c.metric("\u5f53\u524d\u4ed3\u4f4d", format_pct(float(signal["current_position"])))
        st.caption("\u8fd9\u662f\u7eb8\u9762\u9a8c\u8bc1\u4fe1\u53f7\uff0c\u4e0d\u4ee3\u8868\u5b9e\u76d8\u4e70\u5356\u6307\u4ee4\u3002\u5238\u5546\u63a5\u53e3\u3001\u8ba2\u5355\u786e\u8ba4\u548c\u98ce\u63a7\u5ba1\u6838\u7559\u4f5c\u540e\u7eed\u63a5\u5165\u70b9\u3002")
    elif result is None:
        st.info("\u5148\u5b8c\u6210\u4e00\u6b21\u5386\u53f2\u56de\u6d4b\uff0c\u518d\u751f\u6210\u7eb8\u9762\u4fe1\u53f7\u3002")


def render_backtest_panel(template: InterviewTemplate, answers: dict[str, str]) -> None:
    prototype = st.session_state.prototype
    if prototype is None or not st.session_state.backtest_ready:
        return

    try:
        factor_blend = factor_blend_payload(prototype, answers)
    except Exception as exc:
        st.warning(f"\u7b56\u7565\u96cf\u5f62\u8fd8\u7f3a\u5c11\u53ef\u6620\u5c04\u5230\u56e0\u5b50\u5e93\u7684\u4fe1\u606f\uff0c\u53ef\u4ee5\u5148\u7ee7\u7eed\u8865\u5145\u4e00\u4e24\u53e5\u89c2\u5bdf\u3002\u9519\u8bef\u4fe1\u606f\uff1a{exc}")
        st.session_state.backtest_ready = False
        return

    if not st.session_state.show_backtest_controls:
        if st.button("\u8fdb\u5165\u4e0b\u4e00\u6b65\u56de\u6d4b", type="primary", use_container_width=True):
            start_backtest_transition()
            st.rerun()
        return

    symbols = load_symbols()
    symbol_labels = {item.label: item.code for item in symbols}
    code_to_label = {item.code: item.label for item in symbols}
    llm = OpenAICompatibleClient.from_env() if has_llm_env() else None
    if st.session_state.backtest_spec is None:
        try:
            st.session_state.backtest_spec = propose_backtest_spec(prototype, answers, llm=llm)
        except Exception as exc:
            st.warning(f"\u6682\u65f6\u65e0\u6cd5\u628a\u7b56\u7565\u96cf\u5f62\u6620\u5c04\u5230\u56de\u6d4b\u53c2\u6570\u3002\u53ef\u4ee5\u5148\u8865\u5145\u6807\u7684\u8303\u56f4\u6216\u89c2\u5bdf\u6307\u6807\u3002\u9519\u8bef\u4fe1\u606f\uff1a{exc}")
            return

    spec: BacktestSpec = st.session_state.backtest_spec
    result = st.session_state.backtest_result
    st.markdown('<div class="backtest-workbench-marker"></div>', unsafe_allow_html=True)
    st.markdown("### \u56de\u6d4b\u5de5\u4f5c\u53f0")
    st.markdown(
        f"""
        <div class="factor-brief">
          <div><span>\u57fa\u7840\u56e0\u5b50</span><strong>{factor_blend['base_factor']['name']}</strong></div>
          <div><span>\u7528\u6237\u56e0\u5b50</span><strong>{factor_blend['user_factor']['hypothesis']}</strong></div>
          <div><span>\u7ec4\u5408\u65b9\u5f0f</span><strong>{factor_blend['reason']}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    target_label = st.selectbox("\u56de\u6d4b\u6807\u7684", list(symbol_labels), index=list(symbol_labels).index(code_to_label.get(spec.symbol_code, symbols[0].label)))
    benchmark_label = st.selectbox("\u5bf9\u7167\u57fa\u51c6", list(symbol_labels), index=list(symbol_labels).index(code_to_label.get(spec.benchmark_code, symbols[0].label)))
    left, right = st.columns(2)
    with left:
        family = st.selectbox("\u7b56\u7565\u4ee3\u7801", list(VALID_FAMILIES), index=list(VALID_FAMILIES).index(spec.family))
        window = st.selectbox("\u65f6\u95f4\u7a97\u53e3", list(VALID_WINDOWS), index=list(VALID_WINDOWS).index(spec.window))
    with right:
        risk = st.selectbox("\u98ce\u9669\u6863\u4f4d", list(VALID_RISKS), index=list(VALID_RISKS).index(spec.risk_profile))
        enhanced = st.checkbox("\u542f\u7528\u786e\u5b9a\u6027\u98ce\u63a7\u589e\u5f3a", value=spec.enhanced)

    if st.button("\u8fd0\u884c\u56de\u6d4b", type="primary", use_container_width=True):
        chosen = BacktestSpec(symbol_code=symbol_labels[target_label], benchmark_code=symbol_labels[benchmark_label], family=family, risk_profile=risk, enhanced=enhanced, window=window, base_factor_id=factor_blend["base_factor"]["id"], user_factor_weight=float(factor_blend["user_weight"]))
        st.session_state.backtest_spec = chosen
        st.session_state.backtest_result = run_backtest_from_spec(chosen)
        st.session_state.backtest_result["factor_blend"] = factor_blend
        st.session_state.live_signal = None
        st.rerun()

    if result is None:
        return

    st.markdown("#### \u5386\u53f2\u56de\u6d4b\u7ed3\u679c")
    curves = result["curves"].set_index("date")
    summary = result["summary"]
    best = summary.iloc[0]
    best_variant = str(best["方案"]) if "方案" in best.index else str(best.iloc[0])
    total_return = float(best["累计收益"]) if "累计收益" in best.index else 0.0
    max_drawdown = float(best["最大回撤"]) if "最大回撤" in best.index else 0.0
    sharpe = float(best["夏普比率"]) if "夏普比率" in best.index else 0.0
    highest = summary.sort_values("\u7d2f\u8ba1\u6536\u76ca", ascending=False).iloc[0] if "\u7d2f\u8ba1\u6536\u76ca" in summary.columns else best
    safest = summary.sort_values("\u6700\u5927\u56de\u64a4", ascending=False).iloc[0] if "\u6700\u5927\u56de\u64a4" in summary.columns else best
    curve_count = max(0, len(curves.columns) - 1)
    st.markdown(
        f"""
        <div class="backtest-result-cards">
          <div><span>\u7efc\u5408\u6700\u4f73</span><strong>{best_variant}</strong><em>\u6536\u76ca {format_pct(total_return)} / \u56de\u64a4 {format_pct(max_drawdown)}</em></div>
          <div><span>\u6536\u76ca\u6700\u9ad8</span><strong>{highest.get("\u65b9\u6848", "-")}</strong><em>{format_pct(float(highest.get("\u7d2f\u8ba1\u6536\u76ca", 0)))}</em></div>
          <div><span>\u56de\u64a4\u8f83\u4f4e</span><strong>{safest.get("\u65b9\u6848", "-")}</strong><em>{format_pct(float(safest.get("\u6700\u5927\u56de\u64a4", 0)))}</em></div>
          <div><span>\u590f\u666e / \u6837\u672c</span><strong>{sharpe:.2f}</strong><em>{len(summary)} \u4e2a\u7b56\u7565\u7248\u672c\uff0c{curve_count} \u6761\u66f2\u7ebf</em></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("##### \u65b9\u6848\u660e\u7ec6")
    st.dataframe(_format_summary_table(summary), hide_index=True, use_container_width=True)
    st.line_chart(curves)
    render_post_backtest_actions(template, prototype, st.session_state.backtest_spec, result)

templates = load_templates()
template_by_name = {template.name: template for template in templates}
default_template = templates[0]
template = default_template
session_defaults(template)
apply_dev_shortcut(template)

answers: dict[str, str] = st.session_state.answers

if not st.session_state.get("started") and st.query_params.get("start") == "1":
    st.session_state.started = True
    st.session_state.current_view = "chat"
    st.query_params.clear()
    st.rerun()

if not st.session_state.get("started") and st.query_params.get("auth") in {"login", "register"}:
    st.session_state.landing_auth_mode = st.query_params.get("auth")
    st.query_params.clear()
    st.rerun()

if st.query_params.get("dev_entry") == "1":
    st.info("测试入口：用于跳过前置采访流程。")
    left, right = st.columns(2)
    with left:
        if st.button("跳到策略雏形确认", key="dev_jump_prototype", use_container_width=True):
            st.query_params["dev"] = "prototype"
            st.rerun()
    with right:
        if st.button("跳到可进入回测", key="dev_jump_backtest_ready", use_container_width=True):
            st.query_params["dev"] = "backtest_ready"
            st.rerun()

if not st.session_state.get("started"):
    render_landing_page()
    render_landing_auth_buttons()
    if st.session_state.get("landing_auth_mode"):
        render_landing_auth_prompt()
    st.stop()

if len(st.session_state.messages) == 1 and not answers:
    append_next_question(template)

prototype = st.session_state.get("prototype")
if st.session_state.get("live_dashboard"):
    current_view = "live"
elif st.session_state.get("account_dashboard"):
    current_view = "account"
elif st.session_state.get("backtest_transition"):
    current_view = "transition"
elif st.session_state.get("show_backtest_controls") or st.session_state.get("backtest_result") is not None:
    current_view = "backtest"
else:
    current_view = "chat"
st.session_state.current_view = current_view

workflow_index = 3 if current_view == "live" else 2 if current_view in {"backtest", "account"} else 1 if prototype is not None else 0
render_workflow_rail(workflow_index)

model_status = "模型已连接" if has_llm_env() else "本地规则模式"
pending_user_input = st.session_state.get("pending_user_input")
if current_view == "chat":
    st.markdown('<div class="product-shell chat-stage chat-state-marker"></div>', unsafe_allow_html=True)
    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar=(ASSISTANT_AVATAR if message["role"] == "assistant" else USER_AVATAR)):
            st.markdown(message["content"])
    if pending_user_input:
        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            render_thinking()
    if st.session_state.get("pending_strategy_creation"):
        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            render_thinking()
    render_strategy_confirmation_actions(template, answers)
    strategy_locked = bool(
        st.session_state.get("awaiting_strategy_confirmation")
        or st.session_state.get("pending_strategy_creation")
        or (prototype is not None and st.session_state.get("backtest_ready"))
    )
    if st.session_state.get("backtest_ready") and prototype is not None and not pending_user_input and not st.session_state.get("awaiting_strategy_confirmation"):
        if st.button("\u8fdb\u5165\u4e0b\u4e00\u6b65\u56de\u6d4b", type="primary", use_container_width=True):
            start_backtest_transition()
            st.rerun()
    if not strategy_locked:
        render_fixed_composer(template, current_view, pending_user_input)

elif current_view == "transition":
    render_backtest_transition(template, answers)

elif current_view == "strategy":
    follow_up_prompt = current_follow_up_prompt()
    st.markdown('<section class="stage-page strategy-stage"><div class="strategy-panel">', unsafe_allow_html=True)
    st.markdown("## 策略雏形")
    if prototype is not None:
        st.markdown(prototype_message(prototype))
    if follow_up_prompt:
        st.markdown(f'<div class="strategy-followup"><strong>下一步确认</strong><p>{follow_up_prompt}</p></div>', unsafe_allow_html=True)
        render_inline_followup_input(template)
    elif st.session_state.get("backtest_ready"):
        st.markdown(
            '<div class="strategy-followup"><strong>可以进入回测</strong><p>这版策略已经形成，下一步用历史数据看收益、回撤和稳定性。</p></div>',
            unsafe_allow_html=True,
        )
        if st.button("进入下一步回测", type="primary", use_container_width=True):
            st.session_state.show_backtest_controls = True
            st.session_state.current_view = "backtest"
            st.rerun()
    if pending_user_input:
        render_thinking()
    st.markdown("</div></section>", unsafe_allow_html=True)

elif current_view == "account":
    st.markdown('<section class="stage-page account-stage"><div class="account-panel">', unsafe_allow_html=True)
    st.markdown("## \u6211\u7684\u8d26\u6237")
    render_account_panel()
    st.markdown("</div></section>", unsafe_allow_html=True)

elif current_view == "live":
    st.markdown('<section class="stage-page live-stage"><div class="live-panel">', unsafe_allow_html=True)
    render_live_trading_panel()
    st.markdown("</div></section>", unsafe_allow_html=True)

else:
    st.session_state.show_backtest_controls = True
    st.markdown('<div class="backtest-page-marker"></div>', unsafe_allow_html=True)
    st.markdown("## 历史回测")
    render_backtest_panel(template, answers)

if pending_user_input:
    scroll_to_latest()
    active_follow_ups = [str(item).strip() for item in (st.session_state.get("follow_up_questions") or []) if str(item).strip()]
    active_follow_up_index = int(st.session_state.get("follow_up_index") or 0)
    if active_follow_ups and active_follow_up_index < len(active_follow_ups):
        handle_follow_up_answer(template, answers, pending_user_input)
    else:
        llm = OpenAICompatibleClient.from_env() if has_llm_env() else None
        turn = run_interview_turn(template, st.session_state.messages, answers, llm=llm)
        answers.clear()
        answers.update(turn.answers)

        if turn.ready_to_generate:
            st.session_state.messages.append({"role": "assistant", "content": turn.reply})
            st.session_state.awaiting_strategy_confirmation = True
            st.session_state.backtest_ready = False
        else:
            st.session_state.awaiting_strategy_confirmation = False
            st.session_state.messages.append({"role": "assistant", "content": turn.reply})

    st.session_state.pending_user_input = None
    st.rerun()

if st.session_state.get("pending_strategy_creation"):
    st.session_state.pending_strategy_creation = False
    st.session_state.awaiting_strategy_confirmation = False
    generate_and_append_prototype(template, answers)
    begin_follow_up_or_backtest(st.session_state.prototype)
    st.rerun()

if (
    not pending_user_input
    and current_view == "chat"
    and not st.session_state.get("awaiting_strategy_confirmation")
    and not (st.session_state.get("prototype") is not None and st.session_state.get("backtest_ready"))
):
    render_suggestions(latest_assistant_prompt(), template)
elif not pending_user_input and current_view == "strategy":
    render_suggestions(current_follow_up_prompt(), template)

st.markdown('<div class="chat-end-spacer"><span id="chat-scroll-anchor"></span></div>', unsafe_allow_html=True)
scroll_to_latest()
