#!/usr/bin/env python3
"""IH-complete normal recovery, preserving the sealed schema-6 producer.

Historical proof reconstruction pins vfio-recover.py byte-for-byte. Load a
private instance and wrap its transport lifetime; its original GC/SDMA/PSP,
lease, host-state, journal and immutable-receipt checks run unchanged.
"""
from contextlib import contextmanager
import hashlib
import importlib.util
from pathlib import Path


def load(name):
    path = Path(__file__).with_name(name + '.py')
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load('vfio-recover')
IH = load('ih_dma')
SCHEMA = 10
KIND = 'ih-complete-normal-recovery'
LEGACY_PERFORM = R.perform_recovery


def source_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name + '.py').read_bytes()).hexdigest()
            for name in ('ih-vfio-recover', 'ih_dma')}


def perform_recovery(expected_boot, prior_run_id, state_reader, transport_factory,
                     journal_reader, *args, **kwargs):
    proof = {}

    @contextmanager
    def transport():
        with transport_factory() as mmio:
            proof['shutdown'] = IH.quiesce(mmio)
            yield mmio
            proof['final'] = IH.inspect(mmio)
            errors = IH.validate(proof['final'])
            if errors:
                raise R.RecoveryError('IH final gate failed: ' + ','.join(errors))

    result = LEGACY_PERFORM(expected_boot, prior_run_id, state_reader, transport,
                            journal_reader, *args, **kwargs)
    result.update(schema=SCHEMA, kind=KIND, ih_dma=proof,
                  ih_helpers_sha256=source_hashes())
    return result


def recover(vm, prior_run_id, *, ih_helpers_sha256=None, **kwargs):
    if ih_helpers_sha256 != source_hashes():
        raise R.RecoveryError('IH recovery helpers differ from the launch manifest')
    # This module owns its private R instance. R.recover still owns the real
    # experiment lock, latest-ledger check and write-once canonical receipt.
    R.perform_recovery = perform_recovery
    return R.recover(vm, prior_run_id, **kwargs)


def validate_receipt(value, boot, prior, legacy_validator, helper_hashes):
    if (not isinstance(value, dict) or value.get('schema') != SCHEMA or
            value.get('kind') != KIND or value.get('ih_helpers_sha256') != source_hashes()):
        return ['ih_recovery_identity']
    legacy = dict(value, schema=6)
    errors = legacy_validator(legacy, boot, prior, helper_hashes)
    proof = value.get('ih_dma', {})
    errors += IH.validate(proof.get('shutdown', {}))
    errors += IH.validate(proof.get('final', {}))
    return sorted(set(errors))


def __getattr__(name):
    return getattr(R, name)
