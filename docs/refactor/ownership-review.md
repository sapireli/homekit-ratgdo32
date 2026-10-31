# Ownership and execution-context review

The baseline source review used 1.4.6 commit `7931509`. The first two findings below describe that baseline and have candidate source corrections in the isolated refactor branch; they are not descriptions of the current optional-service implementation. The logger finding remains open. The current implementation and verification limits are recorded after the inventory.

Baseline source line references in the findings, inventory, and lock graph refer to `7931509`; later refactor edits move those lines. HomeSpan references use the existing pinned dependency in `/Users/eliransapir/code/homekit-ratgdo32-integration/.pio/libdeps/ratgdo_esp32dev_rev1/HomeSpan/src/`. This investigation performed source review and host regressions, with no device traffic, actuator commands, or hardware validation. The coordinating agent owns target builds and the build/resource record in `resource-baseline.md`.

## Baseline findings and current status

### 1. Baseline optional-service queue retention: corrected in candidate source

Concrete source mechanism: every `DEV_*` service constructor allocates an event queue (`src/homekit.cpp:1098,1170,1218,1240,1262,1295,1332`). None of the service declarations in `src/homekit.h:91-182` defines a destructor. Runtime configuration helpers delete optional accessories and clear the application pointer (`src/homekit.cpp:650-903`). HomeSpan `Span::deleteAccessory` (`HomeSpan.cpp:1592`) deletes the accessory; `SpanService::~SpanService` (`HomeSpan.cpp:2110`) deletes characteristics and framework registrations, but has no knowledge of the application `QueueHandle_t`.

Each disable/enable cycle therefore loses a live queue allocation. An allocation-failure consequence is also concrete: constructors do not check queue creation; service `loop()` methods call `uxQueueMessagesWaiting(event_q)` unconditionally. The producer helper's null guard at `src/homekit.cpp:1048` does not protect consumers. Exact leaked bytes and failure behavior remain unmeasured.

Current correction: remove optional-service queues entirely and publish state through lifetime-stable mailboxes. Producers no longer borrow a deletable service or queue handle. Queue-owning destructors are therefore unnecessary for optional services. The permanent garage-door FIFO remains to preserve intermediate transitions, and its consumer now checks allocation failure.

The production constructor/helper regression fails on the baseline at the retained-queue allocation assertion after 1,000 create/delete cycles and passes on the candidate. The host fixture models framework deletion; actual HomeSpan/FreeRTOS lifecycle and memory-return measurements remain target validation requirements.

### 2. Baseline optional-service lifetime race: corrected in candidate source

The web settings path calls a setting helper directly (`src/web.cpp:2384-2397`), and helpers enable/delete accessories (`src/config.cpp:476-558`). HomeSpan runs on a separate 16 KiB auto-poll task (`src/homekit.cpp:1043`). Installed HomeSpan `pollTask()` holds a unique `pollMutex` lock (`HomeSpan.cpp:185-187`); `deleteAccessory` itself does not lock. Application helpers do not use the matching pause mechanism. They mutate vectors traversed by the poll task and delete characteristics/services it may be using.

In addition, notify functions test a raw optional-service pointer and then access its queue without a lifetime guard (`src/homekit.cpp:1349-1401`). Laser expiry runs in the ESP timer task (`src/led.cpp:61-67`), calls `idle()`, then invokes `notify_homekit_laser` through `stateChangeCallback`. That producer can overlap the web task deleting `assistLaser`. Pausing HomeSpan alone would leave this timer producer race.

The unsynchronized operations and possible stale access follow from the call graph. No adverse interleaving has been reproduced on hardware; this review does not attribute a reported crash to this mechanism.

Current correction: producers use stable mailbox storage, while optional accessory creation/deletion runs from the existing Arduino owner loop under a nonblocking HomeSpan pause. The integrated ESP32 `homekit_loop()` call runs before application locks. It never mutates HomeSpan's service-loop vector from inside that traversal. Timer publication performs bounded critical work without service pointers; intermediate garage-door transitions remain in the permanent FIFO.

