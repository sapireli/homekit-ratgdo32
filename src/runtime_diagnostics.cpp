#include "runtime_diagnostics.h"

#if defined(ESP32) && defined(RATGDO_RUNTIME_DIAGNOSTICS)
#include <atomic>
#include <cstdio>
#include <cstring>
#include <cerrno>
#include <esp_heap_caps.h>
#include <esp_attr.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/queue.h>
#include <lwip/sockets.h>
#include <lwip/inet.h>
#include <lwip/tcpip.h>
#include <lwip/priv/tcp_priv.h>

#ifndef RATGDO_DIAGNOSTIC_HOST
#define RATGDO_DIAGNOSTIC_HOST "192.168.23.158"
#endif
#ifndef RATGDO_DIAGNOSTIC_PORT
#define RATGDO_DIAGNOSTIC_PORT 5515
#endif

namespace {
constexpr unsigned MAX_PCBS = 16;
constexpr unsigned MAX_SEGMENTS = 64;
constexpr uint32_t SAMPLE_MS = 5000;
static_assert(ATOMIC_INT_LOCK_FREE == 2 && ATOMIC_POINTER_LOCK_FREE == 2, "Diagnostic hooks must not lock");
std::atomic<uint32_t> phase{0}, phaseAt{0}, loops{0}, homekitAt{0}, homekitLoops{0};
std::atomic<uint32_t> failures{0}, failedSize{0}, failedCaps{0}, firstBadHeap{0};
struct HeapLatch { uint32_t magic, at, phase, phaseAge, loops, homekitAge, failures; };
RTC_NOINIT_ATTR HeapLatch retainedHeapFailure;
constexpr uint32_t LATCH_MAGIC = 0x52444941;
HeapLatch priorHeapFailure{};
std::atomic<TaskHandle_t> mainTask{nullptr}, homekitTask{nullptr};
std::atomic<uint32_t> tcpPending{0}, tcpRequestedAt{0}, tcpRejected{0}, sendErrors{0};
std::atomic<uint32_t> emitterLowStack{0};
uint32_t milliseconds() { return static_cast<uint32_t>(esp_timer_get_time() / 1000); }

struct Connection {
    uint16_t local, remote, queued, rto;
    uint8_t state, retransmits;
    int16_t retransmitTimer;
    uint32_t sendBuffer, unsent, unacked, acknowledged, next, buffered;
};
struct TcpSnapshot {
    uint32_t sampledAt, delay, active, timeWait, count, truncated, lowStack;
    Connection connections[MAX_PCBS];
};
struct Sample {
    uint32_t at, sample, phase, phaseAge, loops, homekitAge, homekitLoops;
    uint32_t mainState, homekitState, observerLowStack, emitterLowStack;
    uint32_t free, largest, minimum, integrity, firstBad, checkMicros;
    uint32_t failures, failedSize, failedCaps, tcpPendingAge, tcpRejected, sendErrors;
    TcpSnapshot tcp;
};
StaticQueue_t tcpQueueStorage, sampleQueueStorage;
uint8_t tcpQueueBytes[sizeof(TcpSnapshot)], sampleQueueBytes[sizeof(Sample)];
QueueHandle_t tcpQueue, sampleQueue;
StaticTask_t observerStorage, emitterStorage;
StackType_t observerStack[4096 / sizeof(StackType_t)], emitterStack[4096 / sizeof(StackType_t)];

// No allocation, logging, locks, WiFi calls or formatted output in this hook.
void allocationFailed(size_t size, uint32_t caps, const char *) {
    failedSize.store(static_cast<uint32_t>(size), std::memory_order_relaxed);
    failedCaps.store(caps, std::memory_order_relaxed);
    failures.fetch_add(1, std::memory_order_relaxed);
}

uint32_t segmentBytes(const tcp_seg *segment, uint32_t &truncated) {
    uint32_t total = 0;
    unsigned visited = 0;
    while (segment && visited++ < MAX_SEGMENTS) {
        total += segment->len;
        segment = segment->next;
    }
    if (segment) truncated = 1;
    return total;
}

// This callback executes under lwIP's core ownership. Copy only; never log or
// call socket/heap/WiFi APIs here. Both list and segment traversals are bounded.
void snapshotTcp(void *) {
    static TcpSnapshot snapshot;
    snapshot = {};
    snapshot.sampledAt = milliseconds();
    snapshot.lowStack = uxTaskGetStackHighWaterMark(nullptr);
    snapshot.delay = snapshot.sampledAt - tcpRequestedAt.load(std::memory_order_relaxed);
    const tcp_pcb *pcb = tcp_active_pcbs;
    while (pcb && snapshot.active < MAX_PCBS) {
        ++snapshot.active;
        auto &connection = snapshot.connections[snapshot.count++];
        connection.local = pcb->local_port;
        connection.remote = pcb->remote_port;
        connection.state = static_cast<uint8_t>(pcb->state);
        connection.sendBuffer = pcb->snd_buf;
        connection.queued = pcb->snd_queuelen;
        connection.retransmits = pcb->nrtx;
        connection.rto = pcb->rto;
        connection.retransmitTimer = pcb->rtime;
        connection.unsent = segmentBytes(pcb->unsent, snapshot.truncated);
        connection.unacked = segmentBytes(pcb->unacked, snapshot.truncated);
        connection.acknowledged = pcb->lastack;
        connection.next = pcb->snd_nxt;
        connection.buffered = pcb->snd_lbb;
        pcb = pcb->next;
    }
    if (pcb) snapshot.truncated = 1;
    pcb = tcp_tw_pcbs;
    while (pcb && snapshot.timeWait < MAX_PCBS) { ++snapshot.timeWait; pcb = pcb->next; }
    if (pcb) snapshot.truncated = 1;
    xQueueOverwrite(tcpQueue, &snapshot);
    tcpPending.store(0, std::memory_order_release);
}

void observe(void *) {
    uint32_t count = 0;
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        Sample sample{};
        sample.at = milliseconds();
        sample.sample = ++count;
        sample.observerLowStack = uxTaskGetStackHighWaterMark(nullptr);
        sample.emitterLowStack = emitterLowStack.load(std::memory_order_relaxed);
        sample.phase = phase.load(std::memory_order_relaxed);
        sample.phaseAge = sample.at - phaseAt.load(std::memory_order_relaxed);
        sample.loops = loops.load(std::memory_order_relaxed);
        const uint32_t hkAt = homekitAt.load(std::memory_order_relaxed);
        sample.homekitAge = hkAt ? sample.at - hkAt : UINT32_MAX;
        sample.homekitLoops = homekitLoops.load(std::memory_order_relaxed);
        sample.mainState = sample.homekitState = UINT32_MAX;
#if INCLUDE_eTaskGetState
        if (const TaskHandle_t task = mainTask.load(std::memory_order_relaxed))
            sample.mainState = eTaskGetState(task);
        if (const TaskHandle_t task = homekitTask.load(std::memory_order_relaxed))
            sample.homekitState = eTaskGetState(task);
#endif
        const int64_t before = esp_timer_get_time();
        sample.integrity = firstBadHeap.load(std::memory_order_relaxed) == 0 && heap_caps_check_integrity_all(false);
        sample.checkMicros = static_cast<uint32_t>(esp_timer_get_time() - before);
        if (!sample.integrity) {
            uint32_t empty = 0;
            if (firstBadHeap.compare_exchange_strong(empty, sample.at, std::memory_order_relaxed)) {
                // Store before any network allocation. Survives a software reset,
                // not a physical power-cycle; read and reported at the next boot.
                retainedHeapFailure.at = sample.at;
                retainedHeapFailure.phase = sample.phase;
                retainedHeapFailure.phaseAge = sample.phaseAge;
                retainedHeapFailure.loops = sample.loops;
                retainedHeapFailure.homekitAge = sample.homekitAge;
                retainedHeapFailure.failures = failures.load(std::memory_order_relaxed);
                retainedHeapFailure.magic = LATCH_MAGIC;
            }
        }
        sample.firstBad = firstBadHeap.load(std::memory_order_relaxed);
        // Do not revisit heap structures after an integrity failure. The RTC
        // latch is already stored; these sentinel values mean "not sampled".
        sample.free = sample.largest = sample.minimum = UINT32_MAX;
        if (sample.integrity) {
            const uint32_t caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
            sample.free = heap_caps_get_free_size(caps);
            sample.largest = heap_caps_get_largest_free_block(caps);
            sample.minimum = heap_caps_get_minimum_free_size(caps);
        }
        sample.failures = failures.load(std::memory_order_relaxed);
        sample.failedSize = failedSize.load(std::memory_order_relaxed);
        sample.failedCaps = failedCaps.load(std::memory_order_relaxed);
        xQueuePeek(tcpQueue, &sample.tcp, 0);
        if (tcpPending.load(std::memory_order_acquire)) {
            sample.tcpPendingAge = sample.at - tcpRequestedAt.load(std::memory_order_relaxed);
        } else if (sample.integrity) {
            tcpRequestedAt.store(sample.at, std::memory_order_relaxed);
            tcpPending.store(1, std::memory_order_release);
            if (tcpip_try_callback(snapshotTcp, nullptr) != ERR_OK) {
                tcpPending.store(0, std::memory_order_release);
                tcpRejected.fetch_add(1, std::memory_order_relaxed);
            }
        }
        sample.tcpRejected = tcpRejected.load(std::memory_order_relaxed);
        sample.sendErrors = sendErrors.load(std::memory_order_relaxed);
        xQueueOverwrite(sampleQueue, &sample);
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(SAMPLE_MS));
    }
}

