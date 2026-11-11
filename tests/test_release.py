import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.build_release import build, validate


ROOT = Path(__file__).resolve().parents[1]


class ReleasePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # Exercise the real standalone application, including its inline module.
        for name in ("gesture-fx.html", "version.txt", ".release-please-manifest.json", "CHANGELOG.md", "README.md"):
            (self.root / name).write_bytes((ROOT / name).read_bytes())
        self.version = (self.root / "version.txt").read_text().strip()
        self.output = self.root / "dist"

    def edit(self, name, old, new):
        path = self.root / name
        path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

    def test_package_preserves_application_and_records_github_blob_id(self):
        raw = (self.root / "gesture-fx.html").read_bytes()
        revision = build(self.root, "v" + self.version, self.output)
        git_blob = subprocess.check_output(
            ["git", "hash-object", "--stdin"], input=raw, text=False
        ).decode().strip()
        self.assertEqual(revision, git_blob)
        packaged = (self.output / "gesture-fx.html").read_text(encoding="utf-8")
        self.assertIn(f'content="{revision}"', packaged.split("</head>")[0])
        self.assertIn(f'name="gesturefx-version" content="{self.version}"', packaged)
        # Packaging must not alter the module or non-ASCII text inside it.
        self.assertEqual(packaged.split('<script type="module">')[1], raw.decode().split('<script type="module">')[1])
        self.assertEqual((self.root / "gesture-fx.html").read_bytes(), raw)
        self.assertEqual((self.output / "README.md").read_bytes(), (self.root / "README.md").read_bytes())

    def test_checksums_cover_every_distributed_file(self):
        build(self.root, "v" + self.version, self.output)
        entries = (self.output / "SHA256SUMS").read_text().splitlines()
        self.assertEqual(len(entries), 3)
        for entry in entries:
            digest, name = entry.split("  ")
            self.assertEqual(digest, hashlib.sha256((self.output / name).read_bytes()).hexdigest())
        self.assertEqual(set(self.output.iterdir()), {self.output / name for name in ("gesture-fx.html", "README.md", "CHANGELOG.md", "SHA256SUMS")})

    def test_repeated_build_is_identical(self):
        build(self.root, "v" + self.version, self.output)
        first = {path.name: path.read_bytes() for path in self.output.iterdir()}
        build(self.root, "v" + self.version, self.output)
        self.assertEqual(first, {path.name: path.read_bytes() for path in self.output.iterdir()})

    def test_rejects_mismatched_or_unsafe_tag_without_output(self):
        for tag in ("v999.0.0", self.version, "v01.0.0", "v1.0.0-beta.1", "../../main"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                build(self.root, tag, self.output)
        self.assertFalse(self.output.exists())

    def test_refuses_to_overwrite_source(self):
        raw = (self.root / "gesture-fx.html").read_bytes()
        with self.assertRaises(ValueError):
            build(self.root, "v" + self.version, self.root)
        self.assertEqual((self.root / "gesture-fx.html").read_bytes(), raw)

    def test_manifest_and_html_versions_must_agree(self):
        manifest = self.root / ".release-please-manifest.json"
        manifest.write_text(json.dumps({".": "999.0.0"}))
        with self.assertRaisesRegex(ValueError, "disagree"):
            validate(self.root)
        manifest.write_text(json.dumps({".": self.version}))
        self.edit("gesture-fx.html", f'content="{self.version}"', 'content="999.0.0"')
        with self.assertRaisesRegex(ValueError, "gesturefx-version"):
            validate(self.root)

    def test_missing_changelog_entry_blocks_release(self):
        (self.root / "CHANGELOG.md").write_text("# No release notes\n")
        with self.assertRaisesRegex(ValueError, "CHANGELOG"):
            build(self.root, "v" + self.version, self.output)
        self.assertFalse(self.output.exists())

    def test_duplicate_or_missing_revision_is_rejected(self):
        source = (self.root / "gesture-fx.html").read_text(encoding="utf-8")
        meta = re.search(r'<meta name="gesturefx-source-revision"[^>]*>', source)[0]
        for replacement in ("", meta + meta):
            (self.root / "gesture-fx.html").write_text(source.replace(meta, replacement), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "gesturefx-source-revision"):
                validate(self.root)

    def test_invalid_javascript_blocks_release(self):
        self.edit("gesture-fx.html", '<script type="module">', '<script type="module">\nconst = ;')
        with self.assertRaises(subprocess.CalledProcessError):
            build(self.root, "v" + self.version, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
