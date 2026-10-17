# VCN firmware candidate234

Launch46 serial1503: fw_dir_get devType8 ativvaxy_vcn3_1.dat MISS. Native
24G830 registrations atHWLibs0xfee..0x1006 register only ativvaxy_vcn3.dat for8.
VCN0EncLLQ then stalls while graphics/SDMA/VMPT complete. Missing firmware is a
concrete initialization defect, not yet proof it is the only remaining defect.

Native _engine_sw_init0x86ebe copies input+0x18 to context+8 and constructs its
internal IP version atctx+0x268 fromctx+0x10/14. _engine_init_pfn_ptr supports
0x30000/1. _engine_3_0_set_fw_entry_info0x94b65 maps3.1 to the missing filename.
_internal_cos_read_fw0x86648 takes(engine*, input*) with pointer/capacity/name at
input0/8/16. Return is copied byte count; zero means missing/failed read.
The native caller allocates1MiB and retains ownership. Existing native code accepts
an absent image without making SW initialization fail (0x94be2..0x94be7).

Candidate234 opts in with rgpuvcnfw=1. It supplies the host-installed Raphael
vcn_3_1_2.bin payload only for the exact filename and internal version0x30001,
with null/capacity guards. Preserve AMD signed256-byte header; remove only the
Linux outer256-byte wrapper, whose offset/size/header fields were validated.
Native _check_fw_header recognizes AMD@ at+0xa0 and native _set_fw_version reads
+0x60. Native firmware authentication, allocation, initialization and return values
are retained. No substitution of the older Apple VCN3 image or forced success.

Metadata/hashes: build-support/vcn-firmware.json; redistributable AMD licence in
build-support/LICENSE.amdgpu (already included in releases). Header integrity test
checks payload SHA, size and native-recognized header/version. Both hook entry
prologues checked against the exact local24G830 Mach-O using segment translation.
Additional _vcn_hw_init wrapper records input IP/flags/loadmode/firmware and actual
native result, without modifying it. No added MMIO in these wrappers.

Hypothesis: the missing image prevents video-engine startup. The discriminating
observation is image accepted/native initialization followed by completed encoded
frames; a supplied image with the same queue stall rejects firmware supply alone
as sufficient. Firmware command compatibility and actual engine startup are still
untested. Visible corruption requires separate format/compositing coverage.


Launch47 supplied574032 bytes, version04121015. Native HW init0; PSP type13
LOAD_IP_FW succeeds status0 atTMR0xf41f400000. VCN7e04 changes901->906 and
80e0/e1 become50/50. Nevertheless first H264 VCN0EncLLQ TS1 stalls, ring2
7eaf/b0=f40fb08000, RPTR7eb2=0, WPTR7eb3=20. Other engines complete.
Therefore missing firmware was real but supply alone is insufficient. The nearby
PSP unsupported event has tag20, whereas actual VCN type13 load succeeds; do not
attribute that event to VCN without tracing its firmware ID.12 surface/blend cases
pass but visual desktop is still unqualified. Forced shutdown/recovered receipt,
MODE2 reset75 clean, VM stopped. See status for exact run/build/results.
