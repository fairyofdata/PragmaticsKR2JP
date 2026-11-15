"""세션 시작 훅: 새 세션에 지금의 git 상태를 올바른 형식으로 내보내는지 (ADR 0022 — 작업 상황 문서 state.md 는 @state.md 가 읽는다)."""

import json
import subprocess
import sys
from pathlib import Path

from tools import session_handoff

ROOT = Path(__file__).resolve().parent.parent


def test_context_contains_repo_state_and_points_to_state_md():
    context = session_handoff.build_context()
    assert "## 지금의 저장소 상태" in context and "마지막 커밋" in context
    assert "state.md" in context                               # 문서가 낡았을 때 무엇을 고칠지 알려 준다


def test_hook_prints_valid_utf8_json_and_exits_zero():
    # 훅이 실제로 실행되는 방식 그대로: 표준 입력으로 JSON 을 받고, 표준 출력으로 JSON 을 낸다
    done = subprocess.run([sys.executable, str(ROOT / "tools" / "session_handoff.py")],
                          input=b"{}", capture_output=True, timeout=30)
    assert done.returncode == 0
    payload = json.loads(done.stdout.decode("utf-8"))        # 한국어가 깨지면 여기서 실패한다
    out = payload["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart" and "지금의 저장소 상태" in out["additionalContext"]


def test_main_returns_zero():
    assert session_handoff.main() == 0
