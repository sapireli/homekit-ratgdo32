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

## Implemented candidate and return instructions

The first refactor batch changes ownership rather than file organization:

- Optional HomeKit services consume lifetime-stable mailboxes. Producers no longer dereference deletable services; optional notification queues and their recreation leak are removed. Database changes run from the Arduino owner under the existing HomeSpan pause, outside application locks. The permanent door FIFO remains.
- Serial queue initialization is checked and reused. Dry-contact startup skips its unused serial queue. Light/lock admission owns the essential press/release pair, pending intent expires or retires on failure, and TTC reserves capacity for its eventual release. No new task, queue, timer, or full payload buffer was added.
- Independent review corrected stale room occupancy after recreation and kept allocation-error output off console pins already transferred to the Rev1 sensor. Target compilation replaced an unsupported lock-free atomic assumption with an explicit eight-byte, SDK-version-checked critical-section adapter.

See `docs/refactor/ownership-review.md`, `actuator-review.md`, `resource-baseline.md`, and `verification.md` for evidence and limits. Production changes through `bd50ecd`, including publication adapters `eb8f2d8`/`3b56ba8`, have independent correctness and resource reviews. The new branch is a candidate, not a release or proof of field recovery.

To resume the previous work, use `/Users/eliransapir/code/homekit-ratgdo32-integration` on `integrate-mother-main`, or the pushed `preserve/1.4.6-before-resource-refactor` branch. Both retain `7931509`. Do not reset this refactor branch onto that baseline or replace the old PR with it.

Opposite light/lock requests now cancel unwritten work or defer until fresh typed feedback after transmission. Required Releases survive cancellation, expiry, and collision. Accepted lock targets use a latest-value mailbox; pure publishers keep later notifications from rewriting command state. Rejected feedback queries are counted and reported outside command ownership.

## Major work still open

1. Logger serial/network output still runs under its mutex. A deferred design must preserve recursion suppression, serial pin ownership, panic/export evidence, and sink eligibility without another log copy, task, or queue. No replacement is approved yet.
2. UART shutdown is electrically inactive but is not proof that an already transmitted protocol-button press was released at the opener. Do not add speculative teardown writes.
3. Aggregate SDK TCP retention, capability-specific heap/largest block, task stack headroom, critical/loop latency, and sustained recovery remain unmeasured. Native regressions and builds do not satisfy those runtime gates.

The original complete freeze cause remains under investigation. Existing post-power-cycle symptoms and improvement after re-pairing/reflashing are not explained by these source mechanisms alone. Keep this refactor separate from the established testing/release track until its remaining validation is complete.

## Exact tested build

Both clean local builds are from `b42a938540236eff4f1ef3d5acc0afaea666d4fd`. Matched BIN/ELF pairs, maps, dependency records, logs and checksum manifests are under `/Users/eliransapir/Downloads/GRGDO1-Resource-Refactor/b42a938540236eff4f1ef3d5acc0afaea666d4fd`. Embedded ELF hashes were verified against the saved ELFs. Later commits only enable this branch's existing CI workflow and record this provenance; they do not change production source. Local validation passes; no GitHub CI result or hardware recovery is claimed here.
