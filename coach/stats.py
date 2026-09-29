"""집계. LLM을 부르지 않는 순수 함수만 둔다. 같은 입력이면 항상 같은 출력."""

from collections import defaultdict
from datetime import date, timedelta

from .taxonomy import OUT_OF_MODE, name_ko


# 측정 도구의 버전 = 유형표·채점 프롬프트·모델. 이게 다르면 같은 답도 다르게 태깅될 수 있다.
# 스키마(저장 형식)는 넣지 않는다: 필드 추가만으로 쌓아 둔 기록이 기본 화면에서 사라지면 안 된다 (ADR 0012).
VERSION_KEYS = ("taxonomy_version", "prompt_version", "model")


def tag_key(attempt_id, e):
    """확정 태그 하나를 가리키는 고정 키. 사용자 판정(labels.jsonl)이 이 키로 태그를 가리킨다."""
    return f"{attempt_id}:{e['start']}:{e['end']}:{e['type']}"


def filter_records(records, mode, current, include_older=False):
    """집계에 넣을 기록을 고른다.

    기본(엄격): 유형표·채점 프롬프트·모델이 모두 현재(current)와 같은 기록만. 측정 도구가 바뀌면 분포도 바뀌므로 섞지 않는다.
    include_older=True: 유형표만 같으면 포함한다 (태그의 뜻은 같다). 이때는 화면에 섞인 버전 구성을 함께 보여준다.
    유형표가 다르면 태그의 뜻이 달라서 어느 경우에도 섞지 않는다.
    """
    same = [r for r in records
            if r["mode"] == mode and r["taxonomy_version"] == current["taxonomy_version"]]
    if include_older:
        return same
    return [r for r in same if all(r.get(k) == current[k] for k in VERSION_KEYS)]


def version_mix(records):
    """기록들이 어떤 (채점 프롬프트, 모델) 조합으로 만들어졌는지 건수. 많은 순."""
    mix = defaultdict(int)
    for r in records:
        mix[(r.get("prompt_version"), r.get("model"))] += 1
    return sorted(mix.items(), key=lambda kv: (-kv[1], kv[0]))


def top_types(records, n=5, examples_per_type=3, exclude_keys=frozenset()):
    """자주 틀리는 유형 상위 n개.

    순위 기준: 그 유형이 나온 '시도 수' (긴 답 하나에 같은 오류가 몰려 있어도 1로 센다).
    동률이면 전체 건수, 그래도 같으면 코드 알파벳 순 — 항상 같은 순서가 나오게.
    exclude_keys: 순위에서 뺄 태그 키 (사용자가 '실수'로 판정한 것 등, corpus.excluded_keys 가 만든다).
    """
    attempts_with = defaultdict(int)
    counts = defaultdict(int)
    interference = defaultdict(int)
    examples = defaultdict(list)
    votes = defaultdict(list)       # 확정 태그의 표 수 (신뢰도 표시용)
    tentative = defaultdict(int)    # 과반 미달로 순위에서 뺀 건수 (신뢰도 표시용)

    # 최신 기록이 예시로 먼저 나오도록 역순으로 본다
    for r in sorted(records, key=lambda r: r["timestamp"], reverse=True):
        seen = set()
        for e in r["errors"]:
            code = e["type"]
            if code == OUT_OF_MODE or ("id" in r and "start" in e and tag_key(r["id"], e) in exclude_keys):
                continue
            counts[code] += 1
            votes[code].append((e.get("votes", 1), r.get("n_samples", 1)))
            if e["kr_interference"]:
                interference[code] += 1
            seen.add(code)
            if len(examples[code]) < examples_per_type:
                examples[code].append({
                    "answer": r["answer"],
                    "original": e["original"],
                    "corrected": e["corrected"],
                    "explanation_ko": e["explanation_ko"],
                    "severity": e["severity"],
                    "topic": r["topic"],
                })
        for code in seen:
            attempts_with[code] += 1
        for e in r.get("tentative_errors", []):
            tentative[e["type"]] += 1

    total = len(records)
    ranked = sorted(attempts_with, key=lambda c: (-attempts_with[c], -counts[c], c))
    return [{
        "code": code,
        "name_ko": name_ko(code),
        "attempts_with": attempts_with[code],
        "share": attempts_with[code] / total if total else 0.0,
        "count": counts[code],
        "kr_interference": interference[code],
        # 신뢰도: 확정 태그가 n번 채점 중 평균 몇 번 나왔나, 몇 건이 전원 일치였나, 낮은 확신으로 빠진 건수
        "unanimous": sum(1 for v, n in votes[code] if v >= n),
        "mean_vote_share": (sum(v / n for v, n in votes[code]) / len(votes[code])) if votes[code] else 0.0,
        "tentative": tentative[code],
        "examples": examples[code],
    } for code in ranked[:n]]


def weekly_trend(records, codes, exclude_keys=frozenset()):
    """주별로 '그 유형이 나온 시도의 비율'. 주마다 시도 수가 달라서 건수가 아니라 비율로 본다.

    결과: [{"week": "2026-W40", "attempts": 12, "median_sec": 95, "rates": {코드: 0.25, ...}}] 오래된 주부터.
    시도가 적은 주의 비율은 크게 흔들린다 → 화면에 시도 수를 함께 보여준다.
    """
    weeks = defaultdict(list)
    for r in records:
        year, week, _ = date.fromisoformat(r["timestamp"][:10]).isocalendar()
        weeks[f"{year}-W{week:02d}"].append(r)

    def has(r, code):
        return any(e["type"] == code and tag_key(r["id"], e) not in exclude_keys
                   for e in r["errors"] if "start" in e)

    table = []
    for week in sorted(weeks):
        rs = weeks[week]
        durations = sorted(r["duration_sec"] for r in rs if r.get("duration_sec"))
        table.append({
            "week": week,
            "attempts": len(rs),
            "median_sec": durations[len(durations) // 2] if durations else None,
            "rates": {code: sum(has(r, code) for r in rs) / len(rs) for code in codes},
        })
    return table


def summary_counts(records):
    """요약 화면 상단 숫자들."""
    return {
        "attempts": len(records),
        "errors": sum(len(r["errors"]) for r in records),
        "out_of_mode": sum(1 for r in records for e in r["errors"] if e["type"] == OUT_OF_MODE),
        "tentative": sum(len(r["tentative_errors"]) for r in records),
        "untagged_changes": sum(len(r["untagged_changes"]) for r in records),
        "error_free": sum(1 for r in records if not r["errors"]),
    }


def streak_days(records, today=None):
    """오늘(또는 어제)까지 하루도 빠지지 않고 연습한 날 수. 오늘 아직 안 했어도 어제까지 이어졌으면 유지."""
    today = today or date.today()
    days = {date.fromisoformat(r["timestamp"][:10]) for r in records}
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak
