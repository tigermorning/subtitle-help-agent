# 자막 생성기 소통 창구 에이전트

- 모두의연구소 「에이전트 팀 꾸리기_Agt1」 5강 [실습 프로젝트] 라우팅 에이전트 만들기 제출물
- 자막 및 TC 생성기 사용자의 문의를 카테고리로 나누고, 카테고리별 근거 문서로만 답한다
- 근거에 없으면 지어내지 않고 넘긴다(국립국어원 안내 · 건의 접수 · 범위 밖 안내)
- **보고서: [REPORT.md](REPORT.md)**

## 루브릭 항목별 위치

| 평가 기준 | 보고서 | 코드·기록 |
|---|---|---|
| 엔드투엔드 구동 · 완결성 | 5절 구조도 · 6절 데모 | `agent.py` · `app.py` · `tests/test_offline.py` |
| 카테고리 설계 · 근거 연결 | 2절 | `docs/MAPPING.md` · `context.py`의 `ROUTE_DOCS` · `tools.py` |
| 성능 검증 · 실패 분석 | 3·4절 | `evaluate.py` · `runs/LAB.md` · `runs/*.json` |

## 카테고리

| 카테고리 | 처리 | 근거 |
|---|---|---|
| `USAGE` 사용법 | 문서 조회 | `docs/10_usage.md` |
| `QC_EXPLAIN` 검사 결과 설명 | 문서 조회 | `docs/20_qc_checks.md` (+ 인용 조항) |
| `STYLE_RULE` 자막 규정 | 문서 조회 | `docs/30_style_netflix.md` · `docs/31_netflix_related.md` |
| `FEEDBACK` 건의·버그 | 접수 기록 | `docs/40_feedback.md` |
| `OUT_OF_SCOPE` 범위 밖 | 넘기기 | `docs/50_referral_nikl.md` |

## 실행

- 파이썬 3.12에서 확인

```bash
pip install -r requirements.txt
```

- `.env.example`을 `.env`로 복사하고 `OPENAI_API_KEY`를 채운다

```bash
streamlit run app.py
```

## 모델 없이 확인

- 모델 호출을 막고 화면 흐름·그래프를 시험한다(48개)

```bash
python tests/test_offline.py
```

- 데모의 준비된 Q&A 79건이 근거 조각과 맞는지 검사한다

```bash
python faq.py
```

## 평가 다시 재기 (OpenAI 호출)

| 명령 | 재는 것 |
|---|---|
| `python evaluate.py --only router` | 분류 120건 — 정확도 · macro F1 · 혼동 행렬 |
| `python evaluate.py` | 1턴 46건 — 분류 · 도구 호출 · 답변(채점기) |
| `python evaluate.py --validate` | 채점기 자체 검증 — 모범 답안 통과 · 빈 답변 탈락 |
| `python evaluate.py --hard` | 어려운 문항 72건 |
| `python evaluate.py --multiturn` | 여러 턴 대화 12개 |

- 결과는 `runs/`에 남고, 실험마다 바꾼 것과 수치는 `runs/LAB.md`에 적는다

## 넣지 않은 것

- 생성기의 비공개 규정 저장소, 작업자 실무 자료, 방송 전 대본
- 넷플릭스 원문 파일(`sources/raw/`) — 공개 API로 받아 로컬 근거로만 쓴다(`sources/fetch_netflix.py`)
