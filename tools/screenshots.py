"""README 용 스크린샷 만들기.

Streamlit 앱을 띄우고, 브라우저를 자동으로 조작해서 docs/images/ 에 PNG 를 저장한다.
(Playwright = 브라우저를 코드로 조작하는 도구. 여기서는 이미 설치된 Edge 를 쓴다.)

- 실제 기록(data/)을 건드리지 않도록 COACH_DATA_FILE 을 임시 파일로 돌린다.
- 연습 화면 스크린샷 1장을 위해 실제 API 호출이 일어난다 (과제 1회 + 채점 3회, 약 $0.02).

실행: python -m tools.screenshots
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
PORT = 8599
URL = f"http://localhost:{PORT}"
# 문법 모드에서 태그가 보이도록 오류를 넣은 답 (활용 '悪いだから', 수수표현 '渡してあげました')
ANSWER = "お疲れ様です。明日の会議ですが、体調が悪いだから参加が難しいです。資料は田中さんに渡してあげました。"


def wait_for_port(seconds=60):
    for _ in range(seconds * 2):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", PORT)) == 0:
                return True
        time.sleep(0.5)
    return False


def start_app():
    env = dict(os.environ)
    env["COACH_DATA_FILE"] = str(Path(tempfile.gettempdir()) / "coach_screenshot.jsonl")
    return subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.port", str(PORT), "--server.headless", "true",
         "--browser.gatherUsageStats", "false"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def shot(page, name):
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / name))
    print("saved", name)


def main():
    app = start_app()
    try:
        if not wait_for_port():
            raise SystemExit("앱이 뜨지 않았습니다")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1180, "height": 980}, device_scale_factor=2)
            page.goto(URL)
            page.wait_for_selector('[role="tab"]', timeout=60000)

            # 1) 요약 화면 (시연용 예시 12건 기준)
            page.get_by_role("tab", name="요약").click()
            page.wait_for_timeout(1500)
            shot(page, "summary-grammar.png")

            # 2) 표현 모드 요약
            page.get_by_test_id("stSidebar").get_by_text("표현 모드", exact=False).click()
            page.wait_for_timeout(2500)
            shot(page, "summary-expression.png")

            # 3) 연습 화면 (실제 API 호출). 모드를 문법으로 되돌린다
            page.get_by_test_id("stSidebar").get_by_text("문법 모드", exact=False).click()
            page.wait_for_timeout(2000)
            page.get_by_role("tab", name="연습").click()
            page.get_by_role("button", name="과제 받기").click()
            page.wait_for_selector("text=상황", timeout=120000)
            page.wait_for_timeout(1000)
            page.get_by_role("textbox").fill(ANSWER)
            page.keyboard.press("Control+Enter")   # Streamlit 은 입력 확정이 있어야 버튼이 활성화된다
            page.wait_for_timeout(1500)
            page.get_by_role("button", name="채점").click()
            page.wait_for_selector("text=교정 (오류만 고침)", timeout=180000)
            page.wait_for_timeout(1500)
            OUT.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(OUT / "practice.png"), full_page=True)  # 결과까지 다 보이게
            print("saved practice.png")
            browser.close()
    finally:
        app.terminate()


if __name__ == "__main__":
    main()
