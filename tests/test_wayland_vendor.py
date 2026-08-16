import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WaylandVendorTests(unittest.TestCase):
    def test_protocol_inputs_match_manifest(self):
        manifest = json.loads((ROOT / "third_party" / "manifest.json").read_text())

        for filename, expected_hash in manifest["protocols"].items():
            with self.subTest(filename=filename):
                payload = (ROOT / "third_party" / "protocols" / filename).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_hash)

    def test_bundle_has_patched_extension_and_generated_protocols(self):
        site = ROOT / ".vendor" / "pywayland" / "cp313-cp313-linux_x86_64"
        extension_path = (
            site / "pywayland" / "_ffi.cpython-313-x86_64-linux-gnu.so"
        )
        self.assertTrue(extension_path.is_file())
        extension = extension_path.read_bytes()
        self.assertIn(b"wl_display_cancel_read", extension)
        self.assertIn(b"$ORIGIN/../pywayland.libs", extension)
        ffi_stub = (site / "pywayland" / "_ffi" / "lib.pyi").read_text()
        self.assertIn("def wl_display_cancel_read", ffi_stub)
        expected_protocols = {
            "wayland.py",
            "virtual_keyboard_unstable_v1.py",
            "wlr_foreign_toplevel_management_unstable_v1.py",
            "wlr_virtual_pointer_unstable_v1.py",
        }
        actual_protocols = {
            path.name for path in (site / "pywayland" / "protocol").glob("*.py")
        }
        self.assertEqual(actual_protocols, expected_protocols)
        manifest = json.loads((ROOT / "third_party" / "manifest.json").read_text())
        for module, expected_hash in manifest["generated_protocols"].items():
            with self.subTest(generated_module=module):
                payload = (site / "pywayland" / "protocol" / module).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_hash)

    def test_bundle_provenance_and_private_libraries(self):
        site = ROOT / ".vendor" / "pywayland" / "cp313-cp313-linux_x86_64"
        manifest_path = ROOT / "third_party" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())

        self.assertEqual(
            (site / "VENDOR.json").read_bytes(), manifest_path.read_bytes()
        )
        self.assertFalse(any(site.glob("*.dist-info")))
        self.assertFalse((site / "pywayland" / "ffi_build.py").exists())
        for library in manifest["bundle"]["private_libraries"]:
            with self.subTest(library=library):
                self.assertTrue((site / "pywayland.libs" / library).is_file())

        server = (
            site
            / "pywayland.libs"
            / "libwayland-server-2d5f7739.so.0.26.0"
        ).read_bytes()
        self.assertIn(b"GLIBC_2.34", server)


if __name__ == "__main__":
    unittest.main()
