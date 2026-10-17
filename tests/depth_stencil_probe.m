// Depth/stencil and MSAA oracle probe.
// Usage: depth_stencil_probe <registryID>
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <dispatch/dispatch.h>
#include <signal.h>
#import <simd/simd.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static void timeout_handler(int sig) {
  (void)sig;
  const char m[] = "DEPTH_STENCIL_TIMEOUT\n";
  write(STDERR_FILENO, m, sizeof(m) - 1);
  _exit(124);
}
static void status(NSString *phase, NSString *state, NSDictionary *extra) {
  NSMutableDictionary *d = [@{@"phase" : phase, @"status" : state} mutableCopy];
  if (extra)
    [d addEntriesFromDictionary:extra];
  NSData *j = [NSJSONSerialization dataWithJSONObject:d options:0 error:nil];
  fwrite(j.bytes, 1, j.length, stdout);
  fputc('\n', stdout);
  fflush(stdout);
}

static NSString *shaderSource(void) {
  return @"#include <metal_stdlib>\nusing namespace metal;\n"
          "struct V { float4 p [[position]]; };\n"
          "struct U { float4 color; float depth; };\n"
          "vertex V vs(uint id [[vertex_id]]) { float2 "
          "p[4]={{-1,-1},{1,-1},{-1,1},{1,1}}; V v; v.p=float4(p[id],0,1); "
          "return v; }\n"
          "struct F { float4 c [[color(0)]]; float z [[depth(any)]]; };\n"
          "fragment F fs(constant U& u [[buffer(0)]]) { F f; f.c=u.color; "
          "f.z=u.depth; return f; }\n";
}

static id<MTLDepthStencilState> depthState(id<MTLDevice> d,
                                           MTLCompareFunction cmp,
                                           MTLStencilOperation pass,
                                           MTLStencilOperation fail) {
  MTLDepthStencilDescriptor *x = [MTLDepthStencilDescriptor new];
  x.depthCompareFunction = cmp;
  x.depthWriteEnabled = YES;
  MTLStencilDescriptor *s = [MTLStencilDescriptor new];
  s.stencilCompareFunction = MTLCompareFunctionAlways;
  s.stencilFailureOperation = fail;
  s.depthFailureOperation = fail;
  s.depthStencilPassOperation = pass;
  s.readMask = 0xff;
  s.writeMask = 0xff;
  x.frontFaceStencil = s;
  x.backFaceStencil = s;
  return [d newDepthStencilStateWithDescriptor:x];
}
static id<MTLDepthStencilState> stencilEqual2State(id<MTLDevice> d) {
  MTLDepthStencilDescriptor *x = [MTLDepthStencilDescriptor new];
  x.depthCompareFunction = MTLCompareFunctionLess;
  x.depthWriteEnabled = YES;
  MTLStencilDescriptor *s = [MTLStencilDescriptor new];
  s.stencilCompareFunction = MTLCompareFunctionEqual;
  s.stencilFailureOperation = MTLStencilOperationKeep;
  s.depthFailureOperation = MTLStencilOperationKeep;
  s.depthStencilPassOperation = MTLStencilOperationKeep;
  s.readMask = 0xff;
  s.writeMask = 0xff;
  s.stencilCompareFunction = MTLCompareFunctionEqual;
  x.frontFaceStencil = s;
  x.backFaceStencil = s;
  return [d newDepthStencilStateWithDescriptor:x];
}
static BOOL waitCommand(id<MTLCommandBuffer> cb, NSString *phase) {
  dispatch_semaphore_t sem = dispatch_semaphore_create(0);
  __block MTLCommandBufferStatus st = MTLCommandBufferStatusNotEnqueued;
  __block NSError *err = nil;
  [cb addCompletedHandler:^(id<MTLCommandBuffer> b) {
    st = b.status;
    err = b.error;
    dispatch_semaphore_signal(sem);
  }];
  [cb commit];
  long rc = dispatch_semaphore_wait(
      sem, dispatch_time(DISPATCH_TIME_NOW, 20LL * 1000000000LL));
  if (rc != 0) {
    status(phase, @"timeout", @{});
    return NO;
  }
  if (st != MTLCommandBufferStatusCompleted) {
    status(
        phase, @"command-failed", @{
          @"command_status" : @(st),
          @"error" : err.localizedDescription ?: @"unknown"
        });
    return NO;
  }
  [cb waitUntilCompleted];
  status(phase, @"complete", @{});
  return YES;
}
static BOOL readback(id<MTLDevice> d, id<MTLCommandQueue> q, id<MTLTexture> t,
                     uint32_t w, uint32_t h, NSData **out) {
  NSUInteger stride = ((NSUInteger)w * 4 + 255) & ~255UL, bytes = stride * h;
  id<MTLBuffer> b = [d newBufferWithLength:bytes
                                   options:MTLResourceStorageModeManaged];
  if (!b) {
    status(@"readback", @"buffer-create-failed", nil);
    return NO;
  }
  id<MTLCommandBuffer> cb = [q commandBuffer];
  if (!cb) {
    status(@"readback", @"command-create-failed", nil);
    return NO;
  }
  id<MTLBlitCommandEncoder> bl = [cb blitCommandEncoder];
  if (!bl) {
    status(@"readback", @"blit-create-failed", nil);
    return NO;
  }
  [bl copyFromTexture:t
                   sourceSlice:0
                   sourceLevel:0
                  sourceOrigin:MTLOriginMake(0, 0, 0)
                    sourceSize:MTLSizeMake(w, h, 1)
                      toBuffer:b
             destinationOffset:0
        destinationBytesPerRow:stride
      destinationBytesPerImage:bytes];
  [bl synchronizeResource:b];
  [bl endEncoding];
  if (!waitCommand(cb, @"readback-copy"))
    return NO;
  NSMutableData *packed = [NSMutableData dataWithLength:(NSUInteger)w * h * 4];
  for (NSUInteger y = 0; y < h; y++)
    memcpy((uint8_t *)packed.mutableBytes + y * w * 4,
           (const uint8_t *)b.contents + y * stride, w * 4);
  *out = packed;
  return YES;
}

