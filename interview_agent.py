from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

try:
    from agent_runtime import LLMClient
except ModuleNotFoundError:
    from .agent_runtime import LLMClient


INTERVIEW_DIR = Path(__file__).resolve().parent / "interviews"


@dataclass(frozen=True)
class InterviewQuestion:
    id: str
    title: str
    prompt: str
    purpose: str
    stage: str = "采访"
    required: bool = True
    answer_type: str = "text"
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class InterviewTemplate:
    id: str
    name: str
    description: str
    opening_message: str
    system_prompt: str
    questions: tuple[InterviewQuestion, ...]


@dataclass(frozen=True)
class StrategyPrototype:
    title: str
    observation_summary: str
    factor_hypothesis: str
    naive_strategy: str
    target_universe: str
    standard_modules: tuple[str, ...]
    risk_controls: tuple[str, ...]
    validation_plan: str
    missing_info: tuple[str, ...]
    follow_up_questions: tuple[str, ...]
    source: str
    raw: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "observation_summary": self.observation_summary,
            "factor_hypothesis": self.factor_hypothesis,
            "naive_strategy": self.naive_strategy,
            "target_universe": self.target_universe,
            "standard_modules": list(self.standard_modules),
            "risk_controls": list(self.risk_controls),
            "validation_plan": self.validation_plan,
            "missing_info": list(self.missing_info),
            "follow_up_questions": list(self.follow_up_questions),
            "source": self.source,
        }


@dataclass(frozen=True)
class InterviewTurn:
    reply: str
    answers: dict[str, str]
    ready_to_generate: bool
    source: str
    raw: dict[str, Any] | None = None


def current_time_context() -> str:
    if ZoneInfo is not None:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        timezone = "Asia/Shanghai"
    else:
        now = datetime.now().astimezone()
        timezone = str(now.tzinfo or "local")
    return (
        f"当前日期：{now:%Y-%m-%d}。"
        f"当前时间：{now:%H:%M:%S}。"
        f"时区：{timezone}。"
        "回答涉及今天、现在、最近、今年或历史时间时，必须以这个时间为准。"
    )


def _question_from_dict(item: dict[str, Any]) -> InterviewQuestion:
    return InterviewQuestion(
        id=str(item["id"]),
        title=str(item.get("title") or item["id"]),
        prompt=str(item["prompt"]),
        purpose=str(item.get("purpose") or ""),
        stage=str(item.get("stage") or "采访"),
        required=bool(item.get("required", True)),
        answer_type=str(item.get("answer_type") or "text"),
        examples=tuple(str(value) for value in item.get("examples", [])),
    )


def load_template(path: Path) -> InterviewTemplate:
    payload = json.loads(path.read_text(encoding="utf-8"))
    questions = tuple(_question_from_dict(item) for item in payload.get("questions", []))
    if not questions:
        raise ValueError(f"Interview template has no questions: {path}")
    return InterviewTemplate(
        id=str(payload.get("id") or path.stem),
        name=str(payload.get("name") or path.stem),
        description=str(payload.get("description") or ""),
        opening_message=str(payload.get("opening_message") or "我会通过几个问题帮你形成策略雏形。"),
        system_prompt=str(payload.get("system_prompt") or ""),
        questions=questions,
    )


def load_templates(directory: Path = INTERVIEW_DIR) -> list[InterviewTemplate]:
    directory.mkdir(parents=True, exist_ok=True)
    templates = [load_template(path) for path in sorted(directory.glob("*.json"))]
    if not templates:
        raise FileNotFoundError(f"No interview templates found in {directory}")
    return templates


def next_question(template: InterviewTemplate, answers: dict[str, str]) -> InterviewQuestion | None:
    for question in template.questions:
        if question.id not in answers:
            return question
    return None


def build_interview_brief(template: InterviewTemplate, answers: dict[str, str]) -> str:
    lines = [f"采访模板：{template.name}", f"模板说明：{template.description}", ""]
    for question in template.questions:
        answer = answers.get(question.id, "")
        lines.append(f"{question.title}：{answer or '未回答'}")
    return "\n".join(lines)


def fallback_interview_turn(
    template: InterviewTemplate,
    messages: list[dict[str, str]],
    answers: dict[str, str],
) -> InterviewTurn:
    updated = dict(answers)
    latest_user = next((item["content"] for item in reversed(messages) if item.get("role") == "user"), "")
    current = next_question(template, updated)
    if current is not None and latest_user:
        updated[current.id] = latest_user

    next_item = next_question(template, updated)
    if next_item is None:
        return InterviewTurn(
            reply="信息已经够了。我先把它整理成一个可以测试的策略雏形。",
            answers=updated,
            ready_to_generate=True,
            source="rules",
        )
    return InterviewTurn(
        reply=next_item.prompt,
        answers=updated,
        ready_to_generate=False,
        source="rules",
    )


