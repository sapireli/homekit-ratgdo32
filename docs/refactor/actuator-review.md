# Actuator ownership review

Current candidate includes serial ownership correction `321a2eb`, Room publication correction `bd62187`, console-report correction `10a93bf`, and opposite-intent arbitration `bd50ecd` (with pure HomeKit publication dependencies `eb8f2d8`/`3b56ba8`). Evidence below comes from production-source inspection and native execution of extracted production functions with SDK boundaries stubbed. This review performed no PlatformIO build, device command, network demonstration, flashing, or hardware measurement. It does not establish device recovery.

## Corrected mechanisms

| Failure mechanism | Current correction | Evidence |
| --- | --- | --- |
| Startup ignored queue allocation failure and could use a null queue. Dry-contact allocated an unused protocol queue; reinitialization could replace its owner. | Serial setup checks `txQueuePrepare()` before UART initialization. Helpers reject unavailable storage. One firmware-lifetime queue owner is retained, and preparation removes retired entries before enabling a new serial session. Dry-contact skips allocation. | Actual queue helpers exercised with failed creation, unavailable storage, repeated initialization, retired work, and a busy producer mutex. |
| Light/lock pending flags were committed before admission, permanently suppressing retries after rejection or terminal failure. | Two bounded generation owners replace four flags. Accepted admission commits intent; failed replacement restores the previously accepted owner. Terminal pre-write failure or the three-second deadline retires intent. Stale queued generations cannot issue another press. | Baseline actual `set_light` regression failed when retrying after queue-full rejection. Corrected functions pass rejection/retry, missing acknowledgement, terminal failure, and concurrent duplicate-call cases. |
| Sec+1 light/lock could admit Press without Release or discard Release after exhausted retries. TTC held light presses lacked reserved eventual release. | Ordinary essential pairs use atomic sequence admission. Once Press reaches UART, Release survives intent expiry and repeated collision. TTC preserves held presses and reserves one existing slot until completion/cancellation enqueues Release. Explicit light commands remain available during warning. | Actual control, cancellation, dispatcher, and Sec+1 UART functions exercised with one/two free slots, full queues, transient producer contention, missing/mismatched echoes, repeated collisions, and two queued TTC transactions. |
| Room service removal cleared logical occupancy but retained a true lifetime-stable mailbox, allowing recreation to remain occupied indefinitely. | Removal calls `notify_homekit_room_occupancy(false)`, clearing logical state, timeout, and publication together. | Regression failed on `bd61d3c` at recreated occupancy being true while logical state was false. All eight notification regressions pass with the correction under AddressSanitizer/UndefinedBehaviorSanitizer. |
| Queue-failure ROM output bypassed console pin ownership/suppression during a later setup retry. | Failure reporting requires `serialConsole.isReady()` and unsuppressed output. It never initializes the console, enters the logger, or allocates. GDO TX quiescing remains unconditional. | Initial non-GDOLIB setup precedes Rev1 I2C pin transfer. Baseline `321a2eb` regression failed because suppressed output still wrote; corrected ESP32/ESP8266 report helpers make no ROM writes after suppression or console disable. |
| Opposite light/lock requests matching observed state could be ignored while an accepted opposite command remained queued. Changed-only feedback and command echoes could not establish safe reconciliation. | Cancel unwritten opposite generations without a toggle. After a write, coalesce one latest desired target, retain essential Release, and reconcile only after validated typed status processed after completion. Current-state assignment and owner feedback share a short guard; pure HomeKit publishers prevent later publication from rewriting state. | Baseline `5f3c5ce` fails the queued opposite-request assertion. Production admission/dispatch, UART-boundary markers, Sec+1 status case, Sec+2 echo cases, and typed status helpers pass the arbitration regression under sanitizers. |

Earlier door-pair, delayed TTC/partial/encoder cancellation, state-truthfulness, and physical pulse-timer changes are existing baseline work, not new findings here.

## Resource accounting

- `PacketAction` remains 44 bytes, enforced by a candidate size assertion. The preserved ESP32 Rev1 layout has a 92-byte queue header, so its unchanged 16-entry queue requests `92 + 16 × 44 = 796` bytes before allocator overhead. Dry-contact avoids this request. This layout comparison is not a measured heap saving and does not establish ESP8266 queue overhead or fragmentation.
- Each `ControlIntent` is asserted as 20 bytes. Two owners replace four one-byte flags: 40 bytes replacing four bytes, plus readiness, reserved-release, and held-release indicators. The arbitration adds a four-byte saturating rejected-query counter. Expected net metadata growth across both serial corrections is 43 bytes before linker alignment, conditional on supported-target boolean/atomic-boolean layout. Target symbol verification remains required.
- Ordinary admission has an 88-byte packet pair and 20-byte rollback snapshot. Deferred reconciliation adds a 20-byte outer snapshot, and feedback-query admission nests one 44-byte packet: 172 bytes of explicit payload temporaries along that call chain, plus `PacketData`, scalars, lock objects, ABI frames, and other called-function stack. Previous Sec+2 `send_get_status` already nested a 44-byte packet action and separate 28-byte packet. Queue preparation holds one 44-byte packet. These are source-layout counts, not measured compiler frames or stack headroom.
- Each accepted normal/deferred control request attempts at most one feedback query, including forced Sec+2 TTC flashes. There is no periodic query retry. Query admission performs no logging or I/O; an aggregate rejected-query count is reported from the existing main loop after releasing command ownership. Native regression verifies the report runs with command-lock depth zero. No new task, timer, queue, mutex, connection registry, or full payload buffer was added by the serial corrections. Existing command ownership now spans setup retirement and complete queue peek/write/pop. TTC reserves one of the existing slots, leaving at most 15 for ordinary work while holding a light press.

