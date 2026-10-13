"""Read-only, explicit-reference Skill directory audit. Python standard library only."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

EXCLUSIONS = [".git", ".DS_Store", "__pycache__", "*.pyc"]
MAX_FILES = 5000
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024


class AuditError(Exception):
    pass


def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def json_digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_digest(path):
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise AuditError(f"不是支持范围内的常规文件：{path.name}")
    value = hashlib.sha256()
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_ino, opened.st_dev) != (before.st_ino, before.st_dev):
            raise AuditError("读取前文件发生变化")
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    after = path.stat(follow_symlinks=False)
    if (before.st_size, before.st_mtime_ns, before.st_ino, before.st_dev) != (after.st_size, after.st_mtime_ns, after.st_ino, after.st_dev):
        raise AuditError("读取期间文件发生变化")
    return before.st_size, value.hexdigest()


def explicit_root(value):
    requested = Path(value).expanduser().absolute()
    try:
        resolved = requested.resolve(strict=True)
    except OSError as error:
        raise AuditError(f"指定目录不存在：{requested}") from error
    if not resolved.is_dir():
        raise AuditError("输入必须是目录")
    return requested, resolved


def inventory(value):
    requested, root = explicit_root(value)
    files, ignored = [], []
    total = 0
    def walk(directory):
        nonlocal total
        for path in sorted(directory.iterdir(), key=lambda p: p.name):
            relative = path.relative_to(root).as_posix()
            if path.name in {".git", ".DS_Store", "__pycache__"} or path.name.endswith(".pyc"):
                ignored.append(relative)
                continue
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise AuditError(f"拒绝目录内部的符号链接：{relative}")
            if stat.S_ISDIR(mode):
                walk(path)
            elif stat.S_ISREG(mode):
                size, sha = file_digest(path)
                total += size
                if len(files) >= MAX_FILES or total > MAX_TOTAL_BYTES:
                    raise AuditError("目录超过文件数或总字节上限")
                files.append({"path": relative, "bytes": size, "sha256": sha})
            else:
                raise AuditError(f"拒绝特殊文件：{relative}")
    walk(root)
    return {"requested_root": str(requested), "resolved_root": str(root),
            "root_is_symlink": requested.is_symlink(), "files": files,
            "ignored_paths": sorted(ignored), "total_bytes": total}


def new_destination(value, forbidden):
    destination = Path(value).expanduser().absolute()
    resolved = destination.resolve()
    if destination.exists() or destination.is_symlink():
        raise AuditError("输出已经存在，请使用新路径")
    for root in forbidden:
        if resolved.is_relative_to(Path(root).resolve()):
            raise AuditError("输出必须位于被检查目录之外")
    return destination


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def freeze(reference, output, label=None):
    first = inventory(reference)
    destination = new_destination(output, [first["resolved_root"]])
    if "SKILL.md" not in {item["path"] for item in first["files"]}:
        raise AuditError("参考目录缺少 SKILL.md")
    if first != inventory(reference):
        raise AuditError("冻结期间参考目录发生变化")
    body = {"schema_version": 1, "kind": "skill-reference-manifest",
            "created_at": timestamp(), "label": label or "用户指定参考版本",
            "reference": first, "exclusions": EXCLUSIONS,
            "limits": {"files": MAX_FILES, "file_bytes": MAX_FILE_BYTES, "total_bytes": MAX_TOTAL_BYTES}}
    manifest = {**body, "snapshot_id": json_digest(body)}
    write_new(destination, manifest)
    return manifest


def read_manifest(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AuditError("参考清单无法读取") from error
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("kind") != "skill-reference-manifest":
        raise AuditError("不支持的参考清单")
    body = {k: v for k, v in data.items() if k != "snapshot_id"}
    if data.get("snapshot_id") != json_digest(body) or data.get("exclusions") != EXCLUSIONS:
        raise AuditError("参考清单被改动或排除规则不兼容")
    try:
        entries = data["reference"]["files"]
    except (KeyError, TypeError) as error:
        raise AuditError("缺少参考文件清单") from error
    if not isinstance(entries, list) or not 0 < len(entries) <= MAX_FILES:
        raise AuditError("参考文件数量不合法")
    names, total = set(), 0
    for item in entries:
        if not isinstance(item, dict):
            raise AuditError("文件条目格式错误")
        name, sha, size = item.get("path"), item.get("sha256"), item.get("bytes")
        if not isinstance(name, str) or not name or name in names or "\\" in name or ":" in name:
            raise AuditError("参考路径重复或非法")
        parts = PurePosixPath(name)
        if parts.is_absolute() or ".." in parts.parts or str(parts) != name or name == ".":
            raise AuditError("参考路径越界或不规范")
        if type(size) is not int or not 0 <= size <= MAX_FILE_BYTES or not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise AuditError("文件大小或摘要无效")
        if any(parent.as_posix() in names for parent in parts.parents if parent.as_posix() != "."):
            raise AuditError("参考文件与目录路径冲突")
        names.add(name)
        total += size
    if "SKILL.md" not in names or total > MAX_TOTAL_BYTES:
        raise AuditError("参考清单缺少主文件或超出上限")
    # Check prefixes independent of manifest order.
    if any(any(parent.as_posix() in names for parent in PurePosixPath(name).parents if parent.as_posix() != ".") for name in names):
        raise AuditError("参考文件与目录路径冲突")
    return data


def markdown_text(value):
    return html.escape(str(value)).replace("|", "\\|").replace("`", "\\`").replace("\n", "\\n").replace("\r", "\\r")


def csv_text(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t")) else value


def check(manifest_path, installed, output):
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest_bytes = manifest_path.read_bytes()
    reference = read_manifest(manifest_path)
    observed = inventory(installed)
    destination = new_destination(output, [observed["resolved_root"], reference["reference"]["resolved_root"]])
    if manifest_path.is_relative_to(destination.resolve()):
        raise AuditError("输出不能包含输入清单")
    expected = {item["path"]: item for item in reference["reference"]["files"]}
    actual = {item["path"]: item for item in observed["files"]}
    counts = {name: 0 for name in ["match", "modified", "missing", "extra"]}
    rows = []
    for name in sorted(set(expected) | set(actual)):
        before, after = expected.get(name), actual.get(name)
        state = "extra" if before is None else "missing" if after is None else "match" if (before["sha256"], before["bytes"]) == (after["sha256"], after["bytes"]) else "modified"
        counts[state] += 1
        rows.append({"path": name, "status": state,
                     "reference_sha256": before["sha256"] if before else None,
                     "installed_sha256": after["sha256"] if after else None,
                     "reference_bytes": before["bytes"] if before else None,
                     "installed_bytes": after["bytes"] if after else None})
    if observed != inventory(installed) or manifest_path.read_bytes() != manifest_bytes:
        raise AuditError("核对期间输入发生变化，请在输入稳定后使用新目录重试")
    differences = counts["modified"] + counts["missing"] + counts["extra"]
    result = {"schema_version": 1, "skill": "skill-install-audit", "version": "0.1.0",
              "status": "differences_found" if differences else "matches_reference",
              "checked_at": timestamp(), "reference_snapshot_id": reference["snapshot_id"],
              "reference_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
              "reference_label": reference["label"], "installed": {
                  k:v for k,v in observed.items() if k != "files"},
              "counts": counts, "differences": differences, "files": rows,
              "ignored_reference_paths": reference["reference"]["ignored_paths"],
              "exclusions": EXCLUSIONS, "inputs_modified": False, "inspected_code_executed": False,
              "limits": ["仅比较指定参考的文件字节，不判断最新、安全或运行效果。", "未验证宿主实际加载了所指目录。", "改动和额外文件可能是有意保留的内容。"]}
    destination.mkdir(parents=True, exist_ok=False)
    write_new(destination / "audit.json", result)
    labels = {"match": "一致", "modified": "改动", "missing": "缺失", "extra": "额外"}
    lines = ["# Skill 安装文件核对", "", f"结果：{'与参考一致' if not differences else '发现文件差异'}。",
             f"一致 {counts['match']}；改动 {counts['modified']}；缺失 {counts['missing']}；额外 {counts['extra']}。", "",
             "| 文件 | 分类 | 参考摘要 | 目标摘要 |", "| --- | --- | --- | --- |"]
    for row in rows:
        lines.append(f"| {markdown_text(row['path'])} | {labels[row['status']]} | {(row['reference_sha256'] or '—')[:12]} | {(row['installed_sha256'] or '—')[:12]} |")
    lines += ["", "原目录未修改，被检查脚本未执行。", "", "文件一致只表示符合这份参考；不代表最新版本、安全审计、宿主加载或业务验证通过。",
              "差异需要结合本人改动核对，不自动覆盖、删除或更新。", "", "排除规则：" + "、".join(EXCLUSIONS),
              "参考排除项：" + markdown_text(", ".join(result['ignored_reference_paths']) or "无"),
              "目标排除项：" + markdown_text(", ".join(observed['ignored_paths']) or "无")]
    (destination / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (destination / "files.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "status", "reference_sha256", "installed_sha256"])
        for row in rows:
            writer.writerow([csv_text(row["path"]), row["status"], row["reference_sha256"] or "", row["installed_sha256"] or ""])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze_parser = sub.add_parser("freeze")
    freeze_parser.add_argument("--reference", required=True)
    freeze_parser.add_argument("--out", required=True)
    freeze_parser.add_argument("--label")
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--manifest", required=True)
    check_parser.add_argument("--installed", required=True)
    check_parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        if args.command == "freeze":
            result = freeze(args.reference, args.out, args.label)
            print(json.dumps({"status": "frozen", "files": len(result["reference"]["files"]),
                              "snapshot_id": result["snapshot_id"]}, ensure_ascii=False))
            return 0
        result = check(args.manifest, args.installed, args.out)
        print(json.dumps({"status": result["status"], "counts": result["counts"],
                          "differences": result["differences"], "output": str(Path(args.out).resolve())}, ensure_ascii=False))
        return 2 if result["differences"] else 0
    except (AuditError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
