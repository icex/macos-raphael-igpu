// dcc_wedge_probe: discriminate the wedge-shaped, 8x8-grid artifacts seen over translucent
// desktop regions on the Raphael iGPU (macOS 24G830, RaphaelGPU 1.0.230, bit-27 patch on).
//
// Method: a placement MTLHeap lets us poison the exact memory a render target will occupy
// (every poison pixel encodes its own coordinates), then re-create the target on the same
// bytes and run composite-like passes (clear / load, opaque / blended, quads as two
// triangles with a steep shared diagonal, many small quads, a rotated triangle, a compute
// UAV write) with allowGPUOptimizedContents YES vs NO. The target is read back through
// three consumers (blit, fragment sample, compute read). Each mismatched pixel is classified
// against the poison encoding (same pixel / other pixel + displacement), the clear color,
// the draw color, or "other", and aggregated per 8x8 tile and per distance to the quad
// diagonal. Blocks matching poison => stale memory exposed (DCC/fast-clear metadata not
// covering the data); blocks matching content from elsewhere => addressing; nothing => the
// defect needs WindowServer's real materials (IOSurface-backed, blur) to reproduce.
//
// Usage: dcc_wedge_probe [png-dir] [iterations]     (defaults /tmp/dcc_wedge, 20)
// Output: one "DCC_WEDGE {json}" line per case, then "DCC_WEDGE_SUMMARY {json}".
// Exit 2 on no device / shader failure / stalled command buffer (DCC_WEDGE_TIMEOUT <case>).
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <CoreGraphics/CoreGraphics.h>
#import <ImageIO/ImageIO.h>
#import <dispatch/dispatch.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

enum { W = 1920, H = 1080, TILE = 8 };
enum { kMaxPngPairs = 6, kMaxDisplacementRecords = 100000 };
static const double kDeadlineSeconds = 20.0;

// Colors as 8-bit values so unblended expectations are exact.
static const uint8_t kClearRGBA[4] = { 64, 26, 115, 255 };   // purple, like a blurred sidebar
static const uint8_t kDrawRGBA[4]  = { 51, 230, 77, 255 };   // green, like the observed wedges
static const float kBlendAlpha = 0.5f;
static const uint8_t kPoisonAlpha = 0xA5;

static NSString *const kShaderSource =
    @"#include <metal_stdlib>\nusing namespace metal;\n"
     "struct V { float4 p [[position]]; };\n"
     "vertex V vs_pos(uint id [[vertex_id]], constant float2 *pts [[buffer(0)]]) {\n"
     "  V v; v.p = float4(pts[id], 0, 1); return v; }\n"
     "vertex V vs_full(uint id [[vertex_id]]) {\n"
     "  const float2 q[3] = { float2(-1, -1), float2(3, -1), float2(-1, 3) };\n"
     "  V v; v.p = float4(q[id], 0, 1); return v; }\n"
     "fragment float4 fs_const(V in [[stage_in]], constant float4 &c [[buffer(0)]]) { return c; }\n"
     "fragment float4 fs_poison(V in [[stage_in]]) {\n"
     "  uint x = uint(in.p.x), y = uint(in.p.y);\n"
     "  uint b = ((x >> 8) << 4) | (y >> 8);\n"
     "  return float4(float(x & 255u) / 255.0f, float(y & 255u) / 255.0f, float(b & 255u) / 255.0f, 165.0f / 255.0f); }\n"
     "fragment float4 fs_sample(V in [[stage_in]], texture2d<float> t [[texture(0)]]) {\n"
     "  return t.read(uint2(in.p.xy)); }\n"
     "kernel void k_read(texture2d<float> t [[texture(0)]], device uint *out [[buffer(0)]],\n"
     "                   uint2 gid [[thread_position_in_grid]]) {\n"
     "  if (gid.x >= t.get_width() || gid.y >= t.get_height()) return;\n"
     "  float4 v = t.read(gid);\n"
     "  uint4 u = uint4(round(saturate(v) * 255.0f));\n"
     "  out[gid.y * t.get_width() + gid.x] = u.z | (u.y << 8) | (u.x << 16) | (u.w << 24); }\n"
     "kernel void k_write(texture2d<float, access::write> t [[texture(0)]], constant float4 &c [[buffer(0)]],\n"
     "                    constant uint4 &r [[buffer(1)]], uint2 gid [[thread_position_in_grid]]) {\n"
     "  if (gid.x >= r.z || gid.y >= r.w) return;\n"
     "  t.write(c, gid + r.xy); }\n";

typedef enum { ShapeClear, ShapeFullTri, ShapeQuad, ShapeSmallQuads, ShapeRotTri, ShapeUAVRect } Shape;
typedef enum { ConsumerBlit, ConsumerSample, ConsumerCompute } Consumer;

typedef struct {
    Shape shape; BOOL blend; BOOL loadExisting; BOOL gpuOptimized; Consumer consumer; BOOL heap;
} Case;

