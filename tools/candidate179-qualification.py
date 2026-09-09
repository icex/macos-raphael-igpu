#!/usr/bin/env python3
"""Validate one exact candidate-179 same-boot launch authority; no hardware access."""

import hashlib
import json
import math
from pathlib import Path
import re
import struct


ROOT = Path(__file__).resolve().parents[1]
BOOT_ID = '5d6f45d0-4384-4340-b819-7751bc26ebb3'
PRIOR_RUN_ID = '4a45f4a4c1dd49c69fab2dc37e2e4898'
PRIOR_RECOVERY_ID = '8fb71c4acf944fa3b6ee545dfb58a448'
TERMINAL_LEDGER_SHA256 = (
    '8105707580a4d89b2e883be90730e1e84ad32f42e69a0310264f3e5431f0260f')
PRIOR_CANONICAL_RECEIPT_SHA256 = (
    'fc1c08c831cd0b95862ae397f0ac60f09e312bba6316bac67c9cceae609e956c')
PRIOR_RUN_RECEIPT_SHA256 = (
    'ea9f41341b5d0f5ff08f7ef72ee44bd052c2a823ebeaae267c57798b5dd789d5')
PURPOSE = 'candidate179-native-vmm-arena-one-run'
DESIGN_PATH = (ROOT / 'docs/superpowers/specs/'
               '2026-09-10-candidate-179-one-run-qualification-design.md')
EXPERIMENT_CARD_PATH = ROOT / 'experiments/metal-012.json'
FROZEN_LEDGER_PATH = (ROOT / 'findings/experiments/metal-011-178-b/'
                      'used-gpu-boot-ledger.json')
RECOVERY_HELPER_PATHS = (
    'tools/vfio-recover.py',
    'tools/recovery_lease_v2.py',
    'tools/kiq-recovery-proof.py',
)
MANIFEST_RELATIVE_PATH = 'run/candidate179-qualification-manifests/179.json'
OUTPUT_RELATIVE_PATH = 'run/metal-012-179'
POLICY_FIELDS = {
    'schema', 'kind', 'boot_id', 'ledger_preimage_sha256',
    'prior_run_id', 'prior_recovery_id',
    'prior_canonical_receipt_sha256', 'prior_run_receipt_sha256',
    'design_sha256', 'experiment_py_sha256', 'qualification_helper_sha256',
    'recovery_helpers_sha256', 'experiment_card_sha256',
    'manifest_path', 'manifest_sha256', 'run_id', 'output_path',
    'from_max_launches', 'to_max_launches', 'additional_launches',
    'vm_max_seconds', 'probe_max_seconds', 'automatic_extension',
    'automatic_retry', 'purpose',
}
ACTIVATION_FIELDS = {
    'schema', 'kind', 'stage', 'boot_id', 'policy_sha256',
    'ledger_preimage_sha256', 'manifest_sha256', 'run_id',
    'prior_run_id', 'recovery_id', 'canonical_recovery_receipt_sha256',
    'run_recovery_receipt_sha256', 'automatic_retry',
}
GATE_FIELDS = {
    'kernel_cursor_before', 'kernel_cursor_after', 'kernel_messages',
    'host_gate', 'vfio_gate', 'identity_gate',
    'active_launch_units', 'pending_launches',
}
REQUIRED_IDENTITY_FIELDS = {
    'run_id', 'boot_id', 'boot_args', 'recovery_lease_schema',
    'recovery_helpers_sha256', 'build_id', 'source_sha256',
    'binary_sha256', 'bootdisk_sha256',
}
HOST_FAULT = re.compile(
    r'BUG:|Oops:|Hardware Error|IO_PAGE_FAULT|hard LOCKUP|soft lockup|MCE:|'
    r'AMD-Vi:.*fault|vfio.*(?:error|failed)|vfio-pci 0000:7b:00\.0: '
    r'(?:resetting|reset done)\b', re.I)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def current_recovery_helpers_sha256():
    return {relative: sha((ROOT / relative).read_bytes())
            for relative in RECOVERY_HELPER_PATHS}


