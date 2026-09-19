"""데이터 형식. LLM 응답은 반드시 여기 pydantic 모델로 검증한 뒤에만 쓴다.

pydantic: 클래스에 필드 타입을 적어 두면, 들어온 JSON이 그 형식에 맞는지 자동으로 검사해 주는 라이브러리.
"""

from typing import Literal

from pydantic import BaseModel

SCHEMA_VERSION = "s0"


# ---------- LLM이 돌려주는 것 ----------

class Task(BaseModel):
    situation_ko: str      # 한국어 상황 설명
    instruction_ko: str    # 일본어로 무엇을 써야 하는지 (한국어)


class ErrorTag(BaseModel):
    type: str                                  # taxonomy 코드
    severity: Literal["error", "unnatural"]
    original: str                              # 사용자 답에 글자 그대로 있는 부분
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
    answer: str                        # 사용자 입력 원문. 어떤 정규화도 하지 않는다.
    intended_meaning_ko: str
    minimal_correction: str
    natural_version: str
    errors: list[VotedTag]             # 확정 (votes >= 과반)
    tentative_errors: list[VotedTag]   # 참고 (낮은 확신) — 집계 제외
    untagged_changes: list[UntaggedChange]
    dropped_quotes: int                # 원문에 없는 인용이라 버린 태그 수
    n_samples: int
    taxonomy_version: str
    prompt_version: str
    schema_version: str
    model: str
    thinking_level: str
    usage: dict                        # 토큰 수 합계 (비용 계산용)
