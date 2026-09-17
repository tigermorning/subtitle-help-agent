# -*- coding: utf-8 -*-
"""지표를 잰다. 점수보다 그 아래 실패 목록이 중요하다 — 무엇을 고칠지가 거기 적혀 있다.

    python evaluate.py                    # 전체: 분류 + 도구 호출 + 답변 (goldenset eval 분할)
    python evaluate.py --only router      # 분류만 — routing_answers.csv eval 분할(카테고리당 24건)
    python evaluate.py --hard             # 어려운 문항 — 되묻기/처리 판단과 분류 (hard_cases.csv)
    python evaluate.py --multiturn        # 여러 턴 대화 (answer_goldenset_multiturn.json)
    python evaluate.py --category-check   # 질문자가 고른 카테고리 검증 — 분류 120건에 맞는 선택·틀린 선택을 흉내 낸다
    python evaluate.py --validate         # 모범 답안으로 채점기 자체를 검증한다(1턴 + 여러 턴)
    python evaluate.py --label 01-이름     # runs/01-이름.json 으로 결과를 남긴다

지표
    분류        정확도 · macro F1 · 혼동 행렬
    도구 호출   실제 호출 도구 집합 == 기대 도구 집합이면 1점
    답변        must 전부 담고 forbid 하나도 안 어기면 1점 — 채점기(LLM)가 표현이 아니라 사실을 본다
"""
import argparse
import csv
import json
import sys
from collections import Counter

from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score

from common import pmap
from config import DATA, JUDGE_MODEL, ROUTES, RUNS, WORKERS

JUDGE_RULES = """\
너는 자막 생성기 문의 창구의 답변 채점기다. 답변 하나를 두 목록과 대조한다.

[must — 답변에 사실로 담겨야 하는 것]
- 표현이 달라도 같은 사실이면 담긴 것이다(예: "초당 14자" = "1초에 14자까지")
- 사실의 일부만 담겼으면 담기지 않은 것이다
- 되묻기·접수·안내 같은 행동 항목은 답변에 그 행동이 **명시적으로** 적혀 있어야 담긴 것이다
  (예: "접수했다"는 "접수했습니다"·"접수번호는 …" 같은 문장이 있어야 한다. "확인해 보겠습니다"는 접수가 아니다)

[forbid — 답변이 사실로 주장하면 안 되는 것]
- 답변이 그 내용을 **주장하거나 권하면** 위반이다
- 그 내용을 부정하거나("~가 아닙니다"), 틀린 예로 대조하며 언급하는 것은 위반이 아니다
- 비슷한 주제를 말했다는 것만으로 위반으로 보지 않는다

각 항목마다 판정과 근거(답변에서 해당하는 구절, 없으면 "없음")를 낸다.
"""


class ItemVerdict(BaseModel):
    index: int = Field(description="목록에 붙은 번호")
    ok: bool = Field(description="must면 담겼는가, forbid면 위반했는가")
    quote: str = Field(description="판정 근거가 된 답변 구절. 없으면 '없음'")


class Verdict(BaseModel):
    must: list[ItemVerdict] = Field(description="must 항목마다 하나씩, 빠짐없이. ok=담겼다")
    forbid: list[ItemVerdict] = Field(description="forbid 항목마다 하나씩, 빠짐없이. ok=위반했다")


_judge = None


def _ask_judge(question, answer, must, forbid):
    global _judge
    if _judge is None:
        _judge = init_chat_model(JUDGE_MODEL, model_provider="openai", temperature=0,
                                 timeout=90, max_retries=2).with_structured_output(Verdict)
    body = (f"문의: {question}\n\n답변:\n{answer}\n\n"
            f"must ({len(must)}개):\n" + "\n".join(f"{n}. {m}" for n, m in enumerate(must, 1)) +
            f"\n\nforbid ({len(forbid)}개):\n" + "\n".join(f"{n}. {f}" for n, f in enumerate(forbid, 1)))
    return _judge.invoke([("system", JUDGE_RULES), ("human", body)])


