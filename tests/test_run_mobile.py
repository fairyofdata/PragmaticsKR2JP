"""폰 접속용 실행 스크립트: 암호 없이는 네트워크에 열지 않는다."""

from tools import run_mobile


def test_passcode_rules():
    assert run_mobile.passcode_problem(None) and run_mobile.passcode_problem("")
    assert run_mobile.passcode_problem("short")              # 8자 미만
    assert run_mobile.passcode_problem("long-enough-1") is None


def test_refuses_to_start_without_passcode(monkeypatch, capsys):
    monkeypatch.delenv("COACH_PASSCODE", raising=False)
    monkeypatch.setattr(run_mobile, "load_dotenv", lambda *a, **k: None)      # 실제 .env 를 읽지 않게
    started = []
    monkeypatch.setattr(run_mobile.subprocess, "call", lambda *a, **k: started.append(a) or 0)
    assert run_mobile.main() == 1
    assert started == []                                                      # 서버를 띄우지 않았다
    assert "COACH_PASSCODE" in capsys.readouterr().out