Do not blindly add a HomeSpan pause under JSON. HomeSpan's connection callback calls `refresh_ipv4_config()` then `notify_new_ipv4_address()` (`src/homekit.cpp:429-467`), which waits on JSON (`src/web.cpp:1109-1114`). This establishes `HomeSpan -> JSON`. A new `JSON -> HomeSpan` edge would introduce a deadlock. The SDK's `homeSpanPAUSE` is a shared lock (`HomeSpan.h:95`), so it excludes polling but permits multiple external holders; it is not an all-caller lifetime mutex.

Host regressions now cover notification/deletion overlap, nonblocking pause contention with retained requests, recreation state, and failed permanent queue allocation. These tests exercise extracted production methods with inert framework boundaries; they do not substitute for a target test using HomeSpan's actual traversal/deletion and FreeRTOS scheduling.

### 3. Open: logger retains its mutex while doing socket and UART work

`LOG::logToBuffer` holds its recursive logger lock across `Serial.print`, SSE fan-out, and syslog packet construction/transmission (`src/log.cpp:250-317`). `logToSyslog` performs many `WiFiUDP::print` calls and `beginPacket`/`endPacket` (`src/log.cpp:770-824`). This makes any task logging a possible network sender and serial waiter, including HomeSpan callbacks. The baseline optional queue-full path could also invoke logging from the ESP timer task; the candidate mailbox publication removes that particular path. `MSG_DONTWAIT` on the SSE send bounds socket-buffer admission, but does not prove the complete SDK call or `client.stop()` is bounded while other locks are held.

The existing core-held logging guard is valuable: `esp_log_hook` avoids serial setup when the TCPIP core lock is held, and `logToBuffer` uses a zero-wait logger acquisition and skips output in that context (`src/log.cpp:68-79,241-250,272-276,303`). This removes the direct `TCPIP -> logger wait -> TCPIP` cycle; do not report that already-addressed inversion as a current defect.

Major architectural candidate: append under the logger lock and let an existing main-loop owner drain bounded pending log data through existing ring cursor support. This removes external I/O from logging callers without a new task or full buffer. Handle ring overwrite visibly, account for per-subscriber delivery, and preserve syslog behavior. Do not borrow `lineBuffer` after unlocking: recursive error logging can overwrite it, and concurrent callers share it. Native timing or mocked UDP is insufficient to claim SDK boundedness; target latency and capability-specific heap measurements are needed.

## Baseline context and resource inventory

| Context | Owned work and shared resources | Boundaries |
| --- | --- | --- |
| Arduino loop | WebServer request dispatch; comms/service loops; configuration actions; JSON generation; SSE heartbeat polling | Synchronous HTTP handlers can delay comms. `activeRequests[8]` tracks handler scopes, not retained sockets or SDK queued bytes (`web.cpp:1054-1106,1658-1741`). |
| HomeSpan auto-poll | HAP sockets, accessory/service traversal, characteristic notifications, HomeKit actuator update callbacks | 16 KiB task stack; HomeSpan mutex protects framework polling only when application callers cooperate. |
| Arduino network event task | `WiFiGotIP`, IPv4 config refresh, IPv6 address string update | Calls logger/config setters and JSON notification; IPv6 buffer publication has no paired reader guard in this review. |
| ESP timer task | Stable global LED/laser callbacks; stable dry-contact pulse release | LED expiry invokes application notification. Dry-contact callback only lowers its configured pin under spinlock (`comms.cpp:190-298`), without taking FunctionDelayLock. |
| GPIO ISR | Obstruction and optional encoder capture | Must remain independent of logger, socket, blocking mutexes; actuator owner review should verify pin transitions. |
| TCPIP core | SDK networking; experimental HTTP inspect callback | Core-held logger calls are try-only and ring-only. Experimental callback does no application logging/socket methods. |
| Panic/shutdown | `quiesce_gdo_tx`, RTC crash snapshot | Panic handler dereferences logger buffers without initialization checks (`log.cpp:156-187`); boot allocations are unchecked (`log.cpp:213-222`). No runtime failure reproduced. |
| Optional diagnostics | Existing `diag-send` and `diag-observe` static tasks (`runtime_diagnostics.cpp:326-327`) | Count their stacks/storage separately from a production baseline. Do not add comparable tasks as a default fix. |