def policy_path(vm, boot_id):
    return (Path(vm) / 'run/candidate179-qualification-authorities' /
            boot_id / 'policy.json')


def activation_path(vm, boot_id, run_id):
    return (Path(vm) / 'run/candidate179-qualification-authorities' /
            boot_id / (run_id + '.json'))


def _json_file(path):
    raw = Path(path).read_bytes()
    return raw, json.loads(raw)


def _safe_vm_run_path(vm, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None
    vm = Path(vm).resolve()
    path = (vm / relative).resolve()
    try:
        path.relative_to((vm / 'run').resolve())
    except ValueError:
        return None
    return path


def _journal_cursor_position(cursor, boot_id):
    if not isinstance(cursor, str):
        return None
    match = re.search(r'(?:^|;)i=([0-9a-f]+);b=([A-Za-z0-9-]+)(?:;|$)', cursor)
    if (not match or match[2].replace('-', '').lower() !=
            boot_id.replace('-', '').lower()):
        return None
    return int(match[1], 16)


def _numeric_boot_argument(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'(?:0|0x[0-9a-f]+|[1-9][0-9]*)', value):
        return None
    parsed = int(value, 0)
    return parsed if parsed < 1 << 64 else None


def _manifest_ok(manifest, card, helper_hashes):
    if not isinstance(manifest, dict) or not isinstance(card, dict):
        return False
    run_id = manifest.get('run_id')
    if re.fullmatch(r'[0-9a-f]{32}', str(run_id or '')) is None:
        return False
    nonce_lo, nonce_hi = struct.unpack('<QQ', bytes.fromhex(run_id))
    args = manifest.get('boot_args')
    switch_rows = ([word.split('=', 1) for word in args.split() if '=' in word]
                   if isinstance(args, str) else [])
    switches = dict(switch_rows)
    rgpu_keys = [key for key, _ in switch_rows if key.startswith('rgpu')]
    retired = {'rgpucp', 'rgpureset', 'rgpuic', 'rgpurlc', 'rgpufb'}
    digest_fields = ('source_sha256', 'binary_sha256', 'bootdisk_sha256')
    return (
        manifest.get('boot_id') == BOOT_ID and manifest.get('gpu') is True and
        manifest.get('candidate_directory') == 'run/candidate-179' and
        manifest.get('experiment') == 'metal-012' and
        manifest.get('max_seconds') == 180 and type(manifest.get('max_seconds')) is int and
        manifest.get('recovery_lease_schema') == 2 and
        manifest.get('recovery_helpers_sha256') == helper_hashes and
        manifest.get('source_clean') is True and
        manifest.get('bootdisk_verified') is True and
        re.fullmatch(r'[0-9a-f]{32}', str(manifest.get('build_id', ''))) is not None and
        all(re.fullmatch(r'[0-9a-f]{64}', str(manifest.get(key, ''))) is not None
            for key in digest_fields) and
        len(rgpu_keys) == len(set(rgpu_keys)) and
        not retired.intersection(switches) and
        manifest.get('spec') == card and card.get('id') == 'metal-012' and
        card.get('candidate_version') == '1.0.179' and
        card.get('requested_diagnostic') == 'rgpusubmit=1' and
        card.get('max_seconds') == 180 and
        card.get('run_probe_only_after_native_start') is True and
        'one separately reviewed candidate 179 reservation only' in
            str(card.get('repeat_policy', '')) and
        'no automatic retry or extension' in str(card.get('repeat_policy', '')) and
        switches.get('rgpu') == '0xfffa5981' and
        switches.get('rgpuvmm') == '3' and switches.get('rgpumem') == '1' and
        switches.get('rgpuptb') == '2' and switches.get('rgpumqd') == '2' and
        switches.get('rgpuhybrid') == '1' and
        switches.get(card['requested_diagnostic'].split('=', 1)[0]) ==
            card['requested_diagnostic'].split('=', 1)[1] and
        _numeric_boot_argument(switches.get('rgpurnlo')) == nonce_lo and
        _numeric_boot_argument(switches.get('rgpurnhi')) == nonce_hi)


def authorize(vm, manifest, manifest_path, output, expected_policy_sha256,
              expected_activation_sha256, hooks):
    """Read and validate the exact one-run authority without reserving a launch."""
    vm = Path(vm)
    errors = []
    if (re.fullmatch(r'[0-9a-f]{64}', str(expected_policy_sha256 or '')) is None or
            re.fullmatch(r'[0-9a-f]{64}', str(expected_activation_sha256 or '')) is None):
        return None, ['candidate179_authority']
    run_id = manifest.get('run_id') if isinstance(manifest, dict) else None
    if re.fullmatch(r'[0-9a-f]{32}', str(run_id or '')) is None:
        return None, ['candidate179_manifest']
    try:
        policy_raw, policy = _json_file(policy_path(vm, BOOT_ID))
        activation_raw, activation = _json_file(
            activation_path(vm, BOOT_ID, run_id))
        manifest_raw, pinned_manifest = _json_file(
            _safe_vm_run_path(vm, MANIFEST_RELATIVE_PATH))
        card_raw, card = _json_file(EXPERIMENT_CARD_PATH)
        design_raw = DESIGN_PATH.read_bytes()
        ledger_path = vm / 'run/used-gpu-boots' / (BOOT_ID + '.json')
        ledger_raw, ledger = _json_file(ledger_path)
        frozen_raw, frozen_ledger = _json_file(FROZEN_LEDGER_PATH)
        canonical_path = vm / 'run/vfio-recovery' / BOOT_ID / (PRIOR_RUN_ID + '.json')
        run_receipt_path = vm / 'run/metal-011-178-b/recovery.json'
        canonical_raw, canonical = _json_file(canonical_path)
        run_receipt_raw, run_receipt = _json_file(run_receipt_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None, ['candidate179_authority']

    try:
        helper_hashes = current_recovery_helpers_sha256()
        experiment_raw = (ROOT / 'tools/experiment.py').read_bytes()
        qualification_raw = Path(__file__).resolve().read_bytes()
    except OSError:
        return None, ['candidate179_authority']
    fixed_policy = {
        'schema':1, 'kind':'candidate179-one-run-qualification-policy',
        'boot_id':BOOT_ID, 'ledger_preimage_sha256':TERMINAL_LEDGER_SHA256,
        'prior_run_id':PRIOR_RUN_ID, 'prior_recovery_id':PRIOR_RECOVERY_ID,
        'prior_canonical_receipt_sha256':PRIOR_CANONICAL_RECEIPT_SHA256,
        'prior_run_receipt_sha256':PRIOR_RUN_RECEIPT_SHA256,
        'design_sha256':sha(design_raw),
        'experiment_py_sha256':sha(experiment_raw),
        'qualification_helper_sha256':sha(qualification_raw),
        'recovery_helpers_sha256':helper_hashes,
        'experiment_card_sha256':sha(card_raw),
        'manifest_path':MANIFEST_RELATIVE_PATH, 'manifest_sha256':sha(manifest_raw),
        'run_id':run_id, 'output_path':OUTPUT_RELATIVE_PATH,
        'from_max_launches':6, 'to_max_launches':7, 'additional_launches':1,
        'vm_max_seconds':180, 'probe_max_seconds':45,
        'automatic_extension':False, 'automatic_retry':False, 'purpose':PURPOSE,
    }
    if (sha(policy_raw) != expected_policy_sha256 or not isinstance(policy, dict) or
            set(policy) != POLICY_FIELDS or policy != fixed_policy):
        errors.append('candidate179_authority')
    fixed_activation = {
        'schema':1, 'kind':'candidate179-one-run-qualification-activation',
        'stage':'ONLY', 'boot_id':BOOT_ID,
        'policy_sha256':expected_policy_sha256,
        'ledger_preimage_sha256':TERMINAL_LEDGER_SHA256,
        'manifest_sha256':sha(manifest_raw), 'run_id':run_id,
        'prior_run_id':PRIOR_RUN_ID, 'recovery_id':PRIOR_RECOVERY_ID,
        'canonical_recovery_receipt_sha256':PRIOR_CANONICAL_RECEIPT_SHA256,
        'run_recovery_receipt_sha256':PRIOR_RUN_RECEIPT_SHA256,
        'automatic_retry':False,
    }
    if (sha(activation_raw) != expected_activation_sha256 or
            not isinstance(activation, dict) or set(activation) != ACTIVATION_FIELDS or
            activation != fixed_activation):
        errors.append('candidate179_authority')
    try:
        manifest_argument_path = Path(manifest_path).resolve()
        output_argument_path = Path(output).resolve()
        manifest_argument_ok = manifest_argument_path.read_bytes() == manifest_raw
        output_absent = not output_argument_path.exists()
    except (OSError, TypeError):
        manifest_argument_path = output_argument_path = None
        manifest_argument_ok = output_absent = False
    if (manifest != pinned_manifest or manifest_argument_path !=
            _safe_vm_run_path(vm, MANIFEST_RELATIVE_PATH) or
            not manifest_argument_ok or
            output_argument_path != _safe_vm_run_path(vm, OUTPUT_RELATIVE_PATH) or
            not output_absent or not _manifest_ok(manifest, card, helper_hashes)):
        errors.append('candidate179_manifest')
    try:
        output_argument_path.relative_to(ROOT.resolve())
        errors.append('candidate179_output')
    except (ValueError, AttributeError):
        pass
    launches = ledger.get('launches') if isinstance(ledger, dict) else None
    revisions = ledger.get('cap_revisions') if isinstance(ledger, dict) else None
    ledger_shape_ok = (isinstance(launches, list) and len(launches) == 6 and
                       all(isinstance(row, dict) for row in launches) and
                       isinstance(revisions, list) and len(revisions) == 2 and
                       all(isinstance(row, dict) for row in revisions))
    if (sha(frozen_raw) != TERMINAL_LEDGER_SHA256 or
            sha(ledger_raw) != TERMINAL_LEDGER_SHA256 or ledger != frozen_ledger or
            not ledger_shape_ok or ledger.get('schema') != 4 or
            ledger.get('initial_max_launches') != 3 or ledger.get('max_launches') != 6 or
            launches[-1].get('run_id') != PRIOR_RUN_ID or
            any(row.get('run_id') == run_id for row in launches) or
            PRIOR_RECOVERY_ID in {row.get('recovery_id') for row in launches}):
        errors.append('candidate179_ledger')
    receipt = canonical
    try:
        receipt_errors = hooks.validate_receipt(receipt, BOOT_ID, PRIOR_RUN_ID)
    except Exception:
        receipt_errors = ['receipt']
    if (sha(canonical_raw) != PRIOR_CANONICAL_RECEIPT_SHA256 or
            sha(run_receipt_raw) != PRIOR_RUN_RECEIPT_SHA256 or
            canonical != run_receipt or not isinstance(receipt, dict) or
            receipt.get('schema') != 6 or receipt.get('status') != 'recovered' or
            receipt.get('authorizes_launch') is not True or
            receipt.get('boot_id') != BOOT_ID or
            receipt.get('prior_run_id') != PRIOR_RUN_ID or
            receipt.get('recovery_id') != PRIOR_RECOVERY_ID or receipt_errors):
        errors.append('candidate179_receipt')
    if errors:
        return None, sorted(set(errors))
    return {
        'vm':vm.resolve(),
        'manifest':pinned_manifest, 'manifest_path':Path(manifest_path).resolve(),
        'manifest_raw':manifest_raw, 'output':Path(output).resolve(),
        'policy':policy, 'policy_path':policy_path(vm, BOOT_ID),
        'policy_raw':policy_raw, 'policy_sha256':expected_policy_sha256,
        'activation':activation,
        'activation_path':activation_path(vm, BOOT_ID, run_id),
        'activation_raw':activation_raw,
        'activation_sha256':expected_activation_sha256,
        'ledger_path':ledger_path, 'ledger_raw':ledger_raw,
        'receipt':receipt, 'receipt_paths':[canonical_path, run_receipt_path],
        'receipt_raws':[canonical_raw, run_receipt_raw],
        'card_raw':card_raw, 'design_raw':design_raw, 'hooks':hooks,
    }, []


def build_reservation(authorization, boot_id, run_id, recovery, gate,
                      reserved_epoch):
    """Return the prospective schema-5 row-7 ledger without writing it."""
    if (not isinstance(authorization, dict) or boot_id != BOOT_ID or
            run_id != authorization.get('manifest', {}).get('run_id') or
            recovery != authorization.get('receipt') or
            not isinstance(gate, dict) or set(gate) != GATE_FIELDS or
            type(reserved_epoch) not in (int, float) or
            not math.isfinite(reserved_epoch) or reserved_epoch < 0):
        raise ValueError('candidate179 qualification refused: arguments')
    try:
        vm = Path(authorization['vm']).resolve()
        parsed_policy = json.loads(authorization['policy_raw'])
        parsed_activation = json.loads(authorization['activation_raw'])
        parsed_manifest = json.loads(authorization['manifest_raw'])
        expected_paths = {
            'policy_path':policy_path(vm, BOOT_ID),
            'activation_path':activation_path(vm, BOOT_ID, run_id),
            'manifest_path':_safe_vm_run_path(vm, MANIFEST_RELATIVE_PATH),
            'ledger_path':vm / 'run/used-gpu-boots' / (BOOT_ID + '.json'),
            'output':_safe_vm_run_path(vm, OUTPUT_RELATIVE_PATH),
        }
        values_unchanged = (
            parsed_policy == authorization['policy'] and
            parsed_activation == authorization['activation'] and
            parsed_manifest == authorization['manifest'] and
            parsed_policy.get('run_id') == run_id and
            parsed_activation.get('run_id') == run_id and
            all(Path(authorization[key]).resolve() == path
                for key, path in expected_paths.items()))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        values_unchanged = False
    if not values_unchanged:
        raise ValueError('candidate179 qualification refused: concurrent_change')
    immutable = {
        authorization['policy_path']:authorization['policy_raw'],
        authorization['activation_path']:authorization['activation_raw'],
        authorization['manifest_path']:authorization['manifest_raw'],
        authorization['ledger_path']:authorization['ledger_raw'],
        authorization['receipt_paths'][0]:authorization['receipt_raws'][0],
        authorization['receipt_paths'][1]:authorization['receipt_raws'][1],
    }
    try:
        if any(Path(path).read_bytes() != raw for path, raw in immutable.items()):
            raise ValueError('candidate179 qualification refused: concurrent_change')
        policy = authorization['policy']
        if (sha(DESIGN_PATH.read_bytes()) != policy['design_sha256'] or
                sha(EXPERIMENT_CARD_PATH.read_bytes()) != policy['experiment_card_sha256'] or
                sha((ROOT / 'tools/experiment.py').read_bytes()) !=
                    policy['experiment_py_sha256'] or
                sha(Path(__file__).resolve().read_bytes()) !=
                    policy['qualification_helper_sha256'] or
                current_recovery_helpers_sha256() !=
                    policy['recovery_helpers_sha256']):
            raise ValueError('candidate179 qualification refused: concurrent_change')
    except (KeyError, OSError):
        raise ValueError('candidate179 qualification refused: concurrent_change')

    try:
        output_entries = {path.name:path for path in authorization['output'].iterdir()}
        output_manifest = output_entries.get('manifest.json')
        output_host = output_entries.get('host-before.json')
        host_before = json.loads(output_host.read_bytes())
        output_ok = (
            authorization['output'].is_dir() and
            not authorization['output'].is_symlink() and
            set(output_entries) == {'manifest.json', 'host-before.json'} and
            all(path.is_file() and not path.is_symlink()
                for path in output_entries.values()) and
            output_manifest.read_bytes() == authorization['manifest_raw'] and
            isinstance(host_before, dict) and host_before.get('boot_id') == BOOT_ID)
    except (OSError, AttributeError, TypeError, json.JSONDecodeError):
        output_ok = False
    if not output_ok:
        raise ValueError('candidate179 qualification refused: concurrent_change')

    before = _journal_cursor_position(gate.get('kernel_cursor_before'), BOOT_ID)
    after = _journal_cursor_position(gate.get('kernel_cursor_after'), BOOT_ID)
    identity = gate.get('identity_gate')
    hooks = authorization.get('hooks')
    try:
        host_errors = hooks.validate_host(gate.get('host_gate'), BOOT_ID)
        vfio_errors = hooks.validate_vfio(gate.get('vfio_gate'), BOOT_ID)
        receipt_errors = hooks.validate_receipt(recovery, BOOT_ID, PRIOR_RUN_ID)
    except Exception:
        host_errors = vfio_errors = receipt_errors = ['gate']
    try:
        receipt_copies_match = (
            json.loads(authorization['receipt_raws'][0]) == recovery and
            json.loads(authorization['receipt_raws'][1]) == recovery)
    except (KeyError, TypeError, json.JSONDecodeError):
        receipt_copies_match = False
    if (gate.get('kernel_cursor_before') != recovery.get('kernel_cursor_after') or
            before is None or after is None or after < before or
            not isinstance(gate.get('kernel_messages'), list) or
            any(not isinstance(message, str) or HOST_FAULT.search(message)
                for message in gate['kernel_messages']) or
            host_errors or vfio_errors or receipt_errors or
            not receipt_copies_match or
            not isinstance(identity, dict) or
            not REQUIRED_IDENTITY_FIELDS.issubset(identity) or
            any(authorization['manifest'].get(key) != value
                for key, value in identity.items()) or
            gate.get('active_launch_units') != [] or gate.get('pending_launches') != []):
        raise ValueError('candidate179 qualification refused: live_gate')

    ledger = json.loads(authorization['ledger_raw'])
    launches = list(ledger['launches'])
    revisions = list(ledger['cap_revisions'])
    if (ledger.get('schema') != 4 or ledger.get('max_launches') != 6 or
            len(launches) != 6 or len(revisions) != 2 or
            launches[-1].get('run_id') != PRIOR_RUN_ID or
            any(row.get('run_id') == run_id for row in launches) or
            PRIOR_RECOVERY_ID in {row.get('recovery_id') for row in launches}):
        raise ValueError('candidate179 qualification refused: launch_ceiling')
    revisions.append({
        'policy_sha256':authorization['policy_sha256'],
        'activation_sha256':authorization['activation_sha256'],
        'ledger_preimage_sha256':TERMINAL_LEDGER_SHA256,
        'from_max_launches':6, 'to_max_launches':7, 'additional_launches':1,
        'automatic_extension':False, 'automatic_retry':False,
        'purpose':PURPOSE, **gate,
    })
    launches.append({
        'run_id':run_id, 'reserved_epoch':reserved_epoch,
        'recovery_id':recovery['recovery_id'],
        'prior_run_id':recovery['prior_run_id'],
        'candidate179_policy_sha256':authorization['policy_sha256'],
        'candidate179_activation_sha256':authorization['activation_sha256'],
        'qualification':PURPOSE, 'qualification_ordinal':'ONLY',
    })
    updated = dict(ledger)
    updated.update(schema=5, initial_max_launches=3, max_launches=7,
                   cap_revisions=revisions, launches=launches)
    return authorization['ledger_path'], updated
