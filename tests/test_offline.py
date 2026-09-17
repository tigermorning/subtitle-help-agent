# -*- coding: utf-8 -*-
"""API 없이 도는 시험. 모델 호출이 일어나면 바로 실패한다.

    python tests/test_offline.py

- 카테고리 대조(agent.check_category)를 가짜 분류 결과로 확인한다
- 준비된 Q&A 검증(faq.verify_faq)과 비슷한 Q&A 찾기(SimilarIndex)를 확인한다
- 데모 화면(app.py)을 Streamlit AppTest로 띄우고, help_desk를 가짜 응답으로 바꿔 흐름을 확인한다
  사이드바 카테고리 → Q&A 목록 → 직접 질문(카테고리 필수) → 비슷한 Q&A 먼저 보기 → 보내기 → 카테고리 검증 배지
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8")

# ── 모델 호출 차단 ── init_chat_model 을 부르는 순간 실패시킨다
import langchain.chat_models as _cm  # noqa: E402


def _blocked(*a, **k):
    raise RuntimeError("시험 중 모델 호출이 일어났다 — API 금지")


_cm.init_chat_model = _blocked
import router  # noqa: E402
import answer  # noqa: E402
router.init_chat_model = _blocked
answer.init_chat_model = _blocked

import agent  # noqa: E402

try:                                   # 차단이 실제로 걸리는지 먼저 확인한다 — 안 걸리면 아래 시험이 API를 쓸 수 있다
    router._chain = None
    router.classify({"question": "차단 확인"})
    _blocked_ok = False
except RuntimeError:
    _blocked_ok = True
from faq import SimilarIndex, load_faq, verify_faq  # noqa: E402

FAILS = []


def ok(name, cond):
    print(("  통과 " if cond else "  실패 ") + name)
    if not cond:
        FAILS.append(name)


def fake_out(route, confidence, action="ANSWER"):
    out = {"route": route, "confidence": confidence, "action": action, "reason": "가짜",
           "answer": "가짜 답변입니다. [U-07]", "calls": [{"name": "search_usage", "args": {"query": "x"}}],
           "chunks": {}, "prompt_chunks": [], "check": {"ok": True, "violations": [], "evidence_chunks": []}}
    if action == "CLARIFY":
        out.update(message=router.CLARIFY_MESSAGE, calls=[], check=None)
    return out


print("⓪ 모델 호출 차단")
ok("분류기를 부르면 RuntimeError — 이 시험은 API를 쓰지 않는다", _blocked_ok)
if not _blocked_ok:
    sys.exit(1)

print("① 카테고리 대조")
cc = agent.check_category("USAGE", fake_out("USAGE", 0.9))
ok("같으면 match", cc["status"] == "match" and cc["message"] == "")
cc = agent.check_category("STYLE_RULE", fake_out("USAGE", 0.9))
ok("다르면 mismatch + 판단 카테고리 이름을 알린다", cc["status"] == "mismatch" and "사용법" in cc["message"])
cc = agent.check_category("USAGE", fake_out("FEEDBACK", 0.3, "CLARIFY"))
ok("확신도 미달이면 unclear + 되묻는 문구", cc["status"] == "unclear" and "구체적으로" in cc["message"])
ok("고른 카테고리가 없으면 None", agent.check_category(None, fake_out("USAGE", 0.9)) is None)

print("①-2 help_desk (그래프만 가짜)")
GRAPH_INPUTS = []


class FakeGraph:
    def __init__(self, out):
        self.out = out

    def invoke(self, state):
        GRAPH_INPUTS.append(state)
        return dict(self.out)


real_app = agent.agent_app
agent.agent_app = FakeGraph(fake_out("USAGE", 0.9))
r = agent.help_desk("옵션 질문", history=[{"role": "user", "text": "앞 턴"}], selected_category="STYLE_RULE")
ok("고른 카테고리는 그래프(분류기) 입력에 들어가지 않는다",
   set(GRAPH_INPUTS[-1]) == {"question", "history"} and "STYLE_RULE" not in str(GRAPH_INPUTS[-1]))
ok("앞 턴은 그래프에 넘긴다", GRAPH_INPUTS[-1]["history"][0]["text"] == "앞 턴")
ok("mismatch면 안내 문구가 답변 앞에 붙는다",
   r["category_check"]["status"] == "mismatch" and r["answer"].startswith("고르신 카테고리는")
   and r["answer"].endswith("가짜 답변입니다. [U-07]"))
r = agent.help_desk("옵션 질문", selected_category="USAGE")
ok("match면 답변을 바꾸지 않는다", r["answer"] == "가짜 답변입니다. [U-07]")
agent.agent_app = FakeGraph(fake_out("FEEDBACK", 0.3, "CLARIFY"))
r = agent.help_desk("이거 왜 이래요", selected_category="USAGE")
ok("unclear면 답변이 카테고리 확인 불가 + 되묻기 문구이고 도구·근거가 비어 있다",
   r["category_check"]["status"] == "unclear" and r["answer"].startswith("고르신 카테고리 '사용법'")
   and r["calls"] == [] and r["chunks"] == {})
r = agent.help_desk("이거 왜 이래요")
ok("카테고리를 안 주면 category_check 가 없다", "category_check" not in r and r["answer"] == router.CLARIFY_MESSAGE)
agent.agent_app = real_app

print("② 준비된 Q&A")
items = load_faq()
passed, failed = verify_faq(items)
ok(f"Q&A {len(items)}건 모두 근거 검증 통과", not failed)
routes = {i["route"] for i in items}
ok("다섯 카테고리 모두 Q&A가 있다", routes == set(agent.ROUTE_NAMES))
idx = SimilarIndex(items)
first = items[0]
hits = idx.search(first["q"])
ok("같은 질문을 넣으면 그 Q&A가 1위", bool(hits) and hits[0][1]["id"] == first["id"])
ok("무관한 문장은 비슷한 Q&A가 없다", idx.search("오늘 점심 메뉴 추천해 주세요") == [])

print("②-2 규칙 번호를 사용자에게 보이지 않는다")
import json as _json  # noqa: E402
import re as _re  # noqa: E402
import tools  # noqa: E402
from config import DATA  # noqa: E402
from guardrail import guardrail  # noqa: E402

for q, want in [("SDH 읽기 속도 초과", "읽기 속도 초과 (SDH)"), ("괄호가 안 닫혔다", "닫히지 않은 괄호"),
                ("줄 끝 마침표·쉼표", "줄 끝 마침표·쉼표")]:
    r = tools.get_check_info(q)
    ok(f"검사 항목을 내용으로 찾는다: {q}", r["found"] and any(c["title"] == want for c in r["chunks"]))
r = tools.get_check_info("S02")
ok("리포트 표시를 붙여 넣어도 찾는다", r["found"] and any(c["title"] == "읽기 속도 초과 (SDH)" for c in r["chunks"]))
g = guardrail("", {"answer": "S02 reading_speed_exceeded 입니다. [Q-24]", "calls": [], "chunks": {},
                   "prompt_chunks": ["Q-24"]})
ok("답변 속 규칙 번호·검사 이름은 검증기가 잡는다",
   any(v["type"] == "내부 표기 노출" and set(v["detail"]) == {"S02", "reading_speed_exceeded"} for v in g["violations"]))
g = guardrail("", {"answer": "SDH 읽기 속도 초과는 확인 항목입니다. [Q-24]", "calls": [], "chunks": {},
                   "prompt_chunks": ["Q-24"]})
ok("조각 ID 인용만 있으면 내부 표기로 보지 않는다", not any(v["type"] == "내부 표기 노출" for v in g["violations"]))
RULE_NO = _re.compile(r"(?<![A-Za-z0-9.+-])[CTSK]\d{2}(?![0-9A-Za-z])")
leaks = [i["id"] for i in items if RULE_NO.search(i["q"] + i["a"])]
ok("준비된 Q&A 질문·답에 규칙 번호가 없다", not leaks)
gold = _json.loads((DATA / "goldenset.json").read_text(encoding="utf-8"))["items"]
leaks = [i.get("id") for i in gold if RULE_NO.search(_json.dumps(i, ensure_ascii=False))]
ok("평가셋(goldenset) 질문·모범 답에 규칙 번호가 없다", not leaks)
for name in ["inquiries.csv", "hard_cases.csv", "answer_goldenset_multiturn.json"]:
    ok(f"{name} 에 규칙 번호가 없다", not RULE_NO.search((DATA / name).read_text(encoding="utf-8-sig")))

print("③ 데모 화면 (가짜 help_desk)")
from streamlit.testing.v1 import AppTest  # noqa: E402

CALLS = []


def fake_help_desk(question, history=None, selected_category=None):
    CALLS.append((question, selected_category))
    out = fake_out("USAGE", 0.93)
    cc = agent.check_category(selected_category, out)
    out["category_check"] = cc
    if cc and cc["status"] == "mismatch":
        out["answer"] = f"{cc['message']}\n\n{out['answer']}"
    return {"question": question, **out}


agent.help_desk = fake_help_desk

at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
at.run()
ok("처음 화면에 예외가 없다", not at.exception)
ok("사이드바에 카테고리 버튼 5개 + 직접 질문하기", sum(1 for b in at.sidebar.button if "·" in b.label) == 5
   and any("직접 질문하기" in b.label for b in at.sidebar.button))
ok("첫 화면은 사용법 Q&A 목록", at.title[0].value.endswith("사용법") and len(at.expander) >= 5)

style_btn = next(b for b in at.sidebar.button if "자막 규정" in b.label)
style_btn.click().run()
n_style = sum(1 for i in items if i["route"] == "STYLE_RULE")
ok(f"자막 규정 누르면 Q&A {n_style}건이 펼침으로 나온다", at.title[0].value.endswith("자막 규정")
   and len([e for e in at.expander if not e.label.startswith("[")]) == n_style)

at.text_input[0].input("말줄임표").run()
ok("카테고리 안 검색으로 거른다", 0 < len(at.expander) < n_style)

ask_btn = next(b for b in at.sidebar.button if "직접 질문하기" in b.label)
ask_btn.click().run()
ok("직접 질문 화면", at.title[0].value.endswith("직접 질문하기"))

at.text_area[0].input("SubtitleEdit 북마크를 여러 파일에서 모으는 옵션이 뭐예요?")
at.button(key=next(b.key for b in at.button if b.label == "보내기")).click().run()
ok("카테고리 없이 보내면 막힌다", any("카테고리를 먼저" in e.value for e in at.error) and not CALLS)
ok("막혀도 쓴 질문은 남아 있다", at.text_area[0].value.startswith("SubtitleEdit"))

at.selectbox[0].select("STYLE_RULE")
at.button(key=next(b.key for b in at.button if b.label == "보내기")).click().run()
ok("고른 카테고리를 함께 넘긴다", CALLS and CALLS[-1][1] == "STYLE_RULE")
md = " ".join(m.value for m in at.markdown)
ok("다르게 고르면 '카테고리 바로잡음' 배지와 안내 문구", "카테고리 바로잡음" in md and "고르신 카테고리는" in md)
ok("대화에 고른 카테고리가 표시된다", any("고른 카테고리: 자막 규정" in c.value for c in at.caption))

same = items[0]
at.selectbox[0].select(same["route"])
at.text_area[0].input(same["q"])
before = len(CALLS)
at.button(key=next(b.key for b in at.button if b.label == "보내기")).click().run()
ok("준비된 Q&A와 같은 질문은 보내기 전에 비슷한 Q&A를 먼저 보여 준다",
   len(CALLS) == before and any("비슷한 준비된 Q&A" in i.value for i in at.info))
send_anyway = next(b for b in at.button if b.label == "그래도 질문 보내기")
send_anyway.click().run()
ok("그래도 보내면 보낸다", len(CALLS) == before + 1)
ok("끝까지 예외 없음", not at.exception)

print()
print("모두 통과" if not FAILS else f"실패 {len(FAILS)}건: {FAILS}")
sys.exit(1 if FAILS else 0)