typedef struct { float x0, y0, x1, y1; } Rect;
typedef struct { float x[3], y[3]; } Tri;

// Geometry in pixels. The quad is tall and narrow so its shared diagonal is steep (~2.8).
static const Rect kQuad = { 200, 150, 360, 600 };
static const Tri kRotTri = { { 900, 1000, 820 }, { 200, 700, 650 } };
enum { kSmallQuadCount = 40, kSmallQuadW = 24, kSmallQuadH = 18 };
static Rect gSmallQuads[kSmallQuadCount];
static const Rect kUAVRect = { 1200, 300, 1360, 750 };

static uint32_t packBGRA(const uint8_t rgba[4]) {
    return (uint32_t)rgba[2] | ((uint32_t)rgba[1] << 8) | ((uint32_t)rgba[0] << 16) | ((uint32_t)rgba[3] << 24);
}
static uint32_t poisonValue(uint32_t x, uint32_t y) {
    uint8_t rgba[4] = { (uint8_t)(x & 255), (uint8_t)(y & 255), (uint8_t)(((x >> 8) << 4) | (y >> 8)), kPoisonAlpha };
    return packBGRA(rgba);
}
static BOOL decodePoison(uint32_t v, uint32_t *x, uint32_t *y) {
    if ((v >> 24) != kPoisonAlpha) return NO;
    uint32_t r = (v >> 16) & 255, g = (v >> 8) & 255, b = v & 255;
    *x = r | ((b >> 4) << 8); *y = g | ((b & 15) << 8);
    return *x < W && *y < H;
}
static BOOL near8(uint32_t a, uint32_t b) {
    for (int i = 0; i < 4; ++i) {
        int d = (int)((a >> (8 * i)) & 255) - (int)((b >> (8 * i)) & 255);
        if (d > 1 || d < -1) return NO;
    }
    return YES;
}

static void initSmallQuads(void) {
    uint32_t s = 0x9E3779B9u;   // deterministic LCG so every run draws the same rects
    for (int i = 0; i < kSmallQuadCount; ++i) {
        s = s * 1664525u + 1013904223u; float x = 40 + (float)(s >> 8) / 16777216.0f * (W - 120);
        s = s * 1664525u + 1013904223u; float y = 40 + (float)(s >> 8) / 16777216.0f * (H - 120);
        gSmallQuads[i] = (Rect){ floorf(x), floorf(y), floorf(x) + kSmallQuadW, floorf(y) + kSmallQuadH };
    }
}

// Geometry helpers --------------------------------------------------------------------------
static float distToSegment(float px, float py, float ax, float ay, float bx, float by) {
    float vx = bx - ax, vy = by - ay, wx = px - ax, wy = py - ay;
    float len2 = vx * vx + vy * vy;
    float t = len2 > 0 ? (wx * vx + wy * vy) / len2 : 0;
    t = t < 0 ? 0 : (t > 1 ? 1 : t);
    float dx = px - (ax + t * vx), dy = py - (ay + t * vy);
    return sqrtf(dx * dx + dy * dy);
}
static BOOL insideTri(float px, float py, const Tri *t) {
    float d[3];
    for (int i = 0; i < 3; ++i) {
        int j = (i + 1) % 3;
        d[i] = (t->x[j] - t->x[i]) * (py - t->y[i]) - (t->y[j] - t->y[i]) * (px - t->x[i]);
    }
    return (d[0] >= 0 && d[1] >= 0 && d[2] >= 0) || (d[0] <= 0 && d[1] <= 0 && d[2] <= 0);
}
static float triEdgeDistance(float px, float py, const Tri *t) {
    float m = 1e9f;
    for (int i = 0; i < 3; ++i) {
        int j = (i + 1) % 3;
        float d = distToSegment(px, py, t->x[i], t->y[i], t->x[j], t->y[j]);
        if (d < m) m = d;
    }
    return m;
}
static float rectEdgeDistance(float px, float py, const Rect *r) {
    // Only meaningful near the rect; far away the border bands must not be excluded.
    if (px < r->x0 - 2 || px > r->x1 + 2 || py < r->y0 - 2 || py > r->y1 + 2) return 1e9f;
    float d = fabsf(px - r->x0); float e = fabsf(px - r->x1); if (e < d) d = e;
    e = fabsf(py - r->y0); if (e < d) d = e; e = fabsf(py - r->y1); if (e < d) d = e;
    return d;
}
static BOOL insideRect(float px, float py, const Rect *r) {
    return px >= r->x0 && px < r->x1 && py >= r->y0 && py < r->y1;
}

// Vertex buffers: pixel rects as two triangles sharing the (x1,y0)-(x0,y1) diagonal.
static void ndc(float px, float py, float *out) { out[0] = px / W * 2 - 1; out[1] = 1 - py / H * 2; }
static NSUInteger appendRect(float *v, NSUInteger n, const Rect *r) {
    const float xs[6] = { r->x0, r->x1, r->x0,  r->x1, r->x1, r->x0 };
    const float ys[6] = { r->y0, r->y0, r->y1,  r->y0, r->y1, r->y1 };
    for (int i = 0; i < 6; ++i) ndc(xs[i], ys[i], v + 2 * (n + i));
    return n + 6;
}

