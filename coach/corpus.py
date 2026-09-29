"""개인 학습자 코퍼스: 확정 태그를 한 줄씩 펼쳐서 '빈출 오답'을 센다. LLM 은 부르지 않는다.

학습자 코퍼스 = 학습자가 쓴 글에 오류 주석을 붙여 모은 것. 여기서는 사용자 한 명의 코퍼스다.

오타가 '내 약점'으로 잡히지 않도록 세 겹으로 거른다.
  ① 변환 실수 후보: 수정 전후의 읽기가 같으면 (合って/会って) IME 변환 실수로 보고 순위에서 뺀다.
  ② 반복성: 서로 다른 시도에서 2번 이상 나온 패턴만 '빈출 오답'이 된다. 한 번 한 오타는 오르지 않는다.
  ③ 사용자 판정: '실수'·'지적이 틀림'으로 판정한 것은 뺀다. '몰랐음'으로 판정하면 ①이어도 센다.
가나 한 글자 오타(ありがと ございます)는 조사 오류(を→に)와 코드로 구별할 수 없어서 ②와 ③에 맡긴다.
"""

import difflib
from collections import defaultdict

from .lang_ja import CONTENT_POS, PARTICLE_POS, analyze, same_reading
from .stats import tag_key
from .taxonomy import OUT_OF_MODE

# 사용자가 태그마다 누르는 판정
LABELS = {
    "slip": "실수 (오타·변환)",
    "unknown": "몰랐음",
    "unsure": "애매",
    "wrong_flag": "지적이 틀림",
}
EXCLUDED_LABELS = {"slip", "wrong_flag"}   # 빈출 오답·상위 유형 순위에서 뺀다


def pattern_key(e, answer):
    """오류 하나를 '같은 종류의 실수'끼리 묶을 수 있는 키로 만든다: (유형, '바뀐 기본형 → 기본형', 걸리는 말).

    예) 合って→会って        → (ORTHOGRAPHY, '合う → 会う', '')
        を→に (뒤에 会って)  → (PARTICLE, 'を → に', '会う')   ← 조사는 걸리는 동사까지 붙여야 의미가 있다
    """
    a, b = analyze(e["original"]), analyze(e["corrected"])
    left, right, changed_pos = [], [], []
    matcher = difflib.SequenceMatcher(a=[t[1] for t in a], b=[t[1] for t in b], autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        left += [t[1] for t in a[i1:i2]]
        right += [t[1] for t in b[j1:j2]]
        changed_pos += [t[2] for t in a[i1:i2] + b[j1:j2]]
    edit = f"{'·'.join(left) or '∅'} → {'·'.join(right) or '∅'}"

    governing = ""
    if changed_pos and all(p in PARTICLE_POS for p in changed_pos):
        # 조사만 바뀌었으면, 원문에서 그 뒤에 처음 나오는 내용어의 기본형을 붙인다
        for _, lemma, pos in analyze(answer[e["end"]:]):
            if pos in CONTENT_POS:
                governing = lemma
                break
    return (e["type"], edit, governing)


def tag_rows(records, labels):
    """확정 태그를 한 줄씩 펼친다 (모드 밖 오류 제외). labels: {태그 키: 판정}"""
    rows = []
    for r in records:
        for e in r["errors"]:
            if e["type"] == OUT_OF_MODE or "start" not in e:
                continue
            key = tag_key(r["id"], e)
            label = labels.get(key)
            ime = same_reading(e["original"], e["corrected"])
            rows.append({
                "key": key,
                "attempt_id": r["id"],
                "timestamp": r["timestamp"],
                "topic": r["topic"],
                "answer": r["answer"],
                "type": e["type"],
                "original": e["original"],
                "corrected": e["corrected"],
                "explanation_ko": e["explanation_ko"],
                "label": label,
                "ime_candidate": ime,
                "pattern": pattern_key(e, r["answer"]),
                # 순위에서 빼는 것: 실수·지적이 틀림 판정, 또는 판정 없이 변환 실수 후보인 것
                "excluded": label in EXCLUDED_LABELS or (ime and label != "unknown"),
            })
    return rows


def excluded_keys(rows):
    return frozenset(row["key"] for row in rows if row["excluded"])


def frequent_patterns(rows, only_unknown=False, min_attempts=2, examples=3):
    """빈출 오답: 서로 다른 시도에서 min_attempts 번 이상 나온 패턴. 많은 순, 동률이면 키 순."""
    groups = defaultdict(list)
    for row in rows:
        if row["excluded"] or (only_unknown and row["label"] != "unknown"):
            continue
        groups[row["pattern"]].append(row)

    result = []
    for pattern, members in groups.items():
        attempts = {m["attempt_id"] for m in members}
        if len(attempts) < min_attempts:
            continue
        members.sort(key=lambda m: m["timestamp"], reverse=True)
        label_counts = defaultdict(int)
        for m in members:
            label_counts[m["label"] or "none"] += 1
        result.append({
            "type": pattern[0],
            "edit": pattern[1],
            "governing": pattern[2],
            "attempts": len(attempts),
            "count": len(members),
            "labels": dict(label_counts),
            "examples": members[:examples],
        })
    result.sort(key=lambda p: (-p["attempts"], -p["count"], p["type"], p["edit"], p["governing"]))
    return result


def unlabeled(rows, limit=20):
    """아직 판정하지 않은 태그 (최근 것부터)."""
    todo = [row for row in rows if row["label"] is None]
    todo.sort(key=lambda row: row["timestamp"], reverse=True)
    return todo[:limit]
