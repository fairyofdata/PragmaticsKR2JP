"""같은 Wi-Fi(또는 사설망)의 폰에서 접속할 수 있게 앱을 띄운다. 배포가 아니라 내 PC 가 서버가 된다.

실행: python -m tools.run_mobile

네트워크에 열면 같은 망의 누구나 접속할 수 있다 → 내 기록을 보고, 내 API 키로 채점을 돌릴 수 있다.
그래서 .env 에 COACH_PASSCODE 가 없으면 실행하지 않는다. 집·사설망에서만 쓰고, 회사·공용 Wi-Fi 에서는 쓰지 않는다.
"""

import os
import socket
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PORT = 8501
MIN_PASSCODE_LENGTH = 8


def lan_ip():
    """이 PC 의 사설망 주소. UDP 소켓으로 '어느 쪽으로 나가는지'만 물어본다 (실제로 보내는 데이터는 없다)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return None


def passcode_problem(passcode):
    """암호가 쓸 만한지. 문제가 있으면 설명을, 없으면 None 을 돌려준다."""
    if not passcode:
        return "COACH_PASSCODE 가 없습니다. .env 에 COACH_PASSCODE=<8자 이상의 암호> 를 넣어 주세요."
    if len(passcode) < MIN_PASSCODE_LENGTH:
        return f"COACH_PASSCODE 가 너무 짧습니다 ({MIN_PASSCODE_LENGTH}자 이상)."
    return None


def main():
    load_dotenv(ROOT / ".env")
    problem = passcode_problem(os.getenv("COACH_PASSCODE"))
    if problem:
        print(problem)
        print("암호 없이 네트워크에 열면 같은 망의 누구나 기록을 보고 API 비용을 쓸 수 있어서 실행하지 않습니다.")
        return 1

    ip = lan_ip()
    print("폰 브라우저에서 아래 주소로 접속하세요 (PC 와 같은 Wi-Fi 여야 합니다).")
    print(f"  http://{ip}:{PORT}" if ip else "  (사설망 주소를 찾지 못했습니다. ipconfig 로 IPv4 주소를 확인하세요)")
    print("처음 실행하면 Windows 방화벽이 물어봅니다. '개인 네트워크'만 허용하세요.")
    print("끝낼 때는 Ctrl+C.\n")
    return subprocess.call(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.address", "0.0.0.0", "--server.port", str(PORT), "--server.headless", "true"],
        cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