// Separate emitter: a socket call may wait inside the network stack even with
// MSG_DONTWAIT. It must never prevent the observer from taking new snapshots.
void emit(void *) {
    sockaddr_in destination{};
    destination.sin_family = AF_INET;
    destination.sin_port = htons(RATGDO_DIAGNOSTIC_PORT);
    destination.sin_addr.s_addr = inet_addr(RATGDO_DIAGNOSTIC_HOST);
    int fd = -1;
    uint32_t sequence = 0;
    for (;;) {
        Sample sample{};
        xQueueReceive(sampleQueue, &sample, portMAX_DELAY);
        if (fd < 0) fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        auto send = [&](const char *line) {
            const size_t length = strlen(line);
            if (fd < 0 || sendto(fd, line, length, MSG_DONTWAIT,
                reinterpret_cast<sockaddr *>(&destination), sizeof(destination)) != static_cast<int>(length))
                sendErrors.fetch_add(1, std::memory_order_relaxed);
        };
        char line[240];
        if (priorHeapFailure.magic == LATCH_MAGIC) {
            snprintf(line, sizeof(line), "RDIAG seq=%lu s=%lu up=%lu kind=prior badAt=%lu p=%lu age=%lu n=%lu hkAge=%lu fail=%lu",
                     ++sequence, sample.sample, sample.at, priorHeapFailure.at, priorHeapFailure.phase,
                     priorHeapFailure.phaseAge, priorHeapFailure.loops, priorHeapFailure.homekitAge, priorHeapFailure.failures);
            send(line);
        }
        snprintf(line, sizeof(line), "RDIAG seq=%lu s=%lu up=%lu kind=loop p=%lu age=%lu n=%lu hkAge=%lu hkN=%lu",
                 ++sequence, sample.sample, sample.at, sample.phase, sample.phaseAge, sample.loops,
                 sample.homekitAge, sample.homekitLoops);
        send(line);
        snprintf(line, sizeof(line), "RDIAG seq=%lu s=%lu up=%lu kind=tasks main=%lu hk=%lu obsLow=%lu emitLow=%lu pending=%lu rejected=%lu sendErr=%lu",
                 ++sequence, sample.sample, sample.at, sample.mainState, sample.homekitState,
                 sample.observerLowStack, sample.emitterLowStack, sample.tcpPendingAge, sample.tcpRejected, sample.sendErrors);
        send(line);
        snprintf(line, sizeof(line), "RDIAG seq=%lu s=%lu up=%lu kind=heap free=%lu largest=%lu min=%lu ok=%lu firstBad=%lu checkUs=%lu fail=%lu size=%lu caps=%lx",
                 ++sequence, sample.sample, sample.at, sample.free, sample.largest, sample.minimum,
                 sample.integrity, sample.firstBad, sample.checkMicros, sample.failures, sample.failedSize, sample.failedCaps);
        send(line);
        snprintf(line, sizeof(line), "RDIAG seq=%lu s=%lu up=%lu kind=core at=%lu delay=%lu active=%lu tw=%lu truncated=%lu lowStack=%lu",
                 ++sequence, sample.sample, sample.at, sample.tcp.sampledAt, sample.tcp.delay,
                 sample.tcp.active, sample.tcp.timeWait, sample.tcp.truncated, sample.tcp.lowStack);
        send(line);
        for (unsigned i = 0; i < sample.tcp.count; ++i) {
            const auto &c = sample.tcp.connections[i];
            snprintf(line, sizeof(line), "RDIAG seq=%lu s=%lu up=%lu kind=tcp at=%lu l=%u r=%u state=%u snd=%lu q=%u rex=%u rto=%u rt=%d",
                     ++sequence, sample.sample, sample.at, sample.tcp.sampledAt, c.local, c.remote, c.state,
                     c.sendBuffer, c.queued, c.retransmits, c.rto, c.retransmitTimer);
            send(line);
            snprintf(line, sizeof(line), "RDIAG seq=%lu s=%lu up=%lu kind=tcpq at=%lu l=%u r=%u unsent=%lu unack=%lu ack=%lu nxt=%lu end=%lu",
                     ++sequence, sample.sample, sample.at, sample.tcp.sampledAt, c.local, c.remote,
                     c.unsent, c.unacked, c.acknowledged, c.next, c.buffered);
            send(line);
        }
        emitterLowStack.store(uxTaskGetStackHighWaterMark(nullptr), std::memory_order_relaxed);
    }
}
} // namespace

