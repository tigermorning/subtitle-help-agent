# -*- coding: utf-8 -*-
"""분류기. classify(모델이 하는 일)와 gate(정책이 정하는 일)를 다른 노드로 둔다.

둘을 나눠 두면 임계값만 바꿀 때 모델을 다시 부르지 않아도 되고, "무엇으로 보았나"와
"넘길 것인가"를 따로 잴 수 있다.
"""
from typing import Literal, TypedDict

from langchain.chat_models import init_chat_model
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from config import CONF_THRESHOLD, MODEL
from prompts import ROUTE_GUIDE

CLARIFY_MESSAGE = ("문의 내용을 조금 더 구체적으로 알려 주시겠어요? 예를 들어 사용하신 명령이나 옵션, "
                   "리포트에 뜬 경고 내용(예: 읽기 속도 초과), 번역 자막인지 SDH인지를 적어 주시면 정확히 안내해 드리겠습니다.")


class RouterState(TypedDict, total=False):
    question: str
    history: list        # 앞 턴들 [{"role": "user"|"assistant", "text": ...}]
    route: str          # classify
    confidence: float   # classify
    reason: str         # classify
    action: str         # gate — HANDLE / CLARIFY
    message: str        # gate — CLARIFY일 때 나갈 문구


class RouteDecision(BaseModel):
    """문의 한 건에 대한 분류 결과."""

    route: Literal["USAGE", "QC_EXPLAIN", "STYLE_RULE", "FEEDBACK", "OUT_OF_SCOPE"] = Field(
        description="문의를 배정할 카테고리. 5개 값 중 하나만.")
    confidence: float = Field(
        ge=0.0, le=1.0, description="확신도. 두 카테고리 사이에서 갈리거나 무엇을 묻는지 모르면 0.5 미만.")
    reason: str = Field(description="그 카테고리로 판단한 근거 한 문장.")


_chain = None


def with_history(state):
    """분류기에 줄 글. 앞 턴이 있으면 대화를 먼저 보여 주고 이번 문의를 분류하게 한다."""
    prior = state.get("history") or []
    if not prior:
        return f"문의: {state['question']}"
    lines = [f"{'사용자' if t['role'] == 'user' else '창구'}: {t['text']}" for t in prior]
    return ("[앞선 대화]\n" + "\n".join(lines) +
            f"\n\n[이번 문의 — 앞선 대화를 참고해 이것을 분류한다]\n문의: {state['question']}")


def classify(state: RouterState) -> RouterState:
    """노드 ① 분류 — 모델이 카테고리와 확신도를 낸다."""
    global _chain
    if _chain is None:
        _chain = init_chat_model(MODEL, model_provider="openai", temperature=0,
                                 timeout=60, max_retries=2).with_structured_output(RouteDecision)
    d = _chain.invoke([("system", ROUTE_GUIDE), ("human", with_history(state))])
    return {"route": d.route, "confidence": d.confidence, "reason": d.reason}


def gate(state: RouterState) -> RouterState:
    """노드 ② 판정 — 확신도가 기준 미만이면 답하지 않고 되묻는다."""
    if state["confidence"] < CONF_THRESHOLD:
        return {"action": "CLARIFY", "message": CLARIFY_MESSAGE}
    return {"action": "HANDLE"}


def build():
    g = StateGraph(RouterState)
    g.add_node("classify", classify)
    g.add_node("gate", gate)
    g.add_edge(START, "classify")
    g.add_edge("classify", "gate")
    g.add_edge("gate", END)
    return g.compile()


app = build()


def route(question):
    return app.invoke({"question": question})
