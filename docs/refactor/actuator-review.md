# Actuator ownership review

Current candidate includes serial ownership correction `321a2eb`, Room publication correction `bd62187`, and console-report correction `10a93bf`. Evidence below comes from production-source inspection and native execution of extracted production functions with SDK boundaries stubbed. This review performed no PlatformIO build, device command, network demonstration, flashing, or hardware measurement. It does not establish device recovery.

## Corrected mechanisms

| Failure mechanism | Current correction | Evidence |
| --- | --- | --- |
| Startup ignored queue allocation failure and could use a null queue. Dry-contact allocated an unused protocol queue; reinitialization could replace its owner. | Serial setup checks `txQueuePrepare()` before UART initialization. Helpers reject unavailable storage. One firmware-lifetime queue owner is retained, and preparation removes retired entries before enabling a new serial session. Dry-contact skips allocation. | Actual queue helpers exercised with failed creation, unavailable storage, repeated initialization, retired work, and a busy producer mutex. |
| Light/lock pending flags were committed before admission, permanently suppressing retries after rejection or terminal failure. | Two bounded generation owners replace four flags. Accepted admission commits intent; failed replacement restores the previously accepted owner. Terminal pre-write failure or the three-second deadline retires intent. Stale queued generations cannot issue another press. | Baseline actual `set_light` regression failed when retrying after queue-full rejection. Corrected functions pass rejection/retry, missing acknowledgement, terminal failure, and concurrent duplicate-call cases. |
| Sec+1 light/lock could admit Press without Release or discard Release after exhausted retries. TTC held light presses lacked reserved eventual release. | Ordinary essential pairs use atomic sequence admission. Once Press reaches UART, Release survives intent expiry and repeated collision. TTC preserves held presses and reserves one existing slot until completion/cancellation enqueues Release. Explicit light commands remain available during warning. | Actual control, cancellation, dispatcher, and Sec+1 UART functions exercised with one/two free slots, full queues, transient producer contention, missing/mismatched echoes, repeated collisions, and two queued TTC transactions. |
| Room service removal cleared logical occupancy but retained a true lifetime-stable mailbox, allowing recreation to remain occupied indefinitely. | Removal calls `notify_homekit_room_occupancy(false)`, clearing logical state, timeout, and publication together. | Regression failed on `bd61d3c` at recreated occupancy being true while logical state was false. All eight notification regressions pass with the correction under AddressSanitizer/UndefinedBehaviorSanitizer. |
| Queue-failure ROM output bypassed console pin ownership/suppression during a later setup retry. | Failure reporting requires `serialConsole.isReady()` and unsuppressed output. It never initializes the console, enters the logger, or allocates. GDO TX quiescing remains unconditional. | Initial non-GDOLIB setup precedes Rev1 I2C pin transfer. Baseline `321a2eb` regression failed because suppressed output still wrote; corrected ESP32/ESP8266 report helpers make no ROM writes after suppression or console disable. |

Earlier door-pair, delayed TTC/partial/encoder cancellation, state-truthfulness, and physical pulse-timer changes are existing baseline work, not new findings here.

## Resource accounting

- `PacketAction` remains 44 bytes, enforced by a candidate size assertion. The preserved ESP32 Rev1 layout has a 92-byte queue header, so its unchanged 16-entry queue requests `92 + 16 × 44 = 796` bytes before allocator overhead. Dry-contact avoids this request. This layout comparison is not a measured heap saving and does not establish ESP8266 queue overhead or fragmentation.
- Each `ControlIntent` is asserted as 20 bytes. Two owners replace four one-byte flags: 40 bytes replacing four bytes, plus readiness, reserved-release, and held-release indicators. Expected net metadata growth is 39 bytes before linker alignment, conditional on supported-target boolean/atomic-boolean layout. Target symbol verification remains required.
- Ordinary control admission has an 88-byte packet pair and 20-byte rollback snapshot: 108 bytes of payload temporaries, plus `PacketData`, scalars, lock objects, ABI frames, and called-function stack. Queue preparation temporarily holds one 44-byte packet. These are source-layout counts, not measured stack headroom.
- No new task, timer, queue, mutex, connection registry, or full payload buffer was added by the serial correction. Existing command ownership now spans setup retirement and complete queue peek/write/pop. TTC reserves one of the existing slots, leaving at most 15 for ordinary work while holding a light press.

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

## Major open item: opposite light/lock intent arbitration

`set_light` and `set_lock` can reject a request matching observed state while an opposite accepted command remains queued. Example: observed Off → queued On accepted → explicit Off ignored → queued On executes. This pre-existing behavior remains outside `321a2eb`.

Proposed bounded semantics, not implemented:

1. Before the old command reaches UART, a target equal to observed state cancels its generation without another toggle. Admit a replacement requiring actuation completely before retiring the previously accepted intent.
2. After Press reaches UART, retain essential Release and coalesce one deferred desired boolean. After Release succeeds, wait for fresh validated status, including unchanged status. Compare observed state with the deferred target and admit at most one command if they differ. Sec+2 single-write commands enter this feedback stage after successful transmission.
3. Retire deferred intent at the existing three-second deadline if feedback or queue admission remains unavailable, and report observed state. Never infer a second Sec+1 toggle from unconfirmed actuation. An owed Release survives reconciliation failure.

An explicit stage byte and deferred target byte fit the current 20-byte owner layout, subject to its target assertion. Existing comms-loop reconciliation needs no additional task, queue, or timer. Required regressions include opposite requests before write, after write/before Release, fresh unchanged feedback, missing feedback, exhausted admission, terminal failure, and stale generations.

## Open shutdown protocol semantics

Shutdown closes command admission, cancels delayed/accepted intent, resets release metadata, and quiesces physical TX before driver teardown. It does **not** guarantee the opener receives every queued protocol Release. Setup discards retired-session packets rather than replaying them after restart. Current tests establish source-level retirement and inactive GPIO behavior; they do not establish the opener's interpretation of Press interrupted by shutdown or panic.

Ordinary shutdown may need a bounded protocol-release transition if hardware/protocol evidence requires it. Panic safety must remain independent of driver locks, queue availability, and successful transmission. Do not extend timeout/collision release-retention claims to shutdown without that evidence.

## Verification status

Focused host regressions pass for control ownership, actual Sec+1 wire dispatch, door lifecycle/atomic admission/deadlines/target deduplication, TTC cancellation, dry-contact outputs, partial opening, encoder correction, reverse-after-stop, built-in TTC, and HomeKit explicit actuator writes. Relevant C++ fixtures use AddressSanitizer/UndefinedBehaviorSanitizer. Queue/UART/clock substitutes exercise production transitions; they do not reproduce FreeRTOS scheduling, electrical behavior, peer response, SDK memory capabilities, or HomeSpan network polling.

Independent target builds, SDK fault injection, runtime resource comparisons, latency/stack measurements, and authorized hardware validation remain required. Root-coordinated build results must identify their final source commit separately from this source/native review.
