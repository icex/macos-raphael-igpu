#ifndef RAPHAEL_DISPLAY_CONTROL_H
#define RAPHAEL_DISPLAY_CONTROL_H
#include <stdint.h>
#include <stddef.h>
#define RG_CONTROL_MAGIC 0x52475044u
#define RG_CONTROL_REQUEST 20u
#define RG_CONTROL_REPLY 40u
static uint32_t rg_read32(const uint8_t *p) {return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void rg_write32(uint8_t *p,uint32_t v) {for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}
/* status:0 OK,1 malformed,2 unsupported,3 apply,4 verification,5 capacity. */
static unsigned rg_validate(const uint8_t *p,size_t n) {
 if(n!=RG_CONTROL_REQUEST||rg_read32(p)!=RG_CONTROL_MAGIC||rg_read32(p+4)!=1||!rg_read32(p+8))return 1;
 uint32_t w=rg_read32(p+12),h=rg_read32(p+16);
 return w<640||w>3840||h<480||h>2160||(w&1)||(h&1)?2:0;
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
