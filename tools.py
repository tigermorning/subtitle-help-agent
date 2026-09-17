# -*- coding: utf-8 -*-
"""조회·접수 도구 5개. 모델이 골라 부른다.

돌려주는 값에는 항상 조각 ID가 들어 있다 — 답변이 어느 조각을 근거로 했는지 데모와 검증이
그 ID로 추적한다.

검색은 글자 2-gram 겹침 + IDF 가중이다. 한국어 조사가 붙어도 2-gram은 대부분 겹치고,
형태소 분석기 없이 돈다. 조각이 백여 개라 이 정도로 충분한지는 평가로 확인한다.
"""
import json
import math
import re
from collections import Counter
from datetime import datetime
from typing import Literal

from config import FEEDBACK_DIR, SEARCH_TOP_K
from context import CHUNKS, chunks_in

REF_ID = re.compile(r"`([A-Z]{1,2}-(?:I{1,2}\.\d+|[A-Z]?\d+))`")


def _grams(text):
    s = re.sub(r"\s+", " ", text.lower())
    words = re.findall(r"[0-9a-z가-힣\-]+", s)
    grams = []
    for w in words:
        grams += [w[i:i + 2] for i in range(max(1, len(w) - 1))]
    return grams


def _index(doc_name):
    docs = chunks_in(doc_name)
    tfs = {c["id"]: Counter(_grams(c["title"] * 2 + " " + c["text"])) for c in docs}
    df = Counter(g for tf in tfs.values() for g in tf)
    idf = {g: math.log(1 + len(docs) / n) for g, n in df.items()}
    return tfs, idf


_INDEX = {}


def _search(doc_name, query, k=SEARCH_TOP_K):
    if doc_name not in _INDEX:
        _INDEX[doc_name] = _index(doc_name)
    tfs, idf = _INDEX[doc_name]
    q = set(_grams(query))
    scored = []
    for cid, tf in tfs.items():
        score = sum(idf.get(g, 0) * (1 + math.log(tf[g])) for g in q if g in tf)
        if score > 0:
            scored.append((score, cid))
    scored.sort(reverse=True)
    return [_pack(cid) for _, cid in scored[:k]]


def _pack(cid):
    c = CHUNKS[cid]
    return {"id": cid, "title": c["title"], "text": c["text"]}


def search_usage(query: str) -> dict:
    """자막 생성기 사용법 문서에서 질문과 관련된 조각을 찾는다. 옵션·실행 방법·리포트 형식·결과 파일 질문에 쓴다."""
    return {"query": query, "chunks": _search("10_usage.md", query)}


def search_style_rule(query: str) -> dict:
    """넷플릭스 공개 자막 스타일 가이드 요약(한국어 번역·SDH·공통·타이밍)에서 관련 조항을 찾는다."""
    return {"query": query, "chunks": _search("30_style_netflix.md", query)}


def get_check_info(rule: str) -> dict:
    """검사 리포트의 규칙 번호(예: S02, T05, C01)나 검사 이름(예: reading_speed_exceeded)으로 검사 항목 설명을 가져온다.
    항목이 인용한 규정 조항과 리포트 읽는 법(Q-00)도 함께 돌려준다."""
    key = rule.strip().strip("[]`").upper()
    m = re.fullmatch(r"(?:Q-)?([CTS]\d{2})", key)
    hits = []
    if m and f"Q-{m.group(1)}" in CHUNKS:
        hits = [f"Q-{m.group(1)}"]
    elif not m:
        name = rule.strip().strip("`").lower()
        hits = [c["id"] for c in chunks_in("20_qc_checks.md")
                if c["id"] != "Q-00" and f"`{name}`" in c["title"]]
    if not hits:
        return {"rule": rule, "found": False,
                "note": "이 창구의 검사 항목 설명에 없는 번호다. 넷플릭스 외 발주처나 비공개 실무 자료 항목일 수 있다(Q-00).",
                "chunks": [_pack("Q-00")]}
    ids = ["Q-00"] + hits
    for cid in hits:
        basis = next((l for l in CHUNKS[cid]["text"].splitlines() if l.startswith("- 근거:")), "")
        ids += [r for r in REF_ID.findall(basis) if r in CHUNKS and r not in ids]
    return {"rule": rule, "found": True, "chunks": [_pack(cid) for cid in ids]}


def submit_feedback(kind: Literal["feature", "bug", "false_positive", "doc"], summary: str) -> dict:
    """기능 건의·버그·검사 오탐·문서 오류를 접수해 로컬에 기록하고 접수번호를 돌려준다.
    summary에는 요청의 요지만 적는다. 대본·미공개 자막 원문은 절대 넣지 않는다."""
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    n = len(list(FEEDBACK_DIR.glob(f"FB-{today}-*.json"))) + 1
    receipt = f"FB-{today}-{n:03d}"
    record = {"receipt": receipt, "kind": kind, "summary": summary[:500],
              "created": datetime.now().isoformat(timespec="seconds")}
    (FEEDBACK_DIR / f"{receipt}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"receipt": receipt, "kind": kind, "chunks": [_pack("F-02")]}


def refer_to_nikl() -> dict:
    """맞춤법·띄어쓰기·표준어·외래어 표기 같은 한국어 어문 규범 질문을 국립국어원 자료로 안내한다.
    근거 문서에 조항이 없는 어문 규범 질문에만 쓴다."""
    return {"chunks": [_pack("R-01"), _pack("R-02"), _pack("KO-I.21")]}


TOOLS = {f.__name__: f for f in [search_usage, get_check_info, search_style_rule,
                                 submit_feedback, refer_to_nikl]}
