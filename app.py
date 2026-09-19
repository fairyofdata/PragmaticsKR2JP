"""일본어 작문 코치 — Streamlit 화면.

실행: streamlit run app.py
"""

import os
import random

import streamlit as st
from dotenv import load_dotenv

from coach import store
from coach.prompts import TOPICS
from coach.stats import filter_records, streak_days, summary_counts, top_types
from coach.taxonomy import MODES, OUT_OF_MODE, name_ko
from coach.verify import diff_html

load_dotenv()
st.set_page_config(page_title="일본어 작문 코치", page_icon="✍️", layout="centered")

# ---------- 사이드바 ----------
with st.sidebar:
    mode = st.radio("모드", list(MODES), format_func=lambda m: MODES[m])
    topic = st.selectbox("주제", list(TOPICS))
    st.divider()
    source = st.radio("요약에 쓸 기록", ["내 기록", "시연용 예시", "둘 다"], index=2)
    show_streak = st.toggle("연속 사용일 표시", value=False)


def load_records():
    records = []
    if source in ("내 기록", "둘 다"):
        records += store.load(store.DATA_FILE)
    if source in ("시연용 예시", "둘 다"):
        records += store.load(store.SAMPLES_FILE)
    return records


def tag_line(e, n):
    badge = " · 🇰🇷 직역 간섭" if e["kr_interference"] else ""
    level = "오류" if e["severity"] == "error" else "부자연"
    return (f"**[{name_ko(e['type'])}]** `{e['original']}` → `{e['corrected']}` "
            f"({level}, {e['votes']}/{n}회 일치{badge})  \n{e['explanation_ko']}")


def show_result(r):
    st.markdown("**교정 (오류만 고침)**")
    st.markdown(diff_html(r["answer"], r["minimal_correction"]), unsafe_allow_html=True)
    st.markdown("**이 장면에서 자연스러운 문장**")
    st.info(r["natural_version"])
    st.caption(f"해석된 뜻: {r['intended_meaning_ko']}")

    in_mode = [e for e in r["errors"] if e["type"] != OUT_OF_MODE]
    out_mode = [e for e in r["errors"] if e["type"] == OUT_OF_MODE]
    if not r["errors"]:
        st.success("확정된 오류가 없습니다.")
    for e in in_mode:
        st.markdown(tag_line(e, r["n_samples"]))
    if out_mode:
        with st.expander(f"모드 밖 오류 {len(out_mode)}건 (집계 제외)"):
            for e in out_mode:
                st.markdown(tag_line(e, r["n_samples"]))
    if r["tentative_errors"]:
        with st.expander(f"참고: 낮은 확신 {len(r['tentative_errors'])}건 (과반 미달, 집계 제외)"):
            for e in r["tentative_errors"]:
                st.markdown(tag_line(e, r["n_samples"]))
    for m in r.get("merged_tags", []):
        edits = ", ".join(f"`{e['original']}`→`{e['corrected']}`" for e in m["edits"])
        st.warning(f"태그 하나에 수정이 {len(m['edits'])}개 합쳐져 있습니다: {edits} "
                   f"(붙은 유형은 [{name_ko(m['type'])}] 하나뿐 — 나머지 수정도 따로 확인하세요)")
    if r["untagged_changes"]:
        changes = ", ".join(f"`{c['original']}`→`{c['corrected']}`" for c in r["untagged_changes"])
        st.warning(f"태그 없이 고쳐진 곳이 있습니다 (설명 누락): {changes}")
    if r["dropped_quotes"]:
        st.caption(f"원문에 없는 인용이라 버린 태그: {r['dropped_quotes']}건")


tab_practice, tab_summary = st.tabs(["연습", "요약"])

# ---------- 연습 ----------
with tab_practice:
    key_name = "GEMINI_API_KEY" if os.getenv("LLM_PROVIDER") == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key_name):
        st.error(f"{key_name} 가 없습니다. .env.example 을 .env 로 복사해 키를 넣어 주세요.")

    if st.button("과제 받기", type="primary"):
        from coach import llm
        medium, relationship = random.choice(TOPICS[topic])
        with st.spinner("과제를 만드는 중..."):
            task = llm.generate_task(topic, medium, relationship)
        st.session_state.update(task=task, topic=topic, medium=medium,
                                relationship=relationship, result=None)

    task = st.session_state.get("task")
    if task:
        st.caption(f"{st.session_state.topic} · {st.session_state.medium} · "
                   f"상대: {st.session_state.relationship}")
        st.markdown(f"**상황** {task.situation_ko}")
        st.markdown(f"**과제** {task.instruction_ko}")
        answer = st.text_area("일본어로 쓰기", height=150)

        if st.button("채점", disabled=not answer.strip()):
            from coach import llm
            with st.spinner(f"{llm.N_SAMPLES}번 채점해서 합치는 중..."):
                attempt = llm.grade(answer, task, mode, st.session_state.topic,
                                    st.session_state.medium, st.session_state.relationship)
            store.append(attempt)
            st.session_state.result = attempt.model_dump()

    if st.session_state.get("result"):
        st.divider()
        show_result(st.session_state.result)

# ---------- 요약 ----------
with tab_summary:
    all_records = load_records()
    records = filter_records(all_records, mode)
    st.subheader(MODES[mode])

    if show_streak:
        app_records = [r for r in all_records if r["source"] == "app"]  # 합성 예시는 제외
        st.metric("연속 사용일", f"{streak_days(app_records)}일")

    if not records:
        st.info("아직 이 모드의 기록이 없습니다.")
    else:
        c = summary_counts(records)
        col1, col2, col3 = st.columns(3)
        col1.metric("시도", c["attempts"])
        col2.metric("확정 오류", c["errors"] - c["out_of_mode"])
        col3.metric("오류 없는 시도", c["error_free"])
        st.caption(f"모드 밖 오류 {c['out_of_mode']} · 낮은 확신 {c['tentative']} · "
                   f"태그 없이 고쳐진 곳 {c['untagged_changes']} (모두 순위에서 제외)")

        st.markdown("### 자주 틀리는 유형 상위 5개")
        st.caption("순위 = 그 유형이 나온 시도의 수. 한 답에 같은 오류가 여러 번 있어도 1로 셉니다.")
        for i, t in enumerate(top_types(records), start=1):
            label = (f"{i}. {t['name_ko']} — {t['attempts_with']}/{c['attempts']}회 시도 "
                     f"({t['share']:.0%}), 총 {t['count']}건, 직역 간섭 {t['kr_interference']}건")
            with st.expander(label, expanded=(i == 1)):
                for ex in t["examples"]:
                    st.markdown(f"`{ex['original']}` → `{ex['corrected']}` · {ex['topic']}  \n"
                                f"{ex['explanation_ko']}")
                    st.caption(ex["answer"])
