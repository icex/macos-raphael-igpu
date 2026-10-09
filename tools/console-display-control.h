#ifndef RAPHAEL_DISPLAY_CONTROL_H
#define RAPHAEL_DISPLAY_CONTROL_H
#include <stdint.h>
#include <stddef.h>
#define RG_CONTROL_MAGIC 0x52475044u
#define RG_CONTROL_REQUEST 20u
#define RG_CONTROL_REQUEST_MAX 24u
#define RG_CONTROL_REPLY 40u
static uint32_t rg_read32(const uint8_t *p) {return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void rg_write32(uint8_t *p,uint32_t v) {for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}
/* Version 1 is always 2x. Version 2 appends an explicit 1x/2x scale.
 * Size is determined from the version word only after eight bytes arrive. */
static inline size_t rg_request_size(uint32_t version) {
 return version==1?RG_CONTROL_REQUEST:version==2?RG_CONTROL_REQUEST_MAX:0;
}
/* Call only after successful rg_validate: v2 needs the complete 24 bytes. */
static inline unsigned rg_request_scale(const uint8_t *p) {
 return rg_read32(p+4)==1?2:rg_read32(p+20);
}
/* status:0 OK,1 malformed,2 unsupported,3 apply,4 verification,5 capacity. */
static unsigned rg_validate(const uint8_t *p,size_t n) {
 if(n<RG_CONTROL_REQUEST||rg_read32(p)!=RG_CONTROL_MAGIC||
    n!=rg_request_size(rg_read32(p+4))||!rg_read32(p+8))return 1;
 uint32_t w=rg_read32(p+12),h=rg_read32(p+16),scale=rg_request_scale(p);
 return w<640||w>3840||h<480||h>2160||(scale!=1&&scale!=2)||
        (scale==2&&((w&1)||(h&1)))?2:0;
}
/* Read-only asynchronous settle policy. Identity loss/deadline always refuse;
 * readiness must hold across observations spanning 200 ms. No layout mutation is permitted. */
static inline int rg_settle(double *since,int identity,int ready,int expired,double now) {
 if(!identity||expired){*since=-1;return -1;}
 if(!ready){*since=-1;return 0;}
 if(*since<0)*since=now;
 return now-*since>=.2?1:0;
}
/* Oldest first. Operate on a copy until the display accepts the candidate. */
#define RG_DYNAMIC_LIMIT 8u
typedef struct { uint32_t w,h; } RGGeometry;
typedef struct { RGGeometry items[RG_DYNAMIC_LIMIT]; unsigned count; } RGModes;
static inline int rg_equal(RGGeometry a,RGGeometry b){return a.w==b.w&&a.h==b.h;}
static inline void rg_touch(RGModes *m,RGGeometry requested){
 for(unsigned i=0;i<m->count;i++)if(rg_equal(m->items[i],requested)){
  for(unsigned j=i+1;j<m->count;j++)m->items[j-1]=m->items[j];
  m->items[m->count-1]=requested;return;
 }
}
static inline int rg_insert(RGModes *m,RGGeometry requested,RGGeometry current){
 if(m->count>RG_DYNAMIC_LIMIT)return 0;
 for(unsigned i=0;i<m->count;i++)if(rg_equal(m->items[i],requested)){rg_touch(m,requested);return 1;}
 if(m->count==RG_DYNAMIC_LIMIT){
  unsigned victim=0;while(victim<m->count&&rg_equal(m->items[victim],current))victim++;
  if(victim==m->count)return 0;
  for(unsigned j=victim+1;j<m->count;j++)m->items[j-1]=m->items[j];
  m->count--;
 }
 m->items[m->count++]=requested;return 1;
}
#endif