int main(int argc, const char **argv) {
  @autoreleasepool {
    signal(SIGALRM, timeout_handler);
    alarm(180);
    if (argc != 2) {
      fprintf(stderr, "usage: %s <registryID>\n", argv[0]);
      return 2;
    }
    unsigned long long wanted = strtoull(argv[1], NULL, 0);
    id<MTLDevice> dev = nil;
    for (id<MTLDevice> d in MTLCopyAllDevices())
      if (d.registryID == wanted)
        dev = d;
    if (!dev) {
      status(
          @"device", @"requested-registry-id-not-found",
          @{@"registry_id" : @(wanted)});
      return 3;
    }
    status(
        @"device", @"selected",
        @{@"registry_id" : @(dev.registryID),
          @"name" : dev.name ?: @""});
    id<MTLCommandQueue> q = [dev newCommandQueue];
    if (!q) {
      status(@"queue", @"create-failed", nil);
      return 4;
    }
    NSError *e = nil;
    id<MTLLibrary> lib = [dev newLibraryWithSource:shaderSource()
                                           options:nil
                                             error:&e];
    if (!lib) {
      status(@"shader", @"compile-failed",
             @{@"error" : e.localizedDescription ?: @"unknown"});
      return 5;
    }
    id<MTLFunction> vs = [lib newFunctionWithName:@"vs"],
                    fs = [lib newFunctionWithName:@"fs"];
    if (!vs || !fs) {
      status(@"shader", @"function-missing", nil);
      return 6;
    }
    id<MTLDepthStencilState> replace =
        depthState(dev, MTLCompareFunctionLess, MTLStencilOperationReplace,
                   MTLStencilOperationKeep);
    id<MTLDepthStencilState> keep =
        depthState(dev, MTLCompareFunctionLess, MTLStencilOperationKeep,
                   MTLStencilOperationKeep);
    id<MTLDepthStencilState> equal = stencilEqual2State(dev);
    if (!replace || !keep || !equal) {
      status(@"depth-stencil-state", @"create-failed", nil);
      return 16;
    }
    uint64_t totalPixels = 0;
    unsigned cases = 0;
    for (NSUInteger si = 0; si < 2; si++) {
      NSUInteger samples = si ? 4 : 1;
      if (samples > 1 && ![dev supportsTextureSampleCount:samples]) {
        status(@"sample-count", @"unsupported", @{@"samples" : @(samples)});
        return 7;
      }
      for (NSUInteger shape = 0; shape < 2; shape++) {
        uint32_t w = shape ? 1003 : 64, h = shape ? 769 : 64;
        MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
        pd.vertexFunction = vs;
        pd.fragmentFunction = fs;
        pd.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
        pd.depthAttachmentPixelFormat = MTLPixelFormatDepth32Float_Stencil8;
        pd.stencilAttachmentPixelFormat = MTLPixelFormatDepth32Float_Stencil8;
        pd.sampleCount = samples;
        id<MTLRenderPipelineState> p =
            [dev newRenderPipelineStateWithDescriptor:pd error:&e];
        if (!p) {
          status(
              @"pipeline", @"create-failed", @{
                @"samples" : @(samples),
                @"width" : @(w),
                @"height" : @(h),
                @"error" : e.localizedDescription ?: @"unknown"
              });
          return 8;
        }
        MTLTextureDescriptor *cd = [MTLTextureDescriptor
            texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
                                         width:w
                                        height:h
                                     mipmapped:NO];
        cd.storageMode = MTLStorageModePrivate;
        cd.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
        cd.sampleCount = samples;
        cd.textureType =
            samples > 1 ? MTLTextureType2DMultisample : MTLTextureType2D;
        id<MTLTexture> color = [dev newTextureWithDescriptor:cd];
        MTLTextureDescriptor *rd =
            [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:
                                      MTLPixelFormatDepth32Float_Stencil8
                                                               width:w
                                                              height:h
                                                           mipmapped:NO];
        rd.storageMode = MTLStorageModePrivate;
        rd.usage = MTLTextureUsageRenderTarget;
        rd.sampleCount = samples;
        rd.textureType =
            samples > 1 ? MTLTextureType2DMultisample : MTLTextureType2D;
        id<MTLTexture> ds = [dev newTextureWithDescriptor:rd];
        id<MTLTexture> resolved = color;
        if (!color || !ds) {
          status(
              @"resources", @"texture-create-failed",
              @{@"samples" : @(samples)});
          return 9;
        }
        if (samples > 1) {
          MTLTextureDescriptor *r = [MTLTextureDescriptor
              texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
                                           width:w
                                          height:h
                                       mipmapped:NO];
          r.storageMode = MTLStorageModePrivate;
          r.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
          resolved = [dev newTextureWithDescriptor:r];
          if (!resolved) {
            status(@"resources", @"resolve-texture-create-failed", nil);
            return 10;
          }
        }
        for (NSUInteger round = 0; round < 32; round++) {
          @autoreleasepool {
            id<MTLCommandBuffer> cb = [q commandBuffer];
            if (!cb) {
              status(
                  @"round", @"command-create-failed",
                  @{@"round" : @(round)});
              return 11;
            }
            MTLRenderPassDescriptor *rp =
                [MTLRenderPassDescriptor renderPassDescriptor];
            rp.colorAttachments[0].texture = color;
            rp.colorAttachments[0].resolveTexture =
                samples > 1 ? resolved : nil;
            rp.colorAttachments[0].loadAction = MTLLoadActionClear;
            rp.colorAttachments[0].storeAction =
                samples > 1 ? MTLStoreActionMultisampleResolve
                            : MTLStoreActionStore;
            rp.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 0, 1);
            rp.depthAttachment.texture = ds;
            rp.depthAttachment.loadAction = MTLLoadActionClear;
            rp.depthAttachment.storeAction = MTLStoreActionDontCare;
            rp.depthAttachment.clearDepth = 1.0;
            rp.stencilAttachment.texture = ds;
            rp.stencilAttachment.loadAction = MTLLoadActionClear;
            rp.stencilAttachment.storeAction = MTLStoreActionDontCare;
            rp.stencilAttachment.clearStencil = 0;
            id<MTLRenderCommandEncoder> re =
                [cb renderCommandEncoderWithDescriptor:rp];
            if (!re) {
              status(
                  @"round", @"encoder-create-failed",
                  @{@"round" : @(round)});
              return 12;
            }
            [re setRenderPipelineState:p];
            struct U {
              vector_float4 color;
              float depth;
            };
            struct U u;
            [re setDepthStencilState:replace];
            [re setStencilReferenceValue:1];
            u = (struct U){(vector_float4){1, 0, 0, 1}, .6f};
            [re setFragmentBytes:&u length:sizeof(u) atIndex:0];
            [re drawPrimitives:MTLPrimitiveTypeTriangleStrip
                   vertexStart:0
                   vertexCount:4];
            MTLScissorRect left = ((MTLScissorRect){0, 0, w / 2, h});
            [re setScissorRect:left];
            [re setStencilReferenceValue:2];
            u = (struct U){(vector_float4){0, 1, 0, 1}, .2f};
            [re setFragmentBytes:&u length:sizeof(u) atIndex:0];
            [re drawPrimitives:MTLPrimitiveTypeTriangleStrip
                   vertexStart:0
                   vertexCount:4];
            [re setScissorRect:((MTLScissorRect){0, 0, w, h})];
            [re setDepthStencilState:keep];
            [re setStencilReferenceValue:1];
            u = (struct U){(vector_float4){0, 0, 1, 1}, .8f};
            [re setFragmentBytes:&u length:sizeof(u) atIndex:0];
            [re drawPrimitives:MTLPrimitiveTypeTriangleStrip
                   vertexStart:0
                   vertexCount:4];
            [re setDepthStencilState:equal];
            [re setStencilReferenceValue:2];
            BOOL alt = (round & 1) != 0;
            u = (struct U){alt ? (vector_float4){0, 1, 1, 1}
                               : (vector_float4){1, 0, 1, 1},
                           .05f};
            [re setFragmentBytes:&u length:sizeof(u) atIndex:0];
            [re drawPrimitives:MTLPrimitiveTypeTriangleStrip
                   vertexStart:0
                   vertexCount:4];
            [re endEncoding];
            if (!waitCommand(cb, @"render"))
              return 13;
            NSData *data = nil;
            if (!readback(dev, q, resolved, w, h, &data))
              return 14;
            const uint8_t *px = data.bytes;
            NSUInteger mism = 0, first = 0;
            uint8_t want[4];
            for (uint32_t y = 0; y < h; y++)
              for (uint32_t x = 0; x < w; x++) {
                BOOL leftx = x < w / 2;
                BOOL altc = (round & 1) != 0;
                if (leftx) {
                  want[0] = altc ? 0 : 255;
                  want[1] = altc ? 255 : 0;
                  want[2] = 255;
                } else {
                  want[0] = 255;
                  want[1] = 0;
                  want[2] = 0;
                }
                want[3] = 255;
                const uint8_t *got = px + ((NSUInteger)y * w + x) * 4;
                if (got[0] != want[0] || got[1] != want[1] ||
                    got[2] != want[2] || got[3] != want[3]) {
                  if (!mism)
                    first = ((NSUInteger)y * w + x);
                  mism++;
                }
              }
            status(
                @"round", mism ? @"mismatch" : @"pass", @{
                  @"samples" : @(samples),
                  @"width" : @(w),
                  @"height" : @(h),
                  @"round" : @(round),
                  @"pixel_count" : @((NSUInteger)w * h),
                  @"mismatch_count" : @(mism),
                  @"first_x" : @(mism ? (first % w) : NSNotFound),
                  @"first_y" : @(mism ? (first / w) : NSNotFound)
                });
            if (mism)
              return 15;
            totalPixels += (uint64_t)w * h;
            cases++;
          }
        }
      }
    }
    status(
        @"result", @"pass",
        @{@"cases" : @(cases),
          @"pixels" : @(totalPixels)});
    alarm(0);
    return 0;
  }
}
