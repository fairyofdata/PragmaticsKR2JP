# 설계 결정 기록 (ADR)

ADR(Architecture Decision Record) = 중요한 설계 결정 하나를 "맥락 → 결정 → 버린 대안 → 결과" 순서로 짧게 적은 문서.
결정을 뒤집을 때는 기존 ADR을 지우지 않고 상태를 "대체됨"으로 바꾸고 새 ADR을 쓴다.

| 번호 | 제목 | 상태 | 날짜 |
|---|---|---|---|
| [0001](0001-llm-as-annotator.md) | LLM은 주석자, 측정의 나머지는 코드 | 채택 | 2026-09-20 |
| [0002](0002-code-checks-over-prompt-rules.md) | 끌려가지 않기: 프롬프트 부탁 대신 코드 검증 | 채택 | 2026-09-20 |
| [0003](0003-no-fixed-fewshot-majority-vote.md) | 고정 few-shot 없이 코드북, 흔들림은 3회 다수결 | 채택 | 2026-09-20 |
| [0004](0004-grammar-expression-modes.md) | 문법 모드 / 표현 모드 분리 | 채택 | 2026-09-20 |
| [0005](0005-llm-provider-openai.md) | LLM 제공자: Gemini → OpenAI | 채택 | 2026-09-20 |
| [0006](0006-taxonomy-v1-priority.md) | 유형표 v1: 더 구체적인 유형을 우선 | 채택 | 2026-09-20 |
| [0007](0007-eval-set-from-user-translations.md) | 평가 세트를 사용자의 실제 번역에서 만든다 | 제안 (진행 중) | 2026-09-20 |
