#!/usr/bin/env python3
"""Validate one exact same-boot launch authority pinned entirely by its policy.

This generalizes candidate179-qualification.py: every identity that helper kept
as a constant (boot, prior run, prior recovery, receipt copies, card, manifest
and output paths, ledger preimage) is a field of the immutable policy file, and
the policy is bound by its own SHA-256 supplied by the operator. The helper never
touches hardware. It reads, validates, and returns a prospective ledger value;
the coordinator performs the locked atomic replacement.

The coordinator refuses generic same-boot reuse for lease-schema launches; a
policy created here selects exactly one launch, binds the prior run's validated
recovery receipt, and cannot be replayed once its ledger preimage changes.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (ROOT / 'docs/superpowers/specs/'
               '2026-09-10-one-run-qualification-design.md')
RECOVERY_HELPER_PATHS_V2 = (
    'tools/vfio-recover.py',
    'tools/recovery_lease_v2.py',
    'tools/kiq-recovery-proof.py',
)
RECOVERY_HELPER_PATHS_V3 = RECOVERY_HELPER_PATHS_V2 + (
    'tools/critical-replay.py',
    'tools/recovery_lifetime_v3.py',
)
POLICY_KIND = 'one-run-qualification-policy'
ACTIVATION_KIND = 'one-run-qualification-activation'
POLICY_FIELDS = {
    'schema', 'kind', 'boot_id', 'ledger_preimage_sha256',
    'prior_run_id', 'prior_recovery_id',
    'prior_canonical_receipt_sha256', 'prior_run_receipt_path',
    'prior_run_receipt_member', 'prior_run_receipt_sha256',
    'design_sha256', 'experiment_py_sha256', 'qualification_helper_sha256',
    'recovery_lease_schema', 'recovery_helpers_sha256',
    'experiment_card_path', 'experiment_card_sha256', 'experiment_id',
    'candidate_version', 'candidate_directory',
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
BASELINE_SWITCHES = {'rgpu':'0xfffa5981', 'rgpuvmm':'3', 'rgpumem':'1',
                     'rgpuptb':'2', 'rgpumqd':'2', 'rgpuhybrid':'1'}
RETIRED_SWITCHES = {'rgpucp', 'rgpureset', 'rgpuic', 'rgpurlc', 'rgpufb'}
HELPER_NAME = 'one-run-qualification'
LABEL = 'one-run'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def current_recovery_helpers_sha256(recovery_lease_schema=3):
    paths = (RECOVERY_HELPER_PATHS_V3 if recovery_lease_schema == 3
             else RECOVERY_HELPER_PATHS_V2)
    return {relative: sha((ROOT / relative).read_bytes()) for relative in paths}


def policy_path(vm, boot_id, run_id=None):
    name = 'policy.json' if run_id is None else run_id + '.policy.json'
    return Path(vm) / 'run/one-run-qualification-authorities' / boot_id / name


def selected_policy_path(vm, boot_id, run_id):
    """Select a run-scoped authority when present, else the legacy authority."""
    scoped = policy_path(vm, boot_id, run_id)
    return scoped if scoped.exists() else policy_path(vm, boot_id)


def activation_path(vm, boot_id, run_id):
    return (Path(vm) / 'run/one-run-qualification-authorities' / boot_id /
            (run_id + '.json'))


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


def _hex(value, digits):
    return re.fullmatch(r'[0-9a-f]{%d}' % digits, str(value or '')) is not None


def _receipt_from_copy(document, member):
    if member is None:
        return document
    return document.get(member) if isinstance(document, dict) else None


def _manifest_ok(manifest, card, policy, helper_hashes):
    if not isinstance(manifest, dict) or not isinstance(card, dict):
        return False
    run_id = manifest.get('run_id')
    if not _hex(run_id, 32):
        return False
    nonce_lo, nonce_hi = struct.unpack('<QQ', bytes.fromhex(run_id))
    args = manifest.get('boot_args')
    switch_rows = ([word.split('=', 1) for word in args.split() if '=' in word]
                   if isinstance(args, str) else [])
    switches = dict(switch_rows)
    rgpu_keys = [key for key, _ in switch_rows if key.startswith('rgpu')]
    digest_fields = ('source_sha256', 'binary_sha256', 'bootdisk_sha256')
    functional = card.get('functional_boot_arguments', {})
    diagnostic = str(card.get('requested_diagnostic', ''))
    lease = policy['recovery_lease_schema']
    tolerance = card.get('critical_replay_tolerance')
    recovery_tolerance = card.get('recovery_critical_replay_tolerance')
    return (
        manifest.get('boot_id') == policy['boot_id'] and manifest.get('gpu') is True and
        manifest.get('candidate_directory') == policy['candidate_directory'] and
        manifest.get('experiment') == policy['experiment_id'] and
        type(manifest.get('max_seconds')) is int and
        manifest.get('max_seconds') == policy['vm_max_seconds'] and
        manifest.get('recovery_lease_schema') == lease and
        (lease != 3 or manifest.get('critical_replay_schema') == 2) and
        manifest.get('critical_replay_tolerance') == tolerance and
        manifest.get('recovery_critical_replay_tolerance') == recovery_tolerance and
        recovery_tolerance in (None, 'terminal-prefix-open') and
        manifest.get('recovery_helpers_sha256') == helper_hashes and
        manifest.get('source_clean') is True and
        manifest.get('bootdisk_verified') is True and
        _hex(manifest.get('build_id'), 32) and
        all(_hex(manifest.get(key), 64) for key in digest_fields) and
        len(rgpu_keys) == len(set(rgpu_keys)) and
        not RETIRED_SWITCHES.intersection(switches) and
        manifest.get('spec') == card and card.get('id') == policy['experiment_id'] and
        card.get('candidate_version') == policy['candidate_version'] and
        '=' in diagnostic and
        card.get('max_seconds') == policy['vm_max_seconds'] and
        card.get('run_probe_only_after_native_start') is True and
        (lease != 3 or card.get('critical_replay_schema') == 2) and
        card.get('recovery_lease_schema') == lease and
        'no automatic retry' in str(card.get('repeat_policy', '')) and
        isinstance(functional, dict) and
        all(switches.get(key) == value for key, value in BASELINE_SWITCHES.items()) and
        all(switches.get(key) == value for key, value in functional.items()) and
        switches.get(diagnostic.split('=', 1)[0]) == diagnostic.split('=', 1)[1] and
        _numeric_boot_argument(switches.get('rgpurnlo')) == nonce_lo and
        _numeric_boot_argument(switches.get('rgpurnhi')) == nonce_hi)


def _ledger_ok(ledger, policy, run_id):
    launches = ledger.get('launches') if isinstance(ledger, dict) else None
    return (isinstance(launches, list) and launches and
            all(isinstance(row, dict) for row in launches) and
            ledger.get('boot_id') == policy['boot_id'] and
            type(ledger.get('max_launches')) is int and
            ledger['max_launches'] == policy['from_max_launches'] and
            len(launches) < policy['to_max_launches'] and
            policy['to_max_launches'] == (policy['from_max_launches'] +
                                          policy['additional_launches']) and
            launches[-1].get('run_id') == policy['prior_run_id'] and
            not any(row.get('run_id') == run_id for row in launches) and
            policy['prior_recovery_id'] not in
                {row.get('recovery_id') for row in launches})


def authorize(vm, manifest, manifest_path, output, expected_policy_sha256,
              expected_activation_sha256, hooks):
    """Read and validate the exact one-run authority without reserving a launch."""
    vm = Path(vm)
    errors = []
    if not _hex(expected_policy_sha256, 64) or not _hex(expected_activation_sha256, 64):
        return None, [LABEL + '_authority']
    run_id = manifest.get('run_id') if isinstance(manifest, dict) else None
    boot_id = manifest.get('boot_id') if isinstance(manifest, dict) else None
    if not _hex(run_id, 32) or not re.fullmatch(r'[A-Za-z0-9-]+', str(boot_id or '')):
        return None, [LABEL + '_manifest']
    try:
        policy_file = selected_policy_path(vm, boot_id, run_id)
        policy_raw, policy = _json_file(policy_file)
        if (sha(policy_raw) != expected_policy_sha256 or not isinstance(policy, dict) or
                set(policy) != POLICY_FIELDS or policy.get('kind') != POLICY_KIND):
            return None, [LABEL + '_authority']
        activation_raw, activation = _json_file(activation_path(vm, boot_id, run_id))
        manifest_raw, pinned_manifest = _json_file(
            _safe_vm_run_path(vm, policy['manifest_path']))
        card_path = ROOT / str(policy['experiment_card_path'])
        card_raw, card = _json_file(card_path)
        design_raw = DESIGN_PATH.read_bytes()
        ledger_path = vm / 'run/used-gpu-boots' / (boot_id + '.json')
        ledger_raw, ledger = _json_file(ledger_path)
        canonical_path = (vm / 'run/vfio-recovery' / boot_id /
                          (str(policy['prior_run_id']) + '.json'))
        run_receipt_path = _safe_vm_run_path(vm, policy['prior_run_receipt_path'])
        canonical_raw, canonical = _json_file(canonical_path)
        run_receipt_raw, run_receipt_document = _json_file(run_receipt_path)
        lease = policy['recovery_lease_schema']
        if lease not in (2, 3):
            return None, [LABEL + '_authority']
        helper_hashes = current_recovery_helpers_sha256(lease)
        experiment_raw = (ROOT / 'tools/experiment.py').read_bytes()
        qualification_raw = Path(__file__).resolve().read_bytes()
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None, [LABEL + '_authority']
    if not (Path(policy['experiment_card_path']).parts[:1] == ('experiments',) and
            not Path(policy['experiment_card_path']).is_absolute()):
        return None, [LABEL + '_authority']
    fixed_policy = {
        'schema':1, 'kind':POLICY_KIND,
        'boot_id':boot_id, 'ledger_preimage_sha256':sha(ledger_raw),
        'prior_run_id':policy['prior_run_id'],
        'prior_recovery_id':policy['prior_recovery_id'],
        'prior_canonical_receipt_sha256':sha(canonical_raw),
        'prior_run_receipt_path':policy['prior_run_receipt_path'],
        'prior_run_receipt_member':policy['prior_run_receipt_member'],
        'prior_run_receipt_sha256':sha(run_receipt_raw),
        'design_sha256':sha(design_raw),
        'experiment_py_sha256':sha(experiment_raw),
        'qualification_helper_sha256':sha(qualification_raw),
        'recovery_lease_schema':lease,
        'recovery_helpers_sha256':helper_hashes,
        'experiment_card_path':policy['experiment_card_path'],
        'experiment_card_sha256':sha(card_raw),
        'experiment_id':policy['experiment_id'],
        'candidate_version':policy['candidate_version'],
        'candidate_directory':policy['candidate_directory'],
        'manifest_path':policy['manifest_path'], 'manifest_sha256':sha(manifest_raw),
        'run_id':run_id, 'output_path':policy['output_path'],
        'from_max_launches':policy['from_max_launches'],
        'to_max_launches':policy['to_max_launches'],
        'additional_launches':policy['additional_launches'],
        'vm_max_seconds':180, 'probe_max_seconds':45,
        'automatic_extension':False, 'automatic_retry':False,
        'purpose':policy['purpose'],
    }
    if (policy != fixed_policy or not _hex(policy['prior_run_id'], 32) or
            not _hex(policy['prior_recovery_id'], 32) or
            type(policy['from_max_launches']) is not int or
            type(policy['to_max_launches']) is not int or
            type(policy['additional_launches']) is not int or
            policy['additional_launches'] < 0 or
            not isinstance(policy['purpose'], str) or not policy['purpose']):
        errors.append(LABEL + '_authority')
    fixed_activation = {
        'schema':1, 'kind':ACTIVATION_KIND, 'stage':'ONLY', 'boot_id':boot_id,
        'policy_sha256':expected_policy_sha256,
        'ledger_preimage_sha256':sha(ledger_raw),
        'manifest_sha256':sha(manifest_raw), 'run_id':run_id,
        'prior_run_id':policy['prior_run_id'],
        'recovery_id':policy['prior_recovery_id'],
        'canonical_recovery_receipt_sha256':sha(canonical_raw),
        'run_recovery_receipt_sha256':sha(run_receipt_raw),
        'automatic_retry':False,
    }
    if (sha(activation_raw) != expected_activation_sha256 or
            not isinstance(activation, dict) or set(activation) != ACTIVATION_FIELDS or
            activation != fixed_activation):
        errors.append(LABEL + '_authority')
    try:
        manifest_argument_path = Path(manifest_path).resolve()
        output_argument_path = Path(output).resolve()
        manifest_argument_ok = manifest_argument_path.read_bytes() == manifest_raw
        output_absent = not output_argument_path.exists()
    except (OSError, TypeError):
        manifest_argument_path = output_argument_path = None
        manifest_argument_ok = output_absent = False
    if (manifest != pinned_manifest or manifest_argument_path !=
            _safe_vm_run_path(vm, policy['manifest_path']) or
            not manifest_argument_ok or
            output_argument_path != _safe_vm_run_path(vm, policy['output_path']) or
            not output_absent or not _manifest_ok(manifest, card, policy, helper_hashes)):
        errors.append(LABEL + '_manifest')
    try:
        output_argument_path.relative_to(ROOT.resolve())
        errors.append(LABEL + '_output')
    except (ValueError, AttributeError):
        pass
    if not _ledger_ok(ledger, policy, run_id):
        errors.append(LABEL + '_ledger')
    receipt = canonical
    run_receipt = _receipt_from_copy(run_receipt_document, policy['prior_run_receipt_member'])
    try:
        receipt_errors = hooks.validate_receipt(receipt, boot_id, policy['prior_run_id'])
    except Exception:
        receipt_errors = ['receipt']
    if (canonical != run_receipt or not isinstance(receipt, dict) or
            receipt.get('schema') != 6 or receipt.get('status') != 'recovered' or
            receipt.get('authorizes_launch') is not True or
            receipt.get('boot_id') != boot_id or
            receipt.get('prior_run_id') != policy['prior_run_id'] or
            receipt.get('recovery_id') != policy['prior_recovery_id'] or
            receipt.get('recovery_helpers_sha256') != helper_hashes or
            receipt_errors):
        errors.append(LABEL + '_receipt')
    if errors:
        return None, sorted(set(errors))
    return {
        'helper_name':HELPER_NAME, 'label':LABEL,
        'vm':vm.resolve(), 'boot_id':boot_id,
        'manifest':pinned_manifest, 'manifest_path':Path(manifest_path).resolve(),
        'manifest_raw':manifest_raw, 'output':Path(output).resolve(),
        'policy':policy, 'policy_path':policy_file,
        'policy_raw':policy_raw, 'policy_sha256':expected_policy_sha256,
        'activation':activation,
        'activation_path':activation_path(vm, boot_id, run_id),
        'activation_raw':activation_raw,
        'activation_sha256':expected_activation_sha256,
        'ledger_path':ledger_path, 'ledger_raw':ledger_raw,
        'receipt':receipt, 'receipt_paths':[canonical_path, run_receipt_path],
        'receipt_raws':[canonical_raw, run_receipt_raw],
        'card_path':card_path, 'card_raw':card_raw, 'design_raw':design_raw,
        'hooks':hooks,
    }, []


def build_reservation(authorization, boot_id, run_id, recovery, gate,
                      reserved_epoch):
    """Return the prospective ledger with exactly one appended row, without writing."""
    if (not isinstance(authorization, dict) or
            boot_id != authorization.get('boot_id') or
            run_id != authorization.get('manifest', {}).get('run_id') or
            recovery != authorization.get('receipt') or
            not isinstance(gate, dict) or set(gate) != GATE_FIELDS or
            type(reserved_epoch) not in (int, float) or
            not math.isfinite(reserved_epoch) or reserved_epoch < 0):
        raise ValueError(LABEL + ' qualification refused: arguments')
    policy = authorization.get('policy')
    try:
        vm = Path(authorization['vm']).resolve()
        parsed_policy = json.loads(authorization['policy_raw'])
        parsed_activation = json.loads(authorization['activation_raw'])
        parsed_manifest = json.loads(authorization['manifest_raw'])
        expected_paths = {
            'policy_path':selected_policy_path(vm, boot_id, run_id).resolve(),
            'activation_path':activation_path(vm, boot_id, run_id),
            'manifest_path':_safe_vm_run_path(vm, policy['manifest_path']),
            'ledger_path':vm / 'run/used-gpu-boots' / (boot_id + '.json'),
            'output':_safe_vm_run_path(vm, policy['output_path']),
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
        raise ValueError(LABEL + ' qualification refused: concurrent_change')
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
            raise ValueError(LABEL + ' qualification refused: concurrent_change')
        if (sha(DESIGN_PATH.read_bytes()) != policy['design_sha256'] or
                sha(Path(authorization['card_path']).read_bytes()) !=
                    policy['experiment_card_sha256'] or
                sha((ROOT / 'tools/experiment.py').read_bytes()) !=
                    policy['experiment_py_sha256'] or
                sha(Path(__file__).resolve().read_bytes()) !=
                    policy['qualification_helper_sha256'] or
                current_recovery_helpers_sha256(policy['recovery_lease_schema']) !=
                    policy['recovery_helpers_sha256']):
            raise ValueError(LABEL + ' qualification refused: concurrent_change')
    except (KeyError, OSError):
        raise ValueError(LABEL + ' qualification refused: concurrent_change')

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
            isinstance(host_before, dict) and host_before.get('boot_id') == boot_id)
    except (OSError, AttributeError, TypeError, json.JSONDecodeError):
        output_ok = False
    if not output_ok:
        raise ValueError(LABEL + ' qualification refused: concurrent_change')

    before = _journal_cursor_position(gate.get('kernel_cursor_before'), boot_id)
    after = _journal_cursor_position(gate.get('kernel_cursor_after'), boot_id)
    identity = gate.get('identity_gate')
    hooks = authorization.get('hooks')
    try:
        host_errors = hooks.validate_host(gate.get('host_gate'), boot_id)
        vfio_errors = hooks.validate_vfio(gate.get('vfio_gate'), boot_id)
        receipt_errors = hooks.validate_receipt(recovery, boot_id, policy['prior_run_id'])
    except Exception:
        host_errors = vfio_errors = receipt_errors = ['gate']
    try:
        receipt_copies_match = (
            json.loads(authorization['receipt_raws'][0]) == recovery and
            _receipt_from_copy(json.loads(authorization['receipt_raws'][1]),
                               policy['prior_run_receipt_member']) == recovery)
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
        raise ValueError(LABEL + ' qualification refused: live_gate')

    ledger = json.loads(authorization['ledger_raw'])
    if not _ledger_ok(ledger, policy, run_id):
        raise ValueError(LABEL + ' qualification refused: launch_ceiling')
    launches = list(ledger['launches'])
    launches.append({
        'run_id':run_id, 'reserved_epoch':reserved_epoch,
        'recovery_id':recovery['recovery_id'],
        'prior_run_id':recovery['prior_run_id'],
        'one_run_policy_sha256':authorization['policy_sha256'],
        'one_run_activation_sha256':authorization['activation_sha256'],
        'qualification':policy['purpose'], 'qualification_ordinal':'ONLY',
    })
    updated = dict(ledger)
    updated['launches'] = launches
    if policy['additional_launches']:
        revisions = list(ledger.get('cap_revisions', []))
        revisions.append({
            'policy_sha256':authorization['policy_sha256'],
            'activation_sha256':authorization['activation_sha256'],
            'ledger_preimage_sha256':policy['ledger_preimage_sha256'],
            'from_max_launches':policy['from_max_launches'],
            'to_max_launches':policy['to_max_launches'],
            'additional_launches':policy['additional_launches'],
            'automatic_extension':False, 'automatic_retry':False,
            'purpose':policy['purpose'], **gate,
        })
        updated.update(cap_revisions=revisions, max_launches=policy['to_max_launches'])
    return authorization['ledger_path'], updated


def create(vm, boot_id, prior_run_id, run_receipt_path, run_receipt_member,
           card_relative, manifest_relative, output_relative, purpose,
           additional_launches=0):
    """Write one policy and one activation for the manifest already sealed at
    ``manifest_relative``. Every pin is computed from the live files; the caller
    reviews the printed digests before passing them to the coordinator."""
    vm = Path(vm).resolve()
    manifest_path = _safe_vm_run_path(vm, manifest_relative)
    manifest_raw, manifest = _json_file(manifest_path)
    card_path = ROOT / card_relative
    card_raw, card = _json_file(card_path)
    ledger_raw, ledger = _json_file(vm / 'run/used-gpu-boots' / (boot_id + '.json'))
    canonical_raw, canonical = _json_file(
        vm / 'run/vfio-recovery' / boot_id / (prior_run_id + '.json'))
    run_receipt_raw, _ = _json_file(_safe_vm_run_path(vm, run_receipt_path))
    lease = card['recovery_lease_schema']
    run_id = manifest['run_id']
    policy = {
        'schema':1, 'kind':POLICY_KIND, 'boot_id':boot_id,
        'ledger_preimage_sha256':sha(ledger_raw),
        'prior_run_id':prior_run_id, 'prior_recovery_id':canonical['recovery_id'],
        'prior_canonical_receipt_sha256':sha(canonical_raw),
        'prior_run_receipt_path':run_receipt_path,
        'prior_run_receipt_member':run_receipt_member,
        'prior_run_receipt_sha256':sha(run_receipt_raw),
        'design_sha256':sha(DESIGN_PATH.read_bytes()),
        'experiment_py_sha256':sha((ROOT / 'tools/experiment.py').read_bytes()),
        'qualification_helper_sha256':sha(Path(__file__).resolve().read_bytes()),
        'recovery_lease_schema':lease,
        'recovery_helpers_sha256':current_recovery_helpers_sha256(lease),
        'experiment_card_path':card_relative, 'experiment_card_sha256':sha(card_raw),
        'experiment_id':card['id'], 'candidate_version':card['candidate_version'],
        'candidate_directory':manifest['candidate_directory'],
        'manifest_path':manifest_relative, 'manifest_sha256':sha(manifest_raw),
        'run_id':run_id, 'output_path':output_relative,
        'from_max_launches':ledger['max_launches'],
        'to_max_launches':ledger['max_launches'] + additional_launches,
        'additional_launches':additional_launches,
        'vm_max_seconds':180, 'probe_max_seconds':45,
        'automatic_extension':False, 'automatic_retry':False, 'purpose':purpose,
    }
    policy_file = policy_path(vm, boot_id, run_id)
    policy_file.parent.mkdir(parents=True, exist_ok=True)
    policy_bytes = (json.dumps(policy, sort_keys=True, indent=2) + '\n').encode()
    with policy_file.open('xb') as stream:
        stream.write(policy_bytes)
    policy_sha = sha(policy_bytes)
    activation = {
        'schema':1, 'kind':ACTIVATION_KIND, 'stage':'ONLY', 'boot_id':boot_id,
        'policy_sha256':policy_sha, 'ledger_preimage_sha256':sha(ledger_raw),
        'manifest_sha256':sha(manifest_raw), 'run_id':run_id,
        'prior_run_id':prior_run_id, 'recovery_id':canonical['recovery_id'],
        'canonical_recovery_receipt_sha256':sha(canonical_raw),
        'run_recovery_receipt_sha256':sha(run_receipt_raw),
        'automatic_retry':False,
    }
    activation_bytes = (json.dumps(activation, sort_keys=True, indent=2) + '\n').encode()
    with activation_path(vm, boot_id, run_id).open('xb') as stream:
        stream.write(activation_bytes)
    return {'policy_path':str(policy_file), 'policy_sha256':policy_sha,
            'activation_path':str(activation_path(vm, boot_id, run_id)),
            'activation_sha256':sha(activation_bytes), 'run_id':run_id,
            'created_epoch':time.time()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    make = sub.add_parser('create', help='write one policy and activation for a sealed manifest')
    make.add_argument('--vm-dir', required=True, type=Path)
    make.add_argument('--boot-id', required=True)
    make.add_argument('--prior-run', required=True)
    make.add_argument('--run-receipt-path', required=True,
                      help='VM-relative second copy of the prior receipt')
    make.add_argument('--run-receipt-member', default=None,
                      help='member holding the receipt inside that file, if nested')
    make.add_argument('--card', required=True, help='repository-relative experiment card')
    make.add_argument('--manifest-path', required=True, help='VM-relative sealed manifest')
    make.add_argument('--output-path', required=True, help='VM-relative absent output dir')
    make.add_argument('--purpose', required=True)
    make.add_argument('--additional-launches', type=int, default=0)
    args = parser.parse_args()
    result = create(args.vm_dir, args.boot_id, args.prior_run, args.run_receipt_path,
                    args.run_receipt_member, args.card, args.manifest_path,
                    args.output_path, args.purpose, args.additional_launches)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
