# Actuator correctness review

Source inspection at `2bf1da22b9f23a58d438df36f5ad0cd1730cecdf`. No device commands, builds, or production edits were performed. Findings below are demonstrated source mechanisms; electrical consequences and SDK failure behavior have not been exercised on hardware. The earlier door-pair, delayed-command cancellation, state-truthfulness, and raw pulse timer corrections are treated as existing work.

## Remaining findings

### 1. Queue allocation failure is ignored during startup

`src/comms.cpp:87-98` returns failure when mutex/queue initialization fails. `setup_comms()` ignores that result at line 965 and continues initialization. Sec+2 initialization enqueues status requests (`initialize_gdo_codes`, lines 941-945); the queue helpers then invoke FreeRTOS queue APIs with a null handle. The system also eventually sets `comms_setup_done` at line 1177. A failed allocation therefore reaches invalid SDK calls instead of leaving the transmitter unavailable.

The same queue is allocated in dry-contact mode although that mode does not consume it. Reentry into setup can overwrite an existing queue handle without retiring it; current ordinary startup has one setup call, so repeated reinitialization is a lifecycle risk rather than a reproduced runtime leak.

Smallest correction: give the queue one initialization lifetime, check admission before initializing the serial transmitter, and return with outputs inactive if initialization fails. Skip packet-queue creation for dry contact. A static FreeRTOS queue would remove this allocation failure and give a fixed RAM cost, but its exact queue-object/packet storage cost must be compared with the current dynamic queue rather than claimed as a saving.

Regression: fail queue creation and verify no SDK queue use, serial initialization, ready state, or GPIO assertion follows; exercise setup twice and confirm one queue owner. Use production helper code with the SDK adapter fault injected.

### 2. Lock/light commands retain intent after failed admission and have no bounded recovery

The four flags at `src/comms.cpp:712-715` duplicate lock/light intent. `set_lock()` commits `target_lock` and pending flags before any enqueue (lines 3891-3895); `set_light()` commits its flags before enqueue (4017-4018). A full queue or a busy producer mutex rejects admission, but those flags remain. The next identical command is suppressed at lines 3880 and 4005. Status handling clears them only when a physical state changes (1884-1895, 1904-1926, 2260-2265, 2280-2289); repeated truthful status reports of the unchanged state do not recover the rejected command. Even successful admission followed by transmit exhaustion can leave the same permanent suppression.

Smallest correction: replace each pair of booleans with one bounded pending-intent state. Serialize check/admit/commit with the existing command ownership lock, commit only after complete admission, and retire pending state on a bounded confirmation deadline or explicit terminal transmission failure. Keep observed state separate from requested target. No new task, timer, queue, or periodic scan is needed; the existing comms loop can settle deadlines. Publishing a target before failed admission should be avoided or rolled back.

Regression: fill the real command queue, reject light-on/lock, drain it, and verify the same request can subsequently be accepted. Also inject terminal transmit failure and unchanged status packets, then verify eventual retry admission. Concurrent HomeSpan and web requests should not admit duplicate Sec+1 toggles.

### 3. Sec+1 light/lock still lack complete press/release ownership

The earlier door correction uses `txQueuePushSequence`, but `set_lock()` admits press, release, and repeated release separately (`src/comms.cpp:3905-3926`). With one free slot, the press is accepted and both releases fail. `set_light()` similarly calls separate void press/release helpers (4024-4025; implementations 3954-3995), can return success even when no packet was accepted, and can retain only its press under pressure. `process_send_queue()` protects exhausted releases only for a door generation (2012-2019), so light/lock releases can also be discarded after retry exhaustion.

Smallest correction: extend complete button-transaction admission and release ownership to light and lock. Reserve the essential press/release pair atomically; optional repeated releases remain best effort. Once a press is written, retain its release until transmitted or explicit transmitter shutdown. Preserve the intentional held light press used by TTC (`3539`, `3566`): that path needs reserved release ownership across the existing delay, not an immediate release that changes the warning behavior. Avoid a second queue or general transaction framework.

Regression: with one free slot, no light/lock press is admitted; with two slots, the complete essential pair is admitted. Inject retries/collisions on each release and verify it remains ahead of later presses. Exercise the existing TTC hold duration and cancellation path. A hardware test is needed to assess the opener's response to missing releases; no unintended movement is claimed from source alone.

## Execution and ownership inventory

