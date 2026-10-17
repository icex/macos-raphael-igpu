#include "../src/HdmiFrlEdid.hpp"
#include <assert.h>
#include <string.h>
static void checksum(uint8_t *p) {
    p[127]=0; uint8_t sum=0;
    for (unsigned i=0;i<127;++i) sum+=p[i];
    p[127]=uint8_t(0-sum);
}
int main() {
    uint8_t e[256]={0};
    const uint8_t header[]={0,255,255,255,255,255,255,0};
    memcpy(e,header,8); e[126]=1;
    const uint8_t cta[]={2,3,13,0,0x68,0xd8,0x5d,0xc4,1,120,0x80,0x68,2};
    memcpy(e+128,cta,sizeof(cta));checksum(e);checksum(e+128);
    assert(hdmiFrlEdidRate(e,sizeof(e))==6);
    assert(hdmiFrlEdidRate(nullptr,256)==0);
    assert(hdmiFrlEdidRate(e,128)==0);
    assert(hdmiFrlEdidRate(e,255)==0);
    e[139]=0x78;checksum(e+128);assert(hdmiFrlEdidRate(e,256)==0);
    e[139]=0x68;e[138]=0;checksum(e+128);assert(hdmiFrlEdidRate(e,256)==0);
    e[138]=0x80;checksum(e+128);e[200]^=1;assert(hdmiFrlEdidRate(e,256)==0);
    e[200]^=1;e[130]=12;checksum(e+128);assert(hdmiFrlEdidRate(e,256)==0);
    e[130]=13;e[133]=0;checksum(e+128);assert(hdmiFrlEdidRate(e,256)==0);
    e[133]=0xd8;checksum(e+128);e[0]=1;checksum(e);assert(hdmiFrlEdidRate(e,256)==0);
}
