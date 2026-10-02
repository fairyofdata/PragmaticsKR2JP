"""개인 데이터 백업: 내보내기 / 불러오기 / 분석용 CSV. 화면(Streamlit)과 LLM 을 모른다.

- 백업 = zip 하나. 안에는 data/ 의 JSONL 파일 그대로 + manifest.json(언제, 몇 건, 어떤 버전).
  JSONL 을 그대로 쓰는 이유: 기록 한 건 안에 지적·과제가 중첩돼 있어서 CSV 로 펴면 되돌릴 수 없다.
- 불러오기는 덮어쓰지 않고 '합친다' (기록은 추가만 한다는 원칙). 이미 있는 것은 건너뛴다.
- 분석용 CSV 는 내보내기 전용: 확정된 지적 한 건 = 한 줄. 엑셀로 열거나 원어민 검수에 넘길 때 쓴다.
"""

import csv
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

APP_NAME = "PragmaticsKR2JP"
BACKUP_FORMAT = 1
FILES = ("attempts.jsonl", "labels.jsonl", "revisions.jsonl")
MAX_UNZIPPED_BYTES = 50 * 1024 * 1024      # 압축을 풀었을 때 50MB 를 넘으면 받지 않는다 (잘못된·악의적인 파일 방지)
REQUIRED_ATTEMPT_KEYS = ("id", "timestamp", "answer", "errors")


class BackupError(Exception):
    """불러올 수 없는 백업 파일."""


def _read_lines(path):
    path = Path(path)
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def export_zip(data_dir, versions=None):
    """data_dir 의 JSONL 파일들을 zip 으로 묶은 bytes."""
    data_dir = Path(data_dir)
    buffer = io.BytesIO()
    counts = {}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name in FILES:
            lines = _read_lines(data_dir / name)
            counts[name] = len(lines)
            z.writestr(name, "\n".join(lines) + ("\n" if lines else ""))
        manifest = {"app": APP_NAME, "format": BACKUP_FORMAT,
                    "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "counts": counts, "versions": versions or {}}
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buffer.getvalue()


def _canonical(obj):
    """같은 내용이면 같은 문자열이 되도록 (키 순서가 달라도 중복으로 알아보게)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def import_zip(blob, data_dir):
    """백업 zip 을 data_dir 에 합친다. 결과: {파일명: {"added", "skipped", "invalid"}}.

    - attempts : 같은 id 가 이미 있으면 건너뛴다
    - labels, revisions : 완전히 같은 줄이 이미 있으면 건너뛴다 (판정 이력은 줄 단위로 의미가 있다)
    - 정해진 세 파일과 manifest 만 읽는다. zip 안의 다른 파일은 무시하고, 디스크에 풀지 않는다.
    """
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise BackupError("zip 파일이 아닙니다.")
    with z:
        names = set(z.namelist())
        if "manifest.json" not in names:
            raise BackupError("이 앱의 백업 파일이 아닙니다 (manifest.json 없음).")
        if sum(info.file_size for info in z.infolist()) > MAX_UNZIPPED_BYTES:
            raise BackupError("파일이 너무 큽니다.")
        try:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise BackupError("manifest.json 을 읽을 수 없습니다.")
        if manifest.get("app") != APP_NAME:
            raise BackupError("이 앱의 백업 파일이 아닙니다.")
        if manifest.get("format", 0) > BACKUP_FORMAT:
            raise BackupError("더 새로운 버전의 앱에서 만든 백업입니다. 앱을 먼저 업데이트하세요.")
        incoming = {name: z.read(name).decode("utf-8").splitlines() if name in names else []
                    for name in FILES}

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    report = {}
    for name in FILES:
        existing = []
        for line in _read_lines(data_dir / name):
            try:
                existing.append(json.loads(line))
            except ValueError:
                pass
        seen_ids = {row.get("id") for row in existing} if name == "attempts.jsonl" else set()
        seen_rows = {_canonical(row) for row in existing}

        added, skipped, invalid, new_lines = 0, 0, 0, []
        for line in incoming[name]:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                invalid += 1
                continue
            ok = isinstance(row, dict) and (name != "attempts.jsonl"
                                            or all(k in row for k in REQUIRED_ATTEMPT_KEYS))
            if not ok:
                invalid += 1
            elif (name == "attempts.jsonl" and row["id"] in seen_ids) or _canonical(row) in seen_rows:
                skipped += 1
            else:
                new_lines.append(json.dumps(row, ensure_ascii=False))
                seen_ids.add(row.get("id"))
                seen_rows.add(_canonical(row))
                added += 1
        if new_lines:
            with open(data_dir / name, "a", encoding="utf-8") as f:
                f.write("\n".join(new_lines) + "\n")
        report[name] = {"added": added, "skipped": skipped, "invalid": invalid}
    return report


CSV_COLUMNS = ["timestamp", "attempt_id", "mode", "input_mode", "topic", "medium", "relationship",
               "source_ko", "answer", "type", "original", "corrected", "explanation_ko",
               "severity", "votes", "n_samples", "kr_interference", "label", "ime_candidate",
               "pattern_edit", "pattern_governing"]


def tags_csv(records, rows):
    """분석용 CSV (bytes). rows: corpus.tag_rows 의 결과, records: 그 행들이 나온 시도 기록.
    엑셀이 한국어·일본어를 깨지 않고 열도록 UTF-8 BOM 을 붙인다."""
    by_id = {r["id"]: r for r in records}
    errors = {(r["id"], e.get("start"), e.get("end"), e["type"]): e for r in records for e in r["errors"]}
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in sorted(rows, key=lambda x: x["timestamp"]):
        r = by_id[row["attempt_id"]]
        _, start, end, _ = row["key"].rsplit(":", 3)
        e = errors.get((r["id"], int(start), int(end), row["type"]), {})
        writer.writerow({
            "timestamp": row["timestamp"], "attempt_id": r["id"], "mode": r.get("mode", ""),
            "input_mode": r.get("input_mode", "generated"), "topic": r.get("topic", ""),
            "medium": r.get("medium", ""), "relationship": r.get("relationship", ""),
            "source_ko": r.get("source_ko", ""), "answer": r["answer"], "type": row["type"],
            "original": row["original"], "corrected": row["corrected"],
            "explanation_ko": row["explanation_ko"], "severity": e.get("severity", ""),
            "votes": e.get("votes", ""), "n_samples": r.get("n_samples", ""),
            "kr_interference": e.get("kr_interference", ""), "label": row["label"] or "",
            "ime_candidate": row["ime_candidate"], "pattern_edit": row["pattern"][1],
            "pattern_governing": row["pattern"][2],
        })
    return ("﻿" + out.getvalue()).encode("utf-8")