Baseline persistent buffers include the logger ring, shared logger line buffer, RTC crash/reboot buffers, global web `status_json`/`writeBuffer`, fixed SSE slots, command queue, HomeKit service queues, and optional diagnostics storage. The current candidate replaces optional HomeKit queues with the mailboxes described below; the permanent garage-door FIFO remains. A complete byte budget requires actual build symbols and SDK allocation measurements; this report makes no savings claim.

## Baseline lock graph and socket ownership

- Logger lock can precede SSE try-lock, socket/core operations, UDP operations, and serial driver locks. SSE paths can log while holding SSE, but logger broadcasts try-lock SSE, avoiding a blocking `logger -> SSE` edge. Preserve that behavior until output moves to one owner.
- JSON precedes SSE in heartbeat processing (`web.cpp:1140-1155`); JSON-held status work can log (`web.cpp:1175-1346`). Never add a blocking SSE-to-JSON path.
- HomeSpan precedes JSON via connection callback. HomeSpan callbacks also enter command `FunctionDelayLock` and logger. Configuration setter mutex covers NVS writes and warning logging, then releases before helper side effects (`config.cpp:841-951`).
- `FunctionDelayLock` is recursive and serializes command cancellation, acceptance, encoder control, and polled door callbacks (`comms.cpp:366-451`). TX queue mutex is zero-wait (`comms.cpp:119-134`). GPIO/state critical sections are kept separate from timer APIs in `DryContactPulse`. No demonstrated existing blocking lock cycle was found in this limited investigation.
- Default WebServer owns the current ordinary HTTP client. SSE subscription copies retain the streaming client (`web.cpp:850-861`); SSE lock protects aliases and slot replacement. Closing a shared `NetworkClient` alias can invalidate all aliases, so copying a client is ownership retention, not an independent socket.
- Under `RATGDO_HTTP_LIFECYCLE_EXPERIMENT`, two existing retained owners and one reusable TCPIP callback message manage ordinary response and retired SSE lifetime (`web.cpp:175-460,919-954`). Main pauses owner manipulation while the callback is pending, and callback completion uses release/acquire atomics. It accesses pinned SDK socket/netconn/PCB internals, so version checks and real SDK regressions are required. Quarantine retains resources and pauses admission intentionally; it is containment, not demonstrated recovery.

## Scope and next steps

Validate the integrated mailbox/service-mutation correction on target, then evaluate moving logger delivery to the existing loop owner. Treat HTTP queued-resource retirement as a separate SDK-dependent investigation; do not infer its correctness from application handle lifetime or replace it with another registry.

The review did not inspect every allocation in dependency cryptography, provisioning, mDNS, GDOLIB, or the Arduino SDK, and did not measure stack headroom, heap capabilities, queue retention, or worst-case execution time. These are explicit validation gaps, not evidence that a device is recovered.

## HomeKit candidate implementation

The candidate removes all optional-service FreeRTOS notification queues and their producer references to service objects. Nine fixed state mailboxes occupy 36 bytes of protected 32-bit payload; seven fixed mutation requests occupy 28 bytes. One explicit shared portMUX adds eight bytes. The startup flag, mutation-owner task handle, and round-robin index add approximately 12 bytes on ESP32, subject to target layout/link verification. DHT builds add eight bytes for independent temperature/humidity characteristic samples. There is no new task, blocking mutex, queue, connection registry, or full-size buffer. Motion/occupancy services replace their queue-handle field with a signal enum; actual class-size deltas require the target build.

