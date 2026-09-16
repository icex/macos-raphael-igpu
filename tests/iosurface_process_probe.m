// CPU-oracle GPU transfers through one IOSurface imported in two exec'd
// processes. Host completion + pipes provide ordering; this is NOT GPU
// shared-event coverage.
#import <Foundation/Foundation.h>
#import <IOSurface/IOSurface.h>
#import <Metal/Metal.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <spawn.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
extern char **environ;
static const uint32_t width = 1003, height = 769, rowBytes = 4096, rounds = 32,
                      magic = 0x49535032;
static volatile sig_atomic_t expired, childPID;
static BOOL childMode;
static void watchdog(int sig) {
  (void)sig;
  if (expired) {
    if (childPID > 0)
      kill(childPID, SIGKILL);
    _exit(124);
  }
  expired = 1;
  alarm(5); // Give bounded error paths time to close pipes/reap child.
}
static double now(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec / 1e9;
}
static void emit(NSString *phase, NSDictionary *extra) {
  NSMutableDictionary *d = [extra mutableCopy];
  d[@"phase"] = phase;
  d[@"pid"] = @(getpid());
  NSData *j = [NSJSONSerialization dataWithJSONObject:d options:0 error:NULL];
  FILE *out = childMode ? stderr : stdout;
  fwrite(j.bytes, 1, j.length, out);
  fputc('\n', out);
  fflush(out);
}
typedef struct {
  uint32_t magic, kind, round, pid;
  uint64_t bad;
} Message;
static BOOL nonblocking(int fd) {
  int flags = fcntl(fd, F_GETFL);
  return flags >= 0 && fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0;
}
static BOOL transfer(int fd, void *buffer, size_t count, BOOL writing) {
  double deadline = now() + 20;
  uint8_t *p = buffer;
  while (count && !expired) {
    double remaining = deadline - now();
    if (remaining <= 0)
      return NO;
    struct pollfd item = {fd, writing ? POLLOUT : POLLIN, 0};
    int result = poll(&item, 1, (int)(remaining * 1000) + 1);
    if (result < 0 && errno == EINTR)
      continue;
    if (result <= 0 || !(item.revents & (writing ? POLLOUT : POLLIN)))
      return NO;
    ssize_t n = writing ? write(fd, p, count) : read(fd, p, count);
    if (n > 0) {
      p += n;
      count -= (size_t)n;
    } else if (n < 0 && (errno == EINTR || errno == EAGAIN))
      continue;
    else
      return NO;
  }
  return count == 0 && !expired;
}
static uint32_t value(uint32_t index, uint32_t seed) {
  uint32_t x = index ^ (seed * 0x9e3779b9U);
  x ^= x >> 16;
  x *= 0x7feb352dU;
  x ^= x >> 15;
  x *= 0x846ca68bU;
  return x ^ (x >> 16);
}
static void fill(id<MTLBuffer> buffer, uint32_t seed) {
  memset(buffer.contents, 0x5a, (size_t)rowBytes * height);
  for (uint32_t y = 0; y < height; y++) {
    uint32_t *p = (uint32_t *)((uint8_t *)buffer.contents + y * rowBytes);
    for (uint32_t x = 0; x < width; x++)
      p[x] = value(y * width + x, seed);
  }
  [buffer didModifyRange:NSMakeRange(0, (NSUInteger)rowBytes * height)];
}
static uint64_t mismatches(id<MTLBuffer> buffer, uint32_t seed) {
  uint64_t bad = 0;
  for (uint32_t y = 0; y < height; y++) {
    const uint32_t *p =
        (const uint32_t *)((const uint8_t *)buffer.contents + y * rowBytes);
    for (uint32_t x = 0; x < width; x++)
      if (p[x] != value(y * width + x, seed))
        bad++;
  }
  return bad;
}
static id<MTLDevice> device(uint64_t registry) {
  for (id<MTLDevice> d in MTLCopyAllDevices())
    if (d.registryID == registry)
      return d;
  return nil;
}
static id<MTLTexture> texture(id<MTLDevice> d, IOSurfaceRef surface) {
  if (IOSurfaceGetWidth(surface) != width ||
      IOSurfaceGetHeight(surface) != height ||
      IOSurfaceGetBytesPerRow(surface) != rowBytes ||
      IOSurfaceGetPixelFormat(surface) != 0x42475241)
    return nil;
  MTLTextureDescriptor *desc = [MTLTextureDescriptor
      texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
                                   width:width
                                  height:height
                               mipmapped:NO];
  desc.storageMode = MTLStorageModeManaged;
  desc.usage = MTLTextureUsageShaderRead | MTLTextureUsageRenderTarget;
  return [d newTextureWithDescriptor:desc iosurface:surface plane:0];
}
static BOOL copy(id<MTLCommandQueue> q, id<MTLTexture> t, id<MTLBuffer> b,
                 BOOL upload) {
  if (expired)
    return NO;
  id<MTLCommandBuffer> cb = [q commandBuffer];
  id<MTLBlitCommandEncoder> bl = [cb blitCommandEncoder];
  if (!cb || !bl)
    return NO;
  if (upload)
    [bl copyFromBuffer:b
               sourceOffset:0
          sourceBytesPerRow:rowBytes
        sourceBytesPerImage:(NSUInteger)rowBytes * height
                 sourceSize:MTLSizeMake(width, height, 1)
                  toTexture:t
           destinationSlice:0
           destinationLevel:0
          destinationOrigin:MTLOriginMake(0, 0, 0)];
  else {
    [bl copyFromTexture:t
                     sourceSlice:0
                     sourceLevel:0
                    sourceOrigin:MTLOriginMake(0, 0, 0)
                      sourceSize:MTLSizeMake(width, height, 1)
                        toBuffer:b
               destinationOffset:0
          destinationBytesPerRow:rowBytes
        destinationBytesPerImage:(NSUInteger)rowBytes * height];
    [bl synchronizeResource:b];
  }
  [bl endEncoding];
  dispatch_semaphore_t done = dispatch_semaphore_create(0);
  [cb addCompletedHandler:^(id<MTLCommandBuffer> completed) {
    (void)completed;
    dispatch_semaphore_signal(done);
  }];
  [cb commit];
  if (dispatch_semaphore_wait(
          done, dispatch_time(DISPATCH_TIME_NOW, 20 * NSEC_PER_SEC)) ||
      cb.status != MTLCommandBufferStatusCompleted) {
    emit(
        @"gpu-error", @{
          @"upload" : @(upload),
          @"error" : cb.error.description ?: @"timeout"
        });
    return NO;
  }
  [cb waitUntilCompleted];
  return !expired;
}
static int child(uint64_t registry, uint32_t surfaceID) {
  @autoreleasepool {
    id<MTLDevice> d = device(registry);
    if (!d)
      return 3;
    IOSurfaceRef surface = IOSurfaceLookup(surfaceID);
    if (!surface) {
      emit(@"unqualified-global-iosurface", @{@"surface_id" : @(surfaceID)});
      return 4;
    }
    __attribute__((objc_precise_lifetime)) id owner =
        CFBridgingRelease(surface);
    id<MTLTexture> t = texture(d, surface);
    id<MTLCommandQueue> q = [d newCommandQueue];
    id<MTLBuffer> upload =
        [d newBufferWithLength:(NSUInteger)rowBytes * height
                       options:MTLResourceStorageModeManaged];
    id<MTLBuffer> readback =
        [d newBufferWithLength:(NSUInteger)rowBytes * height
                       options:MTLResourceStorageModeManaged];
    if (!owner || IOSurfaceGetID(surface) != surfaceID || !t || !q || !upload ||
        !readback || !nonblocking(STDIN_FILENO) || !nonblocking(STDOUT_FILENO))
      return 5;
    Message msg = {magic, 0, UINT32_MAX, (uint32_t)getpid(), 0};
    if (!transfer(STDOUT_FILENO, &msg, sizeof(msg), YES))
      return 6;
    uint64_t checked = 0;
    for (uint32_t round = 0; round < rounds; round++) {
      @autoreleasepool {
        if (!transfer(STDIN_FILENO, &msg, sizeof(msg), NO) ||
            msg.magic != magic || msg.kind != 1 || msg.round != round ||
            msg.pid != (uint32_t)getppid())
          return 7;
        if (!copy(q, t, readback, NO))
          return 8;
        uint64_t bad = mismatches(readback, round + 1);
        checked += (uint64_t)width * height;
        if (!bad) {
          fill(upload, round + 0x10000);
          if (!copy(q, t, upload, YES))
            return 9;
        }
        msg = (Message){magic, 2, round, (uint32_t)getpid(), bad};
        if (!transfer(STDOUT_FILENO, &msg, sizeof(msg), YES))
          return 10;
        if (bad) {
          emit(
              @"child-mismatch",
              @{@"round" : @(round),
                @"bad_pixels" : @(bad)});
          return 11;
        }
      }
    }
    emit(
        @"child-result", @{
          @"passed" : @YES,
          @"registry_id" : @(registry),
          @"surface_id" : @(surfaceID),
          @"pixels" : @(checked)
        });
    return 0;
  }
}
static BOOL reap(pid_t pid, BOOL failed, int *status) {
  if (failed)
    kill(pid, SIGTERM);
  double deadline = now() + 2;
  for (int attempt = 0; attempt < 2; attempt++) {
    while (now() < deadline) {
      pid_t result = waitpid(pid, status, WNOHANG);
      if (result == pid) {
        childPID = 0;
        return YES;
      }
      if (result < 0 && errno != EINTR) {
        childPID = 0;
        return NO;
      }
      struct timespec delay = {0, 10000000};
      nanosleep(&delay, NULL);
    }
    kill(pid, SIGKILL);
    deadline = now() + 2;
  }
  emit(@"child-reap-timeout", @{@"child_pid" : @(pid)});
  return NO;
}
int main(int argc, const char **argv) {
  @autoreleasepool {
    signal(SIGALRM, watchdog);
    signal(SIGPIPE, SIG_IGN);
    alarm(180);
    if (argc == 4 && !strcmp(argv[1], "--child")) {
      childMode = YES;
      int result = child(strtoull(argv[2], NULL, 0),
                         (uint32_t)strtoul(argv[3], NULL, 0));
      alarm(0);
      return result;
    }
    if (argc != 2)
      return 2;
    uint64_t registry = strtoull(argv[1], NULL, 0);
    id<MTLDevice> d = device(registry);
    if (!d)
      return 3;
    IOSurfaceRef surface = IOSurfaceCreate((__bridge CFDictionaryRef) @{
      (id)kIOSurfaceWidth : @(width),
      (id)kIOSurfaceHeight : @(height),
      (id)kIOSurfaceBytesPerElement : @4,
      (id)kIOSurfaceBytesPerRow : @(rowBytes),
      (id)kIOSurfaceAllocSize : @((NSUInteger)rowBytes * height),
      (id)kIOSurfacePixelFormat : @(0x42475241),
      (id)kIOSurfaceIsGlobal : @YES
    });
    if (!surface)
      return 4;
    __attribute__((objc_precise_lifetime)) id owner =
        CFBridgingRelease(surface);
    uint32_t sid = IOSurfaceGetID(surface);
    id<MTLTexture> t = texture(d, surface);
    id<MTLCommandQueue> q = [d newCommandQueue];
    id<MTLBuffer> upload =
        [d newBufferWithLength:(NSUInteger)rowBytes * height
                       options:MTLResourceStorageModeManaged];
    id<MTLBuffer> readback =
        [d newBufferWithLength:(NSUInteger)rowBytes * height
                       options:MTLResourceStorageModeManaged];
    if (!owner || !t || !q || !upload || !readback)
      return 5;
    int input[2], output[2];
    if (pipe(input))
      return 6;
    if (pipe(output)) {
      close(input[0]);
      close(input[1]);
      return 6;
    }
    char ridText[32], sidText[32];
    snprintf(ridText, sizeof(ridText), "%llu", (unsigned long long)registry);
    snprintf(sidText, sizeof(sidText), "%u", sid);
    char *args[] = {(char *)argv[0], "--child", ridText, sidText, NULL};
    posix_spawn_file_actions_t actions;
    int spawnError = posix_spawn_file_actions_init(&actions);
    if (!spawnError) {
      spawnError =
          posix_spawn_file_actions_adddup2(&actions, input[0], STDIN_FILENO);
      if (!spawnError)
        spawnError = posix_spawn_file_actions_adddup2(&actions, output[1],
                                                      STDOUT_FILENO);
      for (unsigned i = 0; i < 4 && !spawnError; i++)
        spawnError = posix_spawn_file_actions_addclose(
            &actions, ((int[]){input[0], input[1], output[0], output[1]})[i]);
      pid_t pid = 0;
      if (!spawnError)
        spawnError = posix_spawn(&pid, argv[0], &actions, NULL, args, environ);
      if (!spawnError)
        childPID = pid;
      posix_spawn_file_actions_destroy(&actions);
    }
    close(input[0]);
    close(output[1]);
    if (spawnError) {
      close(input[1]);
      close(output[0]);
      emit(@"spawn-error", @{@"errno" : @(spawnError)});
      return 7;
    }
    pid_t pid = childPID;
    Message msg;
    BOOL passed = nonblocking(input[1]) && nonblocking(output[0]);
    passed = passed && transfer(output[0], &msg, sizeof(msg), NO) &&
             msg.magic == magic && msg.kind == 0 && msg.round == UINT32_MAX &&
             msg.pid == (uint32_t)pid;
    emit(
        @"begin", @{
          @"ready" : @(passed),
          @"registry_id" : @(registry),
          @"surface_id" : @(sid),
          @"child_pid" : @(pid)
        });
    uint32_t completed = 0;
    uint64_t parentBad = 0, childBad = 0;
    for (uint32_t round = 0; passed && round < rounds; round++) {
      @autoreleasepool {
        fill(upload, round + 1);
        passed = copy(q, t, upload, YES);
        if (!passed)
          break;
        msg = (Message){magic, 1, round, (uint32_t)getpid(), 0};
        passed = transfer(input[1], &msg, sizeof(msg), YES) &&
                 transfer(output[0], &msg, sizeof(msg), NO) &&
                 msg.magic == magic && msg.kind == 2 && msg.round == round &&
                 msg.pid == (uint32_t)pid;
        if (!passed)
          break;
        childBad += msg.bad;
        if (msg.bad) {
          passed = NO;
          break;
        }
        passed = copy(q, t, readback, NO);
        if (!passed)
          break;
        uint64_t bad = mismatches(readback, round + 0x10000);
        parentBad += bad;
        emit(
            @"round", @{
              @"round" : @(round),
              @"parent_bad_pixels" : @(bad),
              @"child_bad_pixels" : @(msg.bad)
            });
        if (bad) {
          passed = NO;
          break;
        }
        completed++;
      }
    }
    close(input[1]);
    close(output[0]);
    int childStatus = 0;
    BOOL reaped = reap(pid, !passed, &childStatus);
    passed = passed && reaped && WIFEXITED(childStatus) &&
             WEXITSTATUS(childStatus) == 0 && completed == rounds && !expired;
    emit(
        @"result", @{
          @"passed" : @(passed),
          @"registry_id" : @(registry),
          @"surface_id" : @(sid),
          @"child_pid" : @(pid),
          @"child_reaped" : @(reaped),
          @"child_wait_status" : @(childStatus),
          @"rounds" : @(completed),
          @"pixels_each_direction" : @((uint64_t)width * height * completed),
          @"parent_bad_pixels" : @(parentBad),
          @"child_bad_pixels" : @(childBad)
        });
    alarm(0);
    return passed ? 0 : 1;
  }
}
