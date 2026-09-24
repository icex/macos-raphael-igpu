#include <cassert>
#include "../src/DcnTranslation.hpp"

int main() {
    using namespace RaphaelDcn;
    const size_t count = sizeof(kDcn302To315) / sizeof(kDcn302To315[0]);
    for (size_t i = 1; i < count; i++) assert(kDcn302To315[i - 1].from < kDcn302To315[i].from);

    // Header facts (base segment 2 = 0x34c0): unchanged, moved and removed registers.
    assert(translate(0x34c0 + 0x1b41).action == Action::Pass);           // OTG0_OTG_CONTROL
    const Mapping ip = translate(0x34c0 + 0x00b2);                        // DC_IP_REQUEST_CNTL
    assert(ip.action == Action::Move && ip.index == 0x34c0 + 0x0093);
    const Mapping sdpif = translate(0x34c0 + 0x048f);                     // DCHUBBUB_SDPIF_CFG0
    assert(sdpif.action == Action::Move && sdpif.index == 0x34c0 + 0x046f);
    // Pipe power domains: 3.0.2 HUBP i = DOMAIN 2i -> 3.1.5 pipe i = DOMAIN i; DPP domains drop.
    assert(translate(0x34c0 + 0x0080).action == Action::Pass);            // DOMAIN0_PG_CONFIG
    assert(translate(0x34c0 + 0x0082).action == Action::Drop);            // DOMAIN1_PG_CONFIG (DPP0)
    const Mapping pipe1 = translate(0x34c0 + 0x0084);                     // DOMAIN2_PG_CONFIG (HUBP1)
    assert(pipe1.action == Action::Move && pipe1.index == 0x34c0 + 0x0082);
    const Mapping pipe3 = translate(0x34c0 + 0x008d);                     // DOMAIN6_PG_STATUS (HUBP3)
    assert(pipe3.action == Action::Move && pipe3.index == 0x34c0 + 0x0087);
    assert(translate(0x34c0 + 0x0090).action == Action::Drop);            // DOMAIN8_PG_CONFIG
    const Mapping dsc0 = translate(0x34c0 + 0x00a1);                      // DOMAIN16_PG_CONFIG
    assert(dsc0.action == Action::Move && dsc0.index == 0x34c0 + 0x0089);
    assert(translate(0x34c0 + 0x00a9).action == Action::Drop);            // DOMAIN20_PG_CONFIG
    // DMCUB block: every DMCUB_* register is fenced off, the strap reports DMCUB absent.
    assert(k302DmcubCntl == 0x34c0 + 0x01f6 && k302CcDcPipeDis == 0x34c0 + 0x00ca);
    assert(isDmcubRegister(k302DmcubCntl));
    assert(isDmcubRegister(0x34c0 + 0x01b5));                              // DMCUB_REGION3_CW0_OFFSET
    assert(!isDmcubRegister(k302CcDcPipeDis) && !isDmcubRegister(0x34c0 + 0x1b41));
    const uint32_t dmcubList[] = {3, 7, 9};
    assert(isDmcubRegister(dmcubList, 3, 3) && isDmcubRegister(dmcubList, 3, 9) &&
           !isDmcubRegister(dmcubList, 3, 8) && !isDmcubRegister(dmcubList, 0, 3));
    assert(maskDmcubStrap(0x000100ff) == 0xff && maskDmcubStrap(0xf) == 0xf);
    // DIO I2C memory: clear the forced light sleep, disable light sleep, keep other bits.
    assert(k315DioMemPwrCtrl == 0x539e && k315DioMemPwrStatus == 0x539d);
    assert(wakeDioI2c(0x1) == 0x2 && wakeDioI2c(0x0) == 0x2 && wakeDioI2c(0x3f1) == 0x3f2);
    const uint32_t dramSamples[] = {0u, 0x1000u, 0xffffffffu, 0xa5a5a5a5u};
    for (uint32_t original : dramSamples) {
        assert(scanoutDramAllow(original, false) == forceDramAllow(original));
        const uint32_t active = scanoutDramAllow(original, true);
        assert((active & 0x33u) == 0x32u);
        assert((active & ~0x33u) == (original & ~0x33u));
    }
    assert(k315DchubbubArbDramStateCntl == 0x39bc && forceDramAllow(0x1000) == 0x1033 && forceDramAllow(0) == 0x33);
    assert(k315DcI2cDdc1Speed == 0x5362 && k315MicrosecondTimeBaseDiv == 0x13b && kHostDdc1Speed == 0x9600102);
    assert(isDdcTraceWindow(0x5358) && isDdcTraceWindow(0x5372) && isDdcTraceWindow(0x5377) &&
           isDdcTraceWindow(0x539e) && isDdcTraceWindow(0x5d91) && isDdcTraceWindow(0x5ddd) &&
           !isDdcTraceWindow(0x5357) && !isDdcTraceWindow(0x5378) && !isDdcTraceWindow(0x5dde) &&
           !isDdcTraceWindow(0x1b41));
    assert(translate(0xffffffff).action == Action::Pass);
    assert(translate(0).action == Action::Pass);

    // Binary search over a local table, including both ends.
    const XlatEntry local[] = {{2, 20, kXlatMove}, {5, 0, kXlatDrop}, {9, 90, kXlatMove}};
    assert(translate(local, 3, 2).index == 20);
    assert(translate(local, 3, 5).action == Action::Drop);
    assert(translate(local, 3, 9).index == 90);
    assert(translate(local, 3, 1).action == Action::Pass);
    assert(translate(local, 3, 10).action == Action::Pass);
    assert(translate(local, 0, 2).action == Action::Pass);

    // ODM0_OPTC_DATA_SOURCE_SELECT: 3.0.2 NUM_OF_OUTPUT_SEGMENT [3:2], SEG0 [11:8], SEG1 [15:12]
    // -> 3.1.5 [9:8], [19:16], [23:20]; NUM_OF_INPUT_SEGMENT stays [1:0].
    const FieldRemap *odm = fieldRemap(0x34c0 + 0x1acb);
    assert(odm != nullptr && translate(odm->from).action == Action::Pass);
    const uint32_t odm302 = 0x1 | (0x1 << 2) | (0x0 << 8) | (0xf << 12);   // bypass: SEG0=0, SEG1=0xf
    const uint32_t odm315 = remapWrite(*odm, odm302, 0xffffffffu);
    assert((odm315 & 0x3) == 1 && ((odm315 >> 8) & 3) == 1 && ((odm315 >> 16) & 0xf) == 0 &&
           ((odm315 >> 20) & 0xf) == 0xf);
    assert(remapRead(*odm, odm315) == odm302);
    assert(remapWrite(*odm, 0, 0) == 0);
    // HUBPRET0_HUBPRET_CONTROL: DET_BUF_PLANE1_BASE_ADDRESS [11:0] -> [12:4] (9 bits),
    // PACK_3TO2_ELEMENT_DISABLE bit 12 -> 15; bits no 3.0.2 field reaches are preserved.
    const FieldRemap *ret = fieldRemap(0x34c0 + 0x066c);
    assert(ret != nullptr);
    const uint32_t ret315 = remapWrite(*ret, 0x1000 | 0x5, 0xf);
    assert(((ret315 >> 4) & 0x1ff) == 5 && (ret315 & (1u << 15)) && (ret315 & 0xf) == 0xf);
    assert(fieldRemap(0x34c0 + 0x1b41) == nullptr);                        // OTG0_OTG_CONTROL

    DalMailbox mailbox;
    assert(DalMailbox::owns(0x1628a) && !DalMailbox::owns(0x16265));
    assert(mailbox.read(DalMailbox::kResponse) == DalMailbox::kResultOk);   // ready before a message
    assert(!mailbox.write(DalMailbox::kResponse, 0));
    assert(!mailbox.write(DalMailbox::kArgument, 7));
    assert(mailbox.write(DalMailbox::kMessage, 2));                         // GetSmuVersion
    assert(mailbox.message() == 2 && mailbox.argument() == 7);
    assert(mailbox.read(DalMailbox::kResponse) == DalMailbox::kResultFailed);

    AccessCounter<8> counter;
    assert(counter.note(accessKey(7, true)) == 1);
    assert(counter.note(accessKey(7, true)) == 2);
    assert(counter.note(accessKey(7, false)) == 1);
    for (uint32_t k = 100; k < 104; k++) assert(counter.note(k) == 1);
    assert(counter.used() == 6);
    assert(counter.note(200) == 0);                                        // 75% load cap
    assert(counter.note(accessKey(7, true)) == 3);
    return 0;
}
