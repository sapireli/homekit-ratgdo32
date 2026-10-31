# Logger owner design: open, not approved for implementation

The ESP32 logger performs serial, SSE, and syslog I/O while holding its recursive mutex (`src/log.cpp:235-317`). The proposed correction transfers delivery to the existing Arduino loop, using the existing ring. Panic evidence and serial handoff are unresolved design gates. No logger source changed during this review; no PIO build, network traffic, or hardware action was performed.

## Current ring consumers and callbacks

| Path | Current behavior | Required adapter |
| --- | --- | --- |
| `esp_log_hook`, `log.cpp:68` | Any logging task; non-core-held path also calls `serialConsole.ensureStarted(Serial)` | No console initialization or I/O in the producer hook. Preserve core-held try-only logger acquisition. Do not assume normal ESP logging supports ISR calls. |
| `LOG::logToBuffer`, `log.cpp:235` | Formats in shared 256-byte `lineBuffer`, appends raw text, emits serial/SSE/syslog under lock | Commit a bounded record and append-time eligibility only; no external callbacks, `Print`, or socket work. |
| `panic_handler`, `log.cpp:156` | Direct `msgBuffer` head/wrapped/data reads into `rtcCrashLog` | Bounded plaintext reverse decoder with proven concurrent-writer and cache safety; no mutex, heap, or SDK lock. |
| `saveMessageLog`, `log.cpp:434` | Raw tail copy into `rtcRebootLog` under logger lock | Decode into existing RTC plaintext storage under the ordinary mutex. Called by restart (`utilities.cpp:321`) and Improv error callback (`provision.cpp:217`). |
| `beginMessageLog` / `readMessageLog`, `log.cpp:581,596` | Finite captured-end raw cursor | Record position plus payload offset; strip framing and detect whole-record retirement. |
| `printMessageLog`, `log.cpp:637` | Separate raw traversal and 256-byte stack chunk; sends outside lock | Reuse the plaintext cursor adapter. Keep a stable per-call chunk for concurrent export callers. |
| Ordinary HTTP, `web.cpp:2771` | `printMessageLog(server.client())` | Preserve plaintext output and explicit truncation notices. |
| Experimental HTTP, `web.cpp:518,566` | Cursor plus leased web `writeBuffer`, 256-byte reads | Continue through plaintext cursor; preserve scratch lease and partial-write lifetime. |
| HomeSpan CLI, `homekit.cpp:592`; serial CLI, `serialCLI.cpp:167` | Explicit diagnostic export to Serial | Use common plaintext cursor. These explicit commands remain separate output operations. |
| `printSavedLog`, `log.cpp:491`; `printCrashLog`, `log.cpp:362` | Read RTC buffers as plaintext | Keep RTC layout/text conventions; decode before saving. |
| `DiagnosticCursor` / `DiagnosticWindow`, `log.cpp:526-579` | Formats RTC text and metadata into caller windows | Preserve revision checks; never expose raw framed bytes. Core-summary allocation is separate. |
| ESP8266 crash callback, `log.cpp:107`; saved files, `log.cpp:461`; restart/error file saves | Raw IRAM ring and LittleFS | Retain separate ESP8266 implementation; framing proposal is ESP32-only. |

A repository search found no direct `msgBuffer` reader outside `src/log.cpp` and its declaration in `lib/ratgdo/log.h`. Make its representation an implementation boundary so later readers cannot bypass decoding.

## Proposed delivery ownership

Use the existing approximately 16 KiB allocation for records. A proposed record has a two-byte header containing length (1-255), eligibility flags and validation bits, then payload, then a matching one-byte length trailer. Split headers, payloads and trailers must work modulo capacity. Evict complete records only. Zero/invalid lengths or malformed boundaries stop the reader with an explicit partial/corrupt result. No new task, queue, connection registry, or full ring is proposed.

Three framing bytes cost `3/(L+3)` of retained capacity: 1.16% for 255-byte messages, 5.66% for 50-byte messages, and 75% for one-byte messages. This is a correctness cost, not a saving. The trailer permits reverse panic traversal; a two-byte-only format would require finding boundaries by forward scanning potentially the entire ring.

The existing Arduino loop captures a finite committed end and copies at most a fixed number of complete records into a separate NUL-terminated 256-byte delivery scratch under the logger lock. It releases the lock before delivery. One record per iteration is the smallest initial budget. Advance/count delivery retirement explicitly; overwritten records must be reported as lost rather than silently considered sent. Never chase delivery-error appends during the same iteration.

The separate 256-byte scratch is a proposed correctness exception. Recursive sender errors can overwrite the producer buffer; HTTP can lease the web scratch across iterations; another task can be exporting through its own stack chunk. Sharing these would corrupt bytes or restore locking across I/O. A stack delivery chunk moves the same peak onto the Arduino stack. Count the 256 bytes alongside existing export chunks, UDP formatting/SDK frames, cursor metadata and nested sender frames. Resource review must approve the persistent/transient/capability-specific budget.

