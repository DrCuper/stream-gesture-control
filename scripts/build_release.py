"""Validate and package the standalone HTML; uses only Python's standard library and Node."""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path


VERSION_RE = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
REVISION_META_RE = re.compile(
    r'''<meta\s+name=["']gesturefx-source-revision["'][^>]*>\s*''', re.I
)
VERSION_META_RE = re.compile(
    r'''<meta\s+name=["']gesturefx-version["']\s+content=["']([^"']+)["'][^>]*>''', re.I
)


def validate(root):
    version = (root / "version.txt").read_text(encoding="utf-8").strip()
    if not VERSION_RE.fullmatch(version):
        raise ValueError("version.txt must contain a stable version such as 1.1.0")
    manifest = json.loads((root / ".release-please-manifest.json").read_text(encoding="utf-8"))
    if manifest.get(".") != version:
        raise ValueError("version.txt and .release-please-manifest.json disagree")
    raw = (root / "gesture-fx.html").read_bytes()
    source = raw.decode("utf-8")
    head_end = re.search(r"</head\s*>", source, re.I)
    if not head_end or not re.match(r"\s*<!doctype html>", source, re.I):
        raise ValueError("Invalid HTML document")
    head = source[:head_end.start()]
    if VERSION_META_RE.findall(head) != [version]:
        raise ValueError("HTML must have exactly one gesturefx-version matching version.txt")
    if len(REVISION_META_RE.findall(head)) != 1:
        raise ValueError("HTML must have exactly one gesturefx-source-revision")
    modules = re.findall(r'<script type="module">([\s\S]*?)</script>', source)
    if len(modules) != 1:
        raise ValueError("Expected one inline JavaScript module")
    with tempfile.TemporaryDirectory() as directory:
        module = Path(directory) / "gesture-fx.mjs"
        module.write_text(modules[0], encoding="utf-8")
        subprocess.run(["node", "--check", str(module)], check=True, capture_output=True, text=True)
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(r"^##\s+\[?" + re.escape(version) + r"(?:\]|[ \t]|$)", changelog, re.M):
        raise ValueError("CHANGELOG.md has no entry for " + version)
    return version, raw, source, head_end.start()


def build(root, tag, output):
    version, raw, source, head_end = validate(root)
    if tag != "v" + version:
        raise ValueError("Release tag must match version.txt: v" + version)
    if output.resolve() == root.resolve():
        raise ValueError("Build output must not overwrite the source directory")
    # GitHub Contents API returns the Git blob ID, not the commit SHA.
    revision = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    head = REVISION_META_RE.sub("", source[:head_end])
    packaged = head + f'<meta name="gesturefx-source-revision" content="{revision}">\n' + source[head_end:]
    files = {"gesture-fx.html": packaged.encode("utf-8")}
    for name in ("CHANGELOG.md", "README.md"):
        files[name] = (root / name).read_bytes()
    checksums = "".join(hashlib.sha256(data).hexdigest() + "  " + name + "\n" for name, data in sorted(files.items()))
    files["SHA256SUMS"] = checksums.encode("ascii")
    output.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (output / name).write_bytes(data)
    return revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Validate without producing files")
    mode.add_argument("--tag", help="Stable release tag, for example v1.1.0")
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        if args.check:
            version, *_ = validate(root)
            print("Validated Gesture FX " + version)
        else:
            revision = build(root, args.tag, args.output)
            print(f"Packaged {args.tag} ({revision[:8]}) in {args.output}")
    except subprocess.CalledProcessError as error:
        parser.exit(1, "JavaScript syntax check failed:\n" + error.stderr)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Release validation failed: {error}\n")


if __name__ == "__main__":
    main()
