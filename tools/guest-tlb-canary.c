/* GPU-less guest diagnostic; never acceleration or general memory qualification.
 *
 * Build with macOS clang, C11, -O2 and -pthread. Run with a duration in seconds
 * (1..300, default 30). See guest-memory-corruption-20261015.md for commands.
 *
 * Eight readers check the first 64-bit word of every 4 KiB page after each
 * synchronized MAP_FIXED remap between two known 8 MiB file backings.
 * JSON output reports remaps, page_checks and mismatches. A mismatch returns 1;
 * setup errors return 2. A pass does not exclude corruption elsewhere: APFS
 * integrity errors occurred in a guest that passed this canary.
 */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#define PAGES 2048
#define PAGE 4096
#define READERS 8
static struct {
  pthread_mutex_t m;
  pthread_cond_t c;
  unsigned count, generation;
} b = {PTHREAD_MUTEX_INITIALIZER, PTHREAD_COND_INITIALIZER, 0, 0};
static void barrier(void) {
  pthread_mutex_lock(&b.m);
  unsigned g = b.generation;
  if (++b.count == READERS + 1) {
    b.count = 0;
    b.generation++;
    pthread_cond_broadcast(&b.c);
  } else
    while (g == b.generation)
      pthread_cond_wait(&b.c, &b.m);
  pthread_mutex_unlock(&b.m);
}
static volatile uint64_t *view;
static unsigned phase, done;
static _Atomic unsigned long long errors, checks;
static uint64_t pattern(unsigned bank, unsigned page) {
  return UINT64_C(0x13579bdf2468ace0) ^ ((uint64_t)bank << 60) ^
         ((uint64_t)page * UINT64_C(0x9e3779b97f4a7c15));
}
static void *reader(void *arg) {
  unsigned id = (unsigned)(uintptr_t)arg;
  for (;;) {
    barrier();
    if (done)
      break;
    for (unsigned p = id; p < PAGES; p += READERS) {
      uint64_t want = pattern(phase, p), got = view[(size_t)p * PAGE / 8];
      if (got != want) {
        unsigned long long n = atomic_fetch_add(&errors, 1);
        if (n < 12)
          fprintf(stderr,
                  "CANARY_MISMATCH reader=%u page=%u bank=%u expected=%016llx "
                  "got=%016llx\n",
                  id, p, phase, (unsigned long long)want,
                  (unsigned long long)got);
      }
      atomic_fetch_add(&checks, 1);
    }
    barrier();
  }
  return NULL;
}
static double now(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec / 1e9;
}
int main(int argc, char **argv) {
  int seconds = argc > 1 ? atoi(argv[1]) : 30;
  if (seconds < 1 || seconds > 300)
    return 2;
  int fd[2];
  size_t bytes = (size_t)PAGES * PAGE;
  for (unsigned bank = 0; bank < 2; bank++) {
    char path[] = "/var/tmp/rgpu-canary-XXXXXX";
    fd[bank] = mkstemp(path);
    if (fd[bank] < 0 || ftruncate(fd[bank], bytes)) {
      perror("create");
      return 2;
    }
    unlink(path);
    uint64_t *p =
        mmap(NULL, bytes, PROT_READ | PROT_WRITE, MAP_SHARED, fd[bank], 0);
    if (p == MAP_FAILED) {
      perror("init mmap");
      return 2;
    }
    for (unsigned page = 0; page < PAGES; page++)
      for (unsigned off = 0; off < PAGE / 8; off++)
        p[(size_t)page * PAGE / 8 + off] = pattern(bank, page);
    if (munmap(p, bytes)) {
      perror("init munmap");
      return 2;
    }
  }
  view = mmap(NULL, bytes, PROT_READ, MAP_SHARED, fd[0], 0);
  if (view == MAP_FAILED) {
    perror("view");
    return 2;
  }
  pthread_t ts[READERS];
  for (unsigned i = 0; i < READERS; i++)
    if (pthread_create(&ts[i], NULL, reader, (void *)(uintptr_t)i))
      return 2;
  unsigned long long rounds = 0;
  double start = now();
  while (now() - start < seconds) {
    phase = rounds % 2;
    if (mmap((void *)view, bytes, PROT_READ, MAP_SHARED | MAP_FIXED, fd[phase],
             0) == MAP_FAILED) {
      perror("remap");
      _exit(2);
    }
    barrier();
    barrier();
    rounds++;
    if (atomic_load(&errors))
      break;
  }
  done = 1;
  barrier();
  for (unsigned i = 0; i < READERS; i++)
    pthread_join(ts[i], NULL);
  printf("{\"seconds\":%.3f,\"remaps\":%llu,\"page_checks\":%llu,"
         "\"mismatches\":%llu}\n",
         now() - start, rounds, atomic_load(&checks), atomic_load(&errors));
  munmap((void *)view, bytes);
  close(fd[0]);
  close(fd[1]);
  return atomic_load(&errors) ? 1 : 0;
}
