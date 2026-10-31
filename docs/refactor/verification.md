# Refactor candidate verification

Baseline: `7931509`, preserved regular 1.4.6. Production changes through `bd50ecd`, including pure publication adapters `eb8f2d8`/`3b56ba8`. Both board builds use the same pinned dependencies and ordinary feature flags as the baseline, with no diagnostic tasks. No hardware was accessed or flashed.

## Checks

- Full Python suite: 61 tests passed. New cases cover service recreation, overlapping publication/retirement, failed permanent queue allocation, deferred mutation, the notification guard contract, atomic command admission, retained releases, bounded/opposite intent, typed feedback, pure publication, and disabled-console failure output.
- Four JavaScript tests and three compiled native utility binaries passed.
- Focused notification/control tests passed AddressSanitizer and UndefinedBehaviorSanitizer. The ESP32 guard regression uses a narrow SDK contract shim; it does not measure actual spinlock timing. The earlier atomic candidate's ThreadSanitizer result does not validate the replacement ESP32 guard.
- Rev1 and Rev2 target builds passed. Both panic transmitter-disconnect IRAM checks passed.
- Baseline failures were checked for the queue recreation leak, rejected command retry, stale room occupancy, and failure output after console suppression, queued opposite-command cancellation, and publication mutating state. The rejected-query regression checks that reporting runs with command-lock depth zero. The tests-only baseline compatibility follow-up also passes the current arbitration regression. Host fixtures exercise extracted production methods with SDK boundaries substituted; they do not prove physical protocol or complete HomeSpan network behavior.

## Measured link costs

| Metric | Preserved baseline | Refactor candidate | Delta |
|---|---:|---:|---:|
| Static RAM, both boards | 73,392 B | 73,520 B | +128 B |
| IRAM, both boards | 99,411 B | 99,411 B | 0 B |
| Flash, Rev1 | 1,799,364 B | 1,803,684 B | +4,320 B |
| Flash, Rev2 | 1,798,972 B | 1,803,276 B | +4,304 B |

The measured static/flash increases are an explicit budget exception for complete ownership, release retention, bounded pending state, and stable service lifetime. No extra task, full buffer, or queue offsets those costs. Removing only the queues' destructors would leave producer/deletion races; removing pending state would lose command deduplication and required release ownership.

Target queue layouts establish 172 B per removed optional queue and 796 B for the skipped dry-contact serial queue, before heap overhead. These are allocation-request reductions, conditional on enabled services/protocol. They are not measurements of live heap, fragmentation, or recovered resources. The retained command queue remains 16 entries with 44 B packets. New owner records remain 20 B each; one notification mux is 8 B.

Rev1 disassembly measures entry-frame reservations: baseline light/lock setters 80/96 B; candidate setters 160 B each, reconciliation 64 B, and feedback-query admission 80 B. The visible nested frames total 304 B before called SDK frames, register spills and other callers. This is compiler-frame evidence, not runtime stack headroom. Source-level nested payload temporaries total 172 B; that is not a net-new allocation or a complete stack total.

## Artifacts and remaining gates

Matched binaries, ELFs, maps, logs and SHA256 manifests are preserved under `/Users/eliransapir/Downloads/GRGDO1-Resource-Refactor`, grouped by exact build commit. Intermediate artifacts are labelled separately and must not be distributed as validated firmware. Final build manifests record the source/tree and dependency revisions. These artifacts are separate from the unchanged 1.4.6 release.

Heap capabilities, largest block, SDK retained payload, stack high-water marks, CPU/latency and sustained recovery still require authorized hardware measurement. Pulse coalescing, optional-service churn, pairing, full queues, protocol releases and recovery must retain supported behavior on both boards before release. Logger I/O and shutdown protocol semantics remain open in the handoff. This batch does not establish the complete cause or resolution of the field freeze.