// Expected image + flags for a case (independent of iteration). flag bit0 = edge-excluded,
// bit1 = near a quad diagonal (within 8 px).
static void buildExpected(const Case *c, uint32_t *expected, uint8_t *flags) {
    const uint32_t clearV = packBGRA(kClearRGBA), drawV = packBGRA(kDrawRGBA);
    uint8_t blended[4];
    for (int i = 0; i < 3; ++i) blended[i] = (uint8_t)lrintf(kDrawRGBA[i] * kBlendAlpha + kClearRGBA[i] * (1 - kBlendAlpha));
    blended[3] = (uint8_t)lrintf(255 * (kBlendAlpha + (1 - kBlendAlpha) * (kClearRGBA[3] / 255.0f)));
    const uint32_t drawnV = c->blend ? packBGRA(blended) : drawV;
    for (uint32_t y = 0; y < H; ++y) {
        for (uint32_t x = 0; x < W; ++x) {
            float px = x + 0.5f, py = y + 0.5f;
            BOOL covered = NO; float edge = 1e9f; BOOL nearDiag = NO;
            switch (c->shape) {
                case ShapeClear: break;
                case ShapeFullTri: covered = YES; break;
                case ShapeQuad:
                    covered = insideRect(px, py, &kQuad); edge = rectEdgeDistance(px, py, &kQuad);
                    nearDiag = distToSegment(px, py, kQuad.x1, kQuad.y0, kQuad.x0, kQuad.y1) <= 8;
                    break;
                case ShapeSmallQuads:
                    for (int i = 0; i < kSmallQuadCount; ++i) {
                        const Rect *r = &gSmallQuads[i];
                        if (insideRect(px, py, r)) covered = YES;
                        float d = rectEdgeDistance(px, py, r);
                        if (px > r->x0 - 2 && px < r->x1 + 2 && py > r->y0 - 2 && py < r->y1 + 2 && d < edge) edge = d;
                        if (px > r->x0 - 9 && px < r->x1 + 9 && py > r->y0 - 9 && py < r->y1 + 9 &&
                            distToSegment(px, py, r->x1, r->y0, r->x0, r->y1) <= 8) nearDiag = YES;
                    }
                    break;
                case ShapeRotTri: covered = insideTri(px, py, &kRotTri); edge = triEdgeDistance(px, py, &kRotTri); break;
                case ShapeUAVRect: covered = insideRect(px, py, &kUAVRect); edge = rectEdgeDistance(px, py, &kUAVRect); break;
            }
            uint8_t f = 0;
            if (edge < 1.0f) f |= 1;
            if (nearDiag) f |= 2;
            flags[y * W + x] = f;
            expected[y * W + x] = covered ? (c->shape == ShapeUAVRect ? drawV : drawnV) : clearV;
        }
    }
}

// Metal plumbing ----------------------------------------------------------------------------
static id<MTLDevice> gDevice; static id<MTLCommandQueue> gQueue; static id<MTLLibrary> gLibrary;
static id<MTLRenderPipelineState> gPoisonPipeline, gSamplePipeline, gConstOpaque, gConstBlend;
static id<MTLComputePipelineState> gReadKernel, gWriteKernel;
static id<MTLBuffer> gReadback, gQuadVB, gSmallVB, gTriVB;
static NSString *gCurrentCase = @"init";

static BOOL submitAndWait(id<MTLCommandBuffer> cb) {
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    [cb addCompletedHandler:^(id<MTLCommandBuffer> completed) { dispatch_semaphore_signal(done); }];
    [cb commit];
    if (dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, (int64_t)(kDeadlineSeconds * NSEC_PER_SEC))) != 0) {
        printf("DCC_WEDGE_TIMEOUT %s\n", gCurrentCase.UTF8String); fflush(stdout); exit(2);
    }
    if (cb.status != MTLCommandBufferStatusCompleted) {
        printf("DCC_WEDGE {\"error\":\"command status %ld\",\"case\":\"%s\",\"detail\":\"%s\"}\n", (long)cb.status,
               gCurrentCase.UTF8String, cb.error.localizedDescription.UTF8String ?: "");
        fflush(stdout); return NO;
    }
    return YES;
}

static id<MTLRenderPipelineState> makePipeline(NSString *vs, NSString *fs, BOOL blend) {
    MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
    pd.vertexFunction = [gLibrary newFunctionWithName:vs];
    pd.fragmentFunction = [gLibrary newFunctionWithName:fs];
    pd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
    if (blend) {
        pd.colorAttachments[0].blendingEnabled = YES;
        pd.colorAttachments[0].sourceRGBBlendFactor = MTLBlendFactorSourceAlpha;
        pd.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
        pd.colorAttachments[0].sourceAlphaBlendFactor = MTLBlendFactorOne;
        pd.colorAttachments[0].destinationAlphaBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    }
    NSError *error = nil;
    id<MTLRenderPipelineState> ps = [gDevice newRenderPipelineStateWithDescriptor:pd error:&error];
    if (!ps) { printf("DCC_WEDGE {\"error\":\"pipeline %s/%s: %s\"}\n", vs.UTF8String, fs.UTF8String, error.localizedDescription.UTF8String ?: ""); exit(2); }
    return ps;
}

