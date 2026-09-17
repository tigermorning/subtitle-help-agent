# -*- coding: utf-8 -*-
"""데모 화면 — 자막 생성기 문의 창구.

    streamlit run app.py

흐름
    1. 사이드바에서 카테고리를 누르면 그 카테고리의 준비된 Q&A를 본다(data/faq.json)
    2. Q&A에서 답을 못 찾으면 [직접 질문하기] — 카테고리를 먼저 골라야 보낼 수 있다
    3. 보내기 전에 비슷한 준비된 Q&A가 있으면 먼저 보여 준다. 그래도 보낼 수 있다
    4. 보낸 질문은 고른 카테고리를 믿지 않고 분류기가 따로 판정해 대조한다(agent.check_category)
       - 같으면 그대로, 다르면 알리고 분류기 판단대로 답한다, 확신이 없으면 되묻는다
    5. 답변 아래에 분류 · 호출한 도구 · 근거 조각(원문 발췌) · 검증 결과를 펼쳐 보여 준다
"""
import json

import streamlit as st

from agent import ROUTE_NAMES, help_desk
from context import CHUNKS
from faq import SimilarIndex, load_faq

ROUTES = ["USAGE", "QC_EXPLAIN", "STYLE_RULE", "FEEDBACK", "OUT_OF_SCOPE"]
ROUTE_ICON = {"USAGE": "🛠️", "QC_EXPLAIN": "🔎", "STYLE_RULE": "📏", "FEEDBACK": "📮", "OUT_OF_SCOPE": "🧭"}
ROUTE_DESC = {
    "USAGE": "데스크톱 앱·Subtitle Edit 플러그인 쓰는 법, 검사 결과 보는 법, 저장·결과 파일",
    "QC_EXPLAIN": "검사 리포트에 뜬 특정 경고(예: 읽기 속도 초과)의 뜻과 고치는 법",
    "STYLE_RULE": "넷플릭스 공개 자막 규정 — 글자 수, 읽기 속도, 문장부호, SDH 표기, 타이밍 등",
    "FEEDBACK": "기능 건의, 버그·오탐 제보. 접수번호를 드립니다",
    "OUT_OF_SCOPE": "이 창구가 답하지 않는 질문과 확인할 곳",
}
ACTION_LABEL = {"ANSWER": "답변", "CLARIFY": "되묻기 (확신도 미달)", "WITHHOLD": "답변 보류 (검증 실패)"}
CHECK_BADGE = {"match": ":green-badge[카테고리 확인됨]", "mismatch": ":orange-badge[카테고리 바로잡음]",
               "unclear": ":orange-badge[카테고리 확인 불가 — 되물음]"}

st.set_page_config(page_title="자막 생성기 문의 창구", page_icon="🎬", layout="wide")


@st.cache_data
def faq_items():
    return load_faq()


@st.cache_resource
def faq_index():
    return SimilarIndex(faq_items())


def init_state():
    st.session_state.setdefault("view", ("faq", "USAGE"))   # ("faq", route) | ("ask", None)
    st.session_state.setdefault("turns", [])                 # [{"question", "selected", "result"}]
    st.session_state.setdefault("draft", None)               # 보내기 전 확인 중인 질문


def history():
    out = []
    for t in st.session_state.turns:
        out += [{"role": "user", "text": t["question"]},
                {"role": "assistant", "text": t["result"]["answer"]}]
    return out


# ───────────────────────── 사이드바 ─────────────────────────

def sidebar():
    items = faq_items()
    with st.sidebar:
        st.header("🎬 문의 창구")
        st.caption("카테고리를 누르면 준비된 Q&A를 봅니다. 찾는 답이 없으면 직접 질문하세요.")
        st.subheader("카테고리")
        for r in ROUTES:
            n = sum(1 for i in items if i["route"] == r)
            active = st.session_state.view == ("faq", r)
            if st.button(f"{ROUTE_ICON[r]} {ROUTE_NAMES[r]}  ·  {n}", key=f"cat-{r}",
                         use_container_width=True, type="primary" if active else "secondary"):
                st.session_state.view = ("faq", r)
                st.rerun()
        st.divider()
        if st.button("💬 직접 질문하기", use_container_width=True,
                     type="primary" if st.session_state.view[0] == "ask" else "secondary"):
            st.session_state.view = ("ask", None)
            st.rerun()
        if st.session_state.turns and st.button("대화 새로 시작", use_container_width=True):
            st.session_state.turns = []
            st.session_state.draft = None
            st.rerun()
        st.warning("방송 전 대본·미공개 자막 원문은 붙여넣지 마세요. 직접 질문의 답변 생성에는 외부 API를 씁니다.",
                   icon="⚠️")


