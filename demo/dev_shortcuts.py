from __future__ import annotations

import streamlit as st

from interview_agent import InterviewTemplate, StrategyPrototype


def _mock_answers() -> dict[str, str]:
    return {
        "observation": "猪肉供给偏紧，养殖户反馈出栏节奏放缓。",
        "source": "来自养殖户口头反馈、出栏量跟踪和屠宰企业利润观察。",
        "target_universe": "猪肉产业链相关 ETF、养殖企业和屠宰企业。",
        "risk_preference": "能承受中等波动，希望先看是否跑赢基准。",
    }


def _mock_prototype() -> StrategyPrototype:
    return StrategyPrototype(
        title="猪肉供给偏紧策略雏形",
        observation_summary="观察到猪肉供给偏紧，出栏节奏放缓，屠宰企业利润承压。",
        factor_hypothesis="供给收缩与利润承压可能形成价格修复预期，可作为产业链景气反转因子。",
        naive_strategy="当供给偏紧信号持续且屠宰利润承压时，分批观察猪肉产业链相关标的。",
        target_universe="猪肉产业链相关 ETF、养殖企业和屠宰企业。",
        standard_modules=("趋势过滤", "RSI 超跌修复", "波动率风控"),
        risk_controls=("单次回撤限制", "高波动降仓", "信号失效退出"),
        validation_plan="选择近 1 年和近 3 年窗口，与沪深 300 或行业 ETF 对比收益、回撤和夏普。",
        missing_info=(),
        follow_up_questions=(),
        source="dev_shortcut",
    )


def _reset_runtime_state() -> None:
    st.session_state.pending_user_input = None
    st.session_state.follow_up_questions = []
    st.session_state.follow_up_answers = {}
    st.session_state.follow_up_index = 0
    st.session_state.backtest_result = None
    st.session_state.backtest_spec = None
    st.session_state.live_signal = None
    st.session_state.suggestion_cache = {}
    st.session_state.backtest_transition = False
    st.session_state.transition_started_at = None
    st.session_state.show_backtest_controls = False
    st.session_state.awaiting_strategy_confirmation = False
    st.session_state.pending_strategy_creation = False


def apply_dev_shortcut(template: InterviewTemplate) -> None:
    mode = st.query_params.get("dev")
    if mode not in {"prototype", "backtest_ready"}:
        return

    answers = _mock_answers()
    st.session_state.started = True
    st.session_state.current_view = "chat"
    st.session_state.answers = answers
    _reset_runtime_state()

    if mode == "prototype":
        st.session_state.prototype = None
        st.session_state.messages = [
            {"role": "assistant", "content": template.opening_message},
            {"role": "user", "content": "我想测试猪肉供给偏紧这一类行业观察。"},
            {
                "role": "assistant",
                "content": "我总结一下：你观察到猪肉供给偏紧，养殖户反馈出栏节奏放缓，同时关注屠宰企业利润。信息已经足够，要我把这些转化为可回测的策略雏形吗？",
            },
        ]
        st.session_state.awaiting_strategy_confirmation = True
        st.session_state.backtest_ready = False
    else:
        prototype = _mock_prototype()
        st.session_state.prototype = prototype
        st.session_state.messages = [
            {"role": "assistant", "content": template.opening_message},
            {"role": "user", "content": "猪肉供给偏紧，上游出栏变慢。"},
            {"role": "assistant", "content": "策略雏形已经形成，可以进入历史回测。"},
            {"role": "assistant", "content": _prototype_message(prototype)},
        ]
        st.session_state.backtest_ready = True

    st.query_params.clear()
    st.rerun()


def _prototype_message(prototype: StrategyPrototype) -> str:
    modules = "、".join(prototype.standard_modules)
    risks = "、".join(prototype.risk_controls)
    return (
        f"我先把你的策略雏形整理出来：\n\n"
        f"### {prototype.title}\n\n"
        f"**一手观察**\n\n{prototype.observation_summary}\n\n"
        f"**策略因子假设**\n\n{prototype.factor_hypothesis}\n\n"
        f"**朴素交易逻辑**\n\n{prototype.naive_strategy}\n\n"
        f"**候选标的范围**\n\n{prototype.target_universe}\n\n"
        f"**建议补全的标准量化模块**\n\n{modules}\n\n"
        f"**基础风控**\n\n{risks}\n\n"
        f"**后续验证计划**\n\n{prototype.validation_plan}"
    )
