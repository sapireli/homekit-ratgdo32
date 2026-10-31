# Resource-constrained firmware reliability refactor

Refactor this firmware to prevent recurring classes of crashes, deadlocks, resource exhaustion, and unintended actuator behavior while reducing resource consumption wherever possible. This hardware is near its limits.

Prioritize significant reliability problems. Preserve supported hardware, protocol behavior, configuration compatibility, and existing features. Do not perform a wholesale rewrite.

Work in small, reviewable changes. Use parallel agents for independent investigation and adversarial review, with one agent coordinating integration. Assign independent correctness and resource-budget reviewers.

## Establish evidence and resource budgets

Before changing code:

- Inventory all tasks, callbacks, locks, shared buffers, socket owners, allocations, timers, and actuator-writing paths.
- Map execution contexts, resource ownership, and lock ordering.
- Reproduce known failures using the production implementation wherever possible.
- Separate observed failures, demonstrated mechanisms, and unproven hypotheses. An allocation warning identifies a failed allocation, not necessarily the cause of exhaustion.
- Establish comparable baselines for static RAM and flash usage; free byte-addressable heap, largest free block, and fragmentation; per-task stack headroom; CPU utilization and worst-case loop/callback latency; active connections and queued payload; allocation frequency; and network traffic during normal and degraded operation.
- Define explicit resource budgets and operating headroom. Account for memory capabilities separately; broad free-heap totals can conceal exhaustion of memory a subsystem requires.

## Enforce architectural invariants

### Explicit ownership and complete lifecycles

Every resource must have an explicit owner and a complete lifecycle. No socket, timer, buffer, or callback may outlive its owner. Cleanup must be idempotent and safe against stale callbacks, descriptor reuse, and concurrent retirement. Releasing an application handle must not silently abandon queued SDK resources.

### Bounded critical work

Logging, TCP/IP callbacks, timers, interrupts, and panic handling must perform bounded work. Avoid blocking network I/O, unbounded waits, and dynamic allocation in these paths. Use SDK APIs only from execution contexts where they are safe.

### Enforceable lock ordering

Make lock ordering explicit. Prevent recursive entry into subsystem APIs and cross-task lock inversion. Do not hold application locks across potentially blocking I/O. Error reporting must respect the same ordering rules as normal operation.

### Bounded resource consumption and recovery

Bound queues, connections, retained payload, retry work, and per-task stack usage. Define admission control and recovery when each limit is reached. Include all relevant paths, such as streaming connections, ordinary responses, failed handshakes, replacement clients, and reconnects.

### Failure handling under exhaustion

Reporting an error must not require the resource that just failed. Failure paths must release resources without causing another failure. Distinguish graceful rejection, transient resource pressure, persistent retention, and corruption. Preserve enough evidence to tell them apart.

### Explicit actuator transitions

Actuator writes require an explicit, valid command transition. Startup, shutdown, reconnects, stale events, and recovery must not create unintended movement. Preserve electrical safety during initialization failures and panic handling.

Prefer APIs and types that enforce these rules over comments and conventions. Keep platform-specific internals behind narrow, version-checked adapters.

## Reduce resource use

Prefer removing allocations, copies, duplicated state, unnecessary tasks, timers, polling, and redundant network announcements. Reuse existing storage when ownership and synchronization make that safe.

Do not introduce another full buffer, task, queue, connection registry, or periodic scan as the default solution. First consider eliminating the work, transferring existing ownership, or simplifying the lifecycle.

Temporary allocations still count. Avoid allocation churn in frequently executed paths. Do not move large buffers from heap to stack and call that a memory reduction.

Resource reduction must preserve correctness:

- Never share scratch storage across concurrent callers without protection.
- Never trade a smaller allocation for blocking, deadlock, data corruption, unintended movement, or loss of required functionality.
- Never hide exhaustion by suppressing its detection or reporting.
- Account for hidden allocations and retained resources inside SDK calls.

Reject resource regressions unless a demonstrated correctness requirement makes them necessary. Document the added cost, why cheaper alternatives fail, and any offsetting savings. Do not claim savings without measurements.

## Repeat this verification loop for each change

1. Identify one violated invariant and its concrete failure mechanism.
2. Add a regression that demonstrates the failure before the change. Verify that it fails for the intended reason.
3. Implement the smallest architectural correction, considering lower-cost alternatives first.
4. Verify normal behavior and inject allocation failures, partial writes, disconnected peers, missing acknowledgements, full queues, stale callbacks, and adverse task interleavings. Check that failure handling itself remains safe under exhaustion.
5. Run sanitizers and target builds for every affected platform. Use actual SDK implementations when behavior depends on SDK semantics. Document limits of native tests, mocks, and platform substitutes.
6. Compare resource use before and after under identical normal, peak-load, and recovery scenarios. Account for persistent and transient costs, instrumentation overhead, and the measurement method.
7. Have an independent correctness reviewer challenge ownership, concurrency, actuator behavior, and the claimed evidence.
8. Have an independent resource-budget reviewer challenge added storage and work, including hidden SDK allocations and worst-case resource retention.
9. Fix findings and repeat until correctness checks pass and resource costs meet the budget or have a justified exception.
10. Integrate, rerun system checks, and update the appropriate PR. Keep shared fixes in their upstream project and board-specific changes in the hardware fork. Clearly identify dependencies between PRs.

Do not substitute source-pattern tests or mocks for production behavior when the failure depends on SDK semantics. Do not treat a passing build as proof of runtime reliability.

## Verify the integrated system

- Run sustained stress and recovery tests, including repeated failure cycles and representative network traffic.
- Verify resources return to a stable baseline after clients disconnect, queues fill, allocation attempts fail, and services recover.
- Check worst-case latency, peak resource usage, and operating headroom alongside idle measurements.
- Validate on affected hardware before claiming the device issue is resolved. Distinguish a candidate fix from demonstrated hardware recovery.
- Do not operate the garage door or flash hardware without authorization.
- Preserve each tested binary and its matching ELF before rebuilding. Record the source commit, dependencies, build configuration, checksums, instrumentation, and test results. Never decode a crash using an unmatched ELF.
- Keep PR descriptions and release notes concise, factual, and current. Separate measured results from remaining hypotheses and validation gaps.

Never declare success because the device rebooted, a timeout hid the problem, a feature was disabled, or a short soak stayed quiet.

Completion requires demonstrated recovery, preserved functionality, passing verification, resource consumption within explicit budgets, and accounting for unresolved failure modes. Stable recovery and reduced peak resource usage matter more than a lower idle-memory number.
