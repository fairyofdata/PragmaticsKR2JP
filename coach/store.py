"""JSONL 저장소. 한 줄에 한 건. 추가(append)만 하고 수정·삭제는 하지 않는다.

- attempts.jsonl : 시도 한 건 = 한 줄
- labels.jsonl   : 태그에 대한 사용자 판정 한 건 = 한 줄. 판정을 바꾸면 새 줄을 추가하고, 읽을 때 마지막 줄이 이긴다.
                   (시도 기록을 고치지 않고도 판정을 바꿀 수 있게 따로 둔다)
"""

import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 기본 저장 위치. COACH_DATA_FILE 로 바꿀 수 있다 (스크린샷 생성 등에서 실제 기록을 건드리지 않으려고).
DATA_FILE = Path(os.getenv("COACH_DATA_FILE", ROOT / "data" / "attempts.jsonl"))
SAMPLES_FILE = ROOT / "samples" / "attempts.jsonl"


def labels_file():
    """판정 파일은 기록 파일과 같은 폴더에 둔다."""
    return DATA_FILE.parent / "labels.jsonl"


def _append_line(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def append(attempt, path=None):
    # 기본값을 함수 안에서 정한다 (def 줄에 쓰면 정의 시점에 고정돼서 DATA_FILE 을 바꿔도 반영이 안 된다)
    _append_line(path or DATA_FILE, attempt.model_dump_json())


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


def append_label(key, label, path=None):
    """판정 한 건 추가. label=None 은 '판정 취소'."""
    row = {"key": key, "label": label,
           "timestamp": datetime.now().astimezone().isoformat(timespec="seconds")}
    _append_line(path or labels_file(), json.dumps(row, ensure_ascii=False))


def load_labels(path=None):
    """{태그 키: 판정}. 같은 키가 여러 번 있으면 마지막 것. 취소(None)된 키는 빠진다."""
    labels = {}
    for row in load(path or labels_file()):
        if row["label"] is None:
            labels.pop(row["key"], None)
        else:
            labels[row["key"]] = row["label"]
    return labels
