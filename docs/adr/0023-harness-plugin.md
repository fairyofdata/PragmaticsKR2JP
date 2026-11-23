# 0023. 갱신 스킬과 Stop 훅을 레포 사본에서 사용자 범위 플러그인으로 옮긴다

- 상태: 채택 (2026-11-24) · 0022 의 4번(장치) 을 바꾼다. 나머지(state.md 하나, CLAUDE.local.md 의 `@state.md`)는 그대로다.

## 맥락
0022 의 장치(`/state` 스킬, Stop 훅 `state-check.js`)는 `.claude/`(git 제외)에 복사돼 있었다. 같은 장치가 다른 저장소에도 따로 복사돼 있어서, 고칠 때마다 저장소마다 다시 깔아야 했다. 공개 저장소라 `.claude/` 가 원격에도 없으니, 다른 PC 에서는 장치가 아예 없었다.

## 결정
1. 장치는 사용자 범위로 설치한 Claude Code 플러그인 `harness` 가 맡는다. 스킬 이름은 `/harness:state` 다. 플러그인은 `@state.md` 를 가져오는 저장소에서만 움직인다. 판정(커밋했는데 state.md 를 안 고쳤으면 한 번 알림)은 0022 와 같다.
2. 같은 플러그인에 push 직전 판정 훅이 있다. 나가는 변경에 개인 산출물이 있는지 모델이 맥락으로 판정하고, 의심되거나 판정을 받지 못하면 확인을 받는다.
3. 이 저장소에서 `.claude/hooks/state-check.js`, `.claude/skills/state/SKILL.md`, `settings.local.json` 의 Stop 등록을 지운다. SessionStart 훅(`tools/session_handoff.py`)은 이 저장소의 것이라 그대로 둔다.
4. CLAUDE.md 에 「이 저장소에는 개인 산출물을 만들거나 커밋하지 않는다」 한 줄, `.gitignore` 에 `_private/`·`*.private.*` 를 더한다.

## 결과
- 장치를 고쳐도 저장소를 건드리지 않는다.
- 대가: 플러그인을 설치하지 않은 PC 에서는 스킬과 Stop 훅이 없다(0022 때도 `.claude/` 가 git 밖이라 같았다).
