# -*- coding: utf-8 -*-
"""데모 화면 — 자막 생성기 소통 창구.

    streamlit run app.py

답변 아래에 판단 과정을 펼쳐 보여 준다.
    ① 분류   카테고리 · 확신도 · 이유 · 게이트(되묻기/처리)
    ② 도구   모델이 부른 도구와 인자
    ③ 근거   조회한 조각(요약)과 원문 발췌, 프롬프트에 넣은 조각
    ④ 검증   출처 검사 결과. 재생성했으면 첫 답변과 걸린 이유
"""
import json

import streamlit as st

from agent import help_desk
from context import CHUNKS

ROUTE_LABEL = {
    "USAGE": "사용법",
    "QC_EXPLAIN": "검사 결과 설명",
    "STYLE_RULE": "자막 규정",
    "FEEDBACK": "건의·버그 접수",
    "OUT_OF_SCOPE": "범위 밖·넘기기",
}
ACTION_LABEL = {
    "ANSWER": "답변",
    "CLARIFY": "되묻기 (확신도 미달)",
    "WITHHOLD": "답변 보류 (검증 실패)",
}
EXAMPLES = [
    "TC 작업 끝난 파일에 번역만 하는데 타임코드 안 건드리는 옵션 있어요?",
    "SDH 검사에서 S02 읽기 속도 초과가 떴어요. 기준이 뭐예요?",
    "SDH에서 이름이 아직 안 나온 인물은 화자 표시 어떻게 해요?",
    "3분짜리 예고편 번역했는데 번역자 크레디트 넣어야 해요?",
    "WebVTT 파일도 검사할 수 있게 해 주세요",
    "디즈니플러스 SDH 읽기 속도 기준도 알려 주세요",
]

st.set_page_config(page_title="자막 생성기 문의 창구", page_icon="🎬", layout="wide")


def init_state():
    st.session_state.setdefault("turns", [])      # [{"question", "result"}]
    st.session_state.setdefault("pending", None)


def history():
    out = []
    for t in st.session_state.turns:
        out += [{"role": "user", "text": t["question"]},
                {"role": "assistant", "text": t["result"]["answer"]}]
    return out


def sidebar():
    with st.sidebar:
        st.header("자막 생성기 문의 창구")
        st.caption("사용법 · 검사 결과 · 넷플릭스 자막 규정을 근거 문서로 답하고, 건의·버그는 접수합니다.")
        st.warning("방송 전 대본·미공개 자막 원문은 붙여넣지 마세요. 답변 생성에 외부 API를 씁니다.", icon="⚠️")
        st.subheader("예시 문의")
        for ex in EXAMPLES:
            if st.button(ex, use_container_width=True):
                st.session_state.pending = ex
        st.divider()
        if st.button("대화 새로 시작", use_container_width=True):
            st.session_state.turns = []
            st.rerun()
        st.caption(f"근거 조각 {len(CHUNKS)}개 · 대화 {len(st.session_state.turns)}턴")


def badge_row(r):
    """좁은 화면에서도 잘리지 않게 한 줄 배지로 보여 준다."""
    check = r.get("check")
    if check is None:
        verdict = ":gray-badge[검증 없음]"
    else:
        verdict = ":green-badge[검증 통과]" if check["ok"] else ":red-badge[검증 위반]"
    action = r["action"]
    action_badge = {"ANSWER": ":blue-badge", "CLARIFY": ":orange-badge", "WITHHOLD": ":red-badge"}.get(action, ":gray-badge")
    tools = ", ".join(c["name"] for c in r["calls"]) or "도구 없음"
    st.markdown(f":violet-badge[{ROUTE_LABEL.get(r['route'], r['route'])}] "
                f":gray-badge[확신도 {r['confidence']:.2f}] "
                f"{action_badge}[{ACTION_LABEL.get(action, action)}] {verdict} "
                f":gray-badge[{tools}]")


def show_chunk(c, expanded=False):
    with st.expander(f"[{c['id']}] {c['title']}", expanded=expanded):
        body = c["text"].split("\n", 1)[1] if c["text"].startswith("## ") else c["text"]   # 제목 줄은 펼침 머리에 이미 있다
        st.markdown(body)
        for o in c.get("original", []):
            st.caption(f"원문 발췌 — {o['title']} (개정 {o['edited_at']}) · {o['url']}")
            st.code(o["text"][:1500] + ("…" if len(o["text"]) > 1500 else ""), language=None)


def details(r):
    tab_route, tab_tools, tab_chunks, tab_check = st.tabs(["① 분류", "② 호출한 도구", "③ 근거", "④ 검증"])

    with tab_route:
        st.markdown(f"**{r['route']}** ({ROUTE_LABEL.get(r['route'], '')}) · 확신도 {r['confidence']:.2f}")
        st.markdown(f"이유: {r.get('reason', '')}")
        if r["action"] == "CLARIFY":
            st.info("확신도가 기준(0.5) 미만이라 근거를 조회하지 않고 되물었습니다.")

    with tab_tools:
        if not r["calls"]:
            st.write("부른 도구가 없습니다.")
        for i, c in enumerate(r["calls"], 1):
            st.markdown(f"**{i}. `{c['name']}`**")
            st.code(json.dumps(c["args"], ensure_ascii=False, indent=1), language="json")

    with tab_chunks:
        read = list(r.get("chunks", {}).values())
        st.markdown(f"**도구로 조회한 조각 {len(read)}개**")
        if not read:
            st.write("없음")
        for c in read:
            show_chunk(c)
        prompt_ids = [cid for cid in r.get("prompt_chunks", []) if cid not in r.get("chunks", {})]
        if prompt_ids:
            st.markdown(f"**프롬프트에 넣은 조각 {len(prompt_ids)}개** (카테고리 공통 기준)")
            for cid in prompt_ids:
                show_chunk({"id": cid, **CHUNKS[cid]})

    with tab_check:
        check = r.get("check")
        if check is None:
            st.write("되묻기라 검증하지 않았습니다.")
        else:
            if check["ok"]:
                st.success("답변 속 수치·옵션 이름·조각 인용·주소·접수번호가 모두 근거에서 확인됐습니다.")
            else:
                st.error("근거에서 확인되지 않은 내용이 있습니다.")
                for v in check["violations"]:
                    st.markdown(f"- **{v['type']}**: {v['detail']}")
            st.caption("검사 대상 근거: " + ", ".join(check["evidence_chunks"]))
        first = r.get("first_answer")
        if first:
            st.warning("첫 답변이 검증에서 걸려 한 번 다시 생성했습니다.")
            st.markdown("**첫 답변**")
            st.markdown(first["answer"])
            for v in first["check"]["violations"]:
                st.markdown(f"- {v['type']}: {v['detail']}")


def render_turn(t):
    with st.chat_message("user"):
        st.markdown(t["question"])
    with st.chat_message("assistant"):
        r = t["result"]
        st.markdown(r["answer"])
        badge_row(r)
        details(r)


def main():
    init_state()
    sidebar()
    st.title("🎬 자막 생성기 문의 창구")
    st.caption("근거 문서: 생성기 사용법 · 검사 항목 설명 · 넷플릭스 공개 자막 문서 요약 · 접수 방침 · 국립국어원 안내")

    for t in st.session_state.turns:
        render_turn(t)

    question = st.chat_input("문의를 입력하세요") or st.session_state.pending
    st.session_state.pending = None
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("분류하고 근거를 찾는 중…"):
                result = help_desk(question, history())
        st.session_state.turns.append({"question": question, "result": result})
        st.rerun()


main()
