"""README 용 스크린샷 만들기.

Streamlit 앱을 띄우고, 브라우저를 자동으로 조작해서 docs/images/ 에 PNG 를 저장한다.
(Playwright = 브라우저를 코드로 조작하는 도구. 여기서는 이미 설치된 Edge 를 쓴다.)

- 실제 기록(data/)을 건드리지 않도록 COACH_DATA_FILE 을 임시 폴더로 돌린다.
- 연습 화면(practice.png) 한 장은 실제 API 호출이 일어난다 (과제 1회 + 채점 3회, 약 $0.04).
  --skip-practice 를 주면 그 장은 건너뛰고 무료로 찍을 수 있는 것만 찍는다.

실행: python -m tools.screenshots [--skip-practice]
"""

import argparse
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
DESKTOP = {"width": 1180, "height": 980}
PHONE = {"width": 390, "height": 844}
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
    env["COACH_DATA_FILE"] = str(Path(tempfile.gettempdir()) / "coach_screenshot" / "attempts.jsonl")
    env["COACH_PASSCODE"] = ""      # .env 에 암호가 있어도 스크린샷용 앱은 잠그지 않는다
    return subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.port", str(PORT), "--server.headless", "true",
         "--browser.gatherUsageStats", "false"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def shot(page, name, full_page=False):
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / name), full_page=full_page)
    print("saved", name)


def open_page(browser, viewport):
    page = browser.new_page(viewport=viewport, device_scale_factor=2)
    page.goto(URL)
    page.wait_for_selector('[role="tab"]', timeout=60000)
    return page


def include_older_records(page, phone=False):
    """시연용 예시가 이전 버전(p1)일 때 요약에 보이도록 사이드바 토글을 켠다."""
    if phone:   # 폰에서는 사이드바가 접혀 있다 → 열고, 켜고, 닫는다
        page.get_by_test_id("stExpandSidebarButton").click()
        page.wait_for_timeout(800)
    page.get_by_test_id("stSidebar").get_by_text("이전 버전 기록도 포함").click()
    page.wait_for_timeout(1500)
    if phone:
        page.keyboard.press("Escape")
        page.mouse.click(380, 400)      # 사이드바 바깥을 눌러 닫는다
        page.wait_for_timeout(800)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-practice", action="store_true", help="API 를 쓰는 연습 화면은 찍지 않는다")
    args = parser.parse_args()

    app = start_app()
    try:
        if not wait_for_port():
            raise SystemExit("앱이 뜨지 않았습니다")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")

            # ---- PC 화면 ----
            page = open_page(browser, DESKTOP)
            include_older_records(page)
            page.get_by_role("tab", name="요약").click()
            page.wait_for_timeout(2000)
            shot(page, "summary-grammar.png")

            page.get_by_text("표현 (적절성)").click()       # 모드는 본문 맨 위에 있다
            page.wait_for_timeout(2500)
            shot(page, "summary-expression.png")

            if not args.skip_practice:                       # 실제 API 호출
                page.get_by_text("문법 (정확성)").click()
                page.wait_for_timeout(2000)
                page.get_by_role("tab", name="연습").click()
                page.get_by_role("button", name="과제 받기").click()
                page.wait_for_selector("text=상황", timeout=120000)
                page.wait_for_timeout(1000)
                page.get_by_label("일본어로 쓰기").fill(ANSWER)
                page.keyboard.press("Control+Enter")         # Streamlit 은 입력 확정이 있어야 버튼이 활성화된다
                page.wait_for_timeout(1500)
                page.get_by_role("button", name="채점").click()
                page.wait_for_selector("text=교정 (확정된 오류만 반영)", timeout=180000)
                page.wait_for_timeout(1500)
                shot(page, "practice.png", full_page=True)   # 결과까지 다 보이게
            page.close()

            # ---- 폰 화면 (API 호출 없음) ----
            phone = open_page(browser, PHONE)
            phone.wait_for_timeout(1500)
            shot(phone, "mobile-practice.png")
            include_older_records(phone, phone=True)
            phone.get_by_role("tab", name="요약").click()
            phone.wait_for_timeout(2000)
            shot(phone, "mobile-summary.png")
            browser.close()
    finally:
        app.terminate()


if __name__ == "__main__":
    main()
