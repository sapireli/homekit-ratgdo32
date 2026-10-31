"""Offline staging checks and a host check of the exact allocation guard."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stage_webserver", ROOT / "scripts/stage_webserver.py")
override = importlib.util.module_from_spec(spec)
spec.loader.exec_module(override)


class WebServerOverrideTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.framework = self.root / "framework"
        self.source = self.framework / "libraries/WebServer"
        (self.source / "src").mkdir(parents=True)
        (self.framework / "package.json").write_text('{"version":"3.3.12"}')
        (self.source / "library.properties").write_text("name=WebServer\n")
        (self.source / "src/Parsing.cpp").write_bytes(b"#include <new>\n" + override.ORIGINAL)
        self.manifest = self.root / "hashes.json"
        self.manifest.write_text(json.dumps(override.hashes(self.source)))
        self.destination = self.root / "staged/RatgdoWebServer"

    def stage(self):
        return override.stage(self.framework, self.destination, self.manifest)

    def test_only_guard_and_metadata_change_and_repeat_is_cached(self):
        original = override.hashes(self.source)
        self.stage()
        self.assertEqual(override.hashes(self.source), original)
        parsed = self.destination / "src/Parsing.cpp"
        self.assertEqual(parsed.read_bytes(), b"#include <new>\n" + override.PATCHED)
        before = parsed.stat().st_mtime_ns
        self.stage()
        self.assertEqual(parsed.stat().st_mtime_ns, before)
        self.assertEqual(json.loads((self.destination / "library.json").read_text())["name"], "RatgdoWebServer")

    def test_modified_source_rejected_even_with_valid_cached_copy(self):
        self.stage()
        (self.source / "src/Parsing.cpp").write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "source hash mismatch"):
            self.stage()

    def test_changed_version_rejected(self):
        (self.framework / "package.json").write_text('{"version":"3.3.13"}')
        with self.assertRaisesRegex(RuntimeError, "requires Arduino 3.3.12"):
            self.stage()

    def test_modified_staged_copy_is_rebuilt(self):
        self.stage()
        (self.destination / "src/Parsing.cpp").write_bytes(b"changed")
        (self.destination / "unexpected.cpp").write_bytes(b"unexpected")
        self.stage()
        self.assertEqual((self.destination / "src/Parsing.cpp").read_bytes(), b"#include <new>\n" + override.PATCHED)
        self.assertFalse((self.destination / "unexpected.cpp").exists())

    def test_patch_context_must_be_unique(self):
        (self.source / "src/Parsing.cpp").write_bytes(b"#include <new>\n" + override.ORIGINAL * 2)
        self.manifest.write_text(json.dumps(override.hashes(self.source)))
        with self.assertRaisesRegex(RuntimeError, "context changed"):
            self.stage()

    def test_success_and_null_allocation(self):
        compiler = shutil.which("c++")
        if not compiler:
            self.skipTest("host C++ compiler unavailable")
        # Compile the exact staged fragment with an ordinary allocator stub.
        # This checks both outcomes without network or an embedded target.
        self.stage()
        fragment = (self.destination / "src/Parsing.cpp").read_text().replace("#include <new>\n", "")
        program = r'''
#include <cassert>
#include <cstdlib>
#include <memory>
#include <new>
bool failAllocation = false;
struct HTTPUpload {
  int status = 0;
  static void *operator new(std::size_t size, const std::nothrow_t &) noexcept {
    return failAllocation ? nullptr : std::malloc(size);
  }
  static void operator delete(void *p) noexcept { std::free(p); }
};
struct Parser {
  std::unique_ptr<HTTPUpload> _currentUpload;
  bool aborted = false;
  bool _parseFormUploadAborted() { aborted = true; return false; }
  bool parse() {
''' + fragment + r'''
    _currentUpload->status = 1;
    return true;
  }
};
int main() {
  Parser success;
  assert(success.parse());
  assert(success._currentUpload->status == 1 && !success.aborted);
  failAllocation = true;
  Parser failure;
  assert(!failure.parse());
  assert(!failure._currentUpload && failure.aborted);
}
'''
        source = self.root / "allocation.cpp"
        source.write_text(program)
        executable = self.root / "allocation"
        subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
