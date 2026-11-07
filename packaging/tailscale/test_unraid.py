import hashlib
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile
import unraid


def fixture():
    files = {name: b"synthetic source" for name in unraid.REQUIRED}
    files["package.json"] = b'{"name":"artcraft-studio"}'
    files["services.json"] = json.dumps({"apps": [{"id": app, "name": app, "container": "old-host-container"}
        for app, _, _ in unraid.SPECS if app != "vectorcraft"]}).encode()
    files["compose.yaml"] = b'name: artcraft-dashboard\nservices:\n  studio:\n    build: .\n    image: artcraft-dashboard-local:1.0.0\n'
    return files


class UnraidDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="unraid-dashboard-test-")
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def archive(self, extra=None):
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as bundle:
            for name, data in fixture().items():
                bundle.writestr("artcraft-dashboard/" + name, data)
            if extra:
                member, data = extra
                if isinstance(member, str):
                    raw_name = member
                    member = zipfile.ZipInfo(raw_name)
                    member.filename = raw_name
                bundle.writestr(member, data)
        target = self.root / "bundle.zip"
        target.write_bytes(content.getvalue())
        return target, hashlib.sha256(content.getvalue()).hexdigest()

    def test_corridantower_has_seven_unique_correct_links_and_containers(self):
        config = unraid.settings_for(json.loads(fixture()["services.json"]), "CorridanTower.example.ts.net.", "CorridanTower")
        self.assertEqual(config["publicUrl"], "https://corridantower.example.ts.net:7443")
        self.assertEqual(config["hostName"], "CorridanTower")
        self.assertEqual(len(config["apps"]), 7)
        self.assertNotIn("old-host", json.dumps(config))
        for app in config["apps"]:
            self.assertEqual(app["container"], app["id"] + "-tailnet-web-1")
            self.assertEqual(app["version"], unraid.RELEASES[app["id"]][0])
        specs = {app: (https, local) for app, https, local in unraid.SPECS}
        self.assertEqual(specs["vectorcraft"], (12443, 18769))
        self.assertEqual(specs["filmcraft"], (13443, 18771))
        all_specs = unraid.SPECS + (unraid.DASHBOARD,)
        self.assertEqual(len({item[1] for item in all_specs}), 8)
        self.assertEqual(len({item[2] for item in all_specs}), 8)

    def test_other_host_is_generated_and_invalid_input_rejected(self):
        template = json.loads(fixture()["services.json"])
        config = unraid.settings_for(template, "another.example.ts.net", "Another host")
        self.assertEqual(config["allowedHosts"][0], "another.example.ts.net:7443")
        for dns in ("https://example.ts.net", "example.ts.net:1234", "localhost", "../example.ts.net"):
            with self.assertRaises(RuntimeError):
                unraid.settings_for(template, dns, "host")

    def test_bundle_hash_is_checked_before_reading_source(self):
        archive, digest = self.archive()
        self.assertEqual(set(unraid.read_bundle(archive, digest)), set(fixture()))
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            unraid.read_bundle(archive, "0" * 64)

    def test_unsafe_archive_members_and_symlinks_rejected(self):
        for name in ("artcraft-dashboard/../../escape", "/artcraft-dashboard/absolute", "artcraft-dashboard/dir/../escape", "artcraft-dashboard/a\\escape", "artcraft-dashboard/.env"):
            archive, digest = self.archive((name, "bad"))
            with self.assertRaises(RuntimeError):
                unraid.read_bundle(archive, digest)
        member = zipfile.ZipInfo("artcraft-dashboard/link")
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive, digest = self.archive((member, "../../escape"))
        with self.assertRaises(RuntimeError):
            unraid.read_bundle(archive, digest)
        self.assertFalse((self.root / "escape").exists())

    def test_repeat_install_preserves_previous_compose_and_state(self):
        root = self.root / "dashboard"
        compose = unraid.prepare_dashboard(root, fixture(), "corridantower.example.ts.net", "CorridanTower", "998")
        first = compose.read_text()
        (root / "activity-placeholder").write_text("keep this")
        unraid.prepare_dashboard(root, fixture(), "corridantower.example.ts.net", "CorridanTower", "0")
        self.assertEqual((root / "compose.previous.yaml").read_text(), first)
        self.assertEqual((root / "activity-placeholder").read_text(), "keep this")
        self.assertEqual((root / ".env").read_text(), "DOCKER_SOCKET_GID=0\n")
        self.assertEqual(len(list((root / "releases").iterdir())), 2)
        self.assertIn("build: ./releases/", compose.read_text())

    def test_unmanaged_compose_and_non_numeric_gid_are_rejected(self):
        root = self.root / "dashboard"
        root.mkdir()
        (root / "compose.yaml").write_text("do not replace")
        with self.assertRaisesRegex(RuntimeError, "unmanaged"):
            unraid.prepare_dashboard(root, fixture(), "host.example.ts.net", "host", "0")
        self.assertEqual((root / "compose.yaml").read_text(), "do not replace")
        with self.assertRaisesRegex(RuntimeError, "numeric"):
            unraid.prepare_dashboard(root, fixture(), "host.example.ts.net", "host", "0\nBAD=1")


if __name__ == "__main__":
    unittest.main()