# ───────────────────────── 근거 조각 ─────────────────────────

def show_chunk(cid, original=None):
    c = CHUNKS[cid]
    with st.expander(f"[{cid}] {c['title']}"):
        body = c["text"].split("\n", 1)[1] if c["text"].startswith("## ") else c["text"]
        st.markdown(body)
        for o in original or []:
            st.caption(f"원문 발췌 — {o['title']} (개정 {o['edited_at']}) · {o['url']}")
            st.code(o["text"][:1500] + ("…" if len(o["text"]) > 1500 else ""), language=None)


# ───────────────────────── Q&A 화면 ─────────────────────────

def faq_view(route):
    st.title(f"{ROUTE_ICON[route]} {ROUTE_NAMES[route]}")
    st.caption(ROUTE_DESC[route])
    items = [i for i in faq_items() if i["route"] == route]
    query = st.text_input("이 카테고리에서 찾기", placeholder="낱말로 거르기 (예: 읽기 속도, 자막 저장, 진단)")
    if query:
        words = query.split()
        items = [i for i in items if all(w in i["q"] + i["a"] for w in words)]
        st.caption(f"{len(items)}건")
    groups = list(dict.fromkeys(i["group"] for i in items))
    for g in groups:
        st.subheader(g)
        for it in [i for i in items if i["group"] == g]:
            with st.expander(it["q"]):
                st.markdown(it["a"])
                st.caption("근거: " + " · ".join(it["sources"]))
                if st.toggle("근거 조각 보기", key=f"src-{it['id']}"):
                    for s in it["sources"]:
                        show_chunk(s)
    if not items:
        st.info("찾는 Q&A가 없습니다.")
    st.divider()
    st.markdown("**여기서 답을 찾지 못했나요?**")
    if st.button(f"💬 {ROUTE_NAMES[route]}(으)로 직접 질문하기"):
        st.session_state.view = ("ask", None)
        st.session_state.ask_category = route
        st.rerun()


# ───────────────────────── 직접 질문 화면 ─────────────────────────

def badge_row(t):
    r = t["result"]
    check = r.get("check")
    verdict = (":gray-badge[검증 없음]" if check is None
               else ":green-badge[검증 통과]" if check["ok"] else ":red-badge[검증 위반]")
    cc = r.get("category_check")
    cc_badge = CHECK_BADGE.get(cc["status"], "") if cc else ""
    tools = ", ".join(c["name"] for c in r["calls"]) or "도구 없음"
    st.markdown(f"{cc_badge} :violet-badge[{ROUTE_NAMES.get(r['route'], r['route'])}] "
                f":gray-badge[확신도 {r['confidence']:.2f}] :blue-badge[{ACTION_LABEL.get(r['action'], r['action'])}] "
                f"{verdict} :gray-badge[{tools}]")


def details(t):
    r = t["result"]
    tab_route, tab_tools, tab_chunks, tab_check = st.tabs(["① 분류·카테고리 검증", "② 호출한 도구", "③ 근거", "④ 검증"])
    with tab_route:
        cc = r.get("category_check")
        if cc:
            st.markdown(f"- 질문자가 고른 카테고리: **{ROUTE_NAMES[cc['selected']]}**")
            st.markdown(f"- 분류기 판단: **{ROUTE_NAMES.get(cc['detected'], cc['detected'])}** (확신도 {cc['confidence']:.2f})")
            {"match": st.success, "mismatch": st.warning, "unclear": st.warning}[cc["status"]](
                {"match": "고른 카테고리가 질문 내용과 맞습니다.",
                 "mismatch": "고른 카테고리가 질문 내용과 달라, 분류기 판단대로 답했습니다.",
                 "unclear": "질문만으로는 카테고리를 확신할 수 없어 답하지 않고 되물었습니다."}[cc["status"]])
            st.caption("고른 카테고리는 분류기에 넘기지 않습니다. 분류기가 질문만 보고 따로 판정한 뒤 대조합니다.")
        st.markdown(f"판단 이유: {r.get('reason', '')}")
    with tab_tools:
        if not r["calls"]:
            st.write("부른 도구가 없습니다.")
        for i, c in enumerate(r["calls"], 1):
            st.markdown(f"**{i}. `{c['name']}`**")
            st.code(json.dumps(c["args"], ensure_ascii=False, indent=1), language="json")
    with tab_chunks:
        read = r.get("chunks", {})
        st.markdown(f"**도구로 조회한 조각 {len(read)}개**")
        for cid, c in read.items():
            show_chunk(cid, c.get("original"))
        prompt_ids = [cid for cid in r.get("prompt_chunks", []) if cid not in read]
        if prompt_ids:
            st.markdown(f"**프롬프트에 넣은 조각 {len(prompt_ids)}개** (카테고리 공통 기준)")
            for cid in prompt_ids:
                show_chunk(cid)
    with tab_check:
        check = r.get("check")
        if check is None:
            st.write("되묻기라 검증하지 않았습니다.")
        else:
            if check["ok"]:
                st.success("답변 속 수치·조각 인용·주소·접수번호가 모두 근거에서 확인됐고, 명령어·규칙 번호가 없습니다.")
            else:
                st.error("근거에서 확인되지 않은 내용이 있습니다.")
                for v in check["violations"]:
                    st.markdown(f"- **{v['type']}**: {v['detail']}")
            st.caption("검사 대상 근거: " + ", ".join(check["evidence_chunks"]))
        first = r.get("first_answer")
        if first:
            st.warning("첫 답변이 검증에서 걸려 한 번 다시 생성했습니다.")
            st.markdown(first["answer"])


