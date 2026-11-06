from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile
import install


class InstallerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="craft-installer-test-")
        self.root = Path(self.temp.name).resolve()
        # All test cleanup stays inside the operating system's temporary directory.
        self.assertTrue(self.root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.addCleanup(self.temp.cleanup)

    def config(self, handler=None):
        return {"TCP": {"8443": {"HTTPS": True}}, "Web": {
            "host.example.ts.net:8443": {"Handlers": handler or {"/": {"Proxy": "http://127.0.0.1:18765"}}}}}

    def validate(self, config):
        install.validate_endpoint(config, "host.example.ts.net", 8443, "http://127.0.0.1:18765")

    def test_existing_other_service_is_preserved(self):
        config = self.config({"/": {"Proxy": "http://127.0.0.1:9000"}})
        with self.assertRaisesRegex(RuntimeError, "another service"):
            self.validate(config)
        self.assertEqual(config["Web"]["host.example.ts.net:8443"]["Handlers"]["/"]["Proxy"], "http://127.0.0.1:9000")

    def test_additional_paths_and_raw_tcp_are_not_overwritten(self):
        config = self.config()
        config["Web"]["host.example.ts.net:8443"]["Handlers"]["/other"] = {"Proxy": "http://127.0.0.1:9000"}
        with self.assertRaises(RuntimeError):
            self.validate(config)
        with self.assertRaises(RuntimeError):
            self.validate({"TCP": {"8443": {"TCPForward": "127.0.0.1:9000"}}})

    def test_private_endpoint_can_be_reused_but_funnel_cannot(self):
        self.validate({})
        self.validate(self.config())
        config = self.config()
        config["AllowFunnel"] = {"host.example.ts.net:8443": True}
        with self.assertRaisesRegex(RuntimeError, "Funnel"):
            self.validate(config)

    def archive(self, extra=None):
        archive = self.root / "release.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("pdfcraft-web-0.18.2/index.html", "original synthetic page")
            bundle.writestr("pdfcraft-web-0.18.2/app.wasm", b"\0asm")
            if extra:
                bundle.writestr(*extra)
        return archive

    def test_traversal_rejected_before_any_files_are_extracted(self):
        archive = self.archive(("pdfcraft-web-0.18.2/../../outside.txt", "no"))
        site = self.root / "site"
        site.mkdir()
        with self.assertRaises(RuntimeError):
            install.extract_release(archive, site, "pdfcraft-web-0.18.2")
        self.assertEqual(list(site.iterdir()), [])
        self.assertFalse((self.root / "outside.txt").exists())

    def test_symlinks_and_oversize_archives_are_rejected(self):
        member = zipfile.ZipInfo("pdfcraft-web-0.18.2/link")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        site = self.root / "site"
        site.mkdir()
        with self.assertRaises(RuntimeError):
            install.extract_release(self.archive((member, "../../outside")), site, "pdfcraft-web-0.18.2")
        with mock.patch.object(install, "MAX_EXPANDED", 1), self.assertRaises(RuntimeError):
            install.extract_release(self.archive(), site, "pdfcraft-web-0.18.2")

    def test_safe_nested_release_extracts_and_checksum_mismatch_stops(self):
        site = self.root / "site"
        site.mkdir()
        archive = self.archive(("pdfcraft-web-0.18.2/fonts/license.txt", "synthetic license fixture"))
        install.extract_release(archive, site, "pdfcraft-web-0.18.2")
        self.assertEqual((site / "fonts/license.txt").read_text(), "synthetic license fixture")
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            install.download(archive.as_uri(), self.root / "copy.zip", "0" * 64)


if __name__ == "__main__":
    unittest.main()