static MTLTextureDescriptor *targetDescriptor(BOOL gpuOptimized, BOOL shaderWrite) {
    MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:W height:H mipmapped:NO];
    d.storageMode = MTLStorageModePrivate;
    d.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead | (shaderWrite ? MTLTextureUsageShaderWrite : 0);
    d.allowGPUOptimizedContents = gpuOptimized;
    return d;
}

static MTLRenderPassDescriptor *passFor(id<MTLTexture> target, BOOL load) {
    MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
    rp.colorAttachments[0].texture = target;
    rp.colorAttachments[0].loadAction = load ? MTLLoadActionLoad : MTLLoadActionClear;
    rp.colorAttachments[0].clearColor = MTLClearColorMake(kClearRGBA[0] / 255.0, kClearRGBA[1] / 255.0, kClearRGBA[2] / 255.0, kClearRGBA[3] / 255.0);
    rp.colorAttachments[0].storeAction = MTLStoreActionStore;
    return rp;
}

// Poison the memory behind `target` (or, for the no-heap control, just a texture we drop).
static BOOL poison(id<MTLTexture> target) {
    id<MTLCommandBuffer> cb = [gQueue commandBuffer];
    id<MTLRenderCommandEncoder> re = [cb renderCommandEncoderWithDescriptor:passFor(target, NO)];
    [re setRenderPipelineState:gPoisonPipeline];
    [re drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
    [re endEncoding];
    return submitAndWait(cb);
}

static BOOL runCase(const Case *c, id<MTLTexture> target, id<MTLTexture> sampleTarget) {
    if (c->loadExisting || c->shape == ShapeUAVRect) {   // separate command buffer: the draw pass must Load DCC'd content
        id<MTLCommandBuffer> cb = [gQueue commandBuffer];
        id<MTLRenderCommandEncoder> re = [cb renderCommandEncoderWithDescriptor:passFor(target, NO)];
        [re endEncoding];
        if (!submitAndWait(cb)) return NO;
    }
    id<MTLCommandBuffer> cb = [gQueue commandBuffer];
    float draw[4] = { kDrawRGBA[0] / 255.0f, kDrawRGBA[1] / 255.0f, kDrawRGBA[2] / 255.0f, c->blend ? kBlendAlpha : kDrawRGBA[3] / 255.0f };
    if (c->shape == ShapeUAVRect) {
        id<MTLComputeCommandEncoder> ce = [cb computeCommandEncoder];
        [ce setComputePipelineState:gWriteKernel];
        [ce setTexture:target atIndex:0];
        float opaque[4] = { draw[0], draw[1], draw[2], kDrawRGBA[3] / 255.0f };
        uint32_t rect[4] = { (uint32_t)kUAVRect.x0, (uint32_t)kUAVRect.y0, (uint32_t)(kUAVRect.x1 - kUAVRect.x0), (uint32_t)(kUAVRect.y1 - kUAVRect.y0) };
        [ce setBytes:opaque length:sizeof opaque atIndex:0];
        [ce setBytes:rect length:sizeof rect atIndex:1];
        [ce dispatchThreads:MTLSizeMake(rect[2], rect[3], 1) threadsPerThreadgroup:MTLSizeMake(8, 8, 1)];
        [ce endEncoding];
    } else {
        id<MTLRenderCommandEncoder> re = [cb renderCommandEncoderWithDescriptor:passFor(target, c->loadExisting)];
        if (c->shape != ShapeClear) {
            [re setRenderPipelineState:c->blend ? gConstBlend : gConstOpaque];
            [re setFragmentBytes:draw length:sizeof draw atIndex:0];
            switch (c->shape) {
                case ShapeFullTri: [re setVertexBuffer:gTriVB offset:0 atIndex:0]; [re drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3]; break;
                case ShapeQuad: [re setVertexBuffer:gQuadVB offset:0 atIndex:0]; [re drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6]; break;
                case ShapeSmallQuads: [re setVertexBuffer:gSmallVB offset:0 atIndex:0]; [re drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6 * kSmallQuadCount]; break;
                case ShapeRotTri: [re setVertexBuffer:gTriVB offset:3 * 2 * sizeof(float) atIndex:0]; [re drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3]; break;
                default: break;
            }
        }
        [re endEncoding];
    }
    switch (c->consumer) {
        case ConsumerBlit: {
            id<MTLBlitCommandEncoder> bl = [cb blitCommandEncoder];
            [bl copyFromTexture:target sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0) sourceSize:MTLSizeMake(W, H, 1)
                       toBuffer:gReadback destinationOffset:0 destinationBytesPerRow:W * 4 destinationBytesPerImage:W * 4 * H];
            [bl endEncoding];
            break;
        }
        case ConsumerSample: {
            id<MTLRenderCommandEncoder> re = [cb renderCommandEncoderWithDescriptor:passFor(sampleTarget, NO)];
            [re setRenderPipelineState:gSamplePipeline];
            [re setFragmentTexture:target atIndex:0];
            [re drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            [re endEncoding];
            id<MTLBlitCommandEncoder> bl = [cb blitCommandEncoder];
            [bl copyFromTexture:sampleTarget sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0) sourceSize:MTLSizeMake(W, H, 1)
                       toBuffer:gReadback destinationOffset:0 destinationBytesPerRow:W * 4 destinationBytesPerImage:W * 4 * H];
            [bl endEncoding];
            break;
        }
        case ConsumerCompute: {
            id<MTLComputeCommandEncoder> ce = [cb computeCommandEncoder];
            [ce setComputePipelineState:gReadKernel];
            [ce setTexture:target atIndex:0];
            [ce setBuffer:gReadback offset:0 atIndex:0];
            [ce dispatchThreads:MTLSizeMake(W, H, 1) threadsPerThreadgroup:MTLSizeMake(8, 8, 1)];
            [ce endEncoding];
            break;
        }
    }
    return submitAndWait(cb);
}