def run_interview_turn(
    template: InterviewTemplate,
    messages: list[dict[str, str]],
    answers: dict[str, str],
    llm: LLMClient | None = None,
) -> InterviewTurn:
    fallback = fallback_interview_turn(template, messages, answers)
    if llm is None:
        return fallback

    question_goals = [
        {"id": item.id, "title": item.title, "stage": item.stage, "prompt": item.prompt}
        for item in template.questions
    ]
    system_prompt = (
        f"{template.system_prompt}\n\n"
        f"{current_time_context()}\n"
        "你是面向普通用户的策略共创 Agent。你要像耐心的股票经理一样追问，但不要暴露内部采访框架。"
        "不要解释为什么要问这个问题，不要说 purpose、阶段、题号、模板或 JSON。"
        "每次只问一个自然的问题。问题要根据用户刚才的回答动态调整。"
        "如果用户询问当前时间、日期或产品使用方式，先直接回答，再自然回到策略共创。"
        "当信息足够形成策略雏形时，ready_to_generate 设为 true。"
        "不要承诺收益，不要给实盘买卖指令。"
    )
    user_prompt = (
        "采访目标如下，它们是内部约束，不要直接展示给用户：\n"
        f"{json.dumps(question_goals, ensure_ascii=False)}\n\n"
        "已整理的信息：\n"
        f"{json.dumps(answers, ensure_ascii=False)}\n\n"
        "最近对话：\n"
        f"{json.dumps(messages[-12:], ensure_ascii=False)}\n\n"
        "请只返回 JSON："
        '{"reply":"下一句对用户说的话","answers":{"问题 id":"从对话中提取或更新后的答案"},"ready_to_generate":false}'
        "\nanswers 只使用采访目标里的 id。reply 必须是用户能直接看到的话。"
    )

    try:
        raw = llm.complete_json(system_prompt, user_prompt)
    except Exception:
        return fallback

    valid_ids = {item.id for item in template.questions}
    updated = dict(answers)
    raw_answers = raw.get("answers")
    if isinstance(raw_answers, dict):
        for key, value in raw_answers.items():
            if key in valid_ids and str(value).strip():
                updated[str(key)] = str(value).strip()

    answered_count = len([item for item in template.questions if updated.get(item.id)])
    ready = bool(raw.get("ready_to_generate")) and answered_count >= min(5, len(template.questions))
    reply = str(raw.get("reply") or "").strip()
    if not reply:
        reply = "信息已经够了。我先整理成策略雏形。" if ready else fallback.reply

    return InterviewTurn(reply=reply, answers=updated, ready_to_generate=ready, source="llm", raw=raw)


def fallback_strategy_prototype(template: InterviewTemplate, answers: dict[str, str]) -> StrategyPrototype:
    observation = answers.get("observation") or answers.get("industry_observation") or "用户提供了一条行业观察。"
    naive = answers.get("naive_strategy") or "当观察继续被市场验证时买入，观察失效或价格跌破关键位时退出。"
    target = answers.get("target_universe") or answers.get("target") or "相关 ETF、行业龙头或用户指定标的"
    horizon = answers.get("horizon") or "中期：1-3 个月"
    risk = answers.get("risk_profile") or "均衡"
    missing_info = tuple(
        item
        for item in [
            "更明确的标的范围" if "target" not in answers and "target_universe" not in answers else "",
            "观察可量化代理变量" if "proxy_metric" not in answers and "factor_translation" not in answers else "",
        ]
        if item
    )
    follow_up_questions = tuple(f"关于{item}，你能补充一个更具体的说法吗？" for item in missing_info)
    return StrategyPrototype(
        title="一手信息驱动的策略雏形",
        observation_summary=observation,
        factor_hypothesis=f"如果该观察能持续改善基本面或市场预期，它可能形成可交易的景气度/供需/价格因子。",
        naive_strategy=naive,
        target_universe=target,
        standard_modules=("买入持有基准", "趋势过滤", "RSI 或超跌修复", "成交/波动过滤"),
        risk_controls=(f"{risk}仓位", "止损", "最大持有期", "高波动降仓"),
        validation_plan=f"使用{horizon}匹配的历史窗口，比较策略收益、回撤、胜率、交易次数和买入持有基准。",
        missing_info=missing_info,
        follow_up_questions=follow_up_questions,
        source="rules",
    )


def generate_strategy_prototype(
    template: InterviewTemplate,
    answers: dict[str, str],
    llm: LLMClient | None = None,
) -> StrategyPrototype:
    fallback = fallback_strategy_prototype(template, answers)
    if llm is None:
        return fallback

    system_prompt = (
        template.system_prompt
        or "你是量化策略采访 Agent。你帮助用户把一手行业观察转成专业策略因子和可回测策略雏形。"
    )
    system_prompt = f"{system_prompt}\n\n{current_time_context()}"
    user_prompt = (
        f"{build_interview_brief(template, answers)}\n\n"
        "请只返回 JSON，字段包括：title, observation_summary, factor_hypothesis, naive_strategy, "
        "target_universe, standard_modules, risk_controls, validation_plan, missing_info, follow_up_questions。"
        "follow_up_questions 是需要继续向用户逐个确认的问题，最多 4 个，每个问题只问一件事。"
        "不要承诺收益，不要直接给实盘买卖指令。"
    )
    raw = llm.complete_json(system_prompt, user_prompt)

    def list_field(name: str, fallback_values: tuple[str, ...]) -> tuple[str, ...]:
        value = raw.get(name)
        if isinstance(value, list):
            return tuple(str(item) for item in value if str(item).strip())
        if isinstance(value, str) and value.strip():
            return (value.strip(),)
        return fallback_values

    return StrategyPrototype(
        title=str(raw.get("title") or fallback.title),
        observation_summary=str(raw.get("observation_summary") or fallback.observation_summary),
        factor_hypothesis=str(raw.get("factor_hypothesis") or fallback.factor_hypothesis),
        naive_strategy=str(raw.get("naive_strategy") or fallback.naive_strategy),
        target_universe=str(raw.get("target_universe") or fallback.target_universe),
        standard_modules=list_field("standard_modules", fallback.standard_modules),
        risk_controls=list_field("risk_controls", fallback.risk_controls),
        validation_plan=str(raw.get("validation_plan") or fallback.validation_plan),
        missing_info=list_field("missing_info", fallback.missing_info),
        follow_up_questions=list_field("follow_up_questions", fallback.follow_up_questions),
        source="llm",
        raw=raw,
    )
