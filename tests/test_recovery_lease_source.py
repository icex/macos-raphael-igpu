import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "RaphaelGPU.cpp").read_text()
PREFLIGHT = (ROOT / "tools" / "preflight.py").read_text()
LEASE = (ROOT / "src" / "RecoveryLease.hpp").read_text()


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

    def test_lease_phase_transitions_are_atomic_and_invalidation_is_terminal(self):
        state = LEASE[LEASE.index("class LeaseState"):
                      LEASE.index("struct PoolFreeSnapshot")]
        self.assertRegex(
            state, re.compile(r"__atomic_compare_exchange_n\(\s*&phase_"))
        self.assertIn("__atomic_store_n(&phase_", state)
        establish = LEASE[LEASE.index("inline bool establishBeforeVmm"):
                          LEASE.index("} // namespace RaphaelRecoveryV2")]
        claim = establish.index("state.beginOwnershipPublication()")
        preflight = establish.index("preflight()")
        self.assertLess(claim, preflight)
        self.assertIn("uint32_t phase_", state)
        self.assertNotIn("Phase phase_", state)

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

    def test_lifetime_marker_is_cleared_before_owned_and_authorizes_before_clients(self):
        self.assertIn('#include "RecoveryLifetime.hpp"', SOURCE)
        ready = self._function(
            "static void wrapVmmSetVSReady", "static void wrapVmmSetAlloc")
        lifetime_clear = ready.index(
            "RaphaelRecoveryV3::LifetimeOffset")
        owned_publish = ready.index("RaphaelRecoveryV2::publishRecord(")
        self.assertLess(lifetime_clear, owned_publish)
        self.assertRegex(
            ready,
            re.compile(r"RaphaelRecoveryV2::clearRecord<\s*"
                       r"RaphaelRecoveryV3::LifetimeStatus>"))

        pool = self._function(
            "static bool wrapHwMemEnable", "//\n// Clearing the flag")
        active_publish = pool.index("publishRecoveryPoolStatus(status)")
        lifetime_publish = pool.index("authorizeRecoveryClients(status)")
        self.assertLess(active_publish, lifetime_publish)

    def test_every_late_v2_abort_poison_is_requested_before_diagnostic(self):
        ready = self._function(
            "static void wrapVmmSetVSReady", "static void wrapVmmSetAlloc")
        pool = self._function(
            "static bool wrapHwMemEnable", "//\n// Clearing the flag")
        for body, reason, diagnostic in (
                (ready, "LifetimeReasonDuplicateReady",
                 "XH2 ABORT reason=duplicate-ready"),
                (ready, "LifetimeReasonVmmRange",
                 "XH2 ABORT reason=vmm-range"),
                (pool, "LifetimeReasonPoolOwner",
                 "XH2 ABORT reason=pool-owner"),
                (pool, "LifetimeReasonDuplicatePool",
                 "XH2 ABORT reason=duplicate-pool")):
            poison = body.index("abortRecoveryLifetime(\n", 0,
                                body.index(diagnostic))
            self.assertIn(reason, body[poison:body.index(diagnostic)])

        abort_helper = self._function(
            "static void abortRecoveryLifetime", "static bool authorizeRecoveryClients")
        request = abort_helper.index("recoveryLifetimeGate.requestAbort(reason)")
        invalidate = abort_helper.index("recoveryLeaseState.invalidate()")
        durable = abort_helper.index(
            "request == RaphaelRecoveryV3::AbortRequest::Owner")
        self.assertLess(request, invalidate)
        self.assertLess(invalidate, durable)

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

    def test_early_disable_is_suppressed_before_vmm_ownership(self):
        wrapper = self._function(
            "static void wrapVmmSetAlloc", "static void probeRlc")
        guard = wrapper.index("early disable", 0)
        native = wrapper.index(
            "FunctionCast(wrapVmmSetAlloc, orgVmmSetAlloc)(self, enable);", guard)
        self.assertLess(guard, native)
        self.assertIn("slot(0x20) == nullptr", wrapper)
        self.assertIn("slot(0x28) == nullptr", wrapper)
        self.assertIn("recoveryLeaseConfigured", wrapper)

    def test_deploy_preflight_guards_the_v2_production_contract(self):
        for token in (
                'static bool wrapHwMemEnable(void *self) {',
                'RaphaelRecoveryV2::establishPools(',
                'vt[0x198 / 8] != x6Base + kOffHwMemReserve',
                'isRaphaelHardware(hardware)',
                'vt[0x180 / 8] != x6Base + kOffHwAppendReserved',
                'recoveryLeaseDisjointFromLiveGart(descriptor)',
                'RaphaelRecoveryV3::LifetimeOffset',
                'authorizeRecoveryClients(status)',
                'LifetimeReasonDuplicateReady',
                'LifetimeReasonVmmRange',
                'LifetimeReasonPoolOwner',
                'LifetimeReasonDuplicatePool',
                'XH2 ABORT reason=duplicate-ready',
                'XH2 ABORT reason=pool-owner',
                'XH2 ABORT reason=duplicate-pool'):
            self.assertIn(token, PREFLIGHT)
        self.assertNotIn('RaphaelRecovery::activate(descriptor, pool0, pool1)',
                         PREFLIGHT)


if __name__ == "__main__":
    unittest.main()
