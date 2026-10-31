# Resource baseline and acceptance budgets

Independent resource review, 2026-10-31. Baseline is commit `7931509b0bc3bacab385337231850bb372fb48d0`, version 1.4.6. Production source was read through `git show 7931509:...`, so concurrent refactor edits do not contaminate this inventory. No builds, device access, traffic, or runtime measurements were performed for this review.

## Measured build baseline

Source: `/Users/eliransapir/Downloads/GRGDO1-Investigation-2026-10-31/final-1.4.6-build.log`, lines 85–106 and 207–228. Artifact provenance: `/Users/eliransapir/Downloads/GRGDO1-1.4.6/build.json`. These are ordinary builds with INFO logging, HTTP lifecycle support, and diagnostics disabled. Platform 55.03.312, Arduino 3.3.12, ESP-IDF 5.5.5+b774170ff46, HomeSpan `e891a284d580f01c5a4c408c447535f344112633`.

| Metric | Rev2 `ratgdo_esp32dev` | Rev1 `ratgdo_esp32dev_rev1` |
|---|---:|---:|
| PlatformIO static RAM | 73,392 B | 73,392 B |
| IDF DRAM report | 73,389 B / 124,580 B | 73,389 B / 124,580 B |
| IRAM | 99,411 B / 131,072 B | 99,411 B / 131,072 B |
| PlatformIO flash | 1,798,972 B / 2,031,616 B | 1,799,364 B / 2,031,616 B |
| Firmware file, manifest | 1,859,760 B | 1,860,240 B |

Keep these different accounting methods separate. Firmware file length includes image overhead absent from the PlatformIO flash figure. The RAM figure excludes startup heap allocations and dynamically allocated task stacks. Neither 22.4% reported RAM use nor the remaining link-time DRAM proves available byte-addressable heap during Wi-Fi traffic.

Read-only `xtensa-esp32-elf-nm -S -C` on the preserved Rev1 ELF confirms: HTTP owner array 416 B, SSE array 928 B, request bookkeeping 384 B, write scratch 512 B, and settings defaults 1,392 B. These are storage symbols, not complete subsystem costs. RTC crash and reboot rings are 3,584 B each in RTC memory. A `status_json` symbol of 4 B is a pointer, not its allocation.

## Allocation and execution inventory

| Owner/path | Bound visible in source | Cost and unresolved accounting |
|---|---|---|
| HomeSpan poll task | One task, `autoPoll(16384, 1, 0)` | 16,384 B requested stack plus task control block. Actual high-water mark unknown; do not shrink from declaration alone. |
| Arduino loop / SDK services | Framework configured loop 8,192 B; timer task 8,192 B; TCP/IP task 4,096 B | Configuration observed in installed ESP32 dio_qspi sdkconfig. Event, Wi-Fi, IDF timer, FreeRTOS timer and system tasks also consume resources. Complete live task list and creation-time allocation totals remain unmeasured. |
| Diagnostic observer/emitter | Opt-in only: two 4,096 B static stacks; two one-entry static queues | Plus task/queue control blocks, snapshots and counters. Absent from ordinary baseline. Never compare diagnostic and ordinary heap without accounting for this overhead. |
| Command transmitter | One queue of 16 `PacketAction` entries | Baseline target queue structure 92 B plus 704 B payload, before allocator overhead; setup failure/repeated setup must be covered. Batch capacity check exists. |
| HomeKit services | Each service instance has a 10-entry `GDOEvent` queue | Seven constructor sites, with motion/occupancy/light classes instantiated for multiple optional accessories. Cost scales with enabled instances, not seven queues total. Preserved ELF DWARF gives 8 B per event and 92 B queue structure, or 172 B requested per instance before allocator overhead. Queue metadata and HomeSpan accessory/characteristic allocations add cost. |
| Logger | Startup heap ring 16,384 B plus line scratch 256 B | At least 16,640 B payload, plus logger object and recursive mutex. RTC rings are separate. Crash summary allocates `sizeof(esp_core_dump_summary_t)` transiently. |
| Shared status JSON | Startup heap allocation 3,072 B on ESP32; 2,048 B on ESP8266 | One buffer serialized by JSON mutex on ESP32. Failure must disable users safely. Moving it to stack is not a saving. |
| Configuration | Heap copy of 1,392 B defaults plus per-string buffers | Defaults remain resident as well as runtime copy. NVS getters allocate variable-sized temporary strings. Validate every failure path and length before accepting allocation reduction. |
| HTTP response lifecycle | Two static owner entries; one reusable `tcpip_callback_msg` allocated at setup | Borrowed flash/generated/log data, shared 512 B scratch. SDK client wrappers, receive buffers, netconns, PCBs, TCP segments and pbufs are additional. Two owners do not imply only two HTTP-related PCBs. |
| SSE | Eight slots; variable-sized UUID `String`; client wrapper per slot | Active, retiring and replacement connections must count together. UUID input is copied from request; fixed slot count does not by itself bound retained string capacity. No complete aggregate payload budget established. |
| Request bookkeeping | Eight entries, 2,000 ms expiry | This is handler bookkeeping, not a bound on SDK socket allocation, backlog, pending handshakes or retained TCP queues. |
| SoftAP Wi-Fi output | 1,024 B text allocation plus escaped-SSID allocation during rendered list; another 1,024 B text allocation on setSSID | Temporary allocations coexist with scan result storage and SDK response/parser buffers. Incremental HTTP mode has separate scan-output ownership; review cancellation and restart lifecycles. |
| Stable GPIO timers | Up to three dry-contact `esp_timer` handles created once; LED and laser each have one timer | SDK allocation sizes unmeasured. These are reused, not created per pulse. Do not count commented Sec 1 Ticker code. ESP8266 uses different Ticker paths. |
| Other transient allocation | Authentication heap `String`, request parsing/arguments/headers, `toString`, `std::to_string`, URI maps, service creation, NVS strings | Hidden SDK and library allocations matter even when application has no explicit malloc. Count construction, steady state, disconnect and teardown separately. |