Record serial suppression and console availability at append time, then recheck current physical pin ownership at delivery. Core-held records remain in history without external delivery eligibility. Publish the delivery owner's task identity under the logger mutex: recursive logs from that same task remain in history but cannot feed network delivery, while other tasks' records remain eligible. A global `inFn`, coarse skipped range, or finite end alone cannot provide that cross-iteration policy without suppressing unrelated logs.

The serial policy for same-task delivery errors must be explicit. Excluding them from all automatic output prevents serial-error feedback; allowing serial-only diagnostics needs a demonstrated bounded failure path. Do not inherit the current global recursion flag accidentally. No producer may call `ensureStarted`, including early boot; the owner initializes Serial only while it owns its pins. Startup buffering must not replay messages suppressed when appended.

## Serial handoff blocker

Rev1 `setup_vehicle` transfers GPIO1/3 from UART0 to I2C (`vehicle.cpp:70`) through `release_serial_console_for_i2c` (`provision.cpp:84`). `LOG::disableSerialConsole` (`log.cpp:225`) currently takes the logger lock to drain in-flight writes before UART teardown. Restore occurs after `Wire.end()` (`provision.cpp:96`). Moving delivery outside that lock removes its barrier.

Prove that delivery and every handoff execute on the Arduino owner, or defer external handoff requests to that owner and acknowledge completed teardown before the caller claims I2C. Never wait for acknowledgement while holding HomeSpan, command, JSON or logger locks. A generation/availability check can reject stale queued serial output, but cannot drain an already-running write. The complete context/acknowledgement proof remains open.

## Panic evidence blocker

The installed Arduino wrapper calls the custom panic handler before `__real_esp_panic_handler` (`esp32-hal-misc.c:460-468`). The other core is therefore not guaranteed stopped. Header-last publication alone cannot protect a committed record that an interrupted append has already overwritten. Marking every odd/in-progress append as an empty snapshot would lose crash evidence exactly when logging fails and is not accepted.

One possible scheme release-publishes an advanced oldest-record boundary before overwriting retired bytes, then publishes the new head only after the complete new record. This can leave a committed suffix when a writer stops mid-append. However, before/after tail checks and matching headers/trailers do not by themselves prove raw payload was not concurrently overwritten while copied. A late eviction can race the copy. Keeping already validated newer plaintext and discarding only an invalidated oldest copy is an option requiring a real platform memory-ordering proof, not an approved implementation.

Aligned 32-bit committed positions could avoid torn 64-bit metadata. Target disassembly must show inline loads/stores/fences with no `libatomic`, SDK lock, or cache-unsafe helper on the panic path. Counter wrap also needs proof: wrapping 32-bit absolute positions cannot be naively reduced modulo the current non-power-of-two payload capacity. One layout option uses all 16,384 allocated bytes as ring data and moves two position words into the existing eight-byte append-counter storage. This preserves allocation size but changes every raw metadata consumer above.

Preserve about 3.5 KiB of plaintext RTC tail. Reverse traversal can fill the existing RTC buffer backward and compact once without another buffer. At one-byte message length, retaining 3.5 KiB plaintext may inspect roughly 14 KiB framed storage. Bound physical bytes, iterations, record lengths, retained ranges, copies and terminators explicitly, and measure CPU cost. Silently capping the walk at 3.5 KiB framed bytes would discard most plaintext in that case and is not assumed acceptable.

Current GRGDO1 targets have no PSRAM; it is not an explanation for the current failure. A future/supported configuration where ordinary `malloc` may return external memory requires separate cache-safety verification. Forcing the whole ring into internal RAM could create a large capability-specific regression; silently abandoning its panic evidence is also unacceptable. Establish actual backing storage before claiming the decoder is panic-safe.

Marking a function IRAM does not make its literals, callees, `memcpy`, arithmetic helpers or source storage cache-safe. Inspect the linked call graph/disassembly. Validate writer interruption during eviction, split header, payload, trailer and final publication without acquiring locks in panic.

## Gates before source changes

1. Approve a bounded concurrent-writer panic algorithm that preserves valid committed history, including raw-byte memory ordering and actual core/cache state at the hook.
2. Approve the independent 256-byte scratch, three-byte framing capacity cost, transient sender stacks and plaintext-tail work budget.
3. Prove serial handoff ordering and acknowledgement without introducing lock inversion.
4. Add production-adapter regressions for wrap, invalid/split records, overwrite during export/delivery, suppression, same-task error feedback versus other-task logs, allocation failure, serial teardown and interrupted panic publication. Host tests cannot establish SDK panic/cache behavior.
5. Build supported targets, inspect panic code/storage, then measure latency, stacks, heap capabilities, evidence retention and recovery on authorized hardware.

The logger remains open. The implemented control/HomeKit ownership work does not depend on merging this design.
