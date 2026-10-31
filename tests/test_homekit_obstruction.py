"""Compile the actual garage callback with inert actuator stubs."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


def callback(source):
    start = source.index("boolean DEV_GarageDoor::update()")
    end = source.index("void DEV_GarageDoor::loop()", start)
    return source[start:end]


HARNESS = r"""
#include <cassert>
#include <initializer_list>
using boolean = bool;
#define ESP_LOGD(...) ((void)0)
#define ESP_LOGI(...) ((void)0)
enum GarageDoorCurrentState { OPENING = 2, CLOSING = 3 };
int opens = 0, closes = 0, locks = 0;
struct GarageDoor { bool obstructed = false; } garage_door;
GarageDoorCurrentState open_door() { ++opens; return OPENING; }
GarageDoorCurrentState close_door() { ++closes; return CLOSING; }
void set_lock(bool) { ++locks; }
struct Config { int security = 2; int getGDOSecurityType() { return security; } };
Config config;
Config *userConfig = &config;
struct Value {
    static constexpr int OPEN = 0, CLOSED = 1, LOCK = 1;
    bool changed = false;
    int value = 0;
    bool updated() { return changed; }
    int getNewVal() { return value; }
    void setVal(int v) { value = v; }
};
struct DEV_GarageDoor {
    Value *target, *lockTarget, *obstruction, *current;
    boolean update();
};
"""

CASES = r"""
int main() {
    Value target, lock, obstruction, current;
    DEV_GarageDoor door{&target, &lock, &obstruction, &current};
    config.security = 3; // Isolate door/beam updates from lock handling.
    target.changed = true;
    for (bool blocked : {false, true}) {
        garage_door.obstructed = blocked;
        for (int desired : {Value::OPEN, Value::CLOSED}) {
            target.value = desired;
            obstruction.value = !blocked; // Force a stale characteristic.
            assert(door.update());
            assert(obstruction.value == blocked);
            assert(garage_door.obstructed == blocked);
            assert(current.value == (desired == Value::OPEN ? OPENING : CLOSING));
        }
    }
    assert(opens == 2 && closes == 2 && locks == 0);
}
"""


class HomeKitObstructionTest(unittest.TestCase):
    def test_target_write_preserves_beam_state(self):
        compiler = shutil.which("c++")
        self.assertIsNotNone(compiler)
        body = callback(Path(os.environ.get("HOMEKIT_TEST_SOURCE", "src/homekit.cpp")).read_text())
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "homekit-writes.cpp"
            binary = Path(directory) / "homekit-writes"
            source.write_text(HARNESS + body + CASES)
            subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                            str(source), "-o", str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True, timeout=5)