// PNG output --------------------------------------------------------------------------------
static void writePNG(NSString *path, const void *bytes, BOOL gray) {
    CGColorSpaceRef cs = gray ? CGColorSpaceCreateDeviceGray() : CGColorSpaceCreateDeviceRGB();
    CGDataProviderRef provider = CGDataProviderCreateWithData(NULL, bytes, gray ? W * H : W * H * 4, NULL);
    CGImageRef image = gray
        ? CGImageCreate(W, H, 8, 8, W, cs, kCGImageAlphaNone, provider, NULL, false, kCGRenderingIntentDefault)
        : CGImageCreate(W, H, 8, 32, W * 4, cs, kCGBitmapByteOrder32Little | kCGImageAlphaNoneSkipFirst, provider, NULL, false, kCGRenderingIntentDefault);
    CGImageDestinationRef dest = CGImageDestinationCreateWithURL((__bridge CFURLRef)[NSURL fileURLWithPath:path], CFSTR("public.png"), 1, NULL);
    if (image && dest) { CGImageDestinationAddImage(dest, image, NULL); CGImageDestinationFinalize(dest); }
    if (dest) CFRelease(dest);
    if (image) CGImageRelease(image);
    CGDataProviderRelease(provider);
    CGColorSpaceRelease(cs);
}

// Analysis ----------------------------------------------------------------------------------
typedef struct {
    uint64_t compared, edgeExcluded, mismatches, stalePoison, stalePoisonOther, clearColor, drawColor, other;
    uint64_t tilesTouched, tilesFull, pixelsInFullTiles, nearDiagMismatch, nearDiagCompared;
    uint64_t runs, maxRun;
} Stats;

static Stats analyze(const Case *c, const uint32_t *readback, const uint32_t *expected, const uint8_t *flags,
                     uint8_t *mismatchMap, NSMutableDictionary *displacements) {
    Stats s; memset(&s, 0, sizeof s);
    const uint32_t clearV = packBGRA(kClearRGBA), drawV = packBGRA(kDrawRGBA);
    static uint16_t tileCounts[(H / TILE) * (W / TILE)];
    memset(tileCounts, 0, sizeof tileCounts);
    for (uint32_t y = 0; y < H; ++y) {
        uint64_t run = 0;
        for (uint32_t x = 0; x < W; ++x) {
            uint32_t i = y * W + x;
            uint8_t f = flags[i];
            if (f & 1) { s.edgeExcluded++; mismatchMap[i] = 0; if (run) { s.runs++; if (run > s.maxRun) s.maxRun = run; run = 0; } continue; }
            s.compared++;
            if (f & 2) s.nearDiagCompared++;
            uint32_t v = readback[i];
            if (near8(v, expected[i])) { mismatchMap[i] = 0; if (run) { s.runs++; if (run > s.maxRun) s.maxRun = run; run = 0; } continue; }
            s.mismatches++; mismatchMap[i] = 255; run++;
            tileCounts[(y / TILE) * (W / TILE) + x / TILE]++;
            if (f & 2) s.nearDiagMismatch++;
            uint32_t px, py;
            if (v == poisonValue(x, y)) s.stalePoison++;
            else if (decodePoison(v, &px, &py)) {
                s.stalePoisonOther++;
                if (displacements.count < 4096 && s.stalePoisonOther <= kMaxDisplacementRecords) {
                    NSString *key = [NSString stringWithFormat:@"%d,%d", (int)px - (int)x, (int)py - (int)y];
                    displacements[key] = @([displacements[key] unsignedLongLongValue] + 1);
                }
            }
            else if (near8(v, clearV)) s.clearColor++;
            else if (near8(v, drawV)) s.drawColor++;
            else s.other++;
        }
        if (run) { s.runs++; if (run > s.maxRun) s.maxRun = run; }
    }
    for (uint32_t t = 0; t < (H / TILE) * (W / TILE); ++t) {
        if (!tileCounts[t]) continue;
        s.tilesTouched++;
        if (tileCounts[t] == TILE * TILE) { s.tilesFull++; s.pixelsInFullTiles += TILE * TILE; }
    }
    return s;
}

