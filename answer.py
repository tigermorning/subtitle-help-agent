# -*- coding: utf-8 -*-
"""답변 생성. 모델이 도구를 골라 부르는 루프다(agent ↔ tools).

돌려주는 것: 답변 · 도구 호출 목록(이름·인자) · 조회한 조각 · 프롬프트에 넣은 조각 ID.
데모와 평가가 이 넷을 그대로 쓴다.
"""
import json
from typing import Annotated, TypedDict

from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.errors import GraphRecursionError
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from config import ANSWER_MODEL, MAX_TOOL_TURNS
from context import build_answer_prompt
from tools import TOOLS

LC_TOOLS = [tool(fn) for fn in TOOLS.values()]
TURN_LIMIT_MESSAGE = "근거 조회가 길어져 답변을 마치지 못했습니다. 문의를 나눠서 다시 보내 주시겠어요?"

_llm = None


def _model():
    global _llm
    if _llm is None:
        # reasoning_effort="none": 이 등급 모델은 추론 모드와 도구 호출을 함께 쓰면 400을 돌려준다
        _llm = init_chat_model(ANSWER_MODEL, model_provider="openai", temperature=0,
                               reasoning_effort="none", timeout=60,
                               max_retries=2).bind_tools(LC_TOOLS)
    return _llm


class ToolState(TypedDict, total=False):
    messages: Annotated[list, add_messages]


def agent(state: ToolState) -> ToolState:
    return {"messages": [_model().invoke(state["messages"])]}


def build_tool_graph():
    g = StateGraph(ToolState)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(LC_TOOLS))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition)
    g.add_edge("tools", "agent")
    return g.compile()


tool_app = build_tool_graph()


def answer_with_tools(question, route, feedback=None, history=None, max_turns=MAX_TOOL_TURNS):
    """반환: {answer, calls, chunks, prompt_chunks, turn_limited}

    feedback: 검증에서 걸린 내용. 재생성할 때 모델에게 되돌려 준다.
    history:  앞 턴들 [{"role": "user"|"assistant", "text": ...}]. 도구 결과는 넘기지 않는다 —
              이번 턴에 필요한 근거는 이번 턴에 다시 조회한다
    """
    system, prompt_chunks = build_answer_prompt(route)
    if feedback:
        system += f"\n\n[직전 답변이 검증에서 걸렸다 — 고쳐서 다시 답한다]\n{feedback}\n"
    prior = [("human" if t["role"] == "user" else "ai", t["text"]) for t in (history or [])]
    init = {"messages": [("system", system), *prior, ("human", question)]}
    try:
        out = tool_app.invoke(init, {"recursion_limit": 2 * max_turns + 1})
    except GraphRecursionError:
        # 상한에 걸린 경우만 잡는다. 그 밖의 예외는 원인을 숨기지 않도록 그대로 올린다
        return {"answer": TURN_LIMIT_MESSAGE, "calls": [], "chunks": {},
                "prompt_chunks": prompt_chunks, "turn_limited": True}

    calls, chunks = [], {}
    for m in out["messages"]:
        for tc in getattr(m, "tool_calls", None) or []:
            calls.append({"name": tc["name"], "args": tc["args"]})
        if getattr(m, "name", None) in TOOLS:
            try:
                result = json.loads(m.content)
            except (json.JSONDecodeError, TypeError):
                continue
            for c in result.get("chunks", []):
                chunks[c["id"]] = c
    return {"answer": out["messages"][-1].content, "calls": calls, "chunks": chunks,
            "prompt_chunks": prompt_chunks, "turn_limited": False}
