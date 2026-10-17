// Build twice: RGPU_XPC_SERVICE selects the bundled NSXPC helper.
// Consumer commits GPU wait/read before producer commits upload/GPU signal.
#import <Foundation/Foundation.h>
#import <IOSurface/IOSurface.h>
#import <Metal/Metal.h>
#include <errno.h>
#include <signal.h>
#include <unistd.h>
static const uint32_t width = 1003, height = 769, rowBytes = 4096;
static void watchdog(int unused) {
  (void)unused;
  _exit(124);
}
static void emit(NSString *phase, NSDictionary *extra) {
  NSMutableDictionary *d = [extra mutableCopy];
  d[@"phase"] = phase;
  d[@"pid"] = @(getpid());
  NSData *j = [NSJSONSerialization dataWithJSONObject:d options:0 error:NULL];
  fwrite(j.bytes, 1, j.length, stdout);
  fputc('\n', stdout);
  fflush(stdout);
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
@protocol Probe
- (void)configure:(NSDictionary *)config
            event:(MTLSharedEventHandle *)handle
            reply:(void (^)(NSDictionary *))reply;
- (void)submit:(uint32_t)round reply:(void (^)(NSDictionary *))reply;
- (void)finish:(uint32_t)round reply:(void (^)(NSDictionary *))reply;
- (void)shutdown:(void (^)(NSDictionary *))reply;
@end
static NSXPCInterface *interface(void) {
  NSXPCInterface *i = [NSXPCInterface interfaceWithProtocol:@protocol(Probe)];
  [i setClasses:[NSSet setWithObject:[MTLSharedEventHandle class]]
        forSelector:@selector(configure:event:reply:)
      argumentIndex:1
            ofReply:NO];
  return i;
}
static BOOL awaitGPU(id<MTLCommandBuffer> cb, dispatch_semaphore_t done) {
  if (dispatch_semaphore_wait(
          done, dispatch_time(DISPATCH_TIME_NOW, 20 * NSEC_PER_SEC)))
    return NO;
  [cb waitUntilCompleted];
  return cb.status == MTLCommandBufferStatusCompleted;
}
#if RGPU_XPC_SERVICE
@interface Worker : NSObject <Probe>
@property(strong) NSXPCConnection *connection;
@property(strong) id owner;
@property(strong) id<MTLDevice> gpu;
@property(strong) id<MTLCommandQueue> queue;
@property(strong) id<MTLTexture> surface;
@property(strong) id<MTLBuffer> readback;
@property(strong) id<MTLSharedEvent> event;
@property(strong) id<MTLCommandBuffer> pending;
@property(strong) dispatch_semaphore_t done;
@property uint32_t completed;
@property BOOL configured;
@end
@implementation Worker
- (void)configure:(NSDictionary *)config
            event:(MTLSharedEventHandle *)handle
            reply:(void (^)(NSDictionary *))reply {
  @synchronized(self) {
    if (self.configured ||
        self.connection.processIdentifier != [config[@"parent_pid"] intValue] ||
        self.connection.effectiveUserIdentifier != getuid()) {
      reply(@{@"passed" : @NO, @"error" : @"peer-or-repeat"});
      return;
    }
    self.gpu = device([config[@"registry_id"] unsignedLongLongValue]);
    uint32_t sid = [config[@"surface_id"] unsignedIntValue];
    IOSurfaceRef s = IOSurfaceLookup(sid);
    if (!self.gpu || !s) {
      if (s)
        CFRelease(s);
      reply(@{@"passed" : @NO, @"error" : @"device-or-surface"});
      return;
    }
    self.owner = CFBridgingRelease(s);
    self.surface = texture(self.gpu, s);
    self.queue = [self.gpu newCommandQueue];
    self.readback =
        [self.gpu newBufferWithLength:(NSUInteger)rowBytes * height
                              options:MTLResourceStorageModeManaged];
    self.event = [self.gpu newSharedEventWithHandle:handle];
    self.configured = self.owner && IOSurfaceGetID(s) == sid && self.surface &&
                      self.queue && self.readback && self.event &&
                      self.event.signaledValue == 0;
    reply(@{
      @"passed" : @(self.configured),
      @"pid" : @(getpid()),
      @"uid" : @(getuid()),
      @"registry_id" : @(self.gpu.registryID),
      @"surface_id" : @(sid),
      @"nonce" : config[@"nonce"] ?: @"",
      @"gpu_submissions" : @0
    });
  }
}
- (void)submit:(uint32_t)round reply:(void (^)(NSDictionary *))reply {
  @synchronized(self) {
    uint64_t v = (uint64_t)round + 1;
    if (!self.configured || self.pending || round != self.completed ||
        round >= 32 || self.event.signaledValue >= v) {
      reply(@{@"passed" : @NO, @"error" : @"submit-state"});
      return;
    }
    id<MTLCommandBuffer> cb = [self.queue commandBuffer];
    if (!cb) {
      reply(@{@"passed" : @NO});
      return;
    }
    [cb encodeWaitForEvent:self.event value:v];
    id<MTLBlitCommandEncoder> bl = [cb blitCommandEncoder];
    if (!bl) {
      reply(@{@"passed" : @NO});
      return;
    }
    [bl copyFromTexture:self.surface
                     sourceSlice:0
                     sourceLevel:0
                    sourceOrigin:MTLOriginMake(0, 0, 0)
                      sourceSize:MTLSizeMake(width, height, 1)
                        toBuffer:self.readback
               destinationOffset:0
          destinationBytesPerRow:rowBytes
        destinationBytesPerImage:(NSUInteger)rowBytes * height];
    [bl synchronizeResource:self.readback];
    [bl endEncoding];
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    [cb addCompletedHandler:^(id<MTLCommandBuffer> b) {
      (void)b;
      dispatch_semaphore_signal(done);
    }];
    self.pending = cb;
    self.done = done;
    [cb commit];
    reply(@{
      @"passed" : @YES,
      @"pid" : @(getpid()),
      @"round" : @(round),
      @"wait_value" : @(v),
      @"consumer_committed" : @YES
    });
  }
}
- (void)finish:(uint32_t)round reply:(void (^)(NSDictionary *))reply {
  @synchronized(self) {
    if (!self.pending || round != self.completed) {
      reply(@{@"passed" : @NO, @"error" : @"finish-state"});
      return;
    }
    BOOL gpu = awaitGPU(self.pending, self.done);
    uint64_t bad = gpu ? mismatches(self.readback, round + 1) : UINT64_MAX;
    if (gpu) {
      self.pending = nil;
      self.done = nil;
    }
    if (gpu && !bad)
      self.completed++;
    reply(@{
      @"passed" : @(gpu && !bad),
      @"pid" : @(getpid()),
      @"round" : @(round),
      @"bad_pixels" : @(bad),
      @"pixels" : @((uint64_t)width * height),
      @"gpu_completed" : @(gpu)
    });
  }
}
- (void)shutdown:(void (^)(NSDictionary *))reply {
  @synchronized(self) {
    BOOL idle = self.pending == nil;
    reply(@{
      @"passed" : @(idle),
      @"pid" : @(getpid()),
      @"completed_rounds" : @(self.completed),
      @"exit_requested" : @YES
    });
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC),
                   dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{
                     exit(idle ? 0 : 1);
                   });
  }
}
@end
@interface Listener : NSObject <NSXPCListenerDelegate>
@property BOOL accepted;
@end
@implementation Listener
- (BOOL)listener:(NSXPCListener *)listener
    shouldAcceptNewConnection:(NSXPCConnection *)connection {
  (void)listener;
  @synchronized(self) {
    if (self.accepted || connection.effectiveUserIdentifier != getuid())
      return NO;
    self.accepted = YES;
  }
  Worker *w = [Worker new];
  w.connection = connection;
  connection.exportedInterface = interface();
  connection.exportedObject = w;
  connection.invalidationHandler = ^{
    exit(2);
  };
  [connection resume];
  return YES;
}
@end
int main(void) {
  @autoreleasepool {
    signal(SIGALRM, watchdog);
    alarm(180);
    Listener *delegate = [Listener new];
    NSXPCListener *listener = [NSXPCListener serviceListener];
    listener.delegate = delegate;
    [listener resume];
    [[NSRunLoop currentRunLoop] run];
    return 3;
  }
}
#else
@interface Answer : NSObject
@property(strong) NSDictionary *result;
@property(strong) dispatch_semaphore_t done;
- (void)accept:(NSDictionary *)value;
@end
@implementation Answer
- (instancetype)init {
  if ((self = [super init]))
    _done = dispatch_semaphore_create(0);
  return self;
}
- (void)accept:(NSDictionary *)value {
  @synchronized(self) {
    if (!self.result) {
      self.result = value;
      dispatch_semaphore_signal(self.done);
    }
  }
}
@end
static NSDictionary *rpc(NSXPCConnection *c,
                         void (^invoke)(id<Probe>, void (^)(NSDictionary *))) {
  Answer *a = [Answer new];
  id<Probe> proxy = [c remoteObjectProxyWithErrorHandler:^(NSError *e) {
    [a accept:@{@"passed" : @NO, @"error" : e.description ?: @"XPC"}];
  }];
  invoke(proxy, ^(NSDictionary *d) {
    [a accept:d];
  });
  if (dispatch_semaphore_wait(
          a.done, dispatch_time(DISPATCH_TIME_NOW, 25 * NSEC_PER_SEC)))
    return @{@"passed" : @NO, @"error" : @"RPC-timeout"};
  @synchronized(a) {
    return a.result;
  }
}
static BOOL produce(id<MTLCommandQueue> q, id<MTLTexture> t, id<MTLBuffer> b,
                    id<MTLSharedEvent> event, uint64_t v) {
  id<MTLCommandBuffer> cb = [q commandBuffer];
  id<MTLBlitCommandEncoder> bl = [cb blitCommandEncoder];
  if (!cb || !bl)
    return NO;
  [bl copyFromBuffer:b
             sourceOffset:0
        sourceBytesPerRow:rowBytes
      sourceBytesPerImage:(NSUInteger)rowBytes * height
               sourceSize:MTLSizeMake(width, height, 1)
                toTexture:t
         destinationSlice:0
         destinationLevel:0
        destinationOrigin:MTLOriginMake(0, 0, 0)];
  [bl endEncoding];
  [cb encodeSignalEvent:event value:v];
  dispatch_semaphore_t done = dispatch_semaphore_create(0);
  [cb addCompletedHandler:^(id<MTLCommandBuffer> b) {
    (void)b;
    dispatch_semaphore_signal(done);
  }];
  [cb commit];
  return awaitGPU(cb, done);
}
int main(int argc, const char **argv) {
  @autoreleasepool {
    signal(SIGALRM, watchdog);
    alarm(180);
    if (argc != 3)
      return 2;
    uint64_t registry = strtoull(argv[1], NULL, 0);
    uint32_t rounds = (uint32_t)strtoul(argv[2], NULL, 0);
    if (rounds > 32)
      return 2;
    id<MTLDevice> d = device(registry);
    if (!d)
      return 3;
    IOSurfaceRef s = IOSurfaceCreate((__bridge CFDictionaryRef) @{
      (id)kIOSurfaceWidth : @(width),
      (id)kIOSurfaceHeight : @(height),
      (id)kIOSurfaceBytesPerElement : @4,
      (id)kIOSurfaceBytesPerRow : @(rowBytes),
      (id)kIOSurfaceAllocSize : @((NSUInteger)rowBytes * height),
      (id)kIOSurfacePixelFormat : @(0x42475241),
      (id)kIOSurfaceIsGlobal : @YES
    });
    if (!s)
      return 4;
    __attribute__((objc_precise_lifetime)) id owner = CFBridgingRelease(s);
    uint32_t sid = IOSurfaceGetID(s);
    id<MTLTexture> t = texture(d, s);
    id<MTLBuffer> upload =
        [d newBufferWithLength:(NSUInteger)rowBytes * height
                       options:MTLResourceStorageModeManaged];
    id<MTLCommandQueue> q = [d newCommandQueue];
    id<MTLSharedEvent> event = [d newSharedEvent];
    MTLSharedEventHandle *handle = [event newSharedEventHandle];
    if (!owner || !t || !upload || !q || !event || !handle ||
        event.signaledValue != 0)
      return 5;
    NSXPCConnection *c = [[NSXPCConnection alloc]
        initWithServiceName:@"org.raphael.GPUEventProbe.Worker"];
    c.remoteObjectInterface = interface();
    [c resume];
    NSString *nonce = [NSUUID UUID].UUIDString;
    NSDictionary *config = @{
      @"parent_pid" : @(getpid()),
      @"registry_id" : @(registry),
      @"surface_id" : @(sid),
      @"nonce" : nonce
    };
    NSDictionary *ready = rpc(c, ^(id<Probe> p, void (^reply)(NSDictionary *)) {
      [p configure:config event:handle reply:reply];
    });
    emit(@"transport", ready);
    pid_t worker = [ready[@"pid"] intValue];
    BOOL ok = [ready[@"passed"] boolValue] && worker > 0 &&
              worker != getpid() &&
              [ready[@"uid"] unsignedIntValue] == getuid() &&
              [ready[@"registry_id"] unsignedLongLongValue] == registry &&
              [ready[@"surface_id"] unsignedIntValue] == sid &&
              [ready[@"nonce"] isEqual:nonce] &&
              [ready[@"gpu_submissions"] unsignedIntValue] == 0;
    uint32_t completed = 0;
    uint64_t bad = 0;
    for (uint32_t r = 0; ok && r < rounds; r++) {
      @autoreleasepool {
        fill(upload, r + 1);
        NSDictionary *submitted =
            rpc(c, ^(id<Probe> p, void (^reply)(NSDictionary *)) {
              [p submit:r reply:reply];
            });
        emit(@"consumer-submitted", submitted);
        ok = [submitted[@"passed"] boolValue] &&
             [submitted[@"pid"] intValue] == worker &&
             [submitted[@"round"] unsignedIntValue] == r &&
             [submitted[@"wait_value"] unsignedLongLongValue] ==
                 (uint64_t)r + 1 &&
             [submitted[@"consumer_committed"] boolValue];
        if (!ok)
          break;
        ok = produce(q, t, upload, event, (uint64_t)r + 1);
        if (!ok) {
          emit(@"producer-error", @{@"round" : @(r)});
          break;
        }
        NSDictionary *result =
            rpc(c, ^(id<Probe> p, void (^reply)(NSDictionary *)) {
              [p finish:r reply:reply];
            });
        emit(@"round", result);
        ok = [result[@"passed"] boolValue] &&
             [result[@"pid"] intValue] == worker &&
             [result[@"round"] unsignedIntValue] == r &&
             [result[@"gpu_completed"] boolValue] &&
             [result[@"pixels"] unsignedLongLongValue] ==
                 (uint64_t)width * height;
        bad += [result[@"bad_pixels"] unsignedLongLongValue];
        if (ok)
          completed++;
      }
    }
    NSDictionary *stopped =
        rpc(c, ^(id<Probe> p, void (^reply)(NSDictionary *)) {
          [p shutdown:reply];
        });
    emit(@"helper-shutdown", stopped);
    BOOL ack = [stopped[@"passed"] boolValue] &&
               [stopped[@"pid"] intValue] == worker &&
               [stopped[@"exit_requested"] boolValue] &&
               [stopped[@"completed_rounds"] unsignedIntValue] == completed;
    BOOL gone = NO;
    if (worker > 0) {
      for (int i = 0; i < 50; i++) {
        if (kill(worker, 0) < 0 && errno == ESRCH) {
          gone = YES;
          break;
        }
        usleep(100000);
      }
    }
    [c invalidate];
    ok = ok && ack && gone && completed == rounds && !bad;
    emit(
        @"result", @{
          @"passed" : @(ok),
          @"registry_id" : @(registry),
          @"surface_id" : @(sid),
          @"worker_pid" : @(worker),
          @"rounds" : @(completed),
          @"pixels" : @((uint64_t)width * height * completed),
          @"bad_pixels" : @(bad),
          @"helper_shutdown_ack" : @(ack),
          @"helper_absent" : @(gone),
          @"transport_only" : @(rounds == 0)
        });
    alarm(0);
    return ok ? 0 : 1;
  }
}
#endif