def judge(question, answer, must, forbid):
    """항목 번호로 판정을 받는다. 채점기가 항목을 빠뜨리면 한 번 더 묻고, 그래도 빠지면
    must는 누락으로, forbid는 판정 누락으로 센다 — 빠진 항목을 조용히 통과시키지 않는다."""
    for _ in range(2):
        v = _ask_judge(question, answer, must, forbid)
        got_m = {x.index: x for x in v.must}
        got_f = {x.index: x for x in v.forbid}
        if set(got_m) >= set(range(1, len(must) + 1)) and set(got_f) >= set(range(1, len(forbid) + 1)):
            break
    missing = [m for n, m in enumerate(must, 1) if n not in got_m or not got_m[n].ok]
    violated = [f for n, f in enumerate(forbid, 1) if n in got_f and got_f[n].ok]
    unjudged = [f for n, f in enumerate(forbid, 1) if n not in got_f]
    return {"pass": not missing and not violated and not unjudged,
            "missing": missing, "violated": violated, "unjudged": unjudged,
            "detail": v.model_dump()}


def load_items(split):
    items = json.loads((DATA / "goldenset.json").read_text(encoding="utf-8"))["items"]
    return [i for i in items if split == "all" or i["split"] == split]


def route_report(golds, preds):
    print(f"\n① 분류  n={len(golds)}")
    print(f"  정확도  {accuracy_score(golds, preds):.3f}")
    print(f"  macro F1 {f1_score(golds, preds, labels=ROUTES, average='macro', zero_division=0):.3f}")
    cm = confusion_matrix(golds, preds, labels=ROUTES)
    short = [r[:6] for r in ROUTES]
    print("  혼동 행렬 (행=정답, 열=예측)")
    print("  " + " " * 13 + " ".join(f"{s:>6}" for s in short))
    for r, row in zip(ROUTES, cm):
        print(f"  {r:<13}" + " ".join(f"{n:>6}" for n in row))
    return cm.tolist()


def load_routing(split):
    inq = {r["qa_id"]: r for r in csv.DictReader(open(DATA / "inquiries.csv", encoding="utf-8-sig"))}
    out = []
    for a in csv.DictReader(open(DATA / "routing_answers.csv", encoding="utf-8-sig")):
        if split == "all" or a["split"] == split:
            out.append({"id": a["qa_id"], "route": a["route"], "question": inq[a["qa_id"]]["question"]})
    return out


def run_router(items):
    from router import route
    outs = pmap(lambda i: route(i["question"]), items, WORKERS)
    golds, preds = [i["route"] for i in items], [o["route"] for o in outs]
    cm = route_report(golds, preds)
    wrong = [(i, o) for i, o in zip(items, outs) if i["route"] != o["route"]]
    if wrong:
        print("\n  오분류")
        for i, o in wrong:
            print(f"  {i['id']} 정답 {i['route']} → {o['route']} (conf {o['confidence']:.2f}) {i['question']}")
            print(f"        이유: {o['reason']}")
    clar = [(i, o) for i, o in zip(items, outs) if o["action"] == "CLARIFY"]
    print(f"\n  되묻기로 빠짐 {len(clar)}건" + "".join(f"\n  {i['id']} conf {o['confidence']:.2f}" for i, o in clar))
    return {"routes": [{"id": i["id"], "gold": i["route"], "pred": o["route"],
                        "confidence": o["confidence"], "action": o["action"], "reason": o["reason"]}
                       for i, o in zip(items, outs)], "confusion": cm}


