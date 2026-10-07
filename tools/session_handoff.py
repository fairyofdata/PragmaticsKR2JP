"""SessionStart 훅: 새 Claude Code 세션이 시작될 때 인수인계 문서를 세션 문맥에 넣는다.

.claude/settings.local.json 의 SessionStart 훅이 이 스크립트를 실행한다.
출력은 JSON 한 덩어리이고, additionalContext 안의 글이 새 세션에 전달된다.

- docs/HANDOFF.md 전체
- 지금의 git 상태 (마지막 커밋, 커밋 안 된 변경, 푸시 안 된 커밋) — 문서가 낡았는지 알 수 있게

표준 라이브러리만 쓴다 (가상환경 없이 시스템 파이썬으로도 돌아야 한다).
어떤 이유로든 실패하면 조용히 끝낸다. 훅 때문에 세션 시작이 막히면 안 된다.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HANDOFF = ROOT / "docs" / "HANDOFF.md"


def git(*args):
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, timeout=10)
        return out.stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def build_context():
    parts = []
    if HANDOFF.exists():
        parts.append(HANDOFF.read_text(encoding="utf-8"))
    else:
        parts.append("docs/HANDOFF.md 가 없습니다. CLAUDE.md 의 '현재 상태와 다음 할 일'을 기준으로 이어 가세요.")

    status = git("status", "--short")
    unpushed = git("log", "--oneline", "origin/main..main")
    parts.append("\n".join([
        "## 지금의 저장소 상태 (훅이 세션 시작 시점에 확인)",
        f"- 마지막 커밋: {git('log', '-1', '--format=%h %s (%ad)', '--date=short') or '확인 못 함'}",
        "- 커밋 안 된 변경: " + ("없음" if not status else "있음\n" + status),
        "- 푸시 안 된 커밋: " + ("없음" if not unpushed else "있음\n" + unpushed),
        "- 위 내용이 인수인계 문서와 다르면 문서가 낡은 것이다. 저장소 상태를 믿고, 문서를 갱신한다.",
    ]))
    return "\n\n".join(parts)


def main():
    try:
        payload = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                          "additionalContext": build_context()}}
        # Windows 콘솔 기본 인코딩(cp949 등)으로 나가면 한국어·일본어가 깨지므로 UTF-8 바이트로 직접 쓴다
        sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