The installed SDK configuration sets 16 sockets, 16 active TCP PCBs and a default TCP send buffer of 5,744 B. Eight SSE streams could therefore expose up to 45,952 B of nominal TCP payload capacity before ordinary HTTP and HomeKit traffic, metadata or receive queues. This is a capacity calculation, not measured simultaneous retention. TCP limits, socket limits and per-PCB limits do not establish a safe shared heap budget. HomeSpan accepts clients into a dynamic list (`HomeSpan.cpp` around line 255); application admission must account for it as well as HTTP. A missing SDK resource can prevent graceful rejection after accepting another peer.

The current 4,096 B broad-free-heap reboot threshold is emergency behavior, not an operating headroom guarantee or evidence of recovery. It does not measure largest eligible block or distinguish memory capabilities.

## Required acceptance budgets

These are proposed gates, not claims that baseline already meets them. Compare identical compiler, feature flags, enabled accessories, workload and preserved artifacts. Obtain hardware authorization before traffic or flashing.

1. Ordinary Rev1/Rev2 builds must not exceed their measured static RAM, IRAM or flash baselines above. Every exception needs a measured byte delta, a demonstrated correctness need, and the cheaper alternatives considered. No new task, full payload buffer, timer-per-event or queue by default.
2. New callback, timer, logger and panic paths must perform zero application heap allocations. Count SDK allocations separately; zero explicit malloc is insufficient. Fail-allocation tests must show rejection and cleanup without secondary allocation or logging recursion.
3. Keep HTTP ownership at two entries and SSE at eight supported slots unless a reviewed compatibility decision changes them. Define one total budget across active, retiring, replacement, handshake and ordinary response resources. All full-capacity paths must reject before allocating another application owner or body copy. Inventory SDK receive buffers and HomeKit request limits before approving a numerical total.
4. Initial target for aggregate HTTP/SSE queued payload is at most 16 KiB, enforced before writes with measured SDK metadata overhead added separately. This is a proposed pressure-control target, not the existing bound. If preserving eight active streams requires more, document measured peak costs and preserve the heap reserve below. Do not add another full buffer to enforce it.
5. For capability-specific internal byte-addressable heap, provisionally require at least 16 KiB free and an 8 KiB largest block at every sampled peak. Once the largest required single allocation and concurrent allocation burst are measured, raise these floors to at least twice those requirements. Track DMA/internal-only allocations separately where used. Sampled floors cannot establish unobserved instantaneous minima; allocation hooks and peak counters are also required.
6. After 100 repeated connect/fail/disconnect cycles per failure scenario, allow 60 seconds to quiesce. Require zero application-owned retired connections, pending bodies, scan leases or queued jobs; active SDK connection counts must return to the matched idle distribution. Free eligible heap and largest block must return within 1 KiB of a matched warmed baseline and show no downward trend. TIME_WAIT must follow the pinned SDK expiry behavior; zero instantaneous TIME_WAIT is not required. Repeat in sustained operation; this finite test alone does not prove recovery.
7. All affected task stack low-water marks must be at least 1,024 B under worst-case tested paths and never below matched baseline without an explicit review. Reducing the 16 KiB poll stack requires measured worst-case usage including pairing, JSON, logging, error and OTA paths, with at least 25% measured margin and the 1 KiB floor. Record units as bytes for this ESP-IDF port.
8. Proposed latency gates: application critical sections and TCP/IP callbacks under 1 ms; ordinary service-loop gap below 50 ms; no allocation/rejection/disconnect path may block a service loop over 100 ms. Measure worst case and distribution with instrumentation overhead recorded. Hardware protocol timing may require tighter limits; these figures cannot override it. Record CPU idle percentage and callback/request rate, and reject a sustained CPU increase above 5 percentage points without a correctness justification.

