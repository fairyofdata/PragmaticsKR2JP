"""재현성·탐지율 미니 실험.

평가 세트(eval_set.jsonl: 오류를 일부러 심은 답 + 정답 위치)를 세 조건으로 각각 3번씩 채점한다.
  (a) plain  : 유형 이름만 주는 단순 지시, 1회 채점
  (b) guide  : 상세 지침(코드북) 프롬프트, 1회 채점
  (c) vote   : 상세 지침 + 3회 다수결 (확정 태그만)

지표 (모두 코드가 계산)
  재현성  exact   : 3번의 유형 집합이 완전히 같은 답의 비율
          jaccard : 3번 중 두 개씩 짝지은 유형 집합 Jaccard 의 평균 (둘 다 빈 집합이면 1)
  탐지율  recall_loc  : 심은 오류 위치에 (유형 불문) 태그가 붙은 비율 — '끌려가지 않았나'
          recall_type : 위치와 유형까지 맞은 비율
  과교정  clean_tags  : 오류 없는 답(G6, E6)에 붙은 모드 내 태그 수 평균
          extra_tags  : 심은 위치 밖에 붙은 모드 내 태그 수 평균 (진짜 오류일 수도 있음)

실행: python -m experiments.repro            (전부)
      python -m experiments.repro --only G1  (한 건만, 동작 확인용)
"""

import argparse
import json
from datetime import datetime
from itertools import combinations
from pathlib import Path

from coach import llm
from coach.prompts import PROMPT_VERSION, grade_prompt, plain_grade_prompt
from coach.schemas import Task
from coach.taxonomy import OUT_OF_MODE, TAXONOMY_VERSION, codes_for_mode
from coach.verify import find_span
from coach.voting import combine

HERE = Path(__file__).resolve().parent
RUNS = 3


def load_eval_set():
    with open(HERE / "eval_set.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run_condition(item, condition):
    """한 조건으로 RUNS 번 채점. 각 run 의 확정 태그 목록과 부가 정보를 돌려준다."""
    task = Task(**item["task"])
    args = (item["mode"], task, item["medium"], item["relationship"], item["answer"])
    codes = codes_for_mode(item["mode"])
    runs, usage = [], {}

    if condition in ("plain", "guide"):
        prompt = plain_grade_prompt(*args) if condition == "plain" else grade_prompt(*args)
        samples, usage = llm.grade_samples(prompt, item["mode"], RUNS)
        for s in samples:
            runs.append(combine(item["answer"], [s], codes))
    else:  # vote
        for _ in range(RUNS):
            samples, u = llm.grade_samples(grade_prompt(*args), item["mode"], llm.N_SAMPLES)
            llm._add_usage(usage, u)
            runs.append(combine(item["answer"], samples, codes))
    return runs, usage


def tags_of(run):
    """모드 내 확정 태그 [(type, (start, end))]."""
    return [(e.type, (e.start, e.end)) for e in run["errors"] if e.type != OUT_OF_MODE]


def jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1]


def score_item(item, runs):
    type_sets = [{t for t, _ in tags_of(r)} for r in runs]
    expected = [(e["type"], find_span(item["answer"], e["original"])) for e in item["expected"]]

    loc_hits = type_hits = extra = 0
    for r in runs:
        tags = tags_of(r)
        all_spans = [(e.start, e.end) for e in r["errors"]]  # 위치 탐지는 OUT_OF_MODE 로 잡아도 인정
        for etype, espan in expected:
            if any(overlaps(span, espan) for span in all_spans):
                loc_hits += 1
            if any(overlaps(span, espan) and t == etype for t, span in tags):
                type_hits += 1
        extra += sum(1 for _, span in tags if not any(overlaps(span, es) for _, es in expected))

    return {
        "id": item["id"],
        "mode": item["mode"],
        "exact": len({frozenset(s) for s in type_sets}) == 1,
        "jaccard": sum(jaccard(a, b) for a, b in combinations(type_sets, 2)) / 3,
        "expected_n": len(expected) * len(runs),
        "loc_hits": loc_hits,
        "type_hits": type_hits,
        "extra_tags": extra / len(runs),
        "type_sets": [sorted(s) for s in type_sets],
        "untagged_changes": sum(len(r["untagged_changes"]) for r in runs),
        "dropped_quotes": sum(r["dropped_quotes"] for r in runs),
    }