def render_turn(t):
    with st.chat_message("user"):
        st.markdown(t["question"])
        st.caption(f"고른 카테고리: {ROUTE_NAMES[t['selected']]}")
    with st.chat_message("assistant"):
        st.markdown(t["result"]["answer"])
        badge_row(t)
        details(t)


def send(question, selected):
    with st.spinner("카테고리를 확인하고 근거를 찾는 중…"):
        result = help_desk(question, history(), selected_category=selected)
    st.session_state.turns.append({"question": question, "selected": selected, "result": result})
    st.session_state.draft = None
    st.session_state.form_no = st.session_state.get("form_no", 0) + 1


def ask_view():
    st.title("💬 직접 질문하기")
    st.caption("준비된 Q&A에서 답을 찾지 못한 질문만 보내 주세요. 카테고리를 먼저 골라야 합니다.")
    for t in st.session_state.turns:
        render_turn(t)

    draft = st.session_state.draft
    if draft:   # 비슷한 준비된 Q&A가 있어 확인 중
        st.info(f"보내기 전에 — 비슷한 준비된 Q&A가 {len(draft['similar'])}건 있습니다.")
        for score, it in draft["similar"]:
            with st.expander(f"{ROUTE_ICON[it['route']]} {it['q']}  ·  {ROUTE_NAMES[it['route']]}"):
                st.markdown(it["a"])
                st.caption("근거: " + " · ".join(it["sources"]) + f" · 유사도 {score:.2f}")
        c1, c2 = st.columns(2)
        if c1.button("이 답으로 해결됐어요", use_container_width=True):
            st.session_state.draft = None
            st.rerun()
        if c2.button("그래도 질문 보내기", type="primary", use_container_width=True):
            send(draft["question"], draft["selected"])
            st.rerun()
        return

    # 보낸 뒤에만 입력칸을 비운다 — 카테고리를 안 골라 막혔을 때 쓴 질문이 지워지지 않게 폼 키를 바꿔 비운다
    with st.form(f"ask-{st.session_state.get('form_no', 0)}"):
        default = st.session_state.pop("ask_category", None)
        selected = st.selectbox("카테고리 (필수)", ROUTES, index=ROUTES.index(default) if default else None,
                                format_func=lambda r: f"{ROUTE_ICON[r]} {ROUTE_NAMES[r]} — {ROUTE_DESC[r]}",
                                placeholder="질문에 맞는 카테고리를 고르세요")
        question = st.text_area("질문", placeholder="예: 받은 TC에 번역만 할 때 읽기 속도 초과가 뜨면 어떻게 해요?")
        submitted = st.form_submit_button("보내기", type="primary")
    if submitted:
        if not selected:
            st.error("카테고리를 먼저 골라 주세요.")
            return
        if not question.strip():
            st.error("질문을 입력해 주세요.")
            return
        similar = faq_index().search(question)
        if similar:
            st.session_state.draft = {"question": question.strip(), "selected": selected, "similar": similar}
        else:
            send(question.strip(), selected)
        st.rerun()


def main():
    init_state()
    sidebar()
    kind, route = st.session_state.view
    if kind == "faq":
        faq_view(route)
    else:
        ask_view()


main()