def run_full(items):
    from agent import help_desk

    def one(i):
        r = help_desk(i["question"])
        called = sorted({c["name"] for c in r["calls"]})
        v = judge(i["question"], r["answer"], i["must"], i["forbid"])
        return {"id": i["id"], "question": i["question"], "gold_route": i["route"],
                "route": r["route"], "confidence": r["confidence"], "action": r["action"],
                "expected_tools": sorted(i["expected_tools"]), "called": called,
                "calls": r["calls"], "tool_pass": called == sorted(i["expected_tools"]),
                "answer": r["answer"], "answer_pass": v["pass"], "missing": v["missing"],
                "violated": v["violated"], "guard": r.get("check"),
                "retried": bool(r.get("first_answer")), "judge": v["detail"]}

    rows = pmap(one, items, WORKERS)
    cm = route_report([r["gold_route"] for r in rows], [r["route"] for r in rows])
    n = len(rows)
    tool_ok = sum(r["tool_pass"] for r in rows)
    ans_ok = sum(r["answer_pass"] for r in rows)
    both = sum(r["tool_pass"] and r["answer_pass"] for r in rows)
    print(f"\n② 도구 호출 적절성  {tool_ok}/{n} = {tool_ok / n:.1%}")
    print(f"③ 답변 적절성       {ans_ok}/{n} = {ans_ok / n:.1%}")
    print(f"   둘 다 통과        {both}/{n} = {both / n:.1%}")
    print(f"   forbid 위반        {sum(bool(r['violated']) for r in rows)}건")
    actions = Counter(r["action"] for r in rows)
    print(f"   행동 분포          {dict(actions)}")
    print(f"   검증 재생성        {sum(r['retried'] for r in rows)}건")

    print("\n실패 목록")
    for r in rows:
        if r["tool_pass"] and r["answer_pass"]:
            continue
        print(f"\n  {r['id']} [{r['gold_route']}→{r['route']} {r['confidence']:.2f} {r['action']}] {r['question']}")
        if not r["tool_pass"]:
            print(f"    도구: 기대 {r['expected_tools']} / 실제 {r['called']}")
        if r["missing"]:
            print(f"    must 누락: {r['missing']}")
        if r["violated"]:
            print(f"    forbid 위반: {r['violated']}")
        if r["guard"] and not r["guard"]["ok"]:
            print(f"    검증 위반: {r['guard']['violations']}")
        print("    답변: " + r["answer"].replace("\n", " ")[:300])
    return {"rows": rows, "confusion": cm,
            "summary": {"n": n, "tool_pass": tool_ok, "answer_pass": ans_ok, "both": both,
                        "route_acc": sum(r["gold_route"] == r["route"] for r in rows) / n,
                        "actions": dict(actions)}}


def run_hard():
    """어려운 문항. 되묻기가 정답인 문항은 action=CLARIFY, 나머지는 HANDLE + 분류를 본다.
    다중의도는 route_expected·route_alt 둘 중 하나면 분류 정답으로 센다."""
    from router import route
    rows = list(csv.DictReader(open(DATA / "hard_cases.csv", encoding="utf-8-sig")))
    outs = pmap(lambda r: route(r["question"]), rows, WORKERS)
    res = []
    for r, o in zip(rows, outs):
        want = "CLARIFY" if r["expected_action"] == "CLARIFY" else "HANDLE"
        ok_action = o["action"] == want
        ok_route = True if want == "CLARIFY" else o["route"] in {r["route_expected"], r["route_alt"]} - {""}
        res.append({"id": r["qa_id"], "type": r["hard_type"], "want": want, "got": o["action"],
                    "route_expected": r["route_expected"], "route_alt": r["route_alt"], "route": o["route"],
                    "confidence": o["confidence"], "pass": ok_action and ok_route, "question": r["question"]})
    n = len(res)
    print(f"어려운 문항 n={n}  통과 {sum(x['pass'] for x in res)}/{n}")
    print("  유형       통과   되묻기가 정답→되물음   처리가 정답→맞게 처리")
    for t in dict.fromkeys(x["type"] for x in res):
        g = [x for x in res if x["type"] == t]
        cl = [x for x in g if x["want"] == "CLARIFY"]
        ha = [x for x in g if x["want"] == "HANDLE"]
        print(f"  {t:<8} {sum(x['pass'] for x in g):>3}/{len(g):<3} "
              f"{sum(x['got'] == 'CLARIFY' for x in cl):>9}/{len(cl):<9} {sum(x['pass'] for x in ha):>9}/{len(ha)}")
    print("\n실패")
    for x in res:
        if not x["pass"]:
            print(f"  {x['id']} [{x['type']}] 기대 {x['want']} {x['route_expected']}/{x['route_alt'] or '-'} "
                  f"→ {x['got']} {x['route']} ({x['confidence']:.2f}) {x['question']}")
    return {"rows": res, "pass": sum(x["pass"] for x in res), "n": n}


