"""데이터 형식. LLM 응답은 반드시 여기 pydantic 모델로 검증한 뒤에만 쓴다.

pydantic: 클래스에 필드 타입을 적어 두면, 들어온 JSON이 그 형식에 맞는지 자동으로 검사해 주는 라이브러리.
"""

from typing import Literal

from pydantic import BaseModel

SCHEMA_VERSION = "s4"  # s0→s1: dropped_width, merged_tags / s1→s2: 인용 문맥, 모호 인용 수, 확정 태그 교정문
                       # s2→s3: 입력 방식, 한국어 원문, 걸린 시간 (개인 코퍼스용)
                       # s3→s4: 입력 방식 'targeted'(약점 겨냥 연습)와 겨냥한 패턴, 고쳐 쓰기 기록(Revision)
                       # 스키마는 저장 형식이라 집계 필터에는 쓰지 않는다 (ADR 0012)


# ---------- LLM이 돌려주는 것 ----------

class Task(BaseModel):
    situation_ko: str      # 한국어 상황 설명
    instruction_ko: str    # 일본어로 무엇을 써야 하는지 (한국어)


class ErrorTag(BaseModel):
    type: str                                  # taxonomy 코드
    severity: Literal["error", "unnatural"]
    original: str                              # 사용자 답에 글자 그대로 있는 부분
    # original 바로 앞뒤의 글자 (같은 문자열이 답에 여러 번 나올 때 위치를 정하려고). 문장 처음/끝이면 빈 문자열
    context_before: str = ""
    context_after: str = ""
    corrected: str
    kr_interference: bool
    explanation_ko: str


class GradeResult(BaseModel):
    intended_meaning_ko: str
    minimal_correction: str
    natural_version: str
    errors: list[ErrorTag]


# ---------- 코드가 만들어 저장하는 것 ----------

class VotedTag(ErrorTag):
    votes: int              # n_samples 번 중 몇 번 나왔나
    start: int              # 사용자 답 안에서의 위치 (코드가 계산)
    end: int


class UntaggedChange(BaseModel):
    original: str
    corrected: str


class Attempt(BaseModel):
    """JSONL 한 줄 = 시도 한 건."""
    id: str
    timestamp: str
    source: Literal["app", "synthetic", "imported"]
    mode: str
    topic: str
    medium: str
    relationship: str
    task: Task
    # 앱이 낸 과제 / 내가 가져온 한국어 문장 (s3~) / 약점 겨냥 연습 (s4~, 기본 집계에서 뺀다)
    input_mode: Literal["generated", "own_korean", "targeted"] = "generated"
    target: dict | None = None         # targeted 일 때 겨냥한 패턴 {type, edit, governing} (s4~)
    source_ko: str = ""                # own_korean 일 때 사용자가 가져온 한국어 원문 (s3~)
    duration_sec: int | None = None    # 과제를 받고 채점을 누를 때까지 걸린 시간 (s3~)
    answer: str                        # 사용자 입력 원문. 어떤 정규화도 하지 않는다.
    intended_meaning_ko: str
    minimal_correction: str
    natural_version: str
    errors: list[VotedTag]             # 확정 (votes >= 과반)
    tentative_errors: list[VotedTag]   # 참고 (낮은 확신) — 집계 제외
    untagged_changes: list[UntaggedChange]
    dropped_quotes: int                # 원문에 없는 인용이라 버린 태그 수
    dropped_width: int = 0             # 전각/반각 차이뿐이라 버린 태그 수 (s1~)
    merged_tags: list[dict] = []       # 태그 하나에 합쳐진 수정들 (s1~) [{type, original, corrected, edits}]
    ambiguous_quotes: int = 0          # 위치를 하나로 정하지 못한 인용 수 (s2~)
    confirmed_correction: str = ""     # 확정 태그만 원문에 적용해 코드가 만든 교정문 (s2~)
    correction_source: str = ""        # confirmed_tags / sample_fallback (s2~)
    n_samples: int
    taxonomy_version: str
    prompt_version: str
    schema_version: str
    model: str
    thinking_level: str
    usage: dict                        # 토큰 수 합계 (비용 계산용)


class RevisionCheck(BaseModel):
    key: str            # 원래 시도의 태그 키 (stats.tag_key)
    type: str
    original: str
    corrected: str
    status: Literal["fixed", "unchanged", "changed"]


class Revision(BaseModel):
    """고쳐 쓰기 한 건 (revisions.jsonl). 피드백을 보고 쓴 답이라 독립적인 시도가 아니다 → 집계에 넣지 않는다.
    다시 채점하면 같은 id 로 새 줄을 추가한다 (읽을 때 마지막 줄이 이긴다)."""
    id: str
    parent_id: str                     # 원래 시도의 id
    timestamp: str
    text: str                          # 고쳐 쓴 답 (정규화 없이)
    duration_sec: int | None = None
    checks: list[RevisionCheck]        # 코드 확인 결과 (무료)
    regraded: bool = False             # '다시 채점'을 눌렀나
    regrade_errors: list[VotedTag] = []
    repeated_patterns: list[dict] = [] # 원래 시도와 다시 채점에서 같은 패턴 = 고쳐 쓰고도 또 틀림
    regrade_model: str = ""
    regrade_prompt_version: str = ""
    usage: dict = {}
    schema_version: str
