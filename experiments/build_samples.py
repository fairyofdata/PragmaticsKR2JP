"""시연용 예시 만들기: 평가 세트의 답을 실제 채점기로 채점해서 samples/attempts.jsonl 에 쓴다.

source="synthetic" 으로 표시된다 (사람이 아니라 Claude 가 쓴 답이라는 뜻).
이 파일은 다시 만들 수 있는 시연용이라 덮어쓴다. 실제 기록(data/)은 append-only.

실행: python -m experiments.build_samples
"""

import json

from coach import llm, store
from coach.schemas import Task
from experiments.repro import load_eval_set


def main():
    store.SAMPLES_FILE.parent.mkdir(exist_ok=True)
    store.SAMPLES_FILE.write_text("", encoding="utf-8")
    for item in load_eval_set():
        print(item["id"], "...", flush=True)
        attempt = llm.grade(item["answer"], Task(**item["task"]), item["mode"], item["topic"],
                            item["medium"], item["relationship"], source="synthetic")
        store.append(attempt, store.SAMPLES_FILE)
        print("  ", json.dumps([(e.type, e.original, e.votes) for e in attempt.errors],
                               ensure_ascii=False))


if __name__ == "__main__":
    main()
