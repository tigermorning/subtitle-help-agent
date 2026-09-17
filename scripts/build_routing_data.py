# -*- coding: utf-8 -*-
"""저작 초안(data/draft/)을 모아 분류 평가용 데이터 두 파일을 만든다.

    data/inquiries.csv        문의 원문과 속성   (모두몰 customer_inquiries.csv 대응)
    data/routing_answers.csv  정답 카테고리와 분할 (모두몰 routing_answers.csv 대응)

분할: 카테고리마다 6건을 fewshot, 나머지를 eval. 씨앗을 고정해 다시 돌려도 같다.
문항 번호는 카테고리 순서대로 400001부터 매긴다.
"""
import csv
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "data" / "draft"
ROUTES = ["USAGE", "QC_EXPLAIN", "STYLE_RULE", "FEEDBACK", "OUT_OF_SCOPE"]
FEWSHOT_PER_ROUTE = 6
SEED = 20260917


def main():
    rows = []
    for name in ["inq_A.csv", "inq_B.csv", "inq_C.csv"]:
        rows += list(csv.DictReader(open(DRAFT / name, encoding="utf-8-sig")))
    rows.sort(key=lambda r: ROUTES.index(r["category"]))
    rng = random.Random(SEED)
    fewshot = set()
    for route in ROUTES:
        idx = [i for i, r in enumerate(rows) if r["category"] == route]
        fewshot |= set(rng.sample(idx, FEWSHOT_PER_ROUTE))

    inq, ans = [], []
    for i, r in enumerate(rows):
        qa_id = str(400001 + i)
        refs = ";".join(x.strip() for x in re.split(r"[;,]", r["ref"]) if x.strip())
        q = r["question"].strip()
        inq.append({"qa_id": qa_id, "category": r["category"], "intent_full": r["intent_full"],
                    "sentiment": r["sentiment"], "question": q, "ref": refs,
                    "expected_tools": r.get("expected_tools", ""), "q_len": len(q),
                    "provenance": r["provenance"]})
        ans.append({"qa_id": qa_id, "route": r["category"],
                    "split": "fewshot" if i in fewshot else "eval"})

    for path, data in [(ROOT / "data" / "inquiries.csv", inq), (ROOT / "data" / "routing_answers.csv", ans)]:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)
    print(len(inq), "건:", {r: sum(a["route"] == r for a in ans) for r in ROUTES},
          "fewshot", sum(a["split"] == "fewshot" for a in ans))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
