# -*- coding: utf-8 -*-
"""근거 문서를 조각으로 쪼개고, 카테고리에 필요한 것만 골라 프롬프트를 조립한다.

조각 = `docs/*.md`의 `## [ID] 제목` 섹션 하나. 매핑은 `docs/MAPPING.md` 2절을 옮긴 것이다.

프롬프트에는 **조각 본문을 전부 넣지 않는다.** 카테고리의 목차(ID·제목)와 항상 넣는 조각만
넣고, 본문은 도구로 조회하게 한다. 그래야 "필요한 근거를 읽었는가"가 도구 호출로 드러나
측정할 수 있고, 관련 없는 조항이 답을 끌고 가는 일도 줄어든다.
"""
import re

from config import DOCS

HEADING = re.compile(r"^## \[([A-Z]+-[A-Z0-9.]+)\] (.+)$", re.M)

# 카테고리 → 조각을 가진 문서. docs/MAPPING.md 2절
ROUTE_DOCS = {
    "USAGE": ["10_usage.md"],
    "QC_EXPLAIN": ["20_qc_checks.md"],
    "STYLE_RULE": ["30_style_netflix.md"],
    "FEEDBACK": ["40_feedback.md"],
    "OUT_OF_SCOPE": ["50_referral_nikl.md"],
}

# 모든 카테고리에 넣는 조각 — 대본 붙여넣기 금지, 범위 밖 기준
ALWAYS = ["F-04", "R-04", "R-05"]

# 목차가 아니라 본문까지 넣는 카테고리 — 조각이 적고, 조회 도구가 따로 없는 판단 기준이다
FULL_TEXT_ROUTES = {"FEEDBACK", "OUT_OF_SCOPE"}


def split_chunks(text, source):
    """`## [ID] 제목` 단위로 쪼갠다. 반환: {id: {id, title, text, source}}"""
    out = {}
    marks = list(HEADING.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[m.group(1)] = {"id": m.group(1), "title": m.group(2).strip(),
                           "text": text[m.start():end].strip(), "source": source}
    return out


def load_chunks():
    chunks = {}
    for name in sorted({f for fs in ROUTE_DOCS.values() for f in fs}):
        chunks.update(split_chunks((DOCS / name).read_text(encoding="utf-8"), name))
    return chunks


CHUNKS = load_chunks()


def chunks_in(doc_name):
    return [c for c in CHUNKS.values() if c["source"] == doc_name]


def table_of_contents(route):
    lines = []
    for doc in ROUTE_DOCS.get(route, []):
        lines += [f"- [{c['id']}] {c['title']}" for c in chunks_in(doc)]
    return "\n".join(lines)


def build_context(route):
    """카테고리에 필요한 근거만 이어 붙인다. 반환: (텍스트, 프롬프트에 넣은 조각 ID 목록)"""
    parts, used = [], []
    if route in FULL_TEXT_ROUTES:
        for doc in ROUTE_DOCS[route]:
            for c in chunks_in(doc):
                parts.append(c["text"])
                used.append(c["id"])
    else:
        parts.append(f"[이 카테고리의 조각 목차 — 본문은 도구로 조회한다]\n{table_of_contents(route)}")
    for cid in ALWAYS:
        if cid not in used:
            parts.append(CHUNKS[cid]["text"])
            used.append(cid)
    return "\n\n".join(parts), used


def build_answer_prompt(route):
    """답변 생성용 시스템 프롬프트. 반환: (프롬프트, 프롬프트에 넣은 조각 ID 목록)"""
    from prompts import ANSWER_RULES, ROUTE_RULES
    ctx, used = build_context(route)
    return (f"{ANSWER_RULES}\n\n===== 카테고리: {route} =====\n{ROUTE_RULES[route]}\n\n"
            f"===== 근거 =====\n{ctx}\n"), used
