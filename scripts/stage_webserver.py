"""Stage the Arduino 3.3.12 WebServer with its upload allocation checked.

The framework package is read-only. Fail closed when its version or any library
file differs from the reviewed inputs; SDK upgrades require an explicit review.
"""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

ORIGINAL = b"            _currentUpload.reset(new HTTPUpload());\n"
PATCHED = b"""            _currentUpload.reset(new (std::nothrow) HTTPUpload());
            if (!_currentUpload) {
              return _parseFormUploadAborted();
            }
"""
LIBRARY_METADATA = {"name": "RatgdoWebServer", "version": "3.3.12", "frameworks": "arduino", "platforms": "espressif32"}


def hashes(directory):
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob("*")) if path.is_file()}


def stage(framework, destination, manifest):
    framework, destination = Path(framework), Path(destination)
    package = json.loads((framework / "package.json").read_text())
    if package.get("version") != "3.3.12":
        raise RuntimeError("WebServer override requires Arduino 3.3.12; review the override before upgrading")
    source = framework / "libraries" / "WebServer"
    expected = json.loads(Path(manifest).read_text())
    if hashes(source) != expected:
        raise RuntimeError("WebServer 3.3.12 source hash mismatch; refusing to patch an unreviewed library")
    parsing = (source / "src" / "Parsing.cpp").read_bytes()
    if parsing.count(ORIGINAL) != 1 or b"#include <new>" not in parsing:
        raise RuntimeError("WebServer upload allocation patch context changed")
    patched = parsing.replace(ORIGINAL, PATCHED)
    metadata = (json.dumps(LIBRARY_METADATA, indent=2) + "\n").encode()
    staged_hashes = dict(expected)
    staged_hashes["src/Parsing.cpp"] = hashlib.sha256(patched).hexdigest()
    staged_hashes["library.json"] = hashlib.sha256(metadata).hexdigest()
    if destination.is_dir() and hashes(destination) == staged_hashes:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="webserver-", dir=destination.parent) as temporary:
        candidate = Path(temporary) / "RatgdoWebServer"
        shutil.copytree(source, candidate)
        (candidate / "src" / "Parsing.cpp").write_bytes(patched)
        (candidate / "library.json").write_bytes(metadata)
        if hashes(candidate) != staged_hashes:
            raise RuntimeError("WebServer staging verification failed")
        if destination.exists():
            shutil.rmtree(destination)
        candidate.rename(destination)
    return destination


def configure(env):
    project = Path(env.subst("$PROJECT_DIR"))
    framework = env.PioPlatform().get_package_dir("framework-arduinoespressif32")
    stage(framework, project / ".pio/patched-libraries/RatgdoWebServer",
          project / "scripts/webserver-3.3.12.sha256.json")


if "Import" in globals():
    Import("env")
    configure(env)
