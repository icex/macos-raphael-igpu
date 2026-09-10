#!/usr/bin/env python3
"""Exact two-run candidate-178 warm-qualification policy; no hardware access."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
BOOT_ID = '5d6f45d0-4384-4340-b819-7751bc26ebb3'
PRIOR_RUN_ID = 'ff2eb6e2492a4c5c96c6c6a847ed0c26'
PRIOR_RECOVERY_ID = '2a24e2279e9b40d383e9f3e23f2c02f7'
CANDIDATE176_RUN_ID = 'e02fbed46a6a4df4ae48d7c1d8597985'
CANDIDATE176_RECOVERY_ID = '11602bc7c6f84c75afb1f2cb617a319c'
CANDIDATE176_CANONICAL_RECEIPT_SHA256 = (
    '4e6c1519f18c0bb60efeb816045eb3aedf6231a0ef8746a530c768996e7e6676')
CANDIDATE176_RUN_RECEIPT_SHA256 = (
    '77b0931dcefe4c710db724d6cedbda22acf42c3c43de2f0aba25546d396ea180')
FOUR_ROW_LEDGER_SHA256 = 'e319d5d954e063a7142bd4873a597cc3bb8ccb9b29d577511eaaf92f924fd496'
PRIOR_CANONICAL_RECEIPT_SHA256 = 'e2fcf3ba93d88b0e19ac5a71260029ead38b501cf1dc5b2adce0bddd6482c446'
PRIOR_RUN_RECEIPT_SHA256 = '09aa1cfd2433b587d37fa45bc23c75ade7757edbae19711af3c83877a980ce4b'
DESIGN_SHA256 = '7b88e2f2b44f50b26104545055c672057762259142cc0d439c25074d7d81377b'
DESIGN_PATH = (ROOT / 'docs/superpowers/specs/'
               '2026-09-09-two-run-warm-qualification-design.md')
PURPOSE = 'm7-two-run-warm-qualification'

POLICY_FIELDS = {
    'schema', 'kind', 'boot_id', 'ledger_preimage_sha256',
    'prior_run_id', 'prior_recovery_id',
    'prior_canonical_receipt_sha256', 'prior_run_receipt_sha256',
    'candidate176_run_id', 'candidate176_recovery_id',
    'candidate176_canonical_receipt_sha256',
    'candidate176_run_receipt_sha256',
    'design_sha256', 'experiment_py_sha256',
    'qualification_helper_sha256', 'recovery_producer_sha256',
    'experiment_card_sha256',
    'manifest_a_path', 'manifest_a_sha256', 'run_id_a', 'output_a_path',
    'manifest_b_path', 'manifest_b_sha256', 'run_id_b', 'output_b_path',
    'from_max_launches', 'to_max_launches', 'additional_launches',
    'vm_max_seconds', 'probe_max_seconds', 'automatic_extension', 'purpose',
}
ACTIVATION_A_FIELDS = {
    'schema', 'kind', 'stage', 'boot_id', 'policy_sha256',
    'ledger_preimage_sha256', 'manifest_sha256', 'run_id',
    'prior_run_id', 'recovery_id', 'canonical_recovery_receipt_sha256',
    'run_recovery_receipt_sha256', 'automatic_retry',
}
ACTIVATION_B_FIELDS = ACTIVATION_A_FIELDS | {
    'a_output_sha256', 'a_activation_sha256',
}
GATE_FIELDS = {
    'kernel_cursor_before', 'kernel_cursor_after', 'kernel_messages',
    'host_gate', 'vfio_gate', 'identity_gate',
    'active_launch_units', 'pending_launches',
}
HOST_FAULT = re.compile(
    r'BUG:|Oops:|Hardware Error|IO_PAGE_FAULT|hard LOCKUP|soft lockup|MCE:|'
    r'AMD-Vi:.*fault|vfio.*(?:error|failed)|vfio-pci 0000:7b:00\.0: '
    r'(?:resetting|reset done)\b', re.I)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def policy_path(vm, boot_id):
    return Path(vm) / 'run/warm-qualification-authorities' / boot_id / 'policy.json'


def activation_path(vm, boot_id, run_id):
    return (Path(vm) / 'run/warm-qualification-authorities' / boot_id /
            (run_id + '.json'))


def evidence_digest(directory):
    rows = []
    for path in sorted(Path(directory).iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.is_symlink():
            raise ValueError('warm output contains unsupported entries')
        rows.append({'name': path.name, 'sha256': sha(path.read_bytes())})
    return sha(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode())


def _json_file(path):
    raw = Path(path).read_bytes()
    return raw, json.loads(raw)


def _safe_vm_run_path(vm, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return None
    vm = Path(vm).resolve()
    path = (vm / value).resolve()
    run = (vm / 'run').resolve()
    try:
        path.relative_to(run)
    except ValueError:
        return None
    return path


def _journal_cursor_position(cursor, boot_id):
    if not isinstance(cursor, str):
        return None
    match = re.search(r'(?:^|;)i=([0-9a-f]+);b=([A-Za-z0-9-]+)(?:;|$)',
                      cursor)
    if (not match or match[2].replace('-', '').lower() !=
            boot_id.replace('-', '').lower()):
        return None
    return int(match[1], 16)


def _manifest_ok(manifest, card):
    spec = manifest.get('spec') if isinstance(manifest, dict) else None
    return (
        isinstance(manifest, dict) and manifest.get('boot_id') == BOOT_ID and
        re.fullmatch(r'[0-9a-f]{32}', str(manifest.get('run_id', ''))) is not None and
        manifest.get('gpu') is True and manifest.get('source_clean') is True and
        manifest.get('candidate_directory') == 'run/candidate-178' and
        manifest.get('experiment') == 'metal-011' and
        type(manifest.get('max_seconds')) is int and manifest['max_seconds'] == 180 and
        isinstance(spec, dict) and spec == card and
        spec.get('id') == 'metal-011' and spec.get('candidate_version') == '1.0.178' and
        spec.get('requested_diagnostic') == 'rgpusubmit=1' and
        type(spec.get('max_seconds')) is int and spec['max_seconds'] == 180 and
        spec.get('run_probe_only_after_native_start') is True and
        'unchanged 45-second Metal probe' in str(spec.get('behavior_change', '')) and
        'no automatic retry' in str(spec.get('repeat_policy', ''))
    )


def _same_artifact_manifest(a, b):
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    left = dict(a); right = dict(b)
    left.pop('run_id', None); right.pop('run_id', None)
    return left == right and a.get('run_id') != b.get('run_id')


def _ledger_gate_ok(gate, manifest):
    if not isinstance(gate, dict) or set(gate) != GATE_FIELDS:
        return False
    before = _journal_cursor_position(gate.get('kernel_cursor_before'), BOOT_ID)
    after = _journal_cursor_position(gate.get('kernel_cursor_after'), BOOT_ID)
    identity = gate.get('identity_gate')
    identity_keys = {
        'binary_sha256', 'info_sha256', 'config_sha256', 'build_id',
        'source_sha256', 'source_commit', 'source_clean',
        'built_from_commit', 'kdk_sha256', 'build_inputs_sha256', 'boot_args',
        'harness_sha256', 'rom_sha256', 'launch_options', 'image_id',
        'guest_build', 'probe_source_sha256', 'probe_binary_sha256',
        'boot_id', 'kernel', 'bootdisk_sha256',
    }
    host = gate.get('host_gate')
    host_keys = {
        'boot_id', 'active_vm', 'driver', 'device', 'iommu_group',
        'pci_command', 'reset_methods', 'canonical_device', 'power_control',
        'power_state', 'runtime_status', 'enable_count', 'sleep_inhibited',
        'watchdogs', 'residual_units', 'siblings', 'reset_domain',
        'kernel_release', 'vfio_module_sha256', 'vfio_module_build_id',
        'journal_cursor', 'journal_messages', 'journal_faults',
        'amdgpu_initialized', 'capture_ready', 'watchdogs_verified',
        'device_pinned_awake', 'device_accessible', 'pstore_files',
    }
    vfio = gate.get('vfio_gate')
    vfio_keys = {
        'boot_id', 'active_vm', 'driver', 'device', 'iommu_group',
        'pci_command', 'reset_methods',
    }
    return (
        before is not None and after is not None and after >= before and
        isinstance(gate.get('kernel_messages'), list) and
        all(isinstance(message, str) and not HOST_FAULT.search(message)
            for message in gate['kernel_messages']) and
        isinstance(host, dict) and set(host) == host_keys and
        host.get('boot_id') == BOOT_ID and
        host.get('journal_cursor') == gate.get('kernel_cursor_after') and
        host.get('journal_messages') == gate.get('kernel_messages') and
        (host.get('pstore_files') is None or isinstance(host.get('pstore_files'), list)) and
        isinstance(vfio, dict) and set(vfio) == vfio_keys and
        vfio.get('boot_id') == BOOT_ID and
        isinstance(identity, dict) and set(identity) == identity_keys and
        all(manifest.get(key) == value for key, value in identity.items()) and
        gate.get('active_launch_units') == [] and gate.get('pending_launches') == []
    )


def _base_ledger_ok(ledger, stage, policy_sha256, activation, manifest_a=None,
                    prior_cursor=None):
    if not isinstance(ledger, dict) or ledger.get('boot_id') != BOOT_ID:
        return False
    launches = ledger.get('launches')
    revisions = ledger.get('cap_revisions')
    if (not isinstance(launches, list) or
            any(not isinstance(row, dict) for row in launches) or
            not isinstance(revisions, list)):
        return False
    if stage == 'A':
        return (
            ledger.get('schema') == 3 and ledger.get('initial_max_launches') == 3 and
            ledger.get('max_launches') == 4 and len(launches) == 4 and
            len(revisions) == 1 and launches[-1].get('run_id') == PRIOR_RUN_ID and
            all(row.get('run_id') != activation.get('run_id') for row in launches) and
            PRIOR_RECOVERY_ID not in {row.get('recovery_id') for row in launches}
        )
    try:
        pinned_raw = (ROOT / 'findings/experiments/metal-010-177/'
                      'used-gpu-boot-ledger.json').read_bytes()
        pinned = json.loads(pinned_raw)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    if (sha(pinned_raw) != FOUR_ROW_LEDGER_SHA256 or
            launches[:4] != pinned.get('launches') or
            revisions[:1] != pinned.get('cap_revisions')):
        return False
    a_row = launches[-1]
    a_revision = revisions[-1]
    row_fields = {
        'run_id', 'reserved_epoch', 'recovery_id', 'prior_run_id',
        'warm_qualification_policy_sha256',
        'warm_qualification_activation_sha256', 'qualification',
        'qualification_ordinal',
    }
    revision_fields = {
        'policy_sha256', 'activation_a_sha256', 'ledger_preimage_sha256',
        'from_max_launches', 'to_max_launches', 'additional_launches',
        'purpose',
    } | GATE_FIELDS
    revision_gate = {key:a_revision.get(key) for key in GATE_FIELDS}
    return (
        ledger.get('schema') == 4 and ledger.get('initial_max_launches') == 3 and
        ledger.get('max_launches') == 6 and len(launches) == 5 and
        len(revisions) == 2 and
        revisions[-1].get('policy_sha256') == policy_sha256 and
        revisions[-1].get('from_max_launches') == 4 and
        revisions[-1].get('to_max_launches') == 6 and
        revisions[-1].get('additional_launches') == 2 and
        set(a_revision) == revision_fields and
        _ledger_gate_ok(revision_gate, manifest_a) and
        a_revision.get('kernel_cursor_before') == prior_cursor and
        a_revision.get('policy_sha256') == policy_sha256 and
        a_revision.get('activation_a_sha256') ==
            activation.get('a_activation_sha256') and
        a_revision.get('ledger_preimage_sha256') == FOUR_ROW_LEDGER_SHA256 and
        a_revision.get('purpose') == PURPOSE and
        set(a_row) == row_fields and
        type(a_row.get('reserved_epoch')) in (int, float) and
        a_row.get('run_id') == activation.get('prior_run_id') and
        a_row.get('prior_run_id') == PRIOR_RUN_ID and
        a_row.get('recovery_id') == PRIOR_RECOVERY_ID and
        a_row.get('qualification') == PURPOSE and
        a_row.get('qualification_ordinal') == 'A' and
        a_row.get('warm_qualification_policy_sha256') == policy_sha256 and
        a_row.get('warm_qualification_activation_sha256') ==
            activation.get('a_activation_sha256') and
        all(row.get('run_id') != activation.get('run_id') for row in launches) and
        activation.get('recovery_id') not in {
            row.get('recovery_id') for row in launches}
    )


def _load_events(path):
    events = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError('event is not an object')
            events.append(value)
    return events


def _probe_ok(probe, run_id):
    if (not isinstance(probe, dict) or probe.get('run_id') != run_id or
            probe.get('transport_exit') != 0 or not isinstance(probe.get('output'), str)):
        return False
    output = probe['output']
    matches = re.findall(r'^RGPU_METAL_RESULT (\{.*\})$', output, re.M)
    exits = re.findall(r'^RGPU_EXIT ([0-9a-f]{32}) ([0-9]+)$', output, re.M)
    if len(matches) != 1 or exits not in ([(run_id, '0')], [(run_id, '1')]):
        return False
    try:
        result = json.loads(matches[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(result, dict) or result.get('run_id') != run_id:
        return False
    if result.get('passed') is True:
        try:
            path = ROOT / 'tools/metal-test.py'
            spec = importlib.util.spec_from_file_location('warm_metal_test', path)
            metal = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(metal)
            metal.validate_output(output, run_id)
        except (AttributeError, OSError, TypeError, ValueError,
                json.JSONDecodeError):
            return False
        return True
    stages = re.findall(r'^RGPU_METAL_STAGE ([a-z_]+)$', output, re.M)
    return (
        result.get('passed') is False and exits == [(run_id, '1')] and
        stages == ['enumerate', 'compile_shaders', 'compute', 'commit'] and
        result.get('device') == 'AMD Radeon Navi23' and
        type(result.get('registry_id')) is int and result['registry_id'] > 0 and
        result.get('metal3') is True and
        all(type(result.get(key)) is int and result[key] == 0 for key in (
            'completed_command_buffers', 'compute_rounds',
            'compute_values_checked', 'render_pixels_checked')) and
        type(result.get('seed')) is int and
        'status=5' in str(result.get('error', '')).lower() and
        'e00002bd' in str(result.get('error', '')).lower()
    )


def _a_evidence(vm, policy, activation, manifest_a, hooks):
    errors = []
    output = _safe_vm_run_path(vm, policy.get('output_a_path'))
    required = {
        'manifest.json', 'supervision.json', 'running-identity.json',
        'events.jsonl', 'serial.txt', 'probe.json', 'shutdown.json',
        'host-before.json', 'host-after.json', 'host-kernel-messages.json',
        'recovery.json', 'verdict.json',
    }
    try:
        if output is None or not output.is_dir() or not required.issubset(
                {path.name for path in output.iterdir() if path.is_file()}):
            return None, ['warm_qualification_a_evidence']
        if evidence_digest(output) != activation.get('a_output_sha256'):
            errors.append('warm_qualification_a_evidence')
        values = {}
        for name in required - {'events.jsonl', 'serial.txt'}:
            _, values[name] = _json_file(output / name)
        events = _load_events(output / 'events.jsonl')
        serial = (output / 'serial.txt').read_bytes()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None, ['warm_qualification_a_evidence']

    if values['manifest.json'] != manifest_a or not serial:
        errors.append('warm_qualification_a_evidence')
    try:
        if hooks.parse_serial(manifest_a, serial.decode('utf-8')) != events:
            errors.append('warm_qualification_a_evidence')
    except (AttributeError, UnicodeDecodeError, ValueError, TypeError):
        errors.append('warm_qualification_a_evidence')
    supervision = values['supervision.json']
    if (not isinstance(supervision, dict) or supervision.get('max_seconds') != 180 or
            not supervision.get('started_at') or not supervision.get('cid') or
            type(supervision.get('deadline_epoch')) not in (int, float) or
            type(supervision.get('launch_deadline_epoch')) not in (int, float)):
        errors.append('warm_qualification_a_evidence')
    if hooks.validate_running(manifest_a, values['running-identity.json']):
        errors.append('warm_qualification_a_evidence')
    if any(event.get('kind') == 'capture_loss' for event in events):
        errors.append('warm_qualification_a_evidence')
    try:
        readiness = hooks.classify_readiness(manifest_a, events)
    except Exception:
        readiness = None
    if (not isinstance(readiness, dict) or readiness.get('valid') is not True or
            readiness.get('verdict') != 'PROBE_NOT_RUN'):
        errors.append('warm_qualification_a_evidence')
    if not _probe_ok(values['probe.json'], manifest_a['run_id']):
        errors.append('warm_qualification_a_evidence')
    shutdown = values['shutdown.json']
    if (not isinstance(shutdown, dict) or
            shutdown.get('outcome') != 'exited-after-guest-request'):
        errors.append('warm_qualification_a_evidence')

    for key in ('host-before.json', 'host-after.json'):
        host = values[key]
        try:
            host_errors = hooks.admit_host(
                manifest_a, host, {BOOT_ID}, reuse_allowed=True)
        except Exception:
            host_errors = ['host']
        if (host_errors or not isinstance(host, dict) or
                host.get('sleep_inhibited') is not True or
                host.get('boot_id') != BOOT_ID):
            errors.append('warm_qualification_a_evidence')
    messages = values['host-kernel-messages.json']
    if (not isinstance(messages, list) or
            any(not isinstance(message, str) or HOST_FAULT.search(message)
                for message in messages)):
        errors.append('warm_qualification_a_evidence')
    verdict = values['verdict.json']
    if (not isinstance(verdict, dict) or verdict.get('warm_reuse') != 'recovered' or
            verdict.get('verdict') in ('INVALID', 'STOP_UNCONFIRMED') or
            verdict.get('error')):
        errors.append('warm_qualification_a_evidence')

    receipt = values['recovery.json']
    canonical_path = Path(vm) / 'run/vfio-recovery' / BOOT_ID / (
        manifest_a['run_id'] + '.json')
    try:
        canonical_raw, canonical = _json_file(canonical_path)
        run_raw = (output / 'recovery.json').read_bytes()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        canonical_raw = run_raw = b''; canonical = None
        errors.append('warm_qualification_a_evidence')
    if (canonical != receipt or
            sha(canonical_raw) != activation.get('canonical_recovery_receipt_sha256') or
            sha(run_raw) != activation.get('run_recovery_receipt_sha256') or
            not isinstance(receipt, dict) or receipt.get('schema') != 6 or
            receipt.get('status') != 'recovered' or
            receipt.get('authorizes_launch') is not True or
            receipt.get('boot_id') != BOOT_ID or
            receipt.get('prior_run_id') != manifest_a['run_id'] or
            receipt.get('recovery_id') != activation.get('recovery_id') or
            hooks.validate_receipt(receipt, BOOT_ID, manifest_a['run_id'])):
        errors.append('warm_qualification_a_evidence')
    return (receipt if not errors else None), sorted(set(errors))


def authorize(vm, manifest, manifest_path, output, expected_policy_sha256,
              expected_activation_sha256, hooks):
    """Validate one exact A or B activation without reserving a launch."""
    errors = []
    vm = Path(vm)
    if (re.fullmatch(r'[0-9a-f]{64}', str(expected_policy_sha256 or '')) is None or
            re.fullmatch(r'[0-9a-f]{64}', str(expected_activation_sha256 or '')) is None):
        return None, ['warm_qualification_authority']
    run_id = manifest.get('run_id') if isinstance(manifest, dict) else None
    boot_id = manifest.get('boot_id') if isinstance(manifest, dict) else None
    if boot_id != BOOT_ID or re.fullmatch(r'[0-9a-f]{32}', str(run_id or '')) is None:
        return None, ['warm_qualification_manifest']

    policy_file = policy_path(vm, boot_id)
    activation_file = activation_path(vm, boot_id, run_id)
    try:
        policy_raw, policy = _json_file(policy_file)
        activation_raw, activation = _json_file(activation_file)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None, ['warm_qualification_authority']
    if (sha(policy_raw) != expected_policy_sha256 or
            sha(activation_raw) != expected_activation_sha256):
        errors.append('warm_qualification_authority')
    if not isinstance(policy, dict) or not isinstance(activation, dict):
        return None, ['warm_qualification_authority']

    manifest_paths = []
    manifest_raws = []
    manifests = []
    for key in ('a', 'b'):
        path = _safe_vm_run_path(vm, policy.get(f'manifest_{key}_path'))
        manifest_paths.append(path)
        try:
            raw, value = _json_file(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            raw = b''; value = None
            errors.append('warm_qualification_manifest')
        manifest_raws.append(raw); manifests.append(value)
        if sha(raw) != policy.get(f'manifest_{key}_sha256'):
            errors.append('warm_qualification_manifest')
    try:
        card_raw, card = _json_file(ROOT / 'experiments/metal-011.json')
        design_raw = DESIGN_PATH.read_bytes()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        card_raw = design_raw = b''; card = None
        errors.append('warm_qualification_source')
    if sha(design_raw) != DESIGN_SHA256:
        errors.append('warm_qualification_source')

    fixed_policy = {
        'schema': 1,
        'kind': 'two-run-same-boot-warm-qualification-policy',
        'boot_id': BOOT_ID,
        'ledger_preimage_sha256': FOUR_ROW_LEDGER_SHA256,
        'prior_run_id': PRIOR_RUN_ID,
        'prior_recovery_id': PRIOR_RECOVERY_ID,
        'prior_canonical_receipt_sha256': PRIOR_CANONICAL_RECEIPT_SHA256,
        'prior_run_receipt_sha256': PRIOR_RUN_RECEIPT_SHA256,
        'candidate176_run_id': CANDIDATE176_RUN_ID,
        'candidate176_recovery_id': CANDIDATE176_RECOVERY_ID,
        'candidate176_canonical_receipt_sha256':
            CANDIDATE176_CANONICAL_RECEIPT_SHA256,
        'candidate176_run_receipt_sha256': CANDIDATE176_RUN_RECEIPT_SHA256,
        'design_sha256': DESIGN_SHA256,
        'experiment_py_sha256': sha((ROOT / 'tools/experiment.py').read_bytes()),
        'qualification_helper_sha256': sha(Path(__file__).resolve().read_bytes()),
        'recovery_producer_sha256': sha((ROOT / 'tools/vfio-recover.py').read_bytes()),
        'experiment_card_sha256': sha(card_raw),
        'manifest_a_path': policy.get('manifest_a_path'),
        'manifest_a_sha256': sha(manifest_raws[0]),
        'run_id_a': manifests[0].get('run_id') if isinstance(manifests[0], dict) else None,
        'output_a_path': policy.get('output_a_path'),
        'manifest_b_path': policy.get('manifest_b_path'),
        'manifest_b_sha256': sha(manifest_raws[1]),
        'run_id_b': manifests[1].get('run_id') if isinstance(manifests[1], dict) else None,
        'output_b_path': policy.get('output_b_path'),
        'from_max_launches': 4,
        'to_max_launches': 6,
        'additional_launches': 2,
        'vm_max_seconds': 180,
        'probe_max_seconds': 45,
        'automatic_extension': False,
        'purpose': PURPOSE,
    }
    try:
        policy_shape_ok = (
            isinstance(policy, dict) and set(policy) == POLICY_FIELDS and
            all(type(policy.get(key)) is type(value) and policy.get(key) == value
                for key, value in fixed_policy.items()))
    except Exception:
        policy_shape_ok = False
    if not policy_shape_ok:
        errors.append('warm_qualification_authority')
    if (not _manifest_ok(manifests[0], card) or
            not _manifest_ok(manifests[1], card) or
            not _same_artifact_manifest(manifests[0], manifests[1])):
        errors.append('warm_qualification_manifest')
    output_paths = [
        _safe_vm_run_path(vm, policy.get('output_a_path')),
        _safe_vm_run_path(vm, policy.get('output_b_path')),
    ]
    if (None in manifest_paths or manifest_paths[0] == manifest_paths[1] or
            None in output_paths or output_paths[0] == output_paths[1]):
        errors.append('warm_qualification_manifest')

    stage = ('A' if run_id == policy.get('run_id_a') else
             'B' if run_id == policy.get('run_id_b') else None)
    expected_manifest = manifests[0] if stage == 'A' else manifests[1] if stage == 'B' else None
    expected_manifest_path = manifest_paths[0] if stage == 'A' else manifest_paths[1] if stage == 'B' else None
    expected_output = output_paths[0 if stage == 'A' else 1] if stage else None
    try:
        actual_manifest_raw = Path(manifest_path).read_bytes()
        actual_output = Path(output).resolve()
    except (OSError, TypeError):
        actual_manifest_raw = b''; actual_output = None
    if (stage is None or manifest != expected_manifest or
            Path(manifest_path).resolve() != expected_manifest_path or
            actual_manifest_raw != manifest_raws[0 if stage == 'A' else 1] or
            actual_output != expected_output):
        errors.append('warm_qualification_manifest')
    try:
        actual_output.relative_to(ROOT.resolve())
        errors.append('warm_qualification_output')
    except (ValueError, AttributeError):
        pass

    ledger_path = vm / 'run/used-gpu-boots' / (BOOT_ID + '.json')
    try:
        ledger_raw, ledger = _json_file(ledger_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        ledger_raw = b''; ledger = None
        errors.append('warm_qualification_ledger')
    fields = ACTIVATION_A_FIELDS if stage == 'A' else ACTIVATION_B_FIELDS
    if not isinstance(activation, dict) or set(activation) != fields:
        errors.append('warm_qualification_authority')

    if stage == 'A':
        canonical_path = vm / 'run/vfio-recovery' / BOOT_ID / (PRIOR_RUN_ID + '.json')
        run_path = vm / 'run/metal-010-177/recovery.json'
        expected_ledger_sha = FOUR_ROW_LEDGER_SHA256
        expected_prior = PRIOR_RUN_ID
        expected_recovery = PRIOR_RECOVERY_ID
        expected_canonical_sha = PRIOR_CANONICAL_RECEIPT_SHA256
        expected_run_sha = PRIOR_RUN_RECEIPT_SHA256
    else:
        canonical_path = vm / 'run/vfio-recovery' / BOOT_ID / (
            str(activation.get('prior_run_id')) + '.json')
        run_path = (output_paths[0] / 'recovery.json'
                    if output_paths[0] is not None else None)
        expected_ledger_sha = sha(ledger_raw)
        expected_prior = policy.get('run_id_a')
        expected_recovery = activation.get('recovery_id')
        expected_canonical_sha = activation.get('canonical_recovery_receipt_sha256')
        expected_run_sha = activation.get('run_recovery_receipt_sha256')

    candidate176_paths = [
        vm / 'run/vfio-recovery' / BOOT_ID / (CANDIDATE176_RUN_ID + '.json'),
        vm / 'run/metal-009-176/recovery.json',
    ]
    candidate176_raws = []
    candidate176_receipts = []
    for path, expected_hash in zip(candidate176_paths, (
            CANDIDATE176_CANONICAL_RECEIPT_SHA256,
            CANDIDATE176_RUN_RECEIPT_SHA256)):
        try:
            raw, value = _json_file(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            raw = b''; value = None
        candidate176_raws.append(raw); candidate176_receipts.append(value)
        if sha(raw) != expected_hash:
            errors.append('warm_qualification_receipt')
    candidate176 = candidate176_receipts[0]
    if (len(candidate176_receipts) != 2 or
            candidate176_receipts[0] != candidate176_receipts[1] or
            not isinstance(candidate176, dict) or
            candidate176.get('prior_run_id') != CANDIDATE176_RUN_ID or
            candidate176.get('recovery_id') != CANDIDATE176_RECOVERY_ID or
            hooks.validate_receipt(
                candidate176, BOOT_ID, CANDIDATE176_RUN_ID)):
        errors.append('warm_qualification_receipt')

    candidate177_paths = [
        vm / 'run/vfio-recovery' / BOOT_ID / (PRIOR_RUN_ID + '.json'),
        vm / 'run/metal-010-177/recovery.json',
    ]
    candidate177_raws = []
    candidate177_receipts = []
    for path, expected_hash in zip(candidate177_paths, (
            PRIOR_CANONICAL_RECEIPT_SHA256, PRIOR_RUN_RECEIPT_SHA256)):
        try:
            raw, value = _json_file(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            raw = b''; value = None
        candidate177_raws.append(raw); candidate177_receipts.append(value)
        if sha(raw) != expected_hash:
            errors.append('warm_qualification_receipt')
    candidate177 = candidate177_receipts[0]
    if (len(candidate177_receipts) != 2 or
            candidate177_receipts[0] != candidate177_receipts[1] or
            not isinstance(candidate177, dict) or
            candidate177.get('prior_run_id') != PRIOR_RUN_ID or
            candidate177.get('recovery_id') != PRIOR_RECOVERY_ID or
            hooks.validate_receipt(candidate177, BOOT_ID, PRIOR_RUN_ID)):
        errors.append('warm_qualification_receipt')

    fixed_activation = {
        'schema': 1,
        'kind': 'two-run-warm-qualification-activation',
        'stage': stage,
        'boot_id': BOOT_ID,
        'policy_sha256': expected_policy_sha256,
        'ledger_preimage_sha256': expected_ledger_sha,
        'manifest_sha256': sha(actual_manifest_raw),
        'run_id': run_id,
        'prior_run_id': expected_prior,
        'recovery_id': expected_recovery,
        'canonical_recovery_receipt_sha256': expected_canonical_sha,
        'run_recovery_receipt_sha256': expected_run_sha,
        'automatic_retry': False,
    }
    if stage == 'B':
        fixed_activation.update(
            a_output_sha256=activation.get('a_output_sha256'),
            a_activation_sha256=activation.get('a_activation_sha256'))
    try:
        activation_shape_ok = all(
            type(activation.get(key)) is type(value) and activation.get(key) == value
            for key, value in fixed_activation.items())
    except Exception:
        activation_shape_ok = False
    if not activation_shape_ok:
        errors.append('warm_qualification_authority')
    a_activation_path = None
    a_activation_raw = None
    if stage == 'B':
        a_activation_path = activation_path(vm, BOOT_ID, policy.get('run_id_a'))
        try:
            a_activation_raw, a_activation = _json_file(a_activation_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            a_activation_raw = b''; a_activation = None
        fixed_a_activation = {
            'schema': 1,
            'kind': 'two-run-warm-qualification-activation',
            'stage': 'A', 'boot_id': BOOT_ID,
            'policy_sha256': expected_policy_sha256,
            'ledger_preimage_sha256': FOUR_ROW_LEDGER_SHA256,
            'manifest_sha256': sha(manifest_raws[0]),
            'run_id': policy.get('run_id_a'),
            'prior_run_id': PRIOR_RUN_ID,
            'recovery_id': PRIOR_RECOVERY_ID,
            'canonical_recovery_receipt_sha256':
                PRIOR_CANONICAL_RECEIPT_SHA256,
            'run_recovery_receipt_sha256': PRIOR_RUN_RECEIPT_SHA256,
            'automatic_retry': False,
        }
        if (sha(a_activation_raw) != activation.get('a_activation_sha256') or
                not isinstance(a_activation, dict) or
                set(a_activation) != ACTIVATION_A_FIELDS or
                any(type(a_activation.get(key)) is not type(value) or
                    a_activation.get(key) != value
                    for key, value in fixed_a_activation.items())):
            errors.append('warm_qualification_authority')
    if (stage == 'A' and sha(ledger_raw) != FOUR_ROW_LEDGER_SHA256) or not _base_ledger_ok(
            ledger, stage, expected_policy_sha256, activation, manifests[0],
            candidate177.get('kernel_cursor_after')
            if isinstance(candidate177, dict) else None):
        errors.append('warm_qualification_ledger')
    if stage == 'B' and isinstance(ledger, dict):
        try:
            saved = ledger['cap_revisions'][-1]
            saved_host = saved['host_gate']
            saved_vfio = saved['vfio_gate']
            saved_errors = list(hooks.admit_host(
                manifests[0], saved_host, {BOOT_ID}, reuse_allowed=True))
            saved_errors.extend(hooks.validate_full_host(saved_host, BOOT_ID))
            saved_errors.extend(hooks.validate_vfio(saved_vfio, BOOT_ID))
        except Exception:
            saved_errors = ['saved gate']
        if saved_errors:
            errors.append('warm_qualification_ledger')

    try:
        canonical_raw, canonical = _json_file(canonical_path)
        run_raw, run_receipt = _json_file(run_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        canonical_raw = run_raw = b''; canonical = run_receipt = None
        errors.append('warm_qualification_receipt')
    receipt = canonical
    if (canonical != run_receipt or sha(canonical_raw) != expected_canonical_sha or
            sha(run_raw) != expected_run_sha or not isinstance(receipt, dict) or
            receipt.get('schema') != 6 or receipt.get('status') != 'recovered' or
            receipt.get('authorizes_launch') is not True or
            receipt.get('boot_id') != BOOT_ID or
            receipt.get('prior_run_id') != expected_prior or
            receipt.get('recovery_id') != expected_recovery or
            hooks.validate_receipt(receipt, BOOT_ID, expected_prior)):
        errors.append('warm_qualification_receipt')

    if stage == 'B':
        a_receipt, a_errors = _a_evidence(vm, policy, activation, manifests[0], hooks)
        errors.extend(a_errors)
        if a_receipt != receipt:
            errors.append('warm_qualification_a_evidence')
    if errors:
        return None, sorted(set(errors))
    return {
        'stage': stage, 'manifest': expected_manifest,
        'policy': policy, 'policy_path': policy_file,
        'policy_raw': policy_raw, 'policy_sha256': expected_policy_sha256,
        'activation': activation, 'activation_path': activation_file,
        'activation_raw': activation_raw,
        'activation_sha256': expected_activation_sha256,
        'a_activation_path': a_activation_path,
        'a_activation_raw': a_activation_raw,
        'manifest_paths': manifest_paths, 'manifest_raws': manifest_raws,
        'ledger_path': ledger_path, 'ledger_raw': ledger_raw,
        'receipt': receipt, 'receipt_raws': [canonical_raw, run_raw],
        'receipt_paths': [canonical_path, run_path],
        'candidate176_receipt_paths': candidate176_paths,
        'candidate176_receipt_raws': candidate176_raws,
        'candidate177_receipt_paths': candidate177_paths,
        'candidate177_receipt_raws': candidate177_raws,
        'a_output': output_paths[0] if stage == 'B' else None,
        'a_output_sha256': activation.get('a_output_sha256') if stage == 'B' else None,
        'output': expected_output,
    }, []


def build_reservation(authorization, boot_id, run_id, recovery, gate,
                      reserved_epoch):
    """Build the exact append-only row-5 or row-6 ledger transition."""
    if (not isinstance(authorization, dict) or
            authorization.get('stage') not in ('A', 'B') or
            boot_id != BOOT_ID or run_id != authorization.get('manifest', {}).get('run_id') or
            recovery != authorization.get('receipt') or
            not isinstance(gate, dict) or set(gate) != GATE_FIELDS):
        raise ValueError('warm qualification refused: arguments')
    for key in ('policy_path', 'activation_path', 'ledger_path'):
        path = authorization.get(key)
        raw_key = key.replace('_path', '_raw')
        try:
            if Path(path).read_bytes() != authorization.get(raw_key):
                raise ValueError('warm qualification refused: concurrent_change')
        except OSError:
            raise ValueError('warm qualification refused: concurrent_change') from None
    if authorization.get('stage') == 'B':
        try:
            if Path(authorization.get('a_activation_path')).read_bytes() != \
                    authorization.get('a_activation_raw'):
                raise ValueError('warm qualification refused: concurrent_change')
        except (OSError, TypeError):
            raise ValueError('warm qualification refused: concurrent_change') from None
    for path, raw in zip(authorization.get('manifest_paths', []),
                         authorization.get('manifest_raws', [])):
        try:
            if Path(path).read_bytes() != raw:
                raise ValueError('warm qualification refused: concurrent_change')
        except OSError:
            raise ValueError('warm qualification refused: concurrent_change') from None
    for paths_key, raws_key in (
            ('receipt_paths', 'receipt_raws'),
            ('candidate176_receipt_paths', 'candidate176_receipt_raws'),
            ('candidate177_receipt_paths', 'candidate177_receipt_raws')):
        paths = authorization.get(paths_key)
        raws = authorization.get(raws_key)
        if (not isinstance(paths, list) or not isinstance(raws, list) or
                len(paths) != len(raws)):
            raise ValueError('warm qualification refused: concurrent_change')
        for path, raw in zip(paths, raws):
            try:
                if Path(path).read_bytes() != raw:
                    raise ValueError('warm qualification refused: concurrent_change')
            except OSError:
                raise ValueError('warm qualification refused: concurrent_change') from None
    if authorization.get('stage') == 'B':
        try:
            if evidence_digest(authorization.get('a_output')) != \
                    authorization.get('a_output_sha256'):
                raise ValueError('warm qualification refused: concurrent_change')
        except (OSError, TypeError):
            raise ValueError('warm qualification refused: concurrent_change') from None
    identity = gate.get('identity_gate')
    host = gate.get('host_gate')
    vfio = gate.get('vfio_gate')
    before_position = _journal_cursor_position(
        gate.get('kernel_cursor_before'), boot_id)
    after_position = _journal_cursor_position(
        gate.get('kernel_cursor_after'), boot_id)
    identity_keys = {'image_id', 'build_id', 'source_sha256',
                     'boot_id', 'bootdisk_sha256'}
    if (authorization['ledger_path'].read_bytes() != authorization.get('ledger_raw') or
            gate.get('kernel_cursor_before') != recovery.get('kernel_cursor_after') or
            before_position is None or after_position is None or
            after_position < before_position or
            not isinstance(gate.get('kernel_messages'), list) or
            any(not isinstance(message, str) or HOST_FAULT.search(message)
                for message in gate['kernel_messages']) or
            not isinstance(host, dict) or not host or host.get('boot_id') != boot_id or
            not isinstance(vfio, dict) or not vfio or vfio.get('boot_id') != boot_id or
            not isinstance(identity, dict) or not identity or
            not identity_keys.issubset(identity) or
            any(authorization['manifest'].get(key) != value
                for key, value in identity.items()) or
            not isinstance(gate.get('active_launch_units'), list) or
            not isinstance(gate.get('pending_launches'), list) or
            gate.get('active_launch_units') or gate.get('pending_launches')):
        raise ValueError('warm qualification refused: live_gate')

    ledger = json.loads(authorization['ledger_raw'])
    launches = list(ledger['launches'])
    revisions = list(ledger['cap_revisions'])
    stage = authorization['stage']
    if stage == 'A':
        revisions.append({
            'policy_sha256': authorization['policy_sha256'],
            'activation_a_sha256': authorization['activation_sha256'],
            'ledger_preimage_sha256': FOUR_ROW_LEDGER_SHA256,
            'from_max_launches': 4, 'to_max_launches': 6,
            'additional_launches': 2, 'purpose': PURPOSE,
            **gate,
        })
    expected_length = 4 if stage == 'A' else 5
    if len(launches) != expected_length:
        raise ValueError('warm qualification refused: launch_ceiling')
    launches.append({
        'run_id': run_id,
        'reserved_epoch': reserved_epoch,
        'recovery_id': recovery['recovery_id'],
        'prior_run_id': recovery['prior_run_id'],
        'warm_qualification_policy_sha256': authorization['policy_sha256'],
        'warm_qualification_activation_sha256': authorization['activation_sha256'],
        'qualification': PURPOSE,
        'qualification_ordinal': stage,
    })
    updated = dict(ledger)
    updated.update(schema=4, initial_max_launches=3, max_launches=6,
                   cap_revisions=revisions, launches=launches)
    return authorization['ledger_path'], updated