def load_multiturn():
    return json.loads((DATA / "answer_goldenset_multiturn.json").read_text(encoding="utf-8"))["conversations"]


def run_multiturn():
    from agent import help_desk

    def one(conv):
        history, called, turns, q = [], set(), [], None
        for t in conv["turns"]:
            if t["role"] == "user":
                q = t["text"]
                continue
            r = help_desk(q, history)
            called |= {c["name"] for c in r["calls"]}
            e = t["expect"]
            v = judge(q, r["answer"], e["must"], e["forbid"])
            turns.append({"question": q, "answer": r["answer"], "route": r["route"], "action": r["action"],
                          "calls": [c["name"] for c in r["calls"]], "pass": v["pass"],
                          "missing": v["missing"], "violated": v["violated"]})
            history += [{"role": "user", "text": q}, {"role": "assistant", "text": r["answer"]}]
        allowed = [conv["tools_union"]] + conv.get("tools_union_alt", [])
        tool_pass = any(sorted(called) == sorted(t) for t in allowed)
        return {"id": conv["conv_id"], "title": conv["title"], "tool_pass": tool_pass,
                "expected_tools": conv["tools_union"], "called": sorted(called), "turns": turns,
                "pass": tool_pass and all(x["pass"] for x in turns)}

    rows = pmap(one, load_multiturn(), WORKERS)
    n = len(rows)
    print(f"여러 턴 대화 n={n}")
    print(f"  도구 집합 일치 {sum(r['tool_pass'] for r in rows)}/{n}")
    print(f"  턴 답변 통과   {sum(t['pass'] for r in rows for t in r['turns'])}/{sum(len(r['turns']) for r in rows)}")
    print(f"  대화 전체 통과 {sum(r['pass'] for r in rows)}/{n}")
    print("\n실패")
    for r in rows:
        if r["pass"]:
            continue
        print(f"\n  {r['id']} {r['title']}")
        if not r["tool_pass"]:
            print(f"    도구: 기대 {r['expected_tools']} / 실제 {r['called']}")
        for k, t in enumerate(r["turns"], 1):
            if not t["pass"]:
                print(f"    {k}턴 [{t['route']} {t['action']} {t['calls']}] must 누락 {t['missing']} / forbid 위반 {t['violated']}")
                print("      답변: " + t["answer"].replace("\n", " ")[:250])
    return {"rows": rows, "summary": {"n": n, "pass": sum(r["pass"] for r in rows),
                                      "tool_pass": sum(r["tool_pass"] for r in rows)}}


def run_category_check():
    """질문자가 고른 카테고리를 제대로 검증하는가.

    같은 질문마다 두 번 흉내 낸다 — 맞게 고른 경우, 틀리게 고른 경우(정답 아닌 카테고리 중 하나, 씨앗 고정).
    분류는 선택과 무관하므로 질문마다 분류기를 한 번만 부른다.
        맞게 고름   → match 가 정답. mismatch 는 멀쩡한 선택을 뒤집은 것
        틀리게 고름 → mismatch 이면서 분류기 판단 == 정답 이 정답. match 는 틀린 선택을 그대로 받아들인 것
    """
    import random
    from agent import check_category
    from router import route
    items = load_routing("eval")
    outs = pmap(lambda i: route(i["question"]), items, WORKERS)
    rng = random.Random(20260917)
    right = Counter()
    wrong = Counter()
    fails = []
    for i, o in zip(items, outs):
        a = check_category(i["route"], o)
        right[a["status"]] += 1
        other = rng.choice([r for r in ROUTES if r != i["route"]])
        b = check_category(other, o)
        corrected = b["status"] == "mismatch" and o["route"] == i["route"]
        wrong["바로잡음" if corrected else b["status"] if b["status"] != "mismatch" else "다른 카테고리로 바꿈"] += 1
        if a["status"] != "match" or not corrected:
            fails.append((i, o, other, a["status"], b["status"]))
    n = len(items)
    print(f"카테고리 검증 n={n}")
    print(f"  맞게 고른 경우   match {right['match']}/{n} · mismatch(멀쩡한 선택 뒤집음) {right['mismatch']} · unclear(되물음) {right['unclear']}")
    print(f"  틀리게 고른 경우 바로잡음 {wrong['바로잡음']}/{n} · 그대로 받아들임 {wrong['match']} · "
          f"다른 카테고리로 바꿈 {wrong['다른 카테고리로 바꿈']} · 되물음 {wrong['unclear']}")
    print("\n실패")
    for i, o, other, sa, sb in fails:
        print(f"  {i['id']} 정답 {i['route']} / 판단 {o['route']} ({o['confidence']:.2f}) · 맞게→{sa} · {other}로 틀리게→{sb} · {i['question'][:50]}")
    return {"n": n, "right": dict(right), "wrong": dict(wrong)}


