# -*- coding: utf-8 -*-
"""한곳에 모아 둔 설정. 여기 값만 바꿔도 동작이 달라진다.

- MODEL          : 분류용. 출력이 짧고 호출이 많다
- ANSWER_MODEL   : 답변 생성용. 근거 조각이 붙어 입력이 길고 지킬 조건이 많다
- JUDGE_MODEL    : 채점용. 답변 모델과 따로 둘 수 있게 갈라 둔다
- CONF_THRESHOLD : 이 값 미만이면 답하지 않고 되묻는다
"""
import os
from pathlib import Path

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
DATA = ROOT / "data"
RUNS = ROOT / "runs"
FEEDBACK_DIR = DATA / "feedback"          # 건의 접수 기록. 저장소에 올리지 않는다

MODEL = os.environ.get("HELP_MODEL", "gpt-5.6-luna")
ANSWER_MODEL = os.environ.get("HELP_ANSWER_MODEL", "gpt-5.6-terra")
JUDGE_MODEL = os.environ.get("HELP_JUDGE_MODEL", ANSWER_MODEL)

CONF_THRESHOLD = 0.5      # 분류 확신도 임계값 — 모두몰 실습 값에서 시작
MAX_TOOL_TURNS = 5        # 도구 호출 루프 상한
GUARDRAIL_RETRY = 1       # 검증 위반 시 재생성 횟수
SEARCH_TOP_K = 3          # 검색 도구가 돌려주는 조각 수
WORKERS = 8               # 동시 호출 수. 요청 한도에 걸리면 낮춘다

ROUTES = ["USAGE", "QC_EXPLAIN", "STYLE_RULE", "FEEDBACK", "OUT_OF_SCOPE"]
TOOL_NAMES = ["search_usage", "get_check_info", "search_style_rule",
              "submit_feedback", "refer_to_nikl"]


def load_env():
    """`.env`가 있으면 환경변수로 읽는다. 이미 설정된 값은 덮지 않는다."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env()
