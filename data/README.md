# 평가 데이터

- 모두 **합성**이다. 실제 문의·실제 작품·대본은 들어 있지 않다
- 정답(카테고리·도구·필수 사실)은 `docs/` 근거 조각과 `docs/MAPPING.md` 규칙으로만 정했다
- 모두몰 실습 데이터(`customer_inquiries.csv`·`routing_answers.csv`·`hard_cases.csv`·`answer_goldenset_multiturn.json`)와 같은 역할로 나눴다

## 파일

| 파일 | 건수 | 쓰는 곳 | 모두몰 대응 |
|---|---|---|---|
| `goldenset.json` | 57 (eval 46 · fewshot 11) | `python evaluate.py` — 분류 + 도구 호출 + 답변 (1턴) | 답변 정답셋 1턴 부분 |
| `inquiries.csv` | 150 (카테고리당 30) | 분류 평가의 문의 원문·속성 | `customer_inquiries.csv` |
| `routing_answers.csv` | 150 (eval 120 · fewshot 30) | `python evaluate.py --only router` | `routing_answers.csv` |
| `hard_cases.csv` | 72 (6유형) | `python evaluate.py --hard` — 되묻기/처리 판단 | `hard_cases.csv` |
| `answer_goldenset_multiturn.json` | 대화 12 (턴 24) | `python evaluate.py --multiturn` | `answer_goldenset_multiturn.json` |
| `draft/` | — | 저작 초안·라벨 검증 중간 파일. 저장소 제외 | — |
| `feedback/` | — | 평가 중 `submit_feedback`이 남긴 접수 기록. 저장소 제외 | — |

## 컬럼

- `inquiries.csv`: `qa_id, category, intent_full, sentiment(m 보통 / n 불만), question, ref(근거 조각, ;로 구분), expected_tools(범위 밖 어문 규범만), q_len, provenance`
- `routing_answers.csv`: `qa_id, route, split(eval / fewshot)`
  - fewshot은 카테고리마다 6건, 씨앗 고정 무작위(`scripts/build_routing_data.py`)
- `hard_cases.csv`: `qa_id, hard_type, route_expected, route_alt, expected_action(ANSWER / CLARIFY), question, expected_behavior, sentiment, ref, provenance, note`
  - 채점: CLARIFY는 게이트가 되물어야 통과. ANSWER는 되묻지 않고 `route_expected`·`route_alt` 중 하나로 분류해야 통과

## 어떻게 만들고 검증했나 (2026-09-17)

- **저작**: 에이전트 4개가 카테고리·유형을 나눠 썼다. 기존 `goldenset.json` 질문과 겹치지 않게 했다
  - 질문 유형 참고: Subtitle Edit GitHub 이슈, 한국어 커뮤니티 질문 게시판 — 원문은 옮기지 않았다
- **분류 라벨 검증 (inquiries 150건)**: 정답을 가린 채 다른 에이전트가 매핑표만 보고 다시 분류
  - **150/150 일치**
  - 매핑표를 적용해도 해석이 갈릴 수 있다고 표시된 문항 15건 — 라벨은 유지하고 아래에 기록
    - 미구현 검사 번호를 들고 와 실제로는 규정을 묻는 문항: 400044, 400053, 400057
    - 규정대로 썼는데 잡힌다는 오탐 제보 ↔ 항목 설명: 400035, 400041, 400055, 400059, 400112, 400114, 400116
    - 그 밖: 400018, 400030, 400105, 400113, 400133
- **어려운 문항 검증 (hard_cases 72건)**: 별도 검토 에이전트가 매핑표·게이트 동작과 대조
  - 17행 지적 → 15행 반영, 2행 유지
  - 가장 큰 지적: 경계모호 12행이 전부 CLARIFY였는데, 상당수는 매핑표 경계 규칙으로 카테고리가 정해진다 → ANSWER로 바꿈
  - 유지: 500008(타임코드가 밀린다 — 버그인지 사용법인지 문장만으로 못 정함), 500041(정산 — 명확한 범위 밖)
  - 반영 뒤 유형·행동 분포: 경계모호 13(ANSWER 11·CLARIFY 2), 극단단답 12(ANSWER 5·CLARIFY 7), 다중의도 12(ANSWER), 분류체계밖 11(ANSWER), 텍스트손상 12(ANSWER), 문맥의존 12(ANSWER 2·CLARIFY 10)
- **채점기 검증 (goldenset 57건 + 여러 턴 24턴)**: 모범 답안 전부 통과, 빈 답변 전부 탈락 (`python evaluate.py --validate`)
- **여러 턴 도구 집합**: 한 턴을 두 도구 중 어느 쪽으로 답해도 같은 조항에 닿는 경우만 `tools_union_alt`로 대체 집합을 둔다(M-02)
