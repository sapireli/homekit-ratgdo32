# Major resource refactor handoff

## Preserved work

The pre-refactor baseline is commit `7931509b0bc3bacab385337231850bb372fb48d0`.

- Branch `preserve/1.4.6-before-resource-refactor` is pushed to origin at that exact commit.
- Branch `integrate-mother-main` and the separate integration worktree remain at the tested 1.4.6 candidate. Do not advance that branch for this refactor.
- Release tag `v1.4.6` and its regular Rev1/Rev2 binaries, symbols, checksums, and build records remain unchanged: https://github.com/sapireli/homekit-ratgdo32/releases/tag/v1.4.6
- Exact local release artifacts: `/Users/eliransapir/Downloads/GRGDO1-1.4.6`.
- Prior audit, PR map, passive logs, source archives, and goal notes: `/Users/eliransapir/Downloads/GRGDO1-Investigation-2026-10-31/AUDIT-RESULTS.md` and `GOAL.md` in that directory.
- Existing Gelidus PR21 and scoped upstream/Gelidus/SDK PRs cover the prior work. They are a separate review/testing track; do not replace their code with this larger refactor.
- Main worktree's untracked `.serena/` and original `resource_refactor.md` belong to the existing workspace and remain untouched.

## Current branch and scope

Branch: `refactor/resource-ownership`.
Worktree: `/Users/eliransapir/code/homekit-ratgdo32-refactor`.
Guide: tracked `resource_refactor.md`, copied without modifying the user's original.

Prioritize major deadlocks, resource exhaustion, unsafe resource lifetimes, actuator errors, and measured reductions in peak consumption. Preserve hardware/protocol behavior and configuration compatibility. This is not a wholesale rewrite or a file-organization exercise.

Before production changes, establish the inventory and budgets under `docs/refactor/`. Parallel reviewers cover ownership/lock ordering, resource costs, and actuator correctness. The coordinator chooses changes and obtains independent correctness and resource review after each implementation.

## Evidence boundary

The 1.4.6 baseline passes 46 host tests, both board builds, UART safety checks, and CI. Those results are preserved baseline evidence, not validation of this new branch.

The installed 1.4.5 passive capture had no reset or failed poll over 1h46m of status samples. The new 1.4.6 candidate was unflashed at the last handoff. Neither fact establishes extended recovery or the complete original freeze cause.

HTTP resource exhaustion is a confirmed mechanism with a candidate fix. Earlier post-power-cycle symptoms, relief after re-pairing/reflashing, and outbound HomeSpan SDK write/close retirement remain investigation boundaries. Do not assume they have one cause.

## Tooling and validation

Use `rtk` for shell commands. Working PlatformIO executable: `/tmp/ratgdo-pio-upgrade-venv/bin/pio` (stock Core6.2.0). The ordinary penv previously reported6.2.0-post.1 and failed the platform version requirement. Verify the executable before building.

Both supported builds are `ratgdo_esp32dev_rev1` and `ratgdo_esp32dev` (Rev2). Platform55.03.312 uses Arduino3.3.12 and ESP-IDF5.5.5. Only one PlatformIO build may run at a time.

Hardware/runtime budgets require byte-addressable heap, largest free block, task headroom, latency, and connection/payload evidence. Broad free-heap totals and target builds alone cannot supply those measurements. Record unavailable measurements as unavailable; do not manufacture savings.

Do not operate or flash the live device under this refactor without authorization for the proposed test.
