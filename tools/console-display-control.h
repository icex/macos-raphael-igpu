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
#endif
