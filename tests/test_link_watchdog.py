"""Native check of the link watchdog decision logic in src/link_watchdog.h."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cassert>
#include <cstdio>
#include "link_watchdog.h"

// Feed one full window of sessions with the given replies per session.
static LinkResult window(LinkWatch &w, unsigned replies) {
    LinkResult r{};
    for (int i = 0; i < LINK_WINDOW_CHECKS; ++i) {
        r = link_watch_step(w, LINK_PINGS_PER_CHECK, replies);
        if (i < LINK_WINDOW_CHECKS - 1) assert(!r.evaluated && r.action == LINK_NONE);
    }
    return r;
}

int main() {
    const unsigned all = LINK_PINGS_PER_CHECK;

    { // Gateway that never answers ping: never act.
        LinkWatch w;
        for (int i = 0; i < 10; ++i) assert(window(w, 0).action == LINK_NONE);
    }
    { // Healthy link, and light loss below threshold: no action.
        LinkWatch w;
        assert(window(w, all).action == LINK_NONE);
        LinkResult r = link_watch_step(w, all, all - 1); // 1 lost of 20 = 5%
        for (int i = 1; i < LINK_WINDOW_CHECKS; ++i) r = link_watch_step(w, all, all);
        assert(r.evaluated && r.lossPct == 5 && r.action == LINK_NONE);
    }
    { // Observed degradation (~45% loss): reconnect, skip own window, then reboot.
        LinkWatch w;
        assert(window(w, all).action == LINK_NONE);
        LinkResult r = window(w, all / 2); // 2 of 5 replies = 60% loss
        assert(r.action == LINK_RECONNECT && r.lossPct == 60);
        r = window(w, 0); // window spanning the reconnect is discarded
        assert(r.action == LINK_NONE && !r.evaluated);
        assert(window(w, all / 2).action == LINK_REBOOT);
    }
    { // Reconnect fixes it: recovered after enough healthy windows, then re-armed.
        LinkWatch w;
        window(w, all);
        assert(window(w, 0).action == LINK_RECONNECT);
        window(w, 0); // skipped
        for (int i = 1; i < LINK_RECOVERED_WINDOWS; ++i) assert(window(w, all).action == LINK_NONE);
        assert(window(w, all).action == LINK_RECOVERED);
        assert(window(w, 0).action == LINK_RECONNECT); // a later episode starts over
    }
    { // A bad window during recovery still escalates to reboot.
        LinkWatch w;
        window(w, all);
        assert(window(w, 0).action == LINK_RECONNECT);
        window(w, 0);
        assert(window(w, all).action == LINK_NONE);
        assert(window(w, 1).action == LINK_REBOOT);
    }
    { // Sessions that never ran (sent == 0) and bogus counts are ignored safely.
        LinkWatch w;
        assert(link_watch_step(w, 0, 0).action == LINK_NONE);
        LinkResult r{};
        for (int i = 0; i < LINK_WINDOW_CHECKS; ++i) r = link_watch_step(w, all, all + 3);
        assert(r.evaluated && r.lossPct == 0);
    }
    std::puts("ok");
}
'''


class LinkWatchdogTest(unittest.TestCase):
    def test_decisions(self):
        with tempfile.TemporaryDirectory(prefix="ratgdo-link-") as d:
            cpp, binary = Path(d) / "t.cpp", Path(d) / "t"
            cpp.write_text(HARNESS)
            subprocess.run([os.environ.get("CXX", "c++"), "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", "-I", str(ROOT / "src"),
                            str(cpp), "-o", str(binary)], check=True)
            self.assertEqual(subprocess.check_output([str(binary)], text=True).strip(), "ok")


if __name__ == "__main__":
    unittest.main()
