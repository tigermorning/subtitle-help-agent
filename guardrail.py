# -*- coding: utf-8 -*-
"""답변에 근거 문서에 없는 내용이 섞였는지 **기계적으로** 검사한다.

근거 = 조회한 조각 + 프롬프트에 넣은 조각 + 문의 문장. 여기서 출처를 못 찾으면 위반이다.

    수치       답변 속 숫자가 근거에 있는가
    옵션       `--옵션` 이름이 근거에 있는가
    인용       [조각 ID]가 실제로 읽은 조각인가
    주소       URL이 근거에 있는가
    접수 단정  접수 도구를 안 부르고 "접수했다"고 하거나, 받지 않은 접수번호를 말하는가
    명령어     명령줄 명령(python·pip·winget·ollama 등)을 답변에 썼는가 — 사용자는 코딩을 모른다
    내부 표기  리포트 규칙 번호(C01·T05·S02·K01)나 검사 이름(snake_case)을 답변에 썼는가 — 사용자는 모른다

한계: 숫자·이름·주소가 아닌 **서술**의 오류(예: "자동으로 고쳐진다")는 못 잡는다. 그건 채점기가 본다.
"""
import re

from context import CHUNKS

ID = r"[A-Z]{1,3}(?:-[A-Z0-9.]+)+"
CITE = re.compile(rf"\[({ID}(?:\s*,\s*{ID})*)\]")
RECEIPT = re.compile(r"FB-\d{8}-\d{3}")
FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
URL = re.compile(r"https?://[^\s)\]>`'\"]+")
NUM = re.compile(r"\d+(?:\.\d+)?")
RULE_NO = re.compile(r"(?<![A-Za-z0-9.+-])[CTSK]\d{2}(?![0-9A-Za-z])")
CHECK_NAME = re.compile(r"\b[a-z]+(?:_[a-z0-9]+){2,}\b")
COMMAND = re.compile(r"\b(?:python3?|pip|winget|ollama)\b|\.bat\b|(?<![\w+-])-[a-z](?=\s)", re.I)


def _strip_meta(text):
    """숫자 검사에서 뺄 부분 — 조각 ID 인용, 접수번호, URL, 옵션 이름, 규칙 번호."""
    text = CITE.sub(" ", text)
    text = RECEIPT.sub(" ", text)
    text = URL.sub(" ", text)
    text = FLAG.sub(" ", text)
    text = re.sub(r"\b[A-Z]{1,3}(?:-[A-Z]+)*-?[A-Z]?\d+(?:\.\d+)?\b", " ", text)   # S02, KO-I.13, NR-TPL-3
    text = re.sub(r"U\+[0-9A-F]{4}", " ", text)
    return text


def _numbers(text):
    return {n.lstrip("0") or "0" for n in NUM.findall(re.sub(r"(?<=\d),(?=\d)", "", text))}


def evidence_text(result, question):
    ids = set(result.get("chunks", {})) | set(result.get("prompt_chunks", []))
    texts = [question] + [CHUNKS[i]["text"] for i in ids if i in CHUNKS]
    for c in result.get("chunks", {}).values():          # 원문 발췌도 근거다
        texts += [o["text"] + " " + o.get("url", "") for o in c.get("original", [])]
    return "\n".join(texts), ids


def guardrail(question, result):
    answer = result["answer"]
    evidence, ids = evidence_text(result, question)
    violations = []

    missing = sorted(_numbers(_strip_meta(answer)) - _numbers(evidence), key=len)
    if missing:
        violations.append({"type": "출처 없는 수치", "detail": missing})

    flags = sorted(set(FLAG.findall(answer)) - set(FLAG.findall(evidence)))
    if flags:
        violations.append({"type": "출처 없는 옵션", "detail": flags})

    cited = {c.strip() for m in CITE.findall(answer) for c in m.split(",")}
    unread = sorted(c for c in cited if c not in ids)
    if unread:
        violations.append({"type": "읽지 않은 조각 인용", "detail": unread})

    urls = sorted(u.rstrip(".,") for u in URL.findall(answer) if u.rstrip(".,") not in evidence)
    if urls:
        violations.append({"type": "출처 없는 주소", "detail": urls})

    called = [c["name"] for c in result.get("calls", [])]
    receipts = set(RECEIPT.findall(answer))
    if receipts and "submit_feedback" not in called:
        violations.append({"type": "접수 단정", "detail": sorted(receipts)})
    elif re.search(r"접수(했|되었|됐|하였)", answer) and "submit_feedback" not in called:
        violations.append({"type": "접수 단정", "detail": "submit_feedback 호출 없이 접수했다고 말함"})

    visible = CITE.sub(" ", answer)
    commands = sorted({m.group(0) for m in COMMAND.finditer(visible)})
    if commands:
        violations.append({"type": "명령어 노출", "detail": commands})
    internal = sorted(set(RULE_NO.findall(visible)) | set(CHECK_NAME.findall(visible)))
    if internal:
        violations.append({"type": "내부 표기 노출", "detail": internal})

    return {"ok": not violations, "violations": violations, "evidence_chunks": sorted(ids)}


def feedback_text(check):
    return "\n".join(f"- {v['type']}: {v['detail']}" for v in check["violations"])
