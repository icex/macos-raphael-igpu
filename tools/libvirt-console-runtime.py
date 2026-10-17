#!/usr/bin/env python3
"""Paused-domain transaction shared by the future supervised libvirt launcher.

This module does not bypass experiment admission and has no standalone launch CLI.
The backend must operate in the admitted container/session and supply observations
from libvirt, QMP and /proc, not from the requested XML alone.
"""
import hashlib
import json
import os
import math
import time


class Refused(RuntimeError):
    pass


def digest(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise Refused(message)


class PausedDomain:
    """One transient domain owner. No restart, adoption or deadline extension."""
    def __init__(self, backend, plan, expected_digest, container, verify_configuration):
        plan = json.loads(json.dumps(plan))
        require(digest(plan) == expected_digest, 'plan digest changed')
        require(plan['required_launch'] == 'transient-paused' and plan['resume_allowed'] is False,
                'plan does not require paused admission')
        external = bool(container.get('cid') and container.get('started_at'))
        local = (container.get('kind') == 'pid-namespace' and
                 all(type(container.get(k)) is int and container[k] > 0
                     for k in ('device', 'inode', 'init_start_ticks')))
        require(external or local, 'container identity missing')
        # Local scope binds namespace + init process; the existing host supervisor
        # independently owns the full Docker CID/StartedAt and exposure deadline.
        self.backend = backend
        # Freeze admitted intent against later caller mutation.
        self.plan = json.loads(json.dumps(plan))
        self.container = dict(container)
        self.verify_configuration = verify_configuration
        self.identity = None
        self.created = False
        self.creation_attempted = False
        self.resumed = False
        self.resume_attempted = False
        self.stop_receipt = None
        self.finished = False
        self.events = []

    def record(self, phase, **fields):
        event = dict(phase=phase, run_id=self.plan['run_id'], **fields)
        self.events.append(event)
        self.backend.record(event)

    def check_container(self):
        require(self.backend.container_identity() == self.container, 'container identity changed')

    def observe(self, paused=False):
        self.check_container()
        state = self.backend.snapshot(self.plan['domain_name'])
        require(state['name'] == self.plan['domain_name'] and
                state['uuid'] == self.plan['uuid'] and
                state['run_id'] == self.plan['run_id'] and
                state['persistent'] is False, 'domain identity changed')
        require(type(state['pid']) is int and state['pid'] > 0 and
                type(state['start_ticks']) is int and state['start_ticks'] > 0,
                'QEMU process identity missing')
        identity = {key: state[key] for key in ('name', 'uuid', 'run_id', 'pid', 'start_ticks')}
        if self.identity is not None:
            require(identity == self.identity, 'QEMU identity changed')
        if self.identity is None:
            self.identity = identity
        if paused:
            require(state['running'] is False and state['status'] in ('prelaunch', 'paused'),
                    'CPUs executed before configuration')
        require(self.verify_configuration(self.plan, state) is True, 'running configuration mismatch')
        return state, identity

    def prepare(self, inherited_fd):
        require(not self.creation_attempted and not self.finished, 'transaction already used')
        self.check_container()
        require(not self.backend.domains(), 'isolated session already contains a domain')
        # Fail closed before creation when the inherited descriptor is already lost.
        os.fstat(inherited_fd)
        self.record('creating-paused')
        self.creation_attempted = True
        try:
            self.backend.create_paused(self.plan['xml'])
            self.created = True
            state, self.identity = self.observe(paused=True)
            self.record('paused-identity', identity=self.identity)
            self.backend.qmp(self.plan['domain_name'], 'getfd',
                             {'fdname': 'rgpu_lan'}, fd=inherited_fd)
            self.observe(paused=True)
            self.backend.qmp(self.plan['domain_name'], 'netdev_add',
                             {'type': 'tap', 'id': 'rgpu_lan_backend', 'fd': 'rgpu_lan'})
            self.observe(paused=True)
            self.backend.qmp(self.plan['domain_name'], 'netdev_add',
                             {'type': 'hubport', 'id': 'rgpu_lan_attachment',
                              'hubid': self.plan['lan_hub'], 'netdev': 'rgpu_lan_backend'})
            state, _ = self.observe(paused=True)
            require(self.backend.network_attached(self.plan['domain_name'], self.plan['lan_hub']) is True,
                    'LAN attachment not verified')
            self.record('network-ready')
            return state
        except BaseException as error:
            self.abort(error, 'prepare-failed')
            raise

    def resume(self):
        require(self.created and not self.resume_attempted and not self.finished, 'invalid resume transition')
        require(any(e['phase'] == 'network-ready' for e in self.events), 'network is not ready')
        try:
            self.observe(paused=True)
            require(self.backend.network_attached(self.plan['domain_name'], self.plan['lan_hub']) is True,
                    'LAN attachment lost before resume')
            self.resume_attempted = True
            self.backend.qmp(self.plan['domain_name'], 'cont', {})
            self.resumed = True
            state, _ = self.observe()
            require(state['running'] is True, 'resume not observed')
            self.record('running', identity=self.identity)
        except BaseException as error:
            self.abort(error, 'resume-failed')
            raise

    def abort(self, error, reason):
        # Losing the evidence writer must never skip stopping the owned process.
        try:
            self.record('failure', reason=reason, error_type=type(error).__name__, error=str(error))
        except Exception as receipt_error:
            self.events.append(dict(phase='receipt-write-failed', error=str(receipt_error)))
        try:
            self.cleanup(reason)
        except BaseException as cleanup_error:
            try:
                self.record('cleanup-unproven', reason=reason,
                            error_type=type(cleanup_error).__name__, error=str(cleanup_error))
            except Exception as receipt_error:
                self.events.append(dict(phase='receipt-write-failed', error=str(receipt_error)))
            raise Refused(reason + '; cleanup unproven: ' + str(cleanup_error)) from error

    def cleanup(self, reason):
        if self.finished:
            return
        if self.stop_receipt is not None:
            self.record('stopped', **self.stop_receipt)
            self.finished = True
            return
        self.check_container()
        if self.creation_attempted and (not self.created or self.identity is None):
            # The backend must reconcile its own create transaction, including a
            # timeout after QEMU started. Never infer absence from a lost reply.
            receipt = self.backend.reconcile_creation(self.plan)
            require(receipt.get('outcome') in ('created', 'no-process'),
                    'create outcome is unproven')
            if receipt['outcome'] == 'created':
                identity = receipt['identity']
                require(identity['name'] == self.plan['domain_name'] and
                        identity['uuid'] == self.plan['uuid'] and
                        identity['run_id'] == self.plan['run_id'], 'creation receipt mismatch')
                self.identity = dict(identity)
                self.created = True
            else:
                require(self.backend.session_processes_gone() is True,
                        'failed create still has a process')
                self.created = False
        domains = self.backend.domains()
        if self.created and self.plan['domain_name'] in domains:
            # A failed configuration check must not prevent destroying our exact
            # process, but never stop a replacement merely sharing the name/UUID.
            try:
                state = self.backend.snapshot(self.plan['domain_name'])
            except Exception as error:
                missing = getattr(self.backend, 'is_missing_domain_error', lambda e: False)(error)
                require(missing and self.identity is not None and
                        self.plan['domain_name'] not in self.backend.domains() and
                        self.backend.process_gone(self.identity), 'cleanup observation failed without exit proof')
                state = None
            if state is not None:
                identity = {key: state[key] for key in ('name', 'uuid', 'run_id', 'pid', 'start_ticks')}
                require(self.identity is not None and identity == self.identity,
                        'cleanup refuses unproven or replaced domain ownership')
                self.check_container()
                try:
                    self.backend.destroy_owned(self.identity)
                except Exception as error:
                    missing = getattr(self.backend, 'is_missing_domain_error', lambda e: False)(error)
                    require(missing and self.backend.process_gone(self.identity),
                            'destroy failed without process exit proof')
                require(self.plan['domain_name'] not in self.backend.domains(), 'domain survived destroy')
        if self.created:
            require(self.backend.process_gone(self.identity) is True,
                    'domain absence does not prove QEMU exit')
        self.check_container()
        self.stop_receipt = dict(reason=reason, resumed=self.resumed,
                                 resume_attempted=self.resume_attempted)
        self.record('stopped', **self.stop_receipt)
        self.finished = True


def monitor(owner, deadline, stop_requested=lambda: False, poll_seconds=0.2):
    """Follow an already running domain until exit, stop request or fixed deadline.

    Backend calls must remain under the independent outer container deadline;
    this loop does not replace that host supervisor or guest shutdown protocol.
    Domain disappearance is never itself proof of process exit or clean shutdown.
    """
    require(owner.resumed and not owner.finished, 'monitor requires running owner')
    require(math.isfinite(deadline) and math.isfinite(poll_seconds) and poll_seconds > 0,
            'invalid monitor deadline or interval')
    try:
        while True:
            owner.check_container()
            getattr(owner.backend, 'health_check', lambda: None)()
            if stop_requested():
                reason = 'controller-stop-request'
                break
            if time.monotonic() >= deadline:
                reason = 'controller-deadline'
                break
            if owner.plan['domain_name'] not in owner.backend.domains():
                reason = owner.backend.exit_reason(owner.plan['domain_name'], deadline)
                require(reason in ('guest-shutdown', 'manager-destroyed', 'domain-crashed',
                                   'domain-exited-unknown'), 'invalid domain exit reason')
                break
            try:
                owner.observe()
            except Exception as error:
                missing = getattr(owner.backend, 'is_missing_domain_error', lambda e: False)(error)
                if not missing or owner.plan['domain_name'] in owner.backend.domains():
                    raise
                require(owner.backend.process_gone(owner.identity), 'domain disappeared with QEMU still live')
                reason = owner.backend.exit_reason(owner.plan['domain_name'], deadline)
                break
            time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
        require(reason in ('guest-shutdown', 'manager-destroyed', 'domain-crashed',
                           'domain-exited-unknown', 'controller-stop-request', 'controller-deadline'),
                'invalid domain exit reason')
        owner.cleanup(reason)
        return reason
    except BaseException as error:
        owner.abort(error, 'monitor-failed')
        raise
