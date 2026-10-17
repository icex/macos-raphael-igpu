/* Bounded macOS probe for the phys_attribute_test / pmap lifetime path.
 * Four fork/exit workers share clean file pages with a parent that queries their
 * dispositions. Only this process, its children and an unlinked scratch file
 * are touched. A pass is scoped stress evidence, not whole-memory certification.
 */
#include <errno.h>
#include <inttypes.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define BYTES (8U * 1024U * 1024U)
#define WORKERS 4
static const volatile uint32_t *pages;
static size_t page_size;
static atomic_int stop_workers;
static atomic_int failed;
static atomic_uint_fast64_t forks_done;
static double now(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) abort();
    return t.tv_sec + t.tv_nsec / 1e9;
}
static int check_pages(void) {
    for (size_t offset = 0; offset < BYTES; offset += page_size)
        if (pages[offset / sizeof(*pages)] != (UINT32_C(0x6a39e17b) ^ (uint32_t)offset))
            return 1;
    return 0;
}
static void *churn(void *unused) {
    (void)unused;
    while (!atomic_load(&stop_workers)) {
        pid_t child = fork();
        if (child == 0) _exit(check_pages());
        if (child < 0) {
            perror("fork"); atomic_store(&failed, 1); break;
        }
        int status = 0;
        pid_t waited;
        do { waited = waitpid(child, &status, 0); } while (waited < 0 && errno == EINTR);
        if (waited != child || !WIFEXITED(status) || WEXITSTATUS(status) != 0) {
            fprintf(stderr, "child failed: pid=%d waited=%d status=%d\n", child, waited, status);
            atomic_store(&failed, 1); break;
        }
        atomic_fetch_add(&forks_done, 1);
    }
    return NULL;
}
int main(int argc, char **argv) {
    char *end = NULL;
    long duration = argc == 2 ? strtol(argv[1], &end, 10) : 0;
    if (argc != 2 || !end || *end || duration < 1 || duration > 300) {
        fprintf(stderr, "usage: %s seconds (1..300)\n", argv[0]); return 2;
    }
    long ps = sysconf(_SC_PAGESIZE);
    if (ps <= 0 || BYTES % (size_t)ps) return 2;
    page_size = (size_t)ps;
    char name[] = "/var/tmp/rgpu-pmap-lifetime-XXXXXX";
    int fd = mkstemp(name);
    if (fd < 0) { perror("mkstemp"); return 2; }
    if (unlink(name) || ftruncate(fd, BYTES)) { perror("scratch setup"); close(fd); return 2; }
    uint32_t *fill = calloc(1, BYTES);
    if (!fill) { close(fd); return 2; }
    for (size_t offset = 0; offset < BYTES; offset += page_size)
        fill[offset / sizeof(*fill)] = UINT32_C(0x6a39e17b) ^ (uint32_t)offset;
    size_t written = 0;
    while (written < BYTES) {
        ssize_t n = write(fd, (char *)fill + written, BYTES - written);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { perror("write"); free(fill); close(fd); return 2; }
        written += (size_t)n;
    }
    free(fill);
    if (fsync(fd)) { perror("fsync"); close(fd); return 2; }
    void *mapping = mmap(NULL, BYTES, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (mapping == MAP_FAILED) { perror("mmap"); return 2; }
    pages = mapping;
    if (check_pages()) { munmap(mapping, BYTES); return 1; }
    size_t count_expected = BYTES / page_size;
    int *dispositions = calloc(count_expected, sizeof(*dispositions));
    if (!dispositions) { munmap(mapping, BYTES); return 2; }
    pthread_t workers[WORKERS];
    size_t started = 0;
    for (; started < WORKERS; ++started) {
        int rc = pthread_create(&workers[started], NULL, churn, NULL);
        if (rc) { fprintf(stderr, "pthread_create: %d\n", rc); atomic_store(&failed, 1); break; }
    }
    double begin = now(), deadline = begin + duration, next_log = begin + 10;
    uint64_t queries = 0;
    printf("PMAP_LIFETIME_START bytes=%u page_size=%zu workers=%zu seconds=%ld\n", BYTES, page_size, started, duration);
    fflush(stdout);
    while (!atomic_load(&failed) && now() < deadline) {
        mach_vm_size_t count = count_expected;
        kern_return_t kr = mach_vm_page_range_query(mach_task_self(),
            (mach_vm_address_t)(uintptr_t)mapping, BYTES,
            (mach_vm_address_t)(uintptr_t)dispositions, &count);
        if (kr != KERN_SUCCESS || count != count_expected || check_pages()) {
            fprintf(stderr, "page query/data failure: kr=%d count=%" PRIu64 "\n", kr, (uint64_t)count);
            atomic_store(&failed, 1); break;
        }
        ++queries;
        if (now() >= next_log) {
            printf("PMAP_LIFETIME_PROGRESS seconds=%.1f queries=%" PRIu64 " forks=%" PRIuFAST64 "\n", now() - begin, queries, atomic_load(&forks_done));
            fflush(stdout); next_log += 10;
        }
    }
    atomic_store(&stop_workers, 1);
    for (size_t i = 0; i < started; ++i) pthread_join(workers[i], NULL);
    int bad = atomic_load(&failed) || queries == 0 || atomic_load(&forks_done) == 0;
    printf("PMAP_LIFETIME_%s seconds=%.1f queries=%" PRIu64 " forks=%" PRIuFAST64 "\n", bad ? "FAIL" : "PASS", now() - begin, queries, atomic_load(&forks_done));
    free(dispositions); munmap(mapping, BYTES);
    return bad ? 1 : 0;
}