| Resource/path | Owner and execution context | Synchronization/lifecycle |
| --- | --- | --- |
| Sec+1 UART / Sec+2 software UART physical writes | Arduino comms loop, `process_send_queue` → `process_PacketAction` → `transmitSec1/2` (`1938`, `2966`, `2816`, `2919`) | `FunctionDelayLock` spans each packet write; shutdown closes ready admission under that lock, quiesces TX, then tears down UART (`1183-1243`). Writes include bounded echo wait, logging, and protocol timing. |
| Packet queue | Multiple web/HomeSpan/loop producers; Arduino loop consumer | 16 entries; producer mutex serializes admission, consumer frees entries independently (`79-178`). Queue object has no explicit teardown; initialization result is ignored. |
| Door transitions / pending generation | Web helper (`web.cpp:2039`), HomeSpan task (`homekit.cpp:1122`), hardwired loop (`drycontact.cpp:140-158`), encoder loop/retry (`encoder.cpp:409-414`, `643`) | Door command entry points and lifecycle use recursive `FunctionDelayLock`; generation prevents stale door presses. HomeSpan runs via `autoPoll` (`homekit.cpp:1044`). |
| TTC, partial open, motion/completion checks, encoder correction | Existing comms/encoder loop | Polled deadlines and delayed command dispatch; cancellation and final acceptance share command lock. No independent actuator callback task is added by these paths. |
| ESP32 dry-contact physical outputs | Command caller asserts under command lock and pulse spinlock; `ESP_TIMER_TASK` releases GPIO | Three stable timer owners, callbacks release only; no command dispatch from expiry (`194-328`). Shutdown disables and releases all pulses. |
| ESP8266 dry-contact outputs | Command caller asserts; static Ticker callbacks release | Local static timer ownership remains in `door_command` (`3053-3105`); this review did not exercise SDK callback lifecycle. |
| Status outputs / wall-panel relay | Protocol status paths and Sec+1 transmitter | `write_status_pin` also drives the wall-panel disconnect relay around transmission (`2840-2910`). These are physical writers even though they are not door-command presses. |
| Light/lock state | Web/HomeSpan command callers plus protocol receive loop | Queue mutex protects storage only; pending flags and command check/admit/commit have no common lock. The preceding findings apply. |
| GDOLIB optional build | `gdo_*` command APIs and library event callback (`779`) | Library owns UART and task/timer behavior. This review inspected caller paths only; SDK/library ownership and deinitialization semantics require separate dependency review. |
| Shared `garage_door` | Protocol, encoder, command callers, web rendering, HomeKit notifications | Multiple writers/readers remain; command lock is not a global state snapshot lock. No new state-wide mutex is proposed without a concrete lock-order and latency analysis. |

The ESP8266 pairing callback temporarily overloads `comms_setup_done` as a pause flag (`homekit.cpp:128-172`). Shutdown also uses that flag as resource readiness. This conflation deserves lifecycle cleanup if pairing/OTA interleavings are brought into scope, but this review has not demonstrated a supported sequence that creates an actuator edge from it.

## Verification limits

This was a read-only production-source audit. The queue-admission and stale-intent mechanisms need regression coverage through production helpers before integration. Target builds, runtime resource comparisons, SDK task interleavings, and authorized hardware validation remain required. No flash/RAM savings or device recovery is claimed.

## Major open item: opposite light/lock intent arbitration

The queue ownership correction is committed as `321a2eb`; the following pre-existing arbitration problem remains outside that change. `set_light` and `set_lock` first reject requests matching the observed state, even when an opposite accepted intent is still queued. For example, observed light Off → accepted queued On → explicit Off ignored → queued On eventually executes. The same mechanism applies to remote locking. The current generation owner can cancel stale queued work, but the entry points do not apply that cancellation for this case.

A proposed bounded correction, pending review and validation:

1. Before the old command reaches UART, a new desired state equal to observed state cancels the old generation without another toggle. A replacement that requires actuation must be admitted completely before retiring the previously accepted intent.
2. After a press reaches UART, retain its essential Release and coalesce one deferred desired boolean. Once Release succeeds, wait for a fresh validated status, including an unchanged status report. Compare that observed state with the deferred target and admit at most one new command if they differ. Sec+2 single-write commands reach this feedback stage after successful transmission.
3. Bound reconciliation by the existing three-second intent deadline. If feedback or queue admission does not arrive, retire the deferred intent and report observed state. Do not infer a second Sec+1 toggle from an unconfirmed first actuation. Timeout or reconciliation failure must retain an owed physical Release.

The current 20-byte owner layout has room for an explicit stage byte and one deferred target byte without increasing its size, subject to the existing target size assertion. The existing comms loop can reconcile it; no additional task, queue, timer, or full payload buffer is proposed. This is a proposed state machine, not implemented or verified behavior. Regressions should cover opposite requests before UART write, requests after write but before Release, fresh unchanged feedback, missing feedback, exhausted queues, failed transmission, and stale generations.
