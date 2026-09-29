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


def _same_pattern(p, q):
    """같은 실수인가. 유형 이름은 채점마다 흔들릴 수 있어서(재현성 실험) '바뀐 기본형'과 '걸리는 말'만 비교한다."""
    return p[1] == q[1] and p[2] == q[2]


# ---------- 고쳐 쓰기 (ADR 0013) ----------

def repeated_after_revision(parent, regrade_errors, rewrite):
    """원래 시도에서 틀린 패턴이 고쳐 쓴 답의 다시 채점에서도 나왔나 → 고쳐 쓰고도 또 틀림 (오개념의 강한 신호)."""
    before = [pattern_key(e, parent["answer"]) for e in parent["errors"]
              if e["type"] != OUT_OF_MODE and "start" in e]
    repeated = []
    for e in regrade_errors:
        if e["type"] == OUT_OF_MODE:
            continue
        p = pattern_key(e, rewrite)
        if any(_same_pattern(p, b) for b in before) and p not in [tuple(r.values()) for r in repeated]:
            repeated.append({"type": p[0], "edit": p[1], "governing": p[2]})
    return repeated


def revision_summary(rows, revisions):
    """고쳐 쓰기 결과를 패턴별로 모은다: 고침 / 그대로 / 다르게 고침 / 다시 채점에서 또 틀림.
    rows: 현재 집계 대상의 태그 행 (다른 버전의 시도에 붙은 고쳐 쓰기는 자연히 빠진다)."""
    by_key = {row["key"]: row for row in rows}
    summary = defaultdict(lambda: {"fixed": 0, "unchanged": 0, "changed": 0, "repeated": 0})
    for rev in revisions:
        for check in rev["checks"]:
            row = by_key.get(check["key"])
            if row:
                summary[row["pattern"]][check["status"]] += 1
        for p in rev.get("repeated_patterns", []):
            for pattern in summary:
                if _same_pattern(pattern, (p["type"], p["edit"], p["governing"])):
                    summary[pattern]["repeated"] += 1
                    break
    result = [{"type": p[0], "edit": p[1], "governing": p[2], **counts} for p, counts in summary.items()]
    # 안 고친 것·또 틀린 것이 많은 순 (고쳐 쓰기로도 안 고쳐지는 게 진짜 약점)
    result.sort(key=lambda x: (-(x["unchanged"] + x["repeated"] + x["changed"]), x["edit"]))
    return result


# ---------- 약점 겨냥 연습 (ADR 0013) ----------

def target_candidates(rows):
    """겨냥할 패턴 후보: 빈출 오답 + '몰랐음'으로 판정한 패턴(한 번뿐이어도). 빈출 오답이 먼저."""
    candidates = [{"type": p["type"], "edit": p["edit"], "governing": p["governing"], "attempts": p["attempts"]}
                  for p in frequent_patterns(rows)]
    for row in rows:
        if row["label"] != "unknown":
            continue
        t, edit, gov = row["pattern"]
        if not any(c["edit"] == edit and c["governing"] == gov for c in candidates):
            candidates.append({"type": t, "edit": edit, "governing": gov, "attempts": 1})
    return candidates


def target_outcome(attempt, target):
    """겨냥 연습 한 건의 결과.
      repeated     — 겨냥한 패턴이 이번에도 확정 오류로 나왔다
      used         — 이번 답에 맞는 형태(교정 쪽 기본형)가 들어 있고, 같은 오류는 없다
      not_used     — 그 표현을 쓰지 않았다 (피해 갔거나 다르게 표현) → 맞게 썼다고 볼 수 없다
    """
    wanted = (target["type"], target["edit"], target["governing"])
    for e in attempt["errors"]:
        if e["type"] != OUT_OF_MODE and "start" in e and _same_pattern(pattern_key(e, attempt["answer"]), wanted):
            return "repeated"
    right = [x for x in target["edit"].split(" → ")[-1].split("·") if x != "∅"]
    lemmas = [t[1] for t in analyze(attempt["answer"])]
    # 맞는 형태가 걸리는 말 바로 앞에 '연속으로' 나와야 쓴 것으로 본다 (に…会う).
    # 답 어딘가에 に 가 있고 어딘가에 会う 가 있는 것만으로는 안 된다 (一緒に … 会って を 로 잘못 판정하지 않게).
    needle = right + ([target["governing"]] if target["governing"] else [])
    n = len(needle)
    used = n > 0 and any(lemmas[i:i + n] == needle for i in range(len(lemmas) - n + 1))
    return "used" if used else "not_used"


def target_summary(attempts):
    """겨냥 연습 결과를 패턴별로: 시도 수와 repeated / used / not_used."""
    summary = {}
    for a in attempts:
        t = a.get("target")
        if not t:
            continue
        key = (t["type"], t["edit"], t["governing"])
        entry = summary.setdefault(key, {"type": key[0], "edit": key[1], "governing": key[2],
                                         "attempts": 0, "repeated": 0, "used": 0, "not_used": 0})
        entry["attempts"] += 1
        entry[target_outcome(a, t)] += 1
    return sorted(summary.values(), key=lambda x: (-x["attempts"], x["edit"]))


def unlabeled(rows, limit=20):
    """아직 판정하지 않은 태그 (최근 것부터)."""
    todo = [row for row in rows if row["label"] is None]
    todo.sort(key=lambda row: row["timestamp"], reverse=True)
    return todo[:limit]
