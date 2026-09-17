# -*- coding: utf-8 -*-
"""근거 문서 요약 조각에 대응하는 **원문 발췌**를 찾는다.

원문은 `sources/fetch_netflix.py`로 받아 `sources/raw/`에 두고, 저장소에는 올리지 않는다.
원문이 없는 환경(저장소만 받은 경우)에서는 빈 목록을 돌려주고 요약만으로 돈다.

대응 규칙
    KO-I.n / KO-II.n   한국어 가이드(216001127)의 I.n / II.n 절
    GR-n               General Requirements(215758617)의 n 절
    TM-n               Subtitle Timing Guidelines(360051554394)의 n 절 (TM-0은 Introduction)
    그 밖              조각의 `- 원문:` 줄에 적힌 글 번호와 "N절" 표기
"""
import re
from functools import lru_cache

from config import ROOT

RAW = ROOT / "sources" / "raw"
MAX_CHARS = 4000

ARTICLE_KO = "216001127"
ARTICLE_GR = "215758617"
ARTICLE_TM = "360051554394"


def _section_key(title):
    t = title.strip()
    if m := re.match(r"^(II|I)\.(\d+)", t):
        return f"{m.group(1)}.{m.group(2)}"
    if m := re.match(r"^(II|I)\.\s", t):
        return m.group(1)
    if m := re.match(r"^(\d+)[.:]", t):
        return m.group(1)
    return t


@lru_cache(maxsize=None)
def load_article(aid):
    path = RAW / f"netflix-{aid}.md"
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    meta = {"article": aid, "title": lines[0].lstrip("# ").strip(), "url": "", "edited_at": ""}
    for line in lines[1:6]:
        if line.startswith("source:"):
            meta["url"] = line.split(":", 1)[1].strip()
        elif line.startswith("edited_at:"):
            meta["edited_at"] = line.split(":", 1)[1].strip()[:10]
    sections, title, buf = [], "(머리말)", []
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.startswith("#"):
            sections.append((title, "\n".join(buf).strip()))
            title, buf = line.lstrip("#").strip(), []
            while not title and i + 1 < len(lines):     # "# " 다음 줄에 제목이 오는 경우
                i += 1
                title = lines[i].strip()
        else:
            buf.append(line)
        i += 1
    sections.append((title, "\n".join(buf).strip()))
    meta["sections"] = [(t, _section_key(t), body) for t, body in sections]
    meta["full"] = "\n".join(lines)
    return meta


def _excerpt(aid, keys=None):
    art = load_article(aid)
    if art is None:
        return None
    if keys:
        picked = [f"# {t}\n{body}" for t, k, body in art["sections"] if k in keys]
        if not picked:
            return None
        text = "\n\n".join(picked)
    else:
        text = art["full"]
    return {"article": aid, "title": art["title"], "url": art["url"],
            "edited_at": art["edited_at"], "text": text[:MAX_CHARS]}


def _hint_keys(line):
    keys = set()
    for a, b in re.findall(r"(\d+)~(\d+)절", line):
        keys |= {str(n) for n in range(int(a), int(b) + 1)}
    for group in re.findall(r"((?:\d+·)*\d+)절", line):
        keys |= set(group.split("·"))
    return keys or None


def originals_for(chunk):
    cid, out = chunk["id"], []
    if m := re.fullmatch(r"KO-(I{1,2})\.(\d+)", cid):
        keys = {"I", "II"} if m.group(2) == "0" else {f"{m.group(1)}.{m.group(2)}"}
        out.append(_excerpt(ARTICLE_KO, keys))
    elif m := re.fullmatch(r"GR-(\d+)", cid):
        # 원문에서 "9. Currency"는 제목이 아니라 8절 본문 안에 있다. GR-9 요약은 통화와 브랜드(10절)를 묶었다
        keys = {"8", "10"} if m.group(1) == "9" else {m.group(1)}
        out.append(_excerpt(ARTICLE_GR, keys))
    elif m := re.fullmatch(r"TM-(\d+)", cid):
        out.append(_excerpt(ARTICLE_TM, {"Introduction"} if m.group(1) == "0" else {m.group(1)}))
    else:
        for line in chunk["text"].splitlines():
            if line.startswith("- 원문:"):
                keys = _hint_keys(line)
                for aid in re.findall(r"\b(\d{6,})\b", line):
                    out.append(_excerpt(aid, keys))
                break
    return [o for o in out if o]
