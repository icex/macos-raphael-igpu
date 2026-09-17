"""candidate 284: rgpuvcnpreset=1 forces the VCN BALANCE encoding preset in
AMDRadeonVADriver2 through the same current-task COW path as kVcnDpmTarget.
Assert the boot-arg name, startup log, and per-target COW/image log strings
exist verbatim, and that the new targets are wired through the shared gate."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VcnPresetSourceTests(unittest.TestCase):
    def test_boot_arg_is_parsed_and_logged(self):
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        self.assertIn(
            'vcnPresetEnabled = PE_parse_boot_argn("rgpuvcnpreset", &vcnPreset, sizeof(vcnPreset)) &&\n'
            '        vcnPreset == 1;',
            source)
        self.assertIn('RLOG("VCNPRESET: rgpuvcnpreset=%u", vcnPresetEnabled);', source)

    def test_lock_allocated_when_boot_arg_set(self):
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        self.assertIn(
            'if (texDiagEnabled == 2 || vcnNoDpmEnabled || vcnPresetEnabled || vd120Enabled)\n'
            '        textureDiagCowLock = IOLockAlloc();',
            source)

    def test_cow_and_image_log_lines_exist(self):
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        self.assertIn(
            '"VCNPRESET: COW target=%s pid=%d addr=%#llx p=%d w=%d r=%d v=%d"',
            source)
        self.assertIn(
            '"VCNPRESET: image target=%s pid=%d st=%u uuid=%u bytes=%u patched=%u addr=%#llx"',
            source)

    def test_preset_gate_requires_existing_vcn_dpm_conditions(self):
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        start = source.index('static bool diagTargetGateOpen(DiagTargetKind kind) {')
        end = source.index('\n}\n', start)
        body = source[start:end]
        self.assertIn('case DiagTargetKind::kVcnPreset:', body)
        self.assertIn(
            'return vcnPresetEnabled && vcnNoDpmEnabled &&\n'
            '               __atomic_load_n(&ppCompatibilityBypassed, __ATOMIC_ACQUIRE);',
            body)

    def test_three_preset_targets_share_vcn_dpm_image_identity(self):
        source = (ROOT / 'src/TextureDiagParser.hpp').read_text()
        for name in ('kVcnPresetValueTarget', 'kVcnPresetHevcGateTarget',
                     'kVcnPresetAvcGateTarget'):
            self.assertIn(
                f'kVcnDpmDriverPath, sizeof(kVcnDpmDriverPath), kVcnDpmUuid,',
                source)
            self.assertIn(name, source)

    def test_new_targets_are_registered_in_the_diag_target_table(self):
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        start = source.index('const DiagTargetEntry kDiagTargets[] = {')
        end = source.index('};', start)
        body = source[start:end]
        self.assertIn('&RaphaelTextureDiag::kTextureTarget, DiagTargetKind::kMetal', body)
        self.assertIn('&RaphaelTextureDiag::kVcnDpmTarget, DiagTargetKind::kVcnDpm', body)
        self.assertIn('&RaphaelTextureDiag::kFeedbackTarget, DiagTargetKind::kFeedback', body)
        self.assertIn(
            '&RaphaelTextureDiag::kVcnPresetValueTarget, DiagTargetKind::kVcnPreset, "preset-value"',
            body)
        self.assertIn(
            '&RaphaelTextureDiag::kVcnPresetHevcGateTarget, DiagTargetKind::kVcnPreset, "hevc-gate"',
            body)
        self.assertIn(
            '&RaphaelTextureDiag::kVcnPresetAvcGateTarget, DiagTargetKind::kVcnPreset, "avc-gate"',
            body)


if __name__ == '__main__':
    unittest.main()
