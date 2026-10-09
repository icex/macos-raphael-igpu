#!/usr/bin/env python3
"""Per-run libvirt admission/paused handoff. No hardware launch CLI."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

MODULES=tuple('libvirt-console-'+name+'.py' for name in
              ('plan','runtime','local','verify','network','native','handoff','entry'))


def require(ok,message):
    if not ok:raise ValueError(message)


def sha(data):return hashlib.sha256(data).hexdigest()


def digest(data):return sha(json.dumps(data,sort_keys=True,separators=(',',':')).encode())


def write_once(path,data):
    path=Path(path);temporary=path.with_name('.'+path.name+'.'+str(os.getpid())+'.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(data,stream,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.link(temporary,path) # exclusive publication after the complete write
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:temporary.unlink(missing_ok=True)


def run_directory(base,run_id):
    require(type(run_id) is str and re.fullmatch('[0-9a-f]{32}',run_id),'invalid libvirt run id')
    return Path(base)/('libvirt-'+run_id)


def validate_refresh(value):
    require(type(value) is str and value in ("default", "60"),
            "invalid admitted console refresh")
    return value


def validate_full_refresh(value):
    require(type(value) is str and value in ("off", "on"),
            "invalid admitted console full refresh")
    return value


def validate_snapshot(value):
    require(type(value) is str and value in ("off", "on", "restart", "restart-timing", "restart-timing-pool"),
            "invalid admitted console snapshot")
    return value


def validate_vdagent(value):
    require(type(value) is str and value in ('off', 'on'), 'invalid admitted console vdagent')
    return value


def prepare(base,manifest,manifest_bytes,network,modules,now=None):
    require(manifest['launch_options'].get('VM_MANAGER')=='libvirt','wrong manager profile')
    refresh=validate_refresh(manifest['launch_options'].get('CONSOLE_REFRESH','default'))
    full=validate_full_refresh(manifest['launch_options'].get('CONSOLE_FULL_REFRESH','off'))
    require(full == 'off' or refresh == '60', 'full refresh requires explicit SPICE60')
    snapshot=validate_snapshot(manifest['launch_options'].get('CONSOLE_SNAPSHOT','off'))
    require(snapshot == 'off' or (full == 'on' and refresh == '60' and
            manifest['launch_options'].get('VM_CONSOLE') == 'bochs-spice' and
            manifest['launch_options'].get('GENERIC_GRAPHICS') == 'off'),
            'snapshot requires native libvirt SPICE60 full refresh')
    vdagent=validate_vdagent(manifest['launch_options'].get('CONSOLE_VDAGENT','off'))
    require(vdagent == 'off' or (manifest['launch_options'].get('VM_CONSOLE') == 'bochs-spice' and
            manifest['launch_options'].get('GENERIC_GRAPHICS') == 'off'), 'vdagent requires native libvirt SPICE')
    require(type(manifest['max_seconds']) is int and 0<manifest['max_seconds']<=6000,'invalid launch bound')
    require(set(modules)==set(MODULES),'incomplete controller module identity')
    directory=run_directory(base,manifest['run_id']);directory.mkdir(mode=0o700)
    now=time.time() if now is None else now
    data=dict(schema=1,run_id=manifest['run_id'],boot_id=manifest['boot_id'],
              manifest_sha256=sha(manifest_bytes),image_id=manifest['image_id'],console_refresh=refresh,console_full_refresh=full,console_snapshot=snapshot,console_vdagent=vdagent,
              deadline_epoch=math.floor(now+manifest['max_seconds']),network=network,
              modules_sha256=modules)
    write_once(directory/'admission.json',data)
    return directory,digest(data)


def validate_admission(data,run_id,expected_digest,modules_dir,boot_id,now=None):
    require(digest(data)==expected_digest and data['schema']==1 and data['run_id']==run_id,
            'admission identity mismatch')
    require(data['boot_id']==boot_id,'admission host boot changed')
    # Historical receipts predate this field and admit the unchanged default only.
    validate_vdagent(data.get('console_vdagent','off'))
    validate_refresh(data.get('console_refresh','default'))
    full=validate_full_refresh(data.get('console_full_refresh','off'))
    require(full == 'off' or data.get('console_refresh') == '60', 'full refresh requires explicit SPICE60')
    snapshot=validate_snapshot(data.get('console_snapshot','off'))
    require(snapshot == 'off' or (full == 'on' and data.get('console_refresh') == '60'),
            'snapshot requires explicit SPICE60 full refresh')
    require(type(data['manifest_sha256']) is str and re.fullmatch('[0-9a-f]{64}',data['manifest_sha256']),
            'missing admitted manifest digest')
    now=time.time() if now is None else now
    require(type(data['deadline_epoch']) is int and 0<data['deadline_epoch']-now<=6000,
            'admission deadline invalid or elapsed')
    require(set(data['modules_sha256'])==set(MODULES),'controller module set changed')
    for name in MODULES:
        require(sha((Path(modules_dir)/name).read_bytes())==data['modules_sha256'][name],
                'controller module identity changed')
    return True


def permit(admission,admission_digest,paused,observed,state):
    require(digest(admission)==admission_digest,'admission changed before release')
    require(paused==observed,'paused identity changed before release')
    require(paused['run_id']==admission['run_id'] and paused['paused'] is True,
            'guest did not remain paused')
    require(type(paused['plan_sha256']) is str and re.fullmatch('[0-9a-f]{64}',paused['plan_sha256']),
            'missing paused plan digest')
    require(re.fullmatch('[0-9a-f]{64}',state['cid']) is not None and state['started_at'],
            'missing outer container identity')
    require(type(state['deadline_epoch']) in (int,float) and math.isfinite(state['deadline_epoch']) and
            time.time()<admission['deadline_epoch']<=state['deadline_epoch'],
            'outer deadline cannot admit this handoff')
    return dict(schema=1,run_id=admission['run_id'],manifest_sha256=admission['manifest_sha256'],
                admission_sha256=admission_digest,paused=paused,cid=state['cid'],
                started_at=state['started_at'],deadline_epoch=admission['deadline_epoch'])


def validate_permit(value,admission,admission_digest,paused):
    require(value['schema']==1 and value['run_id']==admission['run_id'] and
            value['manifest_sha256']==admission['manifest_sha256'] and
            value['admission_sha256']==admission_digest and value['paused']==paused,
            'resume permit identity mismatch')
    require(re.fullmatch('[0-9a-f]{64}',value['cid']) is not None and value['started_at'],
            'resume permit lacks exact container identity')
    require(value['deadline_epoch']==admission['deadline_epoch'] and time.time()<value['deadline_epoch'],
            'resume permit extended or expired')
    return True
