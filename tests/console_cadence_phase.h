// Mixed workload schedule only; no display/capture or presentation claims.
#ifndef CONSOLE_CADENCE_PHASE_H
#define CONSOLE_CADENCE_PHASE_H
#include <math.h>
#include <string.h>
enum { RGPU_SOURCE_INVALID, RGPU_SOURCE_BASELINE, RGPU_SOURCE_PRERENDERED,
       RGPU_SOURCE_MIXED };
static inline int rgpu_source_mode(const char *text) {
 if(!text)return RGPU_SOURCE_INVALID;
 if(!strcmp(text,"baseline"))return RGPU_SOURCE_BASELINE;
 if(!strcmp(text,"prerendered"))return RGPU_SOURCE_PRERENDERED;
 if(!strcmp(text,"mixed"))return RGPU_SOURCE_MIXED;
 return RGPU_SOURCE_INVALID;
}
typedef struct {
 unsigned index;
 int full;
 double start,end,low,high,angle;
} RGPUMixedPhase;
static inline int rgpu_mixed_phase(double elapsed,double duration,RGPUMixedPhase *out) {
 if(!out||!isfinite(elapsed)||!isfinite(duration)||elapsed<0||duration<1||
    duration>120||elapsed>=duration)return 0;
 unsigned index=(unsigned)(elapsed/20.0);
 double start=index*20.0,t=(elapsed-start)/20.0;
 int full=(index&1)!=0;
 // Smooth envelope reaches zero with zero derivative at each phase boundary.
 // Spatial gradient rotation distributes low-contrast changes across the field;
 // a uniform8-bit ramp alone would quantize to only a few changes per second.
 double sine=sin(3.14159265358979323846*t);
 double amplitude=full?.035*sine*sine:0;
 *out=(RGPUMixedPhase){index,full,start,fmin(start+20.0,duration),
                      .12-amplitude,.12+amplitude,full?360.0*t:0};
 return 1;
}
#endif