def aggregate(scores):
    with_errors = [s for s in scores if s["expected_n"]]
    clean = [s for s in scores if not s["expected_n"]]
    exp_total = sum(s["expected_n"] for s in with_errors)
    return {
        "items": len(scores),
        "exact": sum(s["exact"] for s in scores) / len(scores),
        "jaccard": sum(s["jaccard"] for s in scores) / len(scores),
        "recall_loc": sum(s["loc_hits"] for s in with_errors) / exp_total if exp_total else None,
        "recall_type": sum(s["type_hits"] for s in with_errors) / exp_total if exp_total else None,
        "clean_tags": sum(s["extra_tags"] for s in clean) / len(clean) if clean else None,
        "extra_tags": sum(s["extra_tags"] for s in with_errors) / len(with_errors) if with_errors else None,
        "untagged_changes": sum(s["untagged_changes"] for s in scores),
        "dropped_quotes": sum(s["dropped_quotes"] for s in scores),
    }


def per_type_agreement(scores):
    """유형별: 3번 중 한 번이라도 나온 답 중에서, 3번 모두 나온 비율."""
    table = {}
    for s in scores:
        seen = set().union(*map(set, s["type_sets"]))
        for t in seen:
            always = all(t in ts for ts in s["type_sets"])
            any_n, all_n = table.get(t, (0, 0))
            table[t] = (any_n + 1, all_n + always)
    return {t: {"any": a, "all": b, "rate": b / a} for t, (a, b) in sorted(table.items())}


def fmt(x):
    return "-" if x is None else f"{x:.2f}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="이 id 하나만 실행")
    parser.add_argument("--conditions", default="plain,guide,vote")
    args = parser.parse_args()

    items = load_eval_set()
    if args.only:
        items = [i for i in items if i["id"] == args.only]
    conditions = args.conditions.split(",")

    report = {
        "date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": llm.GRADER_MODEL, "thinking_level": llm.GRADER_THINKING,
        "n_samples_vote": llm.N_SAMPLES, "runs": RUNS,
        "taxonomy_version": TAXONOMY_VERSION, "prompt_version": PROMPT_VERSION,
        "conditions": {},
    }
    for cond in conditions:
        scores, usage = [], {}
        for item in items:
            print(f"[{cond}] {item['id']} ...", flush=True)
            runs, u = run_condition(item, cond)
            llm._add_usage(usage, u)
            scores.append(score_item(item, runs))
        by_mode = {}
        for mode in ("grammar", "expression"):
            ms = [s for s in scores if s["mode"] == mode]
            if ms:
                by_mode[mode] = aggregate(ms)
        report["conditions"][cond] = {
            "all": aggregate(scores), "by_mode": by_mode,
            "per_type": per_type_agreement(scores), "usage": usage, "items": scores,
        }

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    name = datetime.now().strftime("repro_%Y%m%d_%H%M%S") + (f"_{args.only}" if args.only else "") + ".json"
    (out_dir / name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n결과: experiments/results/{name}\n")
    print("| 조건 | 모드 | 완전일치 | Jaccard | 위치 탐지율 | 유형까지 일치 | 무오류 답의 태그 | 기대 밖 태그 |")
    print("|---|---|---|---|---|---|---|---|")
    for cond, data in report["conditions"].items():
        for mode, a in [("전체", data["all"])] + list(data["by_mode"].items()):
            print(f"| {cond} | {mode} | {fmt(a['exact'])} | {fmt(a['jaccard'])} | {fmt(a['recall_loc'])} "
                  f"| {fmt(a['recall_type'])} | {fmt(a['clean_tags'])} | {fmt(a['extra_tags'])} |")


if __name__ == "__main__":
    main()
