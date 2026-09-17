# -*- coding: utf-8 -*-
"""준비된 Q&A(`data/faq.json`) — 불러오기, 근거 검증, 비슷한 Q&A 찾기.

    python faq.py        # 전 항목 검증. 하나라도 걸리면 종료 코드 1

Q&A도 답변이다. 모델이 만든 답과 **같은 잣대**로 잰다 — 답 속 수치·옵션·주소·조각 인용이
`sources` 조각에 있어야 한다(`guardrail.py`). 여기에 더해 첫 근거 조각이 그 카테고리의 문서에
있어야 한다. 그래야 Q&A가 엉뚱한 카테고리 칸에 꽂히지 않는다.

한계: guardrail과 같다. 숫자·이름·주소가 아닌 **서술**의 오류는 못 잡는다.
"""
import json
import math
from collections import Counter

from config import DATA, ROUTES
from context import CHUNKS, ROUTE_DOCS
from guardrail import guardrail
from tools import _grams

FAQ_PATH = DATA / "faq.json"

# 비슷한 Q&A로 보여 줄 최소 점수 — 질문 2-gram 가중치 중 Q&A 질문과 겹치는 비율.
# 막는 값이 아니라 "먼저 이것부터 보세요"를 띄우는 값이다. 사용자는 그래도 보낼 수 있다
SIMILAR_MIN = 0.45


def load_faq():
    return json.loads(FAQ_PATH.read_text(encoding="utf-8"))["items"]


def check_item(item):
    """Q&A 한 건의 문제 목록. 빈 목록이면 통과."""
    problems = []
    if item["route"] not in ROUTES:
        return [f"없는 카테고리 {item['route']}"]
    missing = [s for s in item["sources"] if s not in CHUNKS]
    if missing:
        return [f"없는 조각 {missing}"]
    if not item["sources"] or CHUNKS[item["sources"][0]]["source"] not in ROUTE_DOCS[item["route"]]:
        problems.append(f"첫 근거 조각이 {item['route']} 문서에 없음")
    result = {"answer": item["a"], "calls": [],
              "chunks": {s: CHUNKS[s] for s in item["sources"]}, "prompt_chunks": []}
    # 질문 문장은 근거로 치지 않는다 — Q&A 작성자가 질문에 수치를 넣고 답에서 되받는 것을 막는다
    check = guardrail("", result)
    problems += [f"{v['type']}: {v['detail']}" for v in check["violations"]]
    return problems


def verify_faq(items=None):
    """반환: (통과한 항목, {id: 문제 목록}). 중복 ID도 문제로 잡는다."""
    items = load_faq() if items is None else items
    seen, passed, failed = set(), [], {}
    for it in items:
        problems = check_item(it)
        if it["id"] in seen:
            problems.append("중복 ID")
        seen.add(it["id"])
        if problems:
            failed[it["id"]] = problems
        else:
            passed.append(it)
    return passed, failed


class SimilarIndex:
    """질문끼리 글자 2-gram IDF 겹침. 도구의 검색과 같은 방식이다."""

    def __init__(self, items):
        self.items = items
        self.grams = [Counter(_grams(it["q"])) for it in items]
        df = Counter(g for tf in self.grams for g in tf)
        self.idf = {g: math.log(1 + len(items) / n) for g, n in df.items()}
        self.default_idf = math.log(1 + len(items))

    def search(self, question, k=3, min_score=SIMILAR_MIN):
        q = set(_grams(question))
        weight = {g: self.idf.get(g, self.default_idf) for g in q}
        total = sum(weight.values())
        if not total:
            return []
        scored = []
        for it, tf in zip(self.items, self.grams):
            score = sum(w for g, w in weight.items() if g in tf) / total
            if score >= min_score:
                scored.append((score, it))
        scored.sort(key=lambda p: -p[0])
        return scored[:k]


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")   # Windows 기본 cp949 콘솔에서 죽지 않게
    items = load_faq()
    passed, failed = verify_faq(items)
    per_route = Counter(it["route"] for it in items)
    print(f"Q&A {len(items)}건 — 통과 {len(passed)} / 실패 {len(failed)}")
    print("카테고리별:", dict(per_route))
    for fid, problems in failed.items():
        print(f"  {fid}")
        for p in problems:
            print(f"    - {p}")
    sys.exit(1 if failed else 0)
