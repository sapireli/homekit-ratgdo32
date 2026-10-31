@/Users/eliransapir/.codex/RTK.md

This branch is the separate major resource-ownership refactor. Read resource_refactor.md and REFACTOR-HANDOFF.md before changing firmware.

- Start from the preserved 1.4.6 baseline; do not modify integrate-mother-main, its existing PRs, or release tags as part of this refactor.
- Work only on significant operational reliability defects or measured resource improvements. Moving files, renaming APIs, and broad cleanup alone do not qualify.
- Establish ownership/context inventory and comparable resource measurements before production changes. Require independent correctness and resource-budget review.
- Use separate commits for coherent fixes. Coordinate edits and run only one PlatformIO build at a time because SDK packages are shared globally.
- Do not flash hardware, move the door, change device configuration, or run live stress traffic without explicit authorization for the concrete test.
- Keep source findings, host test results, and hardware evidence distinct. The complete field-freeze cause remains open.
- Preserve tested binaries with their exact matching ELFs and source/checksum records before rebuilding.
- Use the installed no-ai-slop skill for prose under the user's writing instructions.
