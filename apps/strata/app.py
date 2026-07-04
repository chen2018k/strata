from __future__ import annotations

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

APP_COPY_VERSION = "clarify-backtest-v1"

st.markdown(
    """
    <style>
      :root {
        --canvas: #fbfbfd;
        --canvas-top: #f6f7f9;
        --canvas-mid: #edf0f4;
        --canvas-bottom: #fbfbfd;
        --ink: #17181c;
        --muted: #7a808a;
        --line: rgba(23, 24, 28, .1);
        --surface: rgba(255, 255, 255, .72);
        --surface-strong: rgba(255, 255, 255, .9);
        --shadow: rgba(31, 38, 51, .08);
        --accent: #0a84ff;
      }
      .stApp {
        background: var(--canvas);
        color: var(--ink);
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
      }
      .block-container {
        max-width: 820px;
        min-height: 100dvh;
        padding: 1.1rem 1.35rem 22rem;
      }
      [data-testid="stSidebar"] { display: none; }
      [data-testid="stHeader"] { background: transparent; }
      [data-testid="stToolbar"],
      #MainMenu,
      footer { visibility: hidden; height: 0; }
      [data-testid="stBottom"],
      [data-testid="stBottomBlockContainer"] {
        background: transparent !important;
        box-shadow: none !important;
      }
      [data-testid="stBottom"] {
        position: fixed !important;
        left: 0 !important;
        right: 0 !important;
        bottom: 0 !important;
        z-index: 20 !important;
        display: flex !important;
        justify-content: center !important;
        padding: 1.1rem 1.35rem 1.35rem !important;
        background: transparent !important;
        pointer-events: none;
      }
      [data-testid="stBottom"]::before,
      [data-testid="stBottom"]::after,
      [data-testid="stBottomBlockContainer"]::before,
      [data-testid="stBottomBlockContainer"]::after {
        display: none !important;
        content: none !important;
      }
      [data-testid="stBottomBlockContainer"] {
        width: min(820px, 100%) !important;
        padding: 0 !important;
        pointer-events: auto;
      }
      [data-testid="element-container"]:has(iframe[height="0"]),
      iframe[height="0"] {
        display: none !important;
        height: 0 !important;
        min-height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        border: 0 !important;
        overflow: hidden !important;
      }
      .strata-title {
        position: sticky;
        top: .65rem;
        z-index: 5;
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin: 0 0 2.2rem;
        padding: .58rem .68rem .58rem .84rem;
        border: 1px solid rgba(255, 255, 255, .78);
        border-radius: 999px;
        background:
          linear-gradient(135deg, rgba(255, 255, 255, .82), rgba(255, 255, 255, .58)),
          rgba(255, 255, 255, .62);
        box-shadow: 0 18px 60px var(--shadow), inset 0 1px 0 rgba(255, 255, 255, .9);
        backdrop-filter: blur(22px) saturate(160%);
        -webkit-backdrop-filter: blur(22px) saturate(160%);
      }
      .strata-title h1 {
        font-size: 1rem;
        line-height: 1;
        margin: 0;
        letter-spacing: 0;
        font-weight: 760;
      }
      .strata-title .brand-pill {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 4.4rem;
        height: 2rem;
        border-radius: 999px;
        background: rgba(23, 24, 28, .92);
        color: #f7f8fb;
        font-size: .82rem;
        font-weight: 650;
      }
      [data-testid="stChatMessage"] {
        padding: .34rem 0 !important;
        background: transparent !important;
      }
      [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
        max-width: 62ch;
        padding: .94rem 1.02rem;
        border: 1px solid rgba(255, 255, 255, .78);
        border-radius: 24px 24px 24px 8px;
        background: var(--surface);
        box-shadow: 0 12px 38px rgba(31, 38, 51, .06), inset 0 1px 0 rgba(255, 255, 255, .82);
        backdrop-filter: blur(18px) saturate(145%);
        -webkit-backdrop-filter: blur(18px) saturate(145%);
      }
      [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p {
        line-height: 1.74;
      }
      [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h3 {
        margin-top: .1rem;
        font-size: 1.05rem;
      }
      [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] ul {
        margin-top: .35rem;
      }
      .thinking-bubble {
        display: inline-flex;
        align-items: center;
        gap: .34rem;
        min-width: 4.4rem;
      }
      .thinking-bubble span {
        width: .42rem;
        height: .42rem;
        border-radius: 999px;
        background: rgba(122, 128, 138, .86);
        animation: strata-dot 1s infinite ease-in-out;
      }
      .thinking-bubble span:nth-child(2) { animation-delay: .14s; }
      .thinking-bubble span:nth-child(3) { animation-delay: .28s; }
      .chat-end-spacer {
        height: 20rem;
      }
      #chat-scroll-anchor {
        display: block;
        height: 1px;
      }
      @keyframes strata-dot {
        0%, 80%, 100% {
          transform: translateY(0);
          opacity: .36;
        }
        40% {
          transform: translateY(-.26rem);
          opacity: 1;
        }
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        display: flex !important;
        flex-direction: row-reverse !important;
        align-items: flex-start !important;
        justify-content: flex-start !important;
        gap: .68rem !important;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"],
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) > div:last-child {
        width: auto !important;
        max-width: calc(100% - 3.2rem) !important;
        flex: 0 1 auto !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: flex-end !important;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stMarkdownContainer"] {
        margin-left: auto !important;
        margin-right: 0 !important;
        max-width: min(62ch, calc(100vw - 8rem));
        border-color: rgba(23, 24, 28, .9);
        border-radius: 24px 24px 8px 24px;
        background: rgba(23, 24, 28, .94);
        color: #f8fafc;
        box-shadow: 0 16px 44px rgba(23, 24, 28, .16);
      }
      [data-testid="stChatMessageAvatarAssistant"],
      [data-testid="stChatMessageAvatarUser"] {
        border: 1px solid rgba(255, 255, 255, .72);
        box-shadow: 0 10px 26px rgba(31, 38, 51, .08);
      }
      [data-testid="stChatInput"] {
        width: 100% !important;
        max-width: 820px;
        margin: 0 auto !important;
        border: 1px solid rgba(255, 255, 255, .78);
        border-radius: 999px;
        background:
          linear-gradient(135deg, rgba(255, 255, 255, .92), rgba(255, 255, 255, .7)),
          rgba(255, 255, 255, .72);
        box-shadow: 0 22px 80px rgba(31, 38, 51, .12), inset 0 1px 0 rgba(255, 255, 255, .9);
        backdrop-filter: blur(24px) saturate(160%);
        -webkit-backdrop-filter: blur(24px) saturate(160%);
      }
      [data-testid="stChatInput"] textarea {
        color: var(--ink) !important;
      }
      [data-testid="stChatInput"] textarea::placeholder {
        color: var(--muted) !important;
      }
      [data-testid="stChatInput"] button {
        border-radius: 999px !important;
      }
      @media (prefers-color-scheme: dark) {
        :root {
          --canvas: #111318;
          --canvas-top: #17191f;
          --canvas-mid: #111318;
          --canvas-bottom: #1d2028;
          --ink: #f5f7fb;
          --muted: #a4aab5;
          --surface: rgba(33, 36, 44, .72);
          --surface-strong: rgba(40, 44, 54, .88);
          --shadow: rgba(0, 0, 0, .3);
        }
        .strata-title {
          border-color: rgba(255, 255, 255, .12);
          background:
            linear-gradient(135deg, rgba(255, 255, 255, .12), rgba(255, 255, 255, .04)),
            rgba(34, 38, 48, .74);
        }
        .strata-title .brand-pill {
          background: rgba(245, 247, 251, .92);
          color: #17181c;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"],
        [data-testid="stChatInput"] {
          border-color: rgba(255, 255, 255, .12);
          background:
            linear-gradient(135deg, rgba(255, 255, 255, .09), rgba(255, 255, 255, .035)),
            var(--surface);
        }
        [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stMarkdownContainer"] {
          background: rgba(245, 247, 251, .92);
          color: #17181c;
          border-color: rgba(245, 247, 251, .72);
        }
        [data-testid="stBottom"] {
          background: transparent !important;
        }
      }
      @media (max-width: 640px) {
        .block-container {
          padding-left: .86rem;
          padding-right: .86rem;
          padding-bottom: 18rem;
        }
        .strata-title {
          margin-bottom: 1.4rem;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
          max-width: 100%;
        }
        [data-testid="stBottom"] {
          padding: .82rem .86rem 1rem !important;
        }
        .chat-end-spacer {
          height: 16rem;
        }
      }

      .stApp {
        background:
          linear-gradient(var(--line) 1px, transparent 1px),
          linear-gradient(90deg, var(--line) 1px, transparent 1px),
          #eeeeee !important;
        background-size: 156px 156px !important;
        color: #050505;
      }
      .block-container {
        max-width: 1120px;
        padding: 1.35rem 1.6rem 24rem 17rem;
      }
      .workflow-rail {
        position: fixed;
        left: 24px;
        top: 50%;
        z-index: 9;
        display: grid;
        gap: 16px;
        width: 142px;
        transform: translateY(-50%);
      }
      .workflow-rail::before {
        content: "";
        position: absolute;
        left: 18px;
        top: 20px;
        bottom: 20px;
        width: 2px;
        background: #050505;
      }
      .workflow-step {
        position: relative;
        display: grid;
        gap: 4px;
        min-height: 82px;
        padding: 12px 12px 12px 46px;
        border: 1px solid #050505;
        background: #fff;
        box-shadow: 5px 5px 0 rgba(0, 0, 0, .08);
      }
      .workflow-step::before {
        content: "";
        position: absolute;
        left: 11px;
        top: 16px;
        width: 16px;
        height: 16px;
        border: 2px solid #050505;
        border-radius: 50%;
        background: #fff;
      }
      .workflow-step.is-active {
        z-index: 1;
        background: #df8b61;
        box-shadow: 8px 8px 0 #050505;
        transform: scale(1.08);
      }
      .workflow-step.is-done {
        background: #efe6a4;
      }
      .workflow-index {
        font-size: .68rem;
        font-weight: 900;
      }
      .workflow-step strong {
        font-size: 1.12rem;
        line-height: 1;
        font-weight: 900;
      }
      .workflow-step em {
        color: #161616;
        font-size: .76rem;
        font-style: normal;
      }
      .strata-title {
        position: relative;
        top: auto;
        z-index: 4;
        margin: 0 0 1.3rem;
        padding: 1rem 1.15rem;
        border: 1px solid #050505;
        border-radius: 0;
        background: rgba(238, 238, 238, .9);
        box-shadow: 8px 8px 0 rgba(0, 0, 0, .09);
        backdrop-filter: none;
        -webkit-backdrop-filter: none;
      }
      .strata-title h1 {
        font-size: 1.25rem;
        font-weight: 900;
      }
      .strata-title .title-copy {
        display: grid;
        gap: .24rem;
      }
      .strata-title .title-copy span {
        color: #3e3e3a;
        font-size: .86rem;
      }
      .strata-title .brand-pill,
      .status-pill {
        border: 1px solid #050505;
        border-radius: 999px;
        background: #050505;
        color: #fff;
        box-shadow: none;
        font-weight: 900;
      }
      .status-pill {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 5.2rem;
        height: 2.1rem;
        padding: 0 .86rem;
        font-size: .8rem;
      }
      .product-shell {
        border: 1px solid #050505;
        background: #f5f5f2;
        box-shadow: 12px 12px 0 rgba(0, 0, 0, .12);
        padding: 1.2rem;
      }
      .backtest-action-panel {
        margin: 2.2rem 0 5rem;
        padding: 1rem 1.08rem;
        border: 1px solid #050505;
        background: #efe6a4;
        box-shadow: 8px 8px 0 rgba(0, 0, 0, .12);
      }
      .backtest-action-panel strong {
        display: block;
        margin-bottom: .2rem;
        font-weight: 900;
      }
      .backtest-action-panel p {
        margin: 0;
        color: #30302d;
        line-height: 1.55;
      }
      .advisor-card {
        display: grid;
        grid-template-columns: 42px 1fr;
        gap: .85rem;
        align-items: start;
        margin-bottom: .9rem;
        padding: .95rem;
        border: 1px solid #050505;
        background: #e7ddb4;
      }
      .advisor-avatar {
        display: grid;
        place-items: center;
        width: 42px;
        height: 42px;
        border: 1px solid #050505;
        border-radius: 50%;
        background: #050505;
        color: #fff;
        font-weight: 900;
      }
      .advisor-card strong {
        display: block;
        margin-bottom: .2rem;
        font-weight: 900;
      }
      .advisor-card p {
        margin: 0;
        color: #30302d;
        line-height: 1.65;
      }
      [data-testid="stChatMessage"] {
        padding: .42rem 0 !important;
      }
      [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
        border: 1px solid #050505;
        border-radius: 0;
        background: #fff;
        box-shadow: 6px 6px 0 rgba(0, 0, 0, .08);
        color: #050505;
        backdrop-filter: none;
        -webkit-backdrop-filter: none;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stMarkdownContainer"] {
        border-color: #050505;
        border-radius: 0;
        background: #050505;
        color: #fff;
        box-shadow: 6px 6px 0 rgba(0, 0, 0, .14);
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        width: 100% !important;
        display: grid !important;
        grid-template-columns: minmax(0, 1fr) auto !important;
        column-gap: .7rem !important;
        justify-content: stretch !important;
        align-items: flex-start !important;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) > div {
        min-width: 0 !important;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) > div:has([data-testid="stChatMessageAvatarUser"]) {
        grid-column: 2 !important;
        grid-row: 1 !important;
        justify-self: end !important;
        width: auto !important;
        max-width: none !important;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) > div:has([data-testid="stMarkdownContainer"]) {
        grid-column: 1 !important;
        grid-row: 1 !important;
        justify-self: end !important;
        width: fit-content !important;
        max-width: min(68%, 640px) !important;
        display: flex !important;
        justify-content: flex-end !important;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageAvatarUser"] {
        grid-column: 2 !important;
        grid-row: 1 !important;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
        grid-column: 1 !important;
        grid-row: 1 !important;
        justify-self: end !important;
        width: fit-content !important;
        max-width: min(68%, 640px) !important;
        min-width: 0 !important;
        display: flex !important;
        justify-content: flex-end !important;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stMarkdownContainer"] {
        width: fit-content !important;
        max-width: 100% !important;
        margin-left: 0 !important;
        margin-right: 0 !important;
        justify-self: end !important;
      }
      [data-testid="stChatMessageAvatarAssistant"],
      [data-testid="stChatMessageAvatarUser"] {
        border: 1px solid #050505;
        box-shadow: 4px 4px 0 rgba(0, 0, 0, .12);
      }
      [data-testid="stBottom"] {
        padding: 1rem 1.6rem 1.25rem 17rem !important;
      }
      [data-testid="stBottomBlockContainer"] {
        max-width: 1120px !important;
      }
      [data-testid="stChatInput"] {
        max-width: 1040px;
        border: 1px solid #050505;
        border-radius: 999px;
        background: #fff;
        box-shadow: 8px 8px 0 rgba(0, 0, 0, .12);
        backdrop-filter: none;
        -webkit-backdrop-filter: none;
      }
      .prototype-card,
      [data-testid="stVerticalBlock"]:has(.prototype-card) {
        border-radius: 0;
      }
      .stButton > button,
      div[data-testid="stButton"] button {
        border: 1px solid #050505 !important;
        border-radius: 999px !important;
        background: #050505 !important;
        color: #fff !important;
        font-weight: 900 !important;
        box-shadow: 5px 5px 0 rgba(0, 0, 0, .12) !important;
      }
      div[data-testid="stButton"] {
        margin: .85rem 0 5rem !important;
      }
      .thinking-bubble {
        padding: .4rem .2rem;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        width: 100% !important;
        display: flex !important;
        flex-direction: row-reverse !important;
        align-items: flex-start !important;
        justify-content: flex-start !important;
        gap: .72rem !important;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) > div:has([data-testid="stChatMessageAvatarUser"]) {
        flex: 0 0 auto !important;
        width: auto !important;
        max-width: none !important;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"],
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) > div:has([data-testid="stMarkdownContainer"]) {
        flex: 1 1 auto !important;
        width: auto !important;
        max-width: none !important;
        min-width: 0 !important;
        display: flex !important;
        justify-content: flex-end !important;
        align-items: flex-start !important;
        margin: 0 !important;
      }
      [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stMarkdownContainer"] {
        width: fit-content !important;
        max-width: min(62ch, calc(100% - 1rem)) !important;
        margin: 0 !important;
        justify-self: auto !important;
      }
      @media (max-width: 780px) {
        .workflow-rail {
          position: static;
          width: auto;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          margin: 0 0 1rem;
          transform: none;
        }
        .workflow-rail::before {
          display: none;
        }
        .workflow-step {
          min-height: 64px;
          padding: .65rem;
        }
        .workflow-step::before,
        .workflow-step em {
          display: none;
        }
        .workflow-step strong {
          font-size: .88rem;
        }
        .block-container {
          padding-left: .9rem;
          padding-right: .9rem;
          padding-bottom: 18rem;
        }
        [data-testid="stBottom"] {
          padding: .82rem .9rem 1rem !important;
        }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


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


def _format_summary_table(summary):
    display = summary.copy()
    for column in ["累计收益", "基准收益", "超额收益", "最大回撤", "胜率", "持仓天数占比"]:
        if column in display.columns:
            display[column] = display[column].map(lambda value: format_pct(float(value)))
    if "夏普比率" in display.columns:
        display["夏普比率"] = display["夏普比率"].map(lambda value: f"{float(value):.2f}")
    return display


def render_backtest_panel(template: InterviewTemplate, answers: dict[str, str]) -> None:
    prototype = st.session_state.prototype
    if prototype is None or not st.session_state.backtest_ready:
        return

    try:
        factor_blend = factor_blend_payload(prototype, answers)
    except Exception as exc:
        st.warning(f"策略雏形还缺少可映射到因子库的信息，可以先继续补充一两句观察。错误信息：{exc}")
        st.session_state.backtest_ready = False
        return

    if not st.session_state.show_backtest_controls:
        st.markdown(
            """
            <section class="backtest-action-panel">
              <strong>策略雏形已形成</strong>
              <p>先进入历史数据里跑一轮，看看这条想法在收益、回撤和稳定性上的表现。</p>
            </section>
            """,
            unsafe_allow_html=True,
        )
        if st.button("进入下一步回测", type="primary", use_container_width=True):
            st.session_state.show_backtest_controls = True
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
            st.warning(f"暂时无法把策略雏形映射到回测参数。可以先补充标的范围或观察指标。错误信息：{exc}")
            return

    spec: BacktestSpec = st.session_state.backtest_spec
    st.markdown("### 因子组合")
    st.markdown(
        f"**基础因子库**：{factor_blend['base_factor']['name']}  \n"
        f"**用户策略因子**：{factor_blend['user_factor']['hypothesis']}  \n"
        f"**组合方式**：{factor_blend['reason']}"
    )
    st.markdown("### 回测设置")
    target_label = st.selectbox(
        "回测标的",
        list(symbol_labels),
        index=list(symbol_labels).index(code_to_label.get(spec.symbol_code, symbols[0].label)),
    )
    benchmark_label = st.selectbox(
        "对照基准",
        list(symbol_labels),
        index=list(symbol_labels).index(code_to_label.get(spec.benchmark_code, symbols[0].label)),
    )
    left, right = st.columns(2)
    with left:
        family = st.selectbox("策略代码", list(VALID_FAMILIES), index=list(VALID_FAMILIES).index(spec.family))
        window = st.selectbox("时间窗口", list(VALID_WINDOWS), index=list(VALID_WINDOWS).index(spec.window))
    with right:
        risk = st.selectbox("风险档位", list(VALID_RISKS), index=list(VALID_RISKS).index(spec.risk_profile))
        enhanced = st.checkbox("启用确定性风控增强", value=spec.enhanced)

    if st.button("运行回测", type="primary", use_container_width=True):
        chosen = BacktestSpec(
            symbol_code=symbol_labels[target_label],
            benchmark_code=symbol_labels[benchmark_label],
            family=family,
            risk_profile=risk,
            enhanced=enhanced,
            window=window,
            base_factor_id=factor_blend["base_factor"]["id"],
            user_factor_weight=float(factor_blend["user_weight"]),
        )
        st.session_state.backtest_spec = chosen
        st.session_state.backtest_result = run_backtest_from_spec(chosen)
        st.session_state.backtest_result["factor_blend"] = factor_blend
        analysis = analyze_backtest_result(st.session_state.backtest_result, prototype, llm=llm)
        st.session_state.messages.append({"role": "assistant", "content": f"回测跑完了。\n\n{analysis}"})
        st.rerun()

    result = st.session_state.backtest_result
    if result is None:
        return

    st.markdown("### 回测结果")
    curves = result["curves"].set_index("date")
    st.line_chart(curves)
    st.dataframe(_format_summary_table(result["summary"]), hide_index=True, use_container_width=True)


templates = load_templates()
template_by_name = {template.name: template for template in templates}
default_template = templates[0]
template = default_template
session_defaults(template)

answers: dict[str, str] = st.session_state.answers
workflow_index = 0
if st.session_state.get("show_backtest_controls") or st.session_state.get("backtest_result") is not None:
    workflow_index = 2
elif st.session_state.get("prototype") is not None:
    workflow_index = 1
render_workflow_rail(workflow_index)

model_status = "模型已连接" if has_llm_env() else "本地规则模式"

st.markdown(
    f"""
    <section class="strata-title">
      <div class="title-copy">
        <h1>智塔 Strata</h1>
        <span>把一手行业观察整理成可测试的策略雏形</span>
      </div>
      <span class="status-pill">{model_status}</span>
    </section>
    <section class="product-shell">
      <section class="advisor-card">
        <div class="advisor-avatar">ST</div>
        <div>
          <strong>小塔会先和你对话</strong>
          <p>你只需要说出行业、订单、库存、价格或供需变化。系统会把你的观察补全成策略因子，再映射到基础因子库和确定性回测接口。</p>
        </div>
      </section>
    """,
    unsafe_allow_html=True,
)

if len(st.session_state.messages) == 1 and not answers:
    append_next_question(template)

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

pending_user_input = st.session_state.get("pending_user_input")
if pending_user_input:
    with st.chat_message("assistant"):
        render_thinking()
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
            generate_and_append_prototype(template, answers)
            begin_follow_up_or_backtest(st.session_state.prototype)
        else:
            st.session_state.messages.append({"role": "assistant", "content": turn.reply})

    st.session_state.pending_user_input = None
    st.rerun()

render_backtest_panel(template, answers)

st.markdown("</section>", unsafe_allow_html=True)
st.markdown('<div class="chat-end-spacer"><span id="chat-scroll-anchor"></span></div>', unsafe_allow_html=True)
scroll_to_latest()

user_input = st.chat_input("和小塔说说你的观察")
if user_input:
    text = user_input.strip()
    if text in {"重新开始", "重来", "/reset"}:
        reset_session(template)
        st.rerun()

    st.session_state.messages.append({"role": "user", "content": text})
    st.session_state.pending_user_input = text
    st.rerun()