static NSString *caseName(const Case *c) {
    static const char *shapes[] = { "clear", "fulltri", "quad", "smallquads", "rottri", "uavrect" };
    static const char *consumers[] = { "blit", "sample", "compute" };
    return [NSString stringWithFormat:@"shape=%s blend=%d load=%s gpuopt=%d consumer=%s heap=%d",
            shapes[c->shape], c->blend, c->loadExisting ? "load" : "clear", c->gpuOptimized, consumers[c->consumer], c->heap];
}

int main(int argc, char **argv) {
    @autoreleasepool {
        NSString *pngDir = argc > 1 ? [NSString stringWithUTF8String:argv[1]] : @"/tmp/dcc_wedge";
        int iterations = argc > 2 ? atoi(argv[2]) : 20;
        if (iterations < 1) iterations = 1;
        mkdir(pngDir.UTF8String, 0755);
        initSmallQuads();

        gDevice = MTLCreateSystemDefaultDevice();
        if (!gDevice) { puts("DCC_WEDGE {\"error\":\"no-device\"}"); return 2; }
        printf("DCC_WEDGE_DEVICE {\"name\":\"%s\",\"registry_id\":%llu,\"iterations\":%d}\n", gDevice.name.UTF8String, gDevice.registryID, iterations);
        fflush(stdout);
        NSError *error = nil;
        gLibrary = [gDevice newLibraryWithSource:kShaderSource options:nil error:&error];
        if (!gLibrary) { printf("DCC_WEDGE {\"error\":\"shader\",\"detail\":\"%s\"}\n", error.localizedDescription.UTF8String ?: ""); return 2; }
        gQueue = [gDevice newCommandQueue];
        if (!gQueue) { puts("DCC_WEDGE {\"error\":\"queue\"}"); return 2; }
        gPoisonPipeline = makePipeline(@"vs_full", @"fs_poison", NO);
        gSamplePipeline = makePipeline(@"vs_full", @"fs_sample", NO);
        gConstOpaque = makePipeline(@"vs_pos", @"fs_const", NO);
        gConstBlend = makePipeline(@"vs_pos", @"fs_const", YES);
        gReadKernel = [gDevice newComputePipelineStateWithFunction:[gLibrary newFunctionWithName:@"k_read"] error:&error];
        gWriteKernel = gReadKernel ? [gDevice newComputePipelineStateWithFunction:[gLibrary newFunctionWithName:@"k_write"] error:&error] : nil;
        if (!gReadKernel || !gWriteKernel) { printf("DCC_WEDGE {\"error\":\"compute pipeline\",\"detail\":\"%s\"}\n", error.localizedDescription.UTF8String ?: ""); return 2; }
        gReadback = [gDevice newBufferWithLength:W * H * 4 options:MTLResourceStorageModeShared];

        // Vertex buffers (NDC float2). gTriVB holds the fullscreen triangle then the rotated one.
        float tri[12];
        const float fx[3] = { 0, 2 * W, 0 }, fy[3] = { 0, 0, 2 * H };   // covers the whole target
        for (int i = 0; i < 3; ++i) { ndc(fx[i], fy[i], tri + 2 * i); ndc(kRotTri.x[i], kRotTri.y[i], tri + 6 + 2 * i); }
        gTriVB = [gDevice newBufferWithBytes:tri length:sizeof tri options:MTLResourceStorageModeShared];
        float quad[12]; appendRect(quad, 0, &kQuad);
        gQuadVB = [gDevice newBufferWithBytes:quad length:sizeof quad options:MTLResourceStorageModeShared];
        float *small = calloc(kSmallQuadCount * 12, sizeof(float)); NSUInteger n = 0;
        for (int i = 0; i < kSmallQuadCount; ++i) n = appendRect(small, n, &gSmallQuads[i]);
        gSmallVB = [gDevice newBufferWithBytes:small length:kSmallQuadCount * 12 * sizeof(float) options:MTLResourceStorageModeShared];
        free(small);
        if (!gReadback || !gTriVB || !gQuadVB || !gSmallVB) { puts("DCC_WEDGE {\"error\":\"buffer allocation\"}"); return 2; }

        // Placement heap sized for one target plus slack.
        MTLSizeAndAlign sa = [gDevice heapTextureSizeAndAlignWithDescriptor:targetDescriptor(YES, YES)];
        MTLHeapDescriptor *hd = [MTLHeapDescriptor new];
        hd.type = MTLHeapTypePlacement;
        hd.storageMode = MTLStorageModePrivate;
        hd.hazardTrackingMode = MTLHazardTrackingModeTracked;
        hd.size = ((sa.size + sa.align - 1) / sa.align) * sa.align + (4 << 20);
        id<MTLHeap> heap = [gDevice newHeapWithDescriptor:hd];
        if (!heap) { puts("DCC_WEDGE {\"error\":\"heap allocation\"}"); return 2; }
        printf("DCC_WEDGE_HEAP {\"texture_size\":%llu,\"align\":%llu,\"heap_size\":%llu}\n", (unsigned long long)sa.size, (unsigned long long)sa.align, (unsigned long long)hd.size);
        fflush(stdout);

        // Case table.
        NSMutableData *caseData = [NSMutableData data];
        Case tmp;
        #define ADD(S, B, L, G, C, HP) do { tmp = (Case){ S, B, L, G, C, HP }; [caseData appendBytes:&tmp length:sizeof tmp]; } while (0)
        const Shape shapes[] = { ShapeClear, ShapeFullTri, ShapeQuad, ShapeSmallQuads, ShapeRotTri };
        for (int si = 0; si < 5; ++si)
            for (int blend = 0; blend < 2; ++blend)
                for (int load = 0; load < 2; ++load)
                    for (int gpuopt = 1; gpuopt >= 0; --gpuopt) {
                        if (shapes[si] == ShapeClear && blend) continue;
                        ADD(shapes[si], blend, load, gpuopt, ConsumerBlit, YES);
                    }
        for (int gpuopt = 1; gpuopt >= 0; --gpuopt) {
            ADD(ShapeQuad, YES, YES, gpuopt, ConsumerSample, YES);
            ADD(ShapeQuad, YES, YES, gpuopt, ConsumerCompute, YES);
            ADD(ShapeSmallQuads, YES, YES, gpuopt, ConsumerSample, YES);
            ADD(ShapeSmallQuads, YES, YES, gpuopt, ConsumerCompute, YES);
            ADD(ShapeUAVRect, NO, YES, gpuopt, ConsumerSample, YES);
            ADD(ShapeUAVRect, NO, YES, gpuopt, ConsumerBlit, YES);
        }
        ADD(ShapeQuad, YES, YES, YES, ConsumerBlit, NO);        // no-heap controls
        ADD(ShapeSmallQuads, YES, YES, YES, ConsumerSample, NO);
        #undef ADD
        const Case *cases = (const Case *)caseData.bytes;
        NSUInteger caseCount = caseData.length / sizeof(Case);

        uint32_t *expected = malloc(W * H * 4); uint8_t *flags = malloc(W * H); uint8_t *mismatchMap = malloc(W * H);
        int pngPairs = 0; uint64_t totalMismatchCases = 0, totalStale = 0, totalStaleOther = 0; int casesWithMismatch = 0;
        NSMutableArray *worst = [NSMutableArray array];

        for (NSUInteger ci = 0; ci < caseCount; ++ci) {
            const Case *c = &cases[ci];
            gCurrentCase = caseName(c);
            buildExpected(c, expected, flags);
            NSMutableDictionary *displacements = [NSMutableDictionary dictionary];
            Stats total; memset(&total, 0, sizeof total);
            uint64_t minM = UINT64_MAX, maxM = 0; int itersWithMismatch = 0, itersRun = 0; BOOL failed = NO;
            NSMutableArray *perIter = [NSMutableArray array];
            for (int it = 0; it < iterations && !failed; ++it) {
                @autoreleasepool {
                    id<MTLTexture> target = nil, sampleTarget = nil;
                    BOOL shaderWrite = c->shape == ShapeUAVRect;
                    if (c->heap) {
                        id<MTLTexture> p = [heap newTextureWithDescriptor:targetDescriptor(YES, NO) offset:0];
                        if (!p || !poison(p)) { failed = YES; break; }
                        p = nil;
                        target = [heap newTextureWithDescriptor:targetDescriptor(c->gpuOptimized, shaderWrite) offset:0];
                    } else {
                        id<MTLTexture> p = [gDevice newTextureWithDescriptor:targetDescriptor(YES, NO)];
                        if (!p || !poison(p)) { failed = YES; break; }
                        p = nil;
                        target = [gDevice newTextureWithDescriptor:targetDescriptor(c->gpuOptimized, shaderWrite)];
                    }
                    if (c->consumer == ConsumerSample) sampleTarget = [gDevice newTextureWithDescriptor:targetDescriptor(YES, NO)];
                    if (!target || (c->consumer == ConsumerSample && !sampleTarget)) { failed = YES; break; }
                    memset(gReadback.contents, 0x7f, W * H * 4);
                    if (!runCase(c, target, sampleTarget)) { failed = YES; break; }
                    itersRun++;
                    Stats s = analyze(c, gReadback.contents, expected, flags, mismatchMap, displacements);
                    [perIter addObject:@(s.mismatches)];
                    if (s.mismatches < minM) minM = s.mismatches;
                    if (s.mismatches > maxM) maxM = s.mismatches;
                    if (s.mismatches) itersWithMismatch++;
                    total.compared += s.compared; total.edgeExcluded += s.edgeExcluded; total.mismatches += s.mismatches;
                    total.stalePoison += s.stalePoison; total.stalePoisonOther += s.stalePoisonOther; total.clearColor += s.clearColor;
                    total.drawColor += s.drawColor; total.other += s.other; total.tilesTouched += s.tilesTouched; total.tilesFull += s.tilesFull;
                    total.pixelsInFullTiles += s.pixelsInFullTiles; total.nearDiagMismatch += s.nearDiagMismatch; total.nearDiagCompared += s.nearDiagCompared;
                    total.runs += s.runs; if (s.maxRun > total.maxRun) total.maxRun = s.maxRun;
                    if (s.mismatches && itersWithMismatch == 1 && pngPairs < kMaxPngPairs) {
                        NSString *stem = [NSString stringWithFormat:@"%@/case%02lu", pngDir, (unsigned long)ci];
                        writePNG([stem stringByAppendingString:@"-mismatch.png"], mismatchMap, YES);
                        writePNG([stem stringByAppendingString:@"-readback.png"], gReadback.contents, NO);
                        pngPairs++;
                    }
                    target = nil; sampleTarget = nil;
                }
            }
            NSMutableDictionary *row = [@{ @"case": gCurrentCase, @"index": @(ci), @"iterations": @(itersRun), @"failed": @(failed) } mutableCopy];
            if (itersRun) {
                NSArray *keys = [displacements keysSortedByValueUsingComparator:^NSComparisonResult(id a, id b) { return [b compare:a]; }];
                NSMutableArray *top = [NSMutableArray array];
                for (NSString *k in keys) { if (top.count >= 5) break; [top addObject:@{ @"dxdy": k, @"count": displacements[k] }]; }
                row[@"compared_per_iter"] = @(total.compared / itersRun);
                row[@"edge_excluded"] = @(total.edgeExcluded / itersRun);
                row[@"mismatch_min"] = @(minM); row[@"mismatch_max"] = @(maxM);
                row[@"mismatch_mean"] = @((double)total.mismatches / itersRun);
                row[@"iters_with_mismatch"] = @(itersWithMismatch);
                row[@"per_iter"] = perIter;
                row[@"classes"] = @{ @"stale_poison": @(total.stalePoison), @"stale_poison_other": @(total.stalePoisonOther),
                                     @"clear_color": @(total.clearColor), @"draw_color": @(total.drawColor), @"other": @(total.other) };
                row[@"tiles_touched"] = @(total.tilesTouched); row[@"tiles_full"] = @(total.tilesFull);
                row[@"full_tile_fraction"] = @(total.mismatches ? (double)total.pixelsInFullTiles / total.mismatches : 0);
                row[@"near_diagonal_fraction"] = @(total.mismatches ? (double)total.nearDiagMismatch / total.mismatches : 0);
                row[@"near_diagonal_compared_fraction"] = @(total.compared ? (double)total.nearDiagCompared / total.compared : 0);
                row[@"runs"] = @(total.runs); row[@"max_run"] = @(total.maxRun);
                row[@"mean_run"] = @(total.runs ? (double)total.mismatches / total.runs : 0);
                row[@"top_displacements"] = top;
                if (total.mismatches) { casesWithMismatch++; totalMismatchCases += total.mismatches; totalStale += total.stalePoison; totalStaleOther += total.stalePoisonOther;
                    [worst addObject:@{ @"case": gCurrentCase, @"mismatch_mean": row[@"mismatch_mean"] }]; }
            }
            NSData *json = [NSJSONSerialization dataWithJSONObject:row options:0 error:nil];
            printf("DCC_WEDGE %.*s\n", (int)json.length, (const char *)json.bytes); fflush(stdout);
        }
        [worst sortUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) { return [b[@"mismatch_mean"] compare:a[@"mismatch_mean"]]; }];
        NSDictionary *summary = @{ @"cases": @(caseCount), @"cases_with_mismatch": @(casesWithMismatch), @"mismatch_pixels": @(totalMismatchCases),
                                   @"stale_poison": @(totalStale), @"stale_poison_other": @(totalStaleOther), @"png_pairs": @(pngPairs), @"png_dir": pngDir,
                                   @"worst": [worst subarrayWithRange:NSMakeRange(0, MIN(worst.count, (NSUInteger)8))] };
        NSData *json = [NSJSONSerialization dataWithJSONObject:summary options:0 error:nil];
        printf("DCC_WEDGE_SUMMARY %.*s\n", (int)json.length, (const char *)json.bytes); fflush(stdout);
        free(expected); free(flags); free(mismatchMap);
    }
    return 0;
}