void runtime_diagnostics_phase(unsigned value) {
    phase.store(value, std::memory_order_relaxed);
    phaseAt.store(milliseconds(), std::memory_order_relaxed);
    if (!value) loops.fetch_add(1, std::memory_order_relaxed);
}
void runtime_diagnostics_homekit_progress() {
    homekitTask.store(xTaskGetCurrentTaskHandle(), std::memory_order_relaxed);
    homekitAt.store(milliseconds(), std::memory_order_relaxed);
    homekitLoops.fetch_add(1, std::memory_order_relaxed);
}
void runtime_diagnostics_setup() {
    mainTask.store(xTaskGetCurrentTaskHandle(), std::memory_order_relaxed);
    if (retainedHeapFailure.magic == LATCH_MAGIC) priorHeapFailure = retainedHeapFailure;
    retainedHeapFailure.magic = 0;
    tcpQueue = xQueueCreateStatic(1, sizeof(TcpSnapshot), tcpQueueBytes, &tcpQueueStorage);
    sampleQueue = xQueueCreateStatic(1, sizeof(Sample), sampleQueueBytes, &sampleQueueStorage);
    heap_caps_register_failed_alloc_callback(allocationFailed);
    xTaskCreateStatic(emit, "diag-send", sizeof(emitterStack), nullptr, 1, emitterStack, &emitterStorage);
    xTaskCreateStatic(observe, "diag-observe", sizeof(observerStack), nullptr, 1, observerStack, &observerStorage);
}
#endif
