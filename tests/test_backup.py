"""백업 내보내기 / 불러오기 / 분석용 CSV 테스트. tmp_path = pytest 가 테스트마다 만들어 주는 임시 폴더."""

import csv
import io
import json
import zipfile

import pytest

from coach import store
from coach.backup import BackupError, export_zip, import_zip, tags_csv
from coach.corpus import tag_rows


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def attempt(id_, answer="友達を会った。"):
    return {"id": id_, "timestamp": "2026-10-01T10:00:00+09:00", "topic": "t", "mode": "grammar",
            "answer": answer, "n_samples": 3, "tentative_errors": [], "untagged_changes": [],
            "errors": [{"type": "PARTICLE", "original": "を", "corrected": "に", "start": 2, "end": 3,
                        "explanation_ko": "설명, 쉼표 포함", "severity": "error",
                        "kr_interference": True, "votes": 3}]}


def label(key, value, ts):
    return {"key": key, "label": value, "timestamp": ts}


def test_roundtrip_into_empty_folder(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    write(src / "attempts.jsonl", [attempt("a"), attempt("b")])
    write(src / "labels.jsonl", [label("a:2:3:PARTICLE", "unknown", "2026-10-01T10:05:00+09:00")])

    report = import_zip(export_zip(src, {"taxonomy": "v1"}), dst)

    assert report["attempts.jsonl"] == {"added": 2, "skipped": 0, "invalid": 0}
    assert [r["id"] for r in store.load(dst / "attempts.jsonl")] == ["a", "b"]
    assert store.load_labels(dst / "labels.jsonl") == {"a:2:3:PARTICLE": "unknown"}


def test_import_merges_and_never_duplicates(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    write(src / "attempts.jsonl", [attempt("a"), attempt("b")])
    write(dst / "attempts.jsonl", [attempt("a"), attempt("mine")])       # a 는 이미 있고, mine 은 내 것
    blob = export_zip(src)

    assert import_zip(blob, dst)["attempts.jsonl"] == {"added": 1, "skipped": 1, "invalid": 0}
    assert import_zip(blob, dst)["attempts.jsonl"] == {"added": 0, "skipped": 2, "invalid": 0}  # 두 번 불러와도 그대로
    assert sorted(r["id"] for r in store.load(dst / "attempts.jsonl")) == ["a", "b", "mine"]


def test_older_label_from_backup_does_not_override_newer(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    write(src / "labels.jsonl", [label("k", "slip", "2026-10-01T09:00:00+09:00")])      # 백업 속의 옛 판정
    write(dst / "labels.jsonl", [label("k", "unknown", "2026-10-02T09:00:00+09:00")])   # 그 뒤에 바꾼 판정
    import_zip(export_zip(src), dst)
    assert store.load_labels(dst / "labels.jsonl") == {"k": "unknown"}     # 파일에서는 뒤에 붙었지만 시각으로 고른다


def test_rejects_foreign_or_broken_files(tmp_path):
    with pytest.raises(BackupError):
        import_zip(b"not a zip", tmp_path)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("attempts.jsonl", json.dumps(attempt("x")) + "\n")      # manifest 없음
    with pytest.raises(BackupError):
        import_zip(buffer.getvalue(), tmp_path)
    assert not (tmp_path / "attempts.jsonl").exists()                        # 거부한 파일은 아무것도 쓰지 않는다


def test_invalid_lines_and_unknown_members_are_ignored(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("manifest.json", json.dumps({"app": "PragmaticsKR2JP", "format": 1}))
        z.writestr("attempts.jsonl", json.dumps(attempt("ok")) + "\n{broken\n" + json.dumps({"id": "no-answer"}) + "\n")
        z.writestr("../evil.txt", "x")                                       # 정해진 파일이 아니면 읽지도 풀지도 않는다
    report = import_zip(buffer.getvalue(), tmp_path / "dst")
    assert report["attempts.jsonl"] == {"added": 1, "skipped": 0, "invalid": 2}
    assert sorted(p.name for p in (tmp_path / "dst").iterdir()) == ["attempts.jsonl"]
    assert not (tmp_path / "evil.txt").exists()


def test_revision_prefers_regraded_regardless_of_order(tmp_path):
    path = tmp_path / "revisions.jsonl"
    write(path, [{"id": "r", "regraded": True, "text": "new"}, {"id": "r", "regraded": False, "text": "old"}])
    assert store.load_revisions(path)["r"]["text"] == "new"


def test_tags_csv_opens_in_excel_and_keeps_commas():
    records = [attempt("a")]
    blob = tags_csv(records, tag_rows(records, {"a:2:3:PARTICLE": "unknown"}))
    assert blob.startswith(b"\xef\xbb\xbf")                                   # BOM: 엑셀이 UTF-8 로 연다
    rows = list(csv.DictReader(io.StringIO(blob.decode("utf-8-sig"))))
    assert len(rows) == 1
    assert (rows[0]["original"], rows[0]["corrected"], rows[0]["label"]) == ("を", "に", "unknown")
    assert rows[0]["explanation_ko"] == "설명, 쉼표 포함" and rows[0]["pattern_governing"] == "会う"
