# 0024. CI 단계를 공용 재사용 워크플로(Concordia)에 맡기고, 공개 위생 검사를 더한다

- 상태: 채택 (2026-11-24) · 0016 의 테스트 단계 구현을 바꾼다. 「push 마다 테스트, 배포는 하지 않음」은 그대로다.

## 맥락
테스트 단계(checkout → setup-python → pip install → pytest)가 다른 저장소들과 거의 같은데 저장소마다 따로 적혀 있어 action 판이 제각각이었다. 공개 저장소에 들어가면 안 되는 파일·경로를 확인하는 장치는 없었다.

## 결정
1. `tests.yml` 은 `fairyofdata/Concordia` 의 `python-tests.yml@v1` 을 부른다. 파이썬 3.14, 설치·테스트 명령은 전과 같다.
2. 같은 파일에서 `hygiene.yml@v1` 을 부른다. 추적되면 안 되는 로컬 파일(state.md, CLAUDE.local.md, .claude/ 등)과 홈 디렉터리 절대 경로를 형식으로만 검사한다.

## 결과
- 단계를 고칠 일이 생기면 Concordia 한 곳만 고친다.
- 대가: Concordia 의 `v1` 태그가 옮겨지면 이 저장소 CI 도 따라 바뀐다.
