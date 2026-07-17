#!/usr/bin/env python3
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


def git_z(*args):
    result = subprocess.run(
        ["git", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
    )
    return [os.fsdecode(item) for item in result.stdout.split(b"\0") if item]


def payload(path, info):
    if stat.S_ISREG(info.st_mode):
        data = path.read_bytes()
        current = path.stat(follow_symlinks=False)
        before = (info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode)
        after = (current.st_ino, current.st_size, current.st_mtime_ns, current.st_mode)
        if before != after:
            raise RuntimeError(f"file changed during snapshot: {path}")
        return "file", data
    if stat.S_ISLNK(info.st_mode):
        return "symlink", os.fsencode(os.readlink(path))
    raise RuntimeError(f"unsupported non-ignored path type: {path}")


def capture(snapshot_dir, label, quiet=False):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", label):
        raise RuntimeError(f"invalid snapshot label: {label}")
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    ).resolve()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    objects = snapshot_dir / "objects"
    objects.mkdir(exist_ok=True)

    files = {}
    for relative in sorted(set(git_z("ls-files", "-co", "--exclude-standard", "-z"))):
        path = root / relative
        try:
            info = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        kind, data = payload(path, info)
        digest = hashlib.sha256(data).hexdigest()
        object_path = objects / digest
        if not object_path.exists():
            object_path.write_bytes(data)
        files[relative] = {
            "type": kind,
            "mode": f"{stat.S_IMODE(info.st_mode):04o}",
            "sha256": digest,
        }

    try:
        changed = git_z("diff", "--name-only", "--no-renames", "-z", "HEAD", "--")
    except subprocess.CalledProcessError:
        changed = list(files)
    untracked = git_z("ls-files", "--others", "--exclude-standard", "-z")
    manifest = {
        "version": 1,
        "root": str(root),
        "files": files,
        "preexisting_paths": sorted(set(changed + untracked)),
    }
    target = snapshot_dir / f"{label}.json"
    temporary = snapshot_dir / f".{label}.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    temporary.replace(target)
    if not quiet:
        print(target)


def load_manifest(snapshot_dir, label):
    path = snapshot_dir / f"{label}.json"
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid {label} snapshot: {error}") from error


def safe_relative(path):
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeError(f"unsafe snapshot path: {path}")
    return candidate