## Major corrections to prioritize

1. Bound resources before SDK work: cover HomeKit parsing/handshakes, HTTP argument/body lengths, UUID storage and all retained TCP payload. Slot counts alone leave hidden resource pressure. Eliminate duplicate body/frame construction before adding caches or worker tasks.
2. Coalesce replaceable HomeKit state notifications into existing service state where protocol ordering permits. Ten-entry queues per accessory retain repeated updates and allocate queue metadata repeatedly. Preserve nonreplaceable transitions and cross-task ownership; measure before claiming bytes saved.
3. Audit retained `String` capacity and configuration duplication. Bound externally supplied lengths before copying; release ownership on every disconnect and failed setup. Prefer borrowing immutable storage or transferring existing ownership over another scratch area.
4. Measure poll-task headroom before considering stack reduction. Its 16 KiB is a large explicit reservation, but changing it without adversarial stack evidence risks corruption. Keep this as a measured follow-up, not an assumed saving.
5. Keep existing reused GPIO timer and borrowed HTTP/SSE buffer approaches. Replacing them with per-event allocations, logger queues, full response buffers or extra periodic scans would increase pressure. Reduce duplicate network announcements and synchronous formatting only when traffic/allocation traces identify repeated work.

Runtime free heap, largest block, fragmentation, stack headroom, CPU load, allocation frequency and worst-case latency remain unknown in this review. No runtime saving, hardware recovery or leak-free soak is claimed.


## Current independent resource review

Scope: actuator commit `321a2eb`, HomeKit commit `bd61d3c` and the notification critical-section adapter commit `cabd742`. These changes are candidates. This review ran no PlatformIO builds, hardware operations or traffic.

### Target layout evidence and current costs

Read-only DWARF extraction from the preserved Rev1 ELF establishes `StaticQueue_t` 92 B, `GDOEvent` 8 B and `PacketAction` 44 B. The pinned FreeRTOS header guarantees that StaticQueue_t matches the genuine private queue layout. Each removed ten-entry optional HomeKit queue therefore removes 172 B of requested structure/payload capacity before heap metadata; the retained sixteen-entry command queue requests 796 B. These are target accounting measurements, not observed runtime recovery.

