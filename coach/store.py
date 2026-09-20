"""JSONL 저장소. 한 줄에 시도 한 건. 추가(append)만 하고 수정·삭제는 하지 않는다."""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 기본 저장 위치. COACH_DATA_FILE 로 바꿀 수 있다 (스크린샷 생성 등에서 실제 기록을 건드리지 않으려고).
DATA_FILE = Path(os.getenv("COACH_DATA_FILE", ROOT / "data" / "attempts.jsonl"))
SAMPLES_FILE = ROOT / "samples" / "attempts.jsonl"


def append(attempt, path=None):
    # 기본값을 함수 안에서 정한다 (def 줄에 쓰면 정의 시점에 고정돼서 DATA_FILE 을 바꿔도 반영이 안 된다)
    path = Path(path or DATA_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(attempt.model_dump_json() + "\n")


def load(path):
    """dict 리스트로 읽는다. 파일이 없으면 빈 리스트."""
    path = Path(path)
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records