def materialize(snapshot_dir, manifest, destination):
    for relative, entry in manifest["files"].items():
        target = destination / safe_relative(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = (snapshot_dir / "objects" / entry["sha256"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"corrupt snapshot object: {relative}")
        if entry["type"] == "file":
            target.write_bytes(data)
            target.chmod(int(entry["mode"], 8))
        elif entry["type"] == "symlink":
            target.symlink_to(os.fsdecode(data))
        else:
            raise RuntimeError(f"unsupported snapshot entry: {relative}")


def classify(pre_files, post_files):
    pre_paths = set(pre_files)
    post_paths = set(post_files)
    common = pre_paths & post_paths
    created = sorted(post_paths - pre_paths)
    deleted = sorted(pre_paths - post_paths)
    modified = sorted(
        path
        for path in common
        if (
            pre_files[path]["type"],
            pre_files[path]["sha256"],
        )
        != (
            post_files[path]["type"],
            post_files[path]["sha256"],
        )
    )
    mode_changed = sorted(
        path
        for path in common
        if pre_files[path]["mode"] != post_files[path]["mode"]
    )
    delegate_paths = sorted(set(created + deleted + modified + mode_changed))
    return created, modified, deleted, mode_changed, delegate_paths


def inspect(snapshot_dir, allowed):
    pre = load_manifest(snapshot_dir, "pre")
    post = load_manifest(snapshot_dir, "post")
    if pre["root"] != post["root"]:
        raise RuntimeError("pre and post snapshots use different repositories")
    created, modified, deleted, mode_changed, delegate_paths = classify(
        pre["files"], post["files"]
    )
    preexisting = set(pre["preexisting_paths"])
    delta = {
        "version": 1,
        "created": created,
        "modified": modified,
        "deleted": deleted,
        "mode_changed": mode_changed,
        "delegate_paths": delegate_paths,
        "preexisting_paths": sorted(preexisting),
        "delegate_touched_preexisting": sorted(preexisting & set(delegate_paths)),
        "scope_violations": sorted(set(delegate_paths) - set(allowed)),
        "patch": "delta.patch",
    }

    with tempfile.TemporaryDirectory(dir=snapshot_dir) as temporary:
        temporary = Path(temporary)
        pre_tree = temporary / "pre"
        post_tree = temporary / "post"
        pre_tree.mkdir()
        post_tree.mkdir()
        materialize(snapshot_dir, pre, pre_tree)
        materialize(snapshot_dir, post, post_tree)
        patch = subprocess.run(
            [
                "git",
                "diff",
                "--no-index",
                "--binary",
                "--no-renames",
                "--no-prefix",
                "--",
                "pre",
                "post",
            ],
            cwd=temporary,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if patch.returncode not in (0, 1):
            raise RuntimeError(os.fsdecode(patch.stderr).strip() or "patch generation failed")
        (snapshot_dir / "delta.patch").write_bytes(patch.stdout)

    (snapshot_dir / "delta.json").write_text(
        json.dumps(delta, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(delta, sort_keys=True))


def restore_entry(snapshot_dir, root, relative, entry):
    target = root / safe_relative(relative)
    if os.path.lexists(target):
        if target.is_dir() and not target.is_symlink():
            raise RuntimeError(f"refusing to replace directory: {relative}")
        target.unlink()
    if entry is None:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    data = (snapshot_dir / "objects" / entry["sha256"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise RuntimeError(f"corrupt snapshot object: {relative}")
    if entry["type"] == "file":
        target.write_bytes(data)
        target.chmod(int(entry["mode"], 8))
    elif entry["type"] == "symlink":
        target.symlink_to(os.fsdecode(data))
    else:
        raise RuntimeError(f"unsupported snapshot entry: {relative}")


def restore(snapshot_dir):
    pre = load_manifest(snapshot_dir, "pre")
    post = load_manifest(snapshot_dir, "post")
    try:
        delta = json.loads((snapshot_dir / "delta.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid delegate delta: {error}") from error

    expected = classify(pre["files"], post["files"])
    keys = ("created", "modified", "deleted", "mode_changed", "delegate_paths")
    try:
        recorded = tuple(delta[key] for key in keys)
    except (KeyError, TypeError) as error:
        raise RuntimeError(f"invalid delegate delta: {error}") from error
    if recorded != expected:
        raise RuntimeError("delegate delta does not match snapshots; refusing restoration")

    capture(snapshot_dir, "current", quiet=True)
    current = load_manifest(snapshot_dir, "current")
    if current["root"] != post["root"] or current["files"] != post["files"]:
        raise RuntimeError("worktree changed after post snapshot; refusing restoration")

    root = Path(pre["root"])
    for relative in delta["delegate_paths"]:
        restore_entry(snapshot_dir, root, relative, pre["files"].get(relative))

    capture(snapshot_dir, "restored", quiet=True)
    restored = load_manifest(snapshot_dir, "restored")
    if restored["files"] != pre["files"]:
        raise RuntimeError("restored state does not match pre-dispatch snapshot")
    print("delegate delta restored")


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "capture":
        capture(Path(sys.argv[2]).resolve(), sys.argv[3])
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "inspect":
        allowed = []
        arguments = sys.argv[3:]
        while arguments:
            if len(arguments) < 2 or arguments[0] != "--allowed":
                raise RuntimeError("inspect accepts repeated --allowed PATH arguments")
            allowed.append(arguments[1])
            arguments = arguments[2:]
        inspect(Path(sys.argv[2]).resolve(), allowed)
        return
    if len(sys.argv) == 3 and sys.argv[1] == "restore":
        restore(Path(sys.argv[2]).resolve())
        return
    raise SystemExit("usage: router_state.py capture SNAPSHOT_DIR LABEL | inspect SNAPSHOT_DIR [--allowed PATH]... | restore SNAPSHOT_DIR")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"snapshot failed: {error}", file=sys.stderr)
        raise SystemExit(1)
