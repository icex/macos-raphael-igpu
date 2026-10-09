// Compact RGBA token band. Nearest-neighbor8x exactly preserves original cells.
#ifndef CONSOLE_CADENCE_BAND_H
#define CONSOLE_CADENCE_BAND_H
#include <stdint.h>
#include <string.h>
#define RGPU_BAND_W 38
#define RGPU_BAND_H 12
#define RGPU_BAND_BYTES (RGPU_BAND_W*RGPU_BAND_H*4)
static void rgpu_band(uint8_t *rgba,const uint8_t nonce[8],uint32_t sequence) {
 uint8_t data[20]={'R','G','P','T'};memcpy(data+4,nonce,8);
 for(int i=0;i<4;i++)data[12+i]=(sequence>>(24-8*i))&255;
 uint32_t crc=~0u;for(int i=0;i<16;i++){crc^=data[i];for(int j=0;j<8;j++)crc=(crc>>1)^(0xedb88320u&-(crc&1));}crc=~crc;
 for(int i=0;i<4;i++)data[16+i]=(crc>>(24-8*i))&255;
 for(int y=0;y<RGPU_BAND_H;y++)for(int x=0;x<RGPU_BAND_W;x++){
  uint8_t *p=rgba+4*(y*RGPU_BAND_W+x);p[0]=p[1]=p[2]=31;p[3]=255;
  int bx=x<18?x:(x>=20?x-20:-1);if(bx<0)continue;
  p[0]=255;p[1]=0;p[2]=255;
  if(bx>=1&&bx<=16&&y>=1&&y<=10){int bit=(y-1)*16+bx-1;uint8_t v=(data[bit/8]&(1<<(7-bit%8)))?255:0;p[0]=p[1]=p[2]=v;}
 }
}
#endif
