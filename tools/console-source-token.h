#ifndef RGPU_CONSOLE_SOURCE_TOKEN_H
#define RGPU_CONSOLE_SOURCE_TOKEN_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <math.h>
enum { RG_T_VALID,RG_T_BOUNDS,RG_T_BORDER,RG_T_AMBIGUOUS,RG_T_TORN,
 RG_T_IDENTITY,RG_T_CRC,RG_T_DUPLICATES,RG_T_UNAVAILABLE,RG_T_BACKWARDS,RG_T_RESULTS };
static int rg_token_nonce(const char *text,uint8_t nonce[8]){
 if(!text||strlen(text)!=16)return 0;
 for(int i=0;i<16;i++){unsigned c=(unsigned char)text[i],v;
  if(c>='0'&&c<='9')v=c-'0';else if(c>='a'&&c<='f')v=c-'a'+10;
  else if(c>='A'&&c<='F')v=c-'A'+10;else return 0;
  if(!(i&1))nonce[i/2]=(uint8_t)(v<<4);else nonce[i/2]|=(uint8_t)v;
 }return 1;
}
static uint32_t rg_token_crc(const uint8_t *p){uint32_t c=~0u;for(int i=0;i<16;i++){c^=p[i];for(int j=0;j<8;j++)c=(c>>1)^(0xedb88320u&-(c&1));}return ~c;}
static uint32_t rg_token_be32(const uint8_t *p){return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];}
// Input is locked32BGRA; alpha ignored, exactly as RGB Python observer.
static int rg_token_decode(const uint8_t *p,size_t w,size_t h,size_t stride,
 const uint8_t nonce[8],unsigned scale,uint32_t *sequence){
 if(!p||(scale!=1&&scale!=2)||w<320*scale||h<160*scale||w>SIZE_MAX/4||stride<w*4||h>SIZE_MAX/stride)return RG_T_BOUNDS;
 uint32_t ids[2];unsigned cell=8*scale;
 for(int copy=0;copy<2;copy++){
  unsigned left=(16+160*copy)*scale,top=64*scale;
  for(int corner=0;corner<2;corner++){
   unsigned x=left+(corner?17*cell:0)+cell/2,y=top+(corner?11*cell:0)+cell/2;
   const uint8_t *q=p+y*stride+x*4;if(!(q[2]>210&&q[1]<50&&q[0]>210))return RG_T_BORDER;
  }
  uint8_t raw[20]={0};static const unsigned dx[]={2,5,2,5,4},dy[]={2,2,5,5,4};
  for(unsigned bit=0;bit<160;bit++){
   int value=-1;for(unsigned sample=0;sample<5;sample++){
    unsigned x=left+(1+bit%16)*cell+dx[sample]*scale,y=top+(1+bit/16)*cell+dy[sample]*scale;
    const uint8_t *q=p+y*stride+x*4;int v;
    if(q[0]>210&&q[1]>210&&q[2]>210)v=1;else if(q[0]<50&&q[1]<50&&q[2]<50)v=0;else return RG_T_AMBIGUOUS;
    if(value!=-1&&value!=v)return RG_T_TORN;value=v;
   }raw[bit/8]|=(uint8_t)(value<<(7-bit%8));
  }
  if(memcmp(raw,"RGPT",4)||memcmp(raw+4,nonce,8))return RG_T_IDENTITY;
  if(rg_token_crc(raw)!=rg_token_be32(raw+16))return RG_T_CRC;
  ids[copy]=rg_token_be32(raw+12);
 }
 if(ids[0]!=ids[1])return RG_T_DUPLICATES;*sequence=ids[0];return RG_T_VALID;
}
typedef struct {
 int enabled,armed,started,done,reported,haveLast,interrupted;unsigned scale;
 uint8_t nonce[8];uint32_t last;
 double armedAt,start,end,checkSeconds,checkMax;
 uint64_t waiting,processed,valid,invalid,duplicates,unique,skipped,errors[RG_T_RESULTS];
} RGTokenWindow;
// Expiration is polled even if no frames arrive. End excludes sample at deadline.
static void rg_token_poll(RGTokenWindow *s,double now){
 if(s->enabled&&s->armed&&!s->done&&now>=(s->started?s->start+30:s->armedAt+60)){s->done=1;s->end=s->started?s->start+30:s->armedAt+60;}
}
static void rg_token_observe(RGTokenWindow *s,double now,int result,uint32_t sequence,unsigned scale){
 rg_token_poll(s,now);if(!s->enabled||!s->armed||s->done)return;
 if(!s->started){if(result!=RG_T_VALID){s->waiting++;return;}s->started=1;s->start=now;s->scale=scale;}
 s->processed++;
 if(result==RG_T_VALID&&s->haveLast&&sequence<s->last)result=RG_T_BACKWARDS;
 if(result!=RG_T_VALID){s->invalid++;s->errors[result]++;return;}
 s->valid++;
 if(s->haveLast&&sequence==s->last)s->duplicates++;
 else{s->unique++;if(s->haveLast)s->skipped+=(uint64_t)sequence-s->last-1;}
 s->last=sequence;s->haveLast=1;
}
#endif