## Execution and lifecycle inventory

This inventory comes from source inspection; task latency and stack measurements are absent.

| Path/resource | Context and boundary |
| --- | --- |
| Serial actuator writes | Arduino comms loop consumes the queue. `process_send_queue` owns peek/write/pop under `FunctionDelayLock`; `process_PacketAction` checks generation and records the UART boundary. |
| Admission | Web, HomeSpan, hardwired, encoder, and delayed controls enter command APIs. Existing command ownership serializes check/admit/cancel and release metadata; the producer mutex protects queue reservations. |
| Protocol queue | One bounded firmware-lifetime owner, allocated only for serial protocols. Setup removes retired-session packets before enabling serial. |
| TTC, partial opening, completion checks, encoder correction | Existing comms/encoder loop dispatches polled work. Cancellation and final acceptance share command ownership. |
| ESP32 dry-contact outputs | Command caller asserts outputs; stable `ESP_TIMER_TASK` callbacks only release GPIO. Admission/shutdown use the existing command lock and pulse spinlock. |
| ESP8266 dry-contact outputs | Static Ticker callbacks release GPIO. This review did not execute the ESP8266 SDK callback lifecycle. |
| Status outputs/wall-panel relay | Receive paths update status GPIO; Sec+1 transmission disconnects/reconnects the wall-panel relay. These remain physical writers. |
| GDOLIB builds | Library APIs/callbacks own UART/task behavior. The serial correction is excluded; dependency deinitialization and callback semantics need separate validation. |
| Reported state | Protocol, encoder, command, HomeKit, and web paths share `garage_door`. Command ownership is not a general snapshot lock; this review does not claim every state access is synchronized. |

## Implemented opposite-intent semantics

Before a command reaches UART, an opposite request matching the observed state cancels its generation without another toggle. Replacements requiring actuation use complete admission before retiring the previously accepted owner. A handled request can therefore mean cancellation or accepted bounded deferral; it does not claim movement or a confirmed physical state.

After a write, the owner retains essential Release and coalesces one latest desired boolean. Successful Sec+1 Release, or completed Sec+2 single write, opens the feedback boundary. Only validated typed Status feedback processed afterward authorizes reconciliation. Unchanged status counts; command/echo packets and feedback before completion do not. Reconciliation compares the owner's captured sample with the latest target, not an arbitrary later inferred global value. Failed queue admission restores the original feedback/deadline snapshot.

The existing three-second deadline retires desired/deferred work without discarding an owed Release. Lock target publication returns to the last observed current state when no intent remains. An unresolved Sec+1 write still requires feedback: a later explicit request starts a new bounded feedback-only wait and attempts a query; fresh unchanged feedback can recover it. It does not leave an old pending flag suppressing identical retries forever. A new explicit absolute Sec+2 request after expiry can be admitted safely without inferring a toggle. This exception does not authorize speculative deferred reconciliation.

The owner remains 20 bytes: four 32-bit counters/timestamps, requested and deferred signed bytes, a stage byte, and one captured-observation byte. Root-coordinated target size/stack verification remains necessary.

Regressions cover queued opposite cancellation, post-write/pre-release requests, mandatory Release under full queues and repeated collision, latest deferred target, failed admission and retry, expiry followed by fresh unchanged feedback, missing feedback, Sec+2 completion and explicit absolute retry, terminal failure/stale generations, typed channel isolation, actual command echoes, invalid repeated Sec+1 status bytes, and a request between status assignment and client publication. Existing Sec+1 TTC status suppression remains unchanged: a deferred request can expire safely while the warning suppresses light/lock feedback. No new warning/control semantics were introduced.

Current status fields retain existing last-observed/inferred compatibility semantics; this change does not add a general freshness/unknown indicator to light state. Missing peer feedback remains an unresolved physical outcome, not confirmation that a command failed or succeeded.

## Open shutdown protocol semantics

Shutdown closes command admission, cancels delayed/accepted intent, resets release metadata, and quiesces physical TX before driver teardown. It does **not** guarantee the opener receives every queued protocol Release. Setup discards retired-session packets rather than replaying them after restart. Current tests establish source-level retirement and inactive GPIO behavior; they do not establish the opener's interpretation of Press interrupted by shutdown or panic.

Ordinary shutdown may need a bounded protocol-release transition if hardware/protocol evidence requires it. Panic safety must remain independent of driver locks, queue availability, and successful transmission. Do not extend timeout/collision release-retention claims to shutdown without that evidence.

## Verification status

Focused host regressions pass for opposite arbitration, feedback-query rejection/reporting, control ownership, actual Sec+1 wire dispatch, door lifecycle/atomic admission/deadlines/target deduplication, TTC cancellation, dry-contact outputs, partial opening, encoder correction, reverse-after-stop, built-in TTC, and HomeKit explicit actuator writes. Relevant C++ fixtures use AddressSanitizer/UndefinedBehaviorSanitizer. Queue/UART/clock substitutes exercise production transitions; they do not reproduce FreeRTOS scheduling, electrical behavior, peer response, SDK memory capabilities, or HomeSpan network polling.

Independent target builds, SDK fault injection, runtime resource comparisons, latency/stack measurements, and authorized hardware validation remain required. Root-coordinated build results must identify their final source commit separately from this source/native review.
