#include <errno.h>
#include <mach/mach.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

extern int GC_pthread_create(pthread_t *, const pthread_attr_t *,
                             void *(*)(void *), void *);
static atomic_long attempts;
static atomic_long failures;
static atomic_long recovered;
static atomic_int max_retry;

static void report(void) {
  fprintf(stderr, "TRACE summary attempts=%ld failures=%ld recovered=%ld max_retry=%d\n",
          atomic_load(&attempts), atomic_load(&failures), atomic_load(&recovered),
          atomic_load(&max_retry));
}

__attribute__((constructor)) static void install_report(void) { atexit(report); }

static int trace_create(pthread_t *thread, const pthread_attr_t *attr,
                        void *(*routine)(void *), void *arg) {
  long attempt = atomic_fetch_add(&attempts, 1) + 1;
  int state = -1;
  size_t stack_size = 0;
  pthread_attr_getdetachstate(attr, &state);
  pthread_attr_getstacksize(attr, &stack_size);
  if (attempt <= 3)
    fprintf(stderr, "TRACE attr detached=%d expected=%d stack=%zu\n", state,
            PTHREAD_CREATE_DETACHED, stack_size);
  const char *setting = getenv("LLGO_TRACE_CREATE_RETRIES");
  int retries = setting ? atoi(setting) : 0;
  int result;
  for (int retry = 0;; ++retry) {
    result = GC_pthread_create(thread, attr, routine, arg);
    int previous = atomic_load(&max_retry);
    while (previous < retry &&
           !atomic_compare_exchange_weak(&max_retry, &previous, retry)) {
    }
    if (result == 0) {
      if (retry != 0)
        atomic_fetch_add(&recovered, 1);
      return 0;
    }
    long failure = atomic_fetch_add(&failures, 1);
    if (failure < 3 || retry >= retries) {
      thread_act_array_t threads;
      mach_msg_type_number_t count = 0;
      if (task_threads(mach_task_self(), &threads, &count) == KERN_SUCCESS) {
        for (mach_msg_type_number_t i = 0; i < count; ++i)
          mach_port_deallocate(mach_task_self(), threads[i]);
        vm_deallocate(mach_task_self(), (vm_address_t)threads,
                      count * sizeof(*threads));
      }
      fprintf(stderr, "TRACE create=%ld retry=%d return=%d EAGAIN=%d threads=%u\n",
              attempt, retry, result, EAGAIN, count);
    }
    if (result != EAGAIN || retry >= retries)
      return result;
    usleep((retry + 1) * 1000);
  }
}

__attribute__((used, section("__DATA,__interpose"))) static const struct {
  const void *replacement;
  const void *original;
} interpose[] = {{(const void *)trace_create, (const void *)GC_pthread_create}};