def run_validate(items):
    """모범 답안을 채점기에 넣는다. 전부 통과해야 채점기를 믿을 수 있다."""
    rows = pmap(lambda i: {"id": i["id"], **judge(i["question"], i["gold_answer"], i["must"], i["forbid"])},
                items, WORKERS)
    ok = sum(r["pass"] for r in rows)
    print(f"채점기 검증 ① 모범 답안 통과 {ok}/{len(rows)} (전부 통과해야 한다)")
    for r in rows:
        if not r["pass"]:
            print(f"  {r['id']} must 누락 {r['missing']} / forbid 위반 {r['violated']} / 판정 누락 {r['unjudged']}")
    # 반대 방향 — 아무 사실도 없는 답을 통과시키면 채점기가 너무 후하다
    empty = pmap(lambda i: {"id": i["id"], **judge(i["question"], EMPTY_ANSWER, i["must"], i["forbid"])},
                 items, WORKERS)
    leaked = [r["id"] for r in empty if r["pass"]]
    print(f"채점기 검증 ② 빈 답변 통과 {len(leaked)}/{len(empty)} (0이어야 한다) {leaked}")
    mt = [(c["conv_id"], k, u["text"], t["expect"]) for c in load_multiturn()
          for k, (u, t) in enumerate(zip(c["turns"][::2], c["turns"][1::2]), 1)]
    mt_ref = pmap(lambda x: (f"{x[0]}-{x[1]}", judge(x[2], x[3]["reference"], x[3]["must"], x[3]["forbid"])),
                  mt, WORKERS)
    mt_empty = pmap(lambda x: (f"{x[0]}-{x[1]}", judge(x[2], EMPTY_ANSWER, x[3]["must"], x[3]["forbid"])),
                    mt, WORKERS)
    print(f"채점기 검증 ③ 여러 턴 모범 답안 통과 {sum(v['pass'] for _, v in mt_ref)}/{len(mt_ref)} "
          f"{[k for k, v in mt_ref if not v['pass']]}")
    print(f"채점기 검증 ④ 여러 턴 빈 답변 통과 {sum(v['pass'] for _, v in mt_empty)}/{len(mt_empty)} (0이어야 한다) "
          f"{[k for k, v in mt_empty if v['pass']]}")
    return {"rows": rows, "pass": ok, "empty_pass": leaked,
            "multiturn_ref_fail": [k for k, v in mt_ref if not v["pass"]],
            "multiturn_empty_pass": [k for k, v in mt_empty if v["pass"]]}


EMPTY_ANSWER = "문의 감사합니다. 확인해 보겠습니다."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["router"])
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--hard", action="store_true")
    ap.add_argument("--multiturn", action="store_true")
    ap.add_argument("--category-check", action="store_true")
    ap.add_argument("--split", default="eval", choices=["eval", "fewshot", "all"])
    ap.add_argument("--label")
    args = ap.parse_args()

    items = load_items("all" if args.validate and args.split == "eval" else args.split)
    if args.validate:
        out = run_validate(items)
    elif args.hard:
        out = run_hard()
    elif args.multiturn:
        out = run_multiturn()
    elif args.category_check:
        out = run_category_check()
    elif args.only == "router":
        out = run_router(load_routing(args.split))
    else:
        out = run_full(items)
    if args.label:
        RUNS.mkdir(exist_ok=True)
        path = RUNS / f"{args.label}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n기록: {path}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
