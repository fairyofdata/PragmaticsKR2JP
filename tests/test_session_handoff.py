"""세션 인수인계 훅: 새 세션에 넘길 글을 올바른 형식으로 내보내는지."""

import json
import subprocess
import sys
from pathlib import Path

from tools import session_handoff

ROOT = Path(__file__).resolve().parent.parent


def test_context_contains_handoff_and_repo_state():
    context = session_handoff.build_context()
    assert "# 인수인계" in context and "지금 멈춘 지점" in context
    assert "## 지금의 저장소 상태" in context and "마지막 커밋" in context


def test_hook_prints_valid_utf8_json_and_exits_zero():
    # 훅이 실제로 실행되는 방식 그대로: 표준 입력으로 JSON 을 받고, 표준 출력으로 JSON 을 낸다
    done = subprocess.run([sys.executable, str(ROOT / "tools" / "session_handoff.py")],
                          input=b"{}", capture_output=True, timeout=30)
    assert done.returncode == 0
    payload = json.loads(done.stdout.decode("utf-8"))        # 한국어가 깨지면 여기서 실패한다
    out = payload["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart" and "인수인계" in out["additionalContext"]


def test_missing_handoff_does_not_break_session_start(monkeypatch, tmp_path):
    monkeypatch.setattr(session_handoff, "HANDOFF", tmp_path / "nope.md")
    assert "CLAUDE.md" in session_handoff.build_context()      # 문서가 없어도 안내만 하고 넘어간다
    assert session_handoff.main() == 0
