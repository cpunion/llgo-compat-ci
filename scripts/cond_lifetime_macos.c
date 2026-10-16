#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <errno.h>
#include <unistd.h>
#include <execinfo.h>

static _Atomic(uintptr_t) signals[4096];
static _Atomic(unsigned) slots;
static _Thread_local unsigned slot;
static _Thread_local int has_slot;

static int spurious_wait(pthread_cond_t *cond, pthread_mutex_t *mutex) {
    struct timespec until;
    clock_gettime(CLOCK_REALTIME, &until);
    until.tv_nsec += 10000;
    if (until.tv_nsec >= 1000000000) { until.tv_nsec -= 1000000000; until.tv_sec++; }
    int result = pthread_cond_timedwait(cond, mutex, &until);
    return result == ETIMEDOUT ? 0 : result;
}

static int delayed_signal(pthread_cond_t *cond) {
    if (!has_slot) { slot = atomic_fetch_add(&slots, 1); has_slot = 1; }
    if (slot >= 4096) _exit(91);
    atomic_store(&signals[slot], (uintptr_t)cond);
    usleep(100);
    int result = pthread_cond_signal(cond);
    atomic_store(&signals[slot], 0);
    return result;
}

static int checked_destroy(pthread_cond_t *cond) {
    for (unsigned i = 0; i < atomic_load(&slots); i++) {
        if (atomic_load(&signals[i]) == (uintptr_t)cond) {
            fprintf(stderr, "condition destroyed while its signal call is active: %p\n", (void *)cond);
            void *frames[24];
            int count = backtrace(frames, 24);
            backtrace_symbols_fd(frames, count, STDERR_FILENO);
            _exit(90);
        }
    }
    return pthread_cond_destroy(cond);
}

#define INTERPOSE(replacement, original) \
    __attribute__((used)) static struct { const void *r; const void *o; } interpose_##original \
    __attribute__((section("__DATA,__interpose"))) = { (const void *)(uintptr_t)&replacement, (const void *)(uintptr_t)&original }
INTERPOSE(spurious_wait, pthread_cond_wait);
INTERPOSE(delayed_signal, pthread_cond_signal);
INTERPOSE(checked_destroy, pthread_cond_destroy);
