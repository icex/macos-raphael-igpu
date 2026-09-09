import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "RaphaelGPU.cpp").read_text()
PREFLIGHT = (ROOT / "tools" / "preflight.py").read_text()


class RecoveryLeaseProductionTests(unittest.TestCase):
    def _function(self, start, end):
        begin = SOURCE.index(start)
        finish = SOURCE.index(end, begin)
        return SOURCE[begin:finish]

    def test_wire_loggers_emit_low_then_high_nonce_halves(self):
        owned = self._function(
            "static void wrapVmmSetVSReady", "static void wrapVmmSetAlloc")
        pool = self._function(
            "static bool publishRecoveryPoolStatus", "static bool wrapHwMemEnable")
        self.assertRegex(
            owned,
            re.compile(r'XH2 OWNED nonce=%016llx_%016llx.*?nonce\.first,\s*'
                       r'nonce\.second', re.S))
        self.assertRegex(
            pool,
            re.compile(r'XH2 POOL state=%s nonce=%016llx_%016llx.*?nonce\.first,\s*'
                       r'nonce\.second', re.S))
        self.assertNotIn('CRLOG("XH2:', SOURCE)

    def test_ready_wrapper_preflights_owner_method_and_gart_before_publication(self):
        wrapper = self._function(
            "static void wrapVmmSetVSReady", "static void wrapVmmSetAlloc")
        ordered = [wrapper.index(token) for token in (
            "isRaphaelHardware(hardware)",
            "vt[0x180 / 8] != x6Base + kOffHwAppendReserved",
            "appendReserved(hardware, 0, RaphaelRecoveryV2::LeaseSize, 0x1000)",
            "recoveryLeaseDisjointFromLiveGart(descriptor)",
            "RaphaelRecoveryV2::publishRecord(",
        )]
        self.assertEqual(ordered, sorted(ordered))
        self.assertIn("if (owned && ready != 0", wrapper)
        self.assertIn("XH2 ABORT reason=duplicate-ready", wrapper)
        self.assertIn("XH2 ABORT reason=vmm-range", wrapper)

    def test_pool_wrapper_uses_tested_one_epoch_helper_and_bool_abi(self):
        wrapper = self._function(
            "static bool wrapHwMemEnable", "//\n// Clearing the flag")
        owner = wrapper.index("recoveryLeaseMemoryOwner")
        abort = wrapper.index("XH2 ABORT reason=pool-owner")
        native = wrapper.index("RaphaelRecoveryV2::establishPools(")
        self.assertLess(owner, abort)
        self.assertLess(abort, native)
        self.assertIn("RaphaelRecoveryV2::establishPools(", wrapper)
        self.assertIn("vt[0x198 / 8] != x6Base + kOffHwMemReserve", wrapper)
        self.assertIn("XH2 ABORT reason=duplicate-pool", wrapper)
        self.assertNotIn("static uint32_t wrapHwMemEnable", SOURCE)

    def test_shutdown_disable_does_not_supersede_native_vmm_readiness(self):
        wrapper = self._function(
            "static void wrapVmmSetAlloc", "static void probeRlc")
        call = wrapper.index(
            "FunctionCast(wrapVmmSetAlloc, orgVmmSetAlloc)(self, enable);")
        guard = wrapper.index("if (enable != 0)", call)
        record = wrapper.index("XV2 VMM phase=native", guard)
        self.assertLess(call, guard)
        self.assertLess(guard, record)
        self.assertIn(
            'CRLOG("XV: setMemoryAllocationsEnabled(%u) entry:', wrapper)

    def test_deploy_preflight_guards_the_v2_production_contract(self):
        for token in (
                'static bool wrapHwMemEnable(void *self) {',
                'RaphaelRecoveryV2::establishPools(',
                'vt[0x198 / 8] != x6Base + kOffHwMemReserve',
                'isRaphaelHardware(hardware)',
                'vt[0x180 / 8] != x6Base + kOffHwAppendReserved',
                'recoveryLeaseDisjointFromLiveGart(descriptor)',
                'XH2 ABORT reason=duplicate-ready',
                'XH2 ABORT reason=pool-owner',
                'XH2 ABORT reason=duplicate-pool'):
            self.assertIn(token, PREFLIGHT)
        self.assertNotIn('RaphaelRecovery::activate(descriptor, pool0, pool1)',
                         PREFLIGHT)


if __name__ == "__main__":
    unittest.main()