| Change | Current storage/work | Assessment |
|---|---|---|
| Optional notification mailboxes | Nine 32-bit boolean words 36 B; seven request words 28 B; DHT pair 8 B; round-robin cursor 4 B; polling flag and task-owner publication about 8 B including alignment | About 84 B new metadata before final linker placement. Optional QueueHandle_t members are removed; motion/occupancy add a byte enum. Exact class deltas need target output. |
| Notification guard adapter | One 8 B global portMUX; compile assertion and IDF 5.5 version guard; fixed operations per critical section, longest reads seven request words | About 92 B total metadata with above estimate. This replaces the unsupported lock-free atomic mailbox assumption. No added task, queue or mutex allocation. Spinlock contention and wall-time bound remain unmeasured. |
| Optional queue removal | 172 B requested per enabled instance; permanent door queue retained | Savings scale with enabled instances. For N enabled optional instances, queue request reduction is 172 * N B before metadata, offset by about 92 B static metadata and final class deltas. The DHT queue was allocated but unused. Do not claim a universal eight-queue saving. |
| Actuator owners | Two 20 B ControlIntent records replace four flags; three readiness/reservation/debt flags | About 39 B net persistent growth before linker padding, guarded by owner-size assertion. No new task/queue/timer/full buffer. PacketAction remains 44 B by assertion. |
| Command queue lifecycle | Reuses existing queue; setup drains at most 16 stale entries; dry-contact avoids allocating unused serial queue | Serial queue capacity/cost unchanged. Dry-contact avoids 796 B requested capacity when no earlier session created it; this is conditional allocation avoidance, not measured released heap. |
| Command admission stack | Two 44 B packets plus 20 B rollback state = 108 B explicit objects, plus PacketData/scalars/compiler frames | Baseline light/lock paths had about 76 B Packet/PacketAction explicit objects. Increased transient peak needs target stack evidence; no high-water claim. |

The static-metadata increases are justified provisionally by complete command ownership and stable notification lifetimes, with reduced dynamic queue requests as the offset. This is an exception to the strict no-static-growth gate, not proof that the integrated binary meets its complete resource budgets. Final build sizes must report the actual static/IRAM/flash delta separately; do not hide static growth in a broad heap-saving estimate.

### Lifecycle, contention and hidden costs

The current mailbox adapter uses short port critical sections with no allocation, I/O, callbacks or nested mailbox operations. It removes CAS retry loops from task-context publication. A spinlock can still wait for another core; measure contention/interrupt latency before claiming a worst-case duration. Native mutex-backed tests do not establish ESP32 spinlock behavior. Remaining polling/owner atomics and the SDK shared pause still need target behavior verification.

Recreated services call beginObservation to discard historical pulse latches while retaining current state. Pulses published after that boundary can be delivered as detected then cleared; repeated pulses merge while polling stalls. This bounds retained state and avoids stale disabled-service detections. It intentionally coalesces repeated pulse events; confirm that supported HomeKit automation behavior permits this. One pending service group is processed per Arduino loop in round-robin order. A vehicle group can still mutate several accessories and call SDK database/announcement work, so one group is not a proven time budget.

HomeSpan setValFinish appends notifications to its existing vector; checking happens in its poll after service loops. Moving optional writes to that owner removes producer-side SDK mutation but does not remove vector allocations or retained capacity. Unpaired behavior and enable/disable churn must be included in peak measurements. Test queue-allocation reduction independently of SDK accessory/characteristic allocations, which remain.

Actuator owner-state methods use the existing command lock. Whole receive-handler locks from the earlier draft are absent. Admission holds that lock for check/admit/commit; process_send_queue now covers session-safe peek/write/pop. Serial writes already ran under this command lock before the change; new setup/queue bookkeeping must still be checked for blocking and lock inversion. Reusing a reserved queue slot lowers ordinary admission capacity to 15 while a TTC release is owed. All producers must honor the reservation. The submitted native regression covers two held transactions, full-queue cancellation, transient producer collision and release retention after terminal collisions; actual UART timing remains unverified.

### Remaining resource gates

No new source-level resource blocker was identified in the reviewed final candidate layouts, subject to the adapter checks and tests passing. Integration/release remains blocked on target sizes, per-task stack headroom, capability-specific peak heap/largest block, SDK queue retention, latency/CPU measurements and sustained recovery defined above. Native tests and compile assertions cannot establish runtime headroom or hardware recovery. Preserve matched binaries/ELFs and compare identical feature configurations.

Logger network/serial I/O under its mutex remains an open major issue outside this batch. Deferred delivery or compact records would change export, panic, suppression and sink ownership semantics; no record-format design or implementation is approved by this review. A future correction must keep the existing ring capacity, avoid another full buffer/task/queue, preserve panic/export evidence, and measure sink blocking rather than equating a byte budget with a time budget.
