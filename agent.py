# -*- coding: utf-8 -*-
"""판정 → 게이트 → 근거 조립·답변 → 검증을 하나의 그래프로 잇는다.

    classify → gate ─ CLARIFY ─────────────────────────→ END
                    └ HANDLE → answer → guard ─ 통과 ──→ END
                                  ↑          ├ 위반(재시도 남음) → answer
                                  └──────────┘ 위반(재시도 소진) → withhold → END
"""
from typing import List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from answer import answer_with_tools
from config import GUARDRAIL_RETRY
from guardrail import feedback_text, guardrail
from router import classify, gate

WITHHOLD_MESSAGE = ("근거 문서로 확인되지 않는 내용이 답변에 섞여 답변을 보류합니다. "
                    "문의를 조금 더 구체적으로 나눠 보내 주시겠어요?")


class AgentState(TypedDict, total=False):
    question: str
    history: List[dict]      # 앞 턴들 [{"role": "user"|"assistant", "text": ...}]
    route: str               # classify
    confidence: float        # classify
    reason: str              # classify
    action: str              # gate / guard — HANDLE / CLARIFY / ANSWER / RETRY / WITHHOLD
    message: str             # gate — 되묻기 문구
    answer: str              # answer / withhold
    calls: List[dict]        # answer — 도구 이름·인자
    chunks: dict             # answer — 조회한 조각
    prompt_chunks: List[str]  # answer — 프롬프트에 넣은 조각 ID
    check: Optional[dict]    # guard — 검증 결과
    attempts: int            # answer 실행 횟수
    first_answer: Optional[dict]  # 재생성 전 답변(데모·분석용)


def node_answer(state: AgentState) -> AgentState:
    fb = feedback_text(state["check"]) if state.get("check") and not state["check"]["ok"] else None
    r = answer_with_tools(state["question"], state["route"], feedback=fb,
                          history=state.get("history"))
    out = {k: r[k] for k in ("answer", "calls", "chunks", "prompt_chunks")}
    out["attempts"] = state.get("attempts", 0) + 1
    if fb:
        out["first_answer"] = {"answer": state["answer"], "calls": state["calls"], "check": state["check"]}
    return out


def node_guard(state: AgentState) -> AgentState:
    prior = " ".join(t["text"] for t in state.get("history") or [])   # 앞 턴에 나온 수치·옵션도 출처로 인정
    check = guardrail(f"{prior} {state['question']}", state)
    return {"check": check, "action": "ANSWER" if check["ok"] else "RETRY"}


def node_withhold(state: AgentState) -> AgentState:
    return {"action": "WITHHOLD", "answer": WITHHOLD_MESSAGE}


def after_gate(state):
    return "answer" if state["action"] == "HANDLE" else END


def after_guard(state):
    if state["check"]["ok"]:
        return END
    return "answer" if state["attempts"] <= GUARDRAIL_RETRY else "withhold"


def build_agent():
    g = StateGraph(AgentState)
    g.add_node("classify", classify)
    g.add_node("gate", gate)
    g.add_node("answer", node_answer)
    g.add_node("guard", node_guard)
    g.add_node("withhold", node_withhold)
    g.add_edge(START, "classify")
    g.add_edge("classify", "gate")
    g.add_conditional_edges("gate", after_gate, {"answer": "answer", END: END})
    g.add_edge("answer", "guard")
    g.add_conditional_edges("guard", after_guard,
                            {"answer": "answer", "withhold": "withhold", END: END})
    g.add_edge("withhold", END)
    return g.compile()


agent_app = build_agent()


ROUTE_NAMES = {"USAGE": "사용법", "QC_EXPLAIN": "검사 결과 설명", "STYLE_RULE": "자막 규정",
               "FEEDBACK": "건의·버그 접수", "OUT_OF_SCOPE": "범위 밖·넘기기"}


def check_category(selected, out):
    """질문자가 고른 카테고리를 분류기 판단과 대조한다. 고른 값은 분류기에 넘기지 않는다 —
    넘기면 분류기가 따라가 버려 검증이 되지 않는다.

    match     같다
    mismatch  다르고 분류기 확신도가 기준 이상 → 알리고 분류기 판단대로 답한다(사용자 결정 2026-09-17)
    unclear   분류기 확신도가 기준 미만 → 어느 쪽인지 되묻는다
    """
    if not selected:
        return None
    detected = out["route"]
    if out["action"] == "CLARIFY":
        status = "unclear"
        message = (f"고르신 카테고리 '{ROUTE_NAMES.get(selected, selected)}'가 맞는지 질문만으로는 확인하기 어렵습니다. "
                   f"{out['message']}")
    elif detected == selected:
        status, message = "match", ""
    else:
        status = "mismatch"
        message = (f"고르신 카테고리는 '{ROUTE_NAMES.get(selected, selected)}'이지만, 질문 내용은 "
                   f"'{ROUTE_NAMES.get(detected, detected)}'에 해당해 그 기준으로 답합니다.")
    return {"selected": selected, "detected": detected, "confidence": out["confidence"],
            "status": status, "message": message}


def help_desk(question, history=None, selected_category=None):
    """문의 한 줄을 파이프라인에 통과시킨다. 되묻기면 answer 자리에 되묻는 문구를 넣는다.

    history:           앞 턴들 [{"role": "user"|"assistant", "text": ...}]. 대화 상태는 부르는 쪽이 들고 있다
    selected_category: 질문자가 고른 카테고리. 분류에는 쓰지 않고 분류 결과와 대조만 한다
    """
    out = agent_app.invoke({"question": question, "history": history or []})
    if out["action"] == "CLARIFY":
        out.update(answer=out["message"], calls=[], chunks={}, prompt_chunks=[])
    cc = check_category(selected_category, out)
    if cc:
        out["category_check"] = cc
        if cc["status"] == "unclear":
            out["answer"] = cc["message"]
        elif cc["status"] == "mismatch":
            out["answer"] = f"{cc['message']}\n\n{out['answer']}"
    return {"question": question, **out}


if __name__ == "__main__":
    import sys
    print(agent_app.get_graph().draw_mermaid())
    if len(sys.argv) > 1:
        r = help_desk(" ".join(sys.argv[1:]))
        print(r["route"], r["confidence"], r["action"])
        print([c["name"] for c in r["calls"]])
        print(r["answer"])
        print(r.get("check"))