The resource reviewer identified the preserved Rev1 ELF's `StaticQueue_t` as 92 bytes and `GDOEvent` as eight bytes, so a ten-event queue requests 172 bytes before allocator overhead. Removing eight live optional queues would remove 1,376 requested bytes; this is an allocation-layout comparison, not a measured heap saving. The permanent garage-door FIFO remains unchanged to preserve intermediate door/lock/obstruction notifications. Its consumer now tolerates queue allocation failure.

Light/laser mailboxes retain latest state. Detection channels retain one pending detected state followed by latest clear state; repeated detections can merge while the consumer stalls. Each recreated service starts from current state rather than replaying historical detections collected while absent. Notification consumers only call `setVal`; actuator calls remain in explicit HomeKit update callbacks. DHT readings now reach `setVal` from the HomeSpan owner rather than the web task.

Optional mutation requests return to the existing Arduino loop. `homekit_loop()` checks pending work, tries the existing HomeSpan shared pause without waiting, and processes one requested group per iteration with round-robin admission. Busy polling leaves requests pending. During OTA service suspension it avoids reacquiring the pause held across upload callbacks. The ESP32 hook is integrated at the start of the Arduino loop before other application locks (`src/ratgdo.cpp`, commit `ed7c0df`). Runtime room-occupancy creation now updates the HomeSpan database so its loop is registered.

Verification performed: eight lifecycle host regressions and the focused adapter regression pass; the optional producer/helper/consumer/drain methods are extracted from production source. The create/delete regression compiled against `7931509` fails specifically at `allocations.load()==0` after 1,000 cycles. The permanent queue-allocation failure case exercises the production garage service consumer. Tests cover publication while absent, producer/deletion overlap, current state after recreation, room occupancy reset/recreation, delayed latest state, preserved true/false detection, nonblocking deferred mutation under a busy poll lock, and suspended mutation during OTA. AddressSanitizer/UndefinedBehaviorSanitizer passed on the host notification suite; ThreadSanitizer passed on the producer/deletion overlap case of the earlier atomic candidate; the portMUX adapter itself has the separate contract-shim coverage described below. The existing explicit HomeKit actuator-write regression also passes.

The host fixture substitutes inert characteristic, allocation, and HomeSpan deletion boundaries. It models the verified SDK pause contract but does not run HomeSpan network polling or actual FreeRTOS allocation. It therefore does not establish target timing, capability-specific heap savings, HAP delivery behavior, runtime recovery, or hardware safety. The target build record belongs to the coordinating integration work; this host investigation performs no hardware actions.

### Pinned target atomic correction

The initial lock-free-word assertion failed in the real Rev1 GCC 14.2 target build. The SDK archive was inspected directly: `libnewlib.a` contains `stdatomic.c.obj`, an `s_atomic_lock`, and `__atomic_compare_exchange_4` dispatches by address to an s32c1i implementation or a global `xPortEnterCriticalTimeout(..., -1)` fallback. Host lock-free behavior therefore cannot establish target semantics.

Mailbox words now use one explicit eight-byte `portMUX_TYPE` shared by the notification adapter. The adapter accepts ESP-IDF 5.5.x and checks the spinlock layout; other versions require review. Every critical body performs fixed integer work, at most seven request-word reads, with no allocation, logging, callbacks, SDK I/O, nested mailbox calls, or CAS retry. IDF's `portENTER_CRITICAL` still waits indefinitely for the opposite core lock owner; fixed critical work does not establish a hard wait bound if the opposite core is stopped or interrupts intervene. Target latency remains unmeasured.

A focused regression compiles the production ESP32 header branch using a narrow port contract shim, runs 100,000 overlapping publications/consumptions under ASAN/UBSAN, verifies balanced nonnested entry/exit, and rejects an unreviewed IDF version. Existing eight lifecycle tests pass after the adapter change. This shim verifies application locking boundaries, not SDK spinlock execution; the root coordinates the pinned target build.
