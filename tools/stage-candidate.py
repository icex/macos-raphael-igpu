#!/usr/bin/env python3
"""Stage the exact candidate 1.0.180 transaction without launching a VM.

This preserves the reviewed candidate-179 transaction boundaries. It refuses
to do anything unless --execute and every candidate-specific identity pin are
supplied. The clean candidate worktree, experiment card, and build-identity
record are immutable inputs; no policy, activation, manifest, or launch is
created.
"""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shutil
import signal
import subprocess
import sys
import uuid


VM = Path.home() / "macos-vm"
ROOT = Path(__file__).resolve().parents[1]
WT = VM / "run/worktrees/candidate-180"
CANDIDATE = VM / "run/candidate-180"
DIST = VM / "run/candidate-180-dist"
IDENTITIES = VM / "run/candidate-180-build-identities.json"
RUN_ID_FILE = VM / "run/candidate180-qualification-run-id.txt"
CARD = ROOT / "experiments/metal-013.json"
CANDIDATE_VERSION = "1.0.180"


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    return sha_bytes(Path(path).read_bytes())


def exact_hex(value, digits, label):
    if not isinstance(value, str) or not re.fullmatch(
            rf"[0-9a-f]{{{digits}}}", value):
        raise RuntimeError(f"{label} must be {digits} lowercase hexadecimal characters")
    return value


def validate_card(raw, expected_sha256):
    exact_hex(expected_sha256, 64, "card digest")
    if sha_bytes(raw) != expected_sha256:
        raise RuntimeError("candidate card digest changed")
    try:
        card = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("candidate card is not valid JSON") from error
    exact = {
        "id": "metal-013",
        "candidate_version": CANDIDATE_VERSION,
        "requested_diagnostic": "rgpusubmit=1",
        "max_seconds": 180,
        "run_probe_only_after_native_start": True,
        "critical_replay_schema": 2,
        "recovery_lease_schema": 3,
    }
    if not isinstance(card, dict) or any(
            type(card.get(key)) is not type(value) or card.get(key) != value
            for key, value in exact.items()):
        raise RuntimeError("candidate card contract mismatch")
    return card


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(argv, timeout=30):
    return subprocess.check_output(argv, text=True, timeout=timeout).strip()


def sync_dir(path):
    descriptor = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def relative_vm_path(path):
    return Path(path).resolve().relative_to(VM.resolve()).as_posix()


def docker_tool(image_id, entrypoint, arguments, timeout=90):
    argv = [
        "docker", "run", "--rm", "--network", "none",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "-v", f"{VM.resolve()}:/run/vm:rw",
        "--entrypoint", entrypoint, image_id,
    ]
    return subprocess.run(
        argv + list(arguments), check=True, capture_output=True, text=True,
        timeout=timeout)


def qconvert(image_id, source, source_format, target, target_format):
    docker_tool(image_id, "qemu-img", [
        "convert", "-f", source_format, "-O", target_format,
        "/run/vm/" + relative_vm_path(source),
        "/run/vm/" + relative_vm_path(target),
    ])


def verify_worktree_before_import(expected_commit):
    if ROOT.resolve() != WT.resolve():
        raise RuntimeError("staging tool must run from the candidate worktree")
    if command(["git", "-C", str(WT), "rev-parse", "HEAD"]) != expected_commit:
        raise RuntimeError("candidate worktree commit changed")
    if command(["git", "-C", str(WT), "status", "--porcelain"]):
        raise RuntimeError("candidate worktree is dirty")


def verify_build_inputs(experiment, builder, expected_commit,
                        expected_identities_sha256, image_id):
    if sha_file(IDENTITIES) != expected_identities_sha256:
        raise RuntimeError("candidate build-identity record changed")
    identities = json.loads(IDENTITIES.read_text())
    manifest_path = CANDIDATE / "build-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    executable = CANDIDATE / "RaphaelGPU.kext/Contents/MacOS/RaphaelGPU"
    info_path = CANDIDATE / "RaphaelGPU.kext/Contents/Info.plist"
    archive = DIST / "RaphaelGPU-1.0.180-experimental.zip"
    sums = DIST / "SHA256SUMS"
    build_log = VM / "run/candidate-180-build.log"

    exact = {
        "schema": 1,
        "version": CANDIDATE_VERSION,
        "source_commit": expected_commit,
        "source_clean": True,
        "worktree": str(WT),
        "extracted_candidate": str(CANDIDATE),
        "archive": str(archive),
    }
    for key, value in exact.items():
        if identities.get(key) != value:
            raise RuntimeError(f"build identity mismatch: {key}")

    observed = {
        "archive_sha256": sha_file(archive),
        "build_log_sha256": sha_file(build_log),
        "build_manifest_sha256": sha_file(manifest_path),
        "executable_sha256": sha_file(executable),
        "info_sha256": sha_file(info_path),
        "sha256sums_sha256": sha_file(sums),
        "source_sha256": builder.tree_digest(WT / "src"),
    }
    for key, value in observed.items():
        if identities.get(key) != value:
            raise RuntimeError(f"artifact hash mismatch: {key}")

    for key in ("version", "source_commit", "source_clean", "build_id",
                "source_sha256", "executable_sha256", "info_sha256"):
        if manifest.get(key) != identities.get(key):
            raise RuntimeError(f"manifest identity mismatch: {key}")
    if manifest.get("metal_execution_verified") is not False:
        raise RuntimeError("candidate incorrectly claims Metal execution")
    if manifest.get("verified_playable_games") != 0:
        raise RuntimeError("candidate incorrectly claims supported games")

    info = plistlib.loads(info_path.read_bytes())
    if (info.get("CFBundleVersion"), info.get("CFBundleShortVersionString")) != (
            CANDIDATE_VERSION, CANDIDATE_VERSION):
        raise RuntimeError("candidate Info.plist version mismatch")
    builder.validate_macho(executable.read_bytes())

    checksum_fields = sums.read_text().split()
    if checksum_fields != [identities["archive_sha256"], archive.name]:
        raise RuntimeError("SHA256SUMS does not bind the candidate archive")
    observed_image_id = command(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image_id])
    if observed_image_id != image_id:
        raise RuntimeError("Docker image identity changed")
    return identities, manifest, archive


def active_or_pending_vm():
    names = command([
        "docker", "ps", "-a", "--filter", "status=running",
        "--filter", "status=created", "--filter", "status=restarting",
        "--filter", "status=paused", "--format", "{{.Names}}",
    ]).splitlines()
    if any(name == "macos-sequoia" or name.startswith("rgpu-launch-")
           for name in names):
        return True
    pending = VM / "run/launch-pending"
    return pending.exists() and any(pending.iterdir())


def select_run_id():
    run_id = secrets.token_hex(16)
    with RUN_ID_FILE.open("x") as stream:
        stream.write(run_id + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    sync_dir(RUN_ID_FILE.parent)
    return run_id


def make_staged_config(experiment, card, run_id):
    original = (VM / "config.plist").read_bytes()
    xml = original.index(b"<?xml")
    header = original[:xml]
    config = plistlib.loads(original[xml:])
    nvram = config["NVRAM"]["Add"][experiment.BOOT_GUID]
    old_words = nvram["boot-args"].split()
    retired = {"rgpucp", "rgpureset", "rgpuic", "rgpurlc", "rgpufb"}
    if any(word.split("=", 1)[0] in retired for word in old_words):
        raise RuntimeError("retired rgpu boot argument remains")

    nonce_lo, nonce_hi = experiment.recovery_nonce_words(run_id)
    updates = {
        "rgpu": "0xfffa5981",
        "rgpuvmm": "3",
        "rgpumem": "1",
        "rgpuptb": "2",
        "rgpumqd": "2",
        "rgpuhybrid": "1",
        "rgpusubmit": "1",
        "rgpurnlo": f"0x{nonce_lo:x}",
        "rgpurnhi": f"0x{nonce_hi:x}",
    }
    words = [word for word in old_words
             if word.split("=", 1)[0] not in updates]
    words.extend(f"{key}={value}" for key, value in updates.items())
    boot_args = " ".join(words)
    nvram["boot-args"] = boot_args
    if not experiment.raphael_target_marked(config):
        raise RuntimeError("Raphael device marker missing")
    errors = experiment.boot_argument_errors(
        boot_args, card["requested_diagnostic"], run_id)
    if errors:
        raise RuntimeError("numeric nonce config rejected: " + ",".join(errors))
    return original, header + plistlib.dumps(config), boot_args, nonce_lo, nonce_hi


def write_synced_exclusive(path, data):
    mode = "xb" if isinstance(data, bytes) else "x"
    with Path(path).open(mode) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def armed_replace(source, target, published, name, replace=os.replace):
    """Pre-arm rollback before an atomic replace can become externally visible."""
    published[name] = True
    replace(source, target)


def armed_exclusive_link(source, target, published, name, link=os.link):
    """Publish a hard-link without clobbering an unexpected destination."""
    published[name] = True
    link(source, target)


def file_has_sha(path, expected):
    try:
        return sha_file(path) == expected
    except OSError:
        return False


class StageInterrupted(Exception):
    pass


def stage(expected_commit, expected_boot_id, expected_card_sha256,
          expected_identities_sha256, image_id):
    exact_hex(expected_commit, 40, "source commit")
    exact_hex(expected_identities_sha256, 64, "build-identities digest")
    if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                    r"[0-9a-f]{4}-[0-9a-f]{12}", expected_boot_id) is None:
        raise RuntimeError("boot ID must be a lowercase UUID")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise RuntimeError("Docker image must be an exact sha256 identity")
    # Imported worktree modules execute top-level Python.  Authenticate their exact
    # committed source before importing either one.
    verify_worktree_before_import(expected_commit)
    card = validate_card(CARD.read_bytes(), expected_card_sha256)
    experiment = load_module("candidate180_experiment", WT / "tools/experiment.py")
    builder = load_module("candidate180_build", WT / "tools/build-release.py")
    identities, manifest, archive = verify_build_inputs(
        experiment, builder, expected_commit, expected_identities_sha256,
        image_id)

    if RUN_ID_FILE.exists():
        raise RuntimeError("candidate-180 run ID already selected; automatic retry refused")
    staged_config_path = CANDIDATE / "staged-config.plist"
    staging_path = CANDIDATE / "staging.json"
    if staged_config_path.exists() or staging_path.exists():
        raise RuntimeError("candidate-180 was already staged")

    raw_image = VM / "run/oc-raw.img"
    bootdisk = VM / "OpenCore.qcow2"
    config_path = VM / "config.plist"
    token = uuid.uuid4().hex
    private_raw = VM / f"run/.candidate180-private-{token}.img"
    preimage_verify = VM / f"run/.candidate180-preimage-{token}.raw"
    candidate_qcow = VM / f".OpenCore-candidate180-{token}.qcow2"
    candidate_verify = VM / f"run/.candidate180-candidate-{token}.raw"
    final_verify = VM / f"run/.candidate180-final-{token}.raw"
    rollback_verify = VM / f"run/.candidate180-rollback-{token}.raw"
    config_temp = VM / f".config-candidate180-{token}.plist"
    pending_record = CANDIDATE / f".staging-pending-{token}.json"
    raw_backup = raw_image.with_name(raw_image.name + ".backup-" + token)
    boot_backup = bootdisk.with_name(bootdisk.name + ".backup-" + token)
    config_backup = config_path.with_name(config_path.name + ".backup-" + token)
    temporary = [private_raw, preimage_verify, candidate_qcow, candidate_verify,
                 final_verify, rollback_verify, config_temp]
    private_stage_backup = None
    original_observed = None
    raw_preimage_sha = None
    boot_preimage_sha = None
    config_preimage_sha = None
    published = {"raw": False, "boot": False, "config": False}
    candidate_metadata_created = False
    metadata_published = {"staging": False}
    staged_config_sha = None
    staging_record_sha = None

    with (VM / "run/experiment.lock").open("a") as experiment_lock:
        fcntl.flock(experiment_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (VM / "run/redeploy.lock").open("a") as media_lock:
            fcntl.flock(media_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if Path("/proc/sys/kernel/random/boot_id").read_text().strip() != expected_boot_id:
                raise RuntimeError("candidate-180 boot authority no longer matches")
            if active_or_pending_vm():
                raise RuntimeError("active or pending VM prevents staging")

            previous_sigterm = signal.signal(
                signal.SIGTERM,
                lambda signum, frame: (_ for _ in ()).throw(
                    StageInterrupted("staging interrupted by SIGTERM")))
            try:
                original_config = config_path.read_bytes()
                raw_preimage_sha = sha_file(raw_image)
                boot_preimage_sha = sha_file(bootdisk)
                config_preimage_sha = sha_bytes(original_config)
                original_observed = experiment.image_files(raw_image)
                if original_observed["config_sha256"] != config_preimage_sha:
                    raise RuntimeError("raw ESP and config.plist preimage differ")

                qconvert(image_id, bootdisk, "qcow2", preimage_verify, "raw")
                errors = experiment.validate_identity(
                    original_observed, experiment.image_files(preimage_verify))
                if errors:
                    raise RuntimeError(
                        "raw ESP and OpenCore.qcow2 preimage differ: " +
                        ",".join(errors))
                preimage_verify.unlink()

                # This is the first durable candidate mutation.  A failed staging
                # attempt retains the identity and cannot silently select another.
                run_id = select_run_id()
                original_config, staged_config, boot_args, nonce_lo, nonce_hi = \
                    make_staged_config(experiment, card, run_id)
                if sha_bytes(original_config) != config_preimage_sha:
                    raise RuntimeError("config.plist changed before nonce staging")

                expected = {
                    "binary_sha256": identities["executable_sha256"],
                    "info_sha256": identities["info_sha256"],
                    "config_sha256": sha_bytes(staged_config),
                }

                # Never let mtools touch the published raw ESP.  stage_image performs
                # its own copy/verify/replace transaction on this private copy only.
                shutil.copyfile(raw_image, private_raw)
                with private_raw.open("rb") as stream:
                    os.fsync(stream.fileno())
                private_stage = experiment.stage_image(
                    private_raw, CANDIDATE / "RaphaelGPU.kext", staged_config)
                private_stage_backup = Path(private_stage["backup"])
                errors = experiment.validate_identity(
                    expected, experiment.image_files(private_raw))
                if errors:
                    raise RuntimeError("private raw ESP readback failed: " + ",".join(errors))

                qconvert(image_id, private_raw, "raw", candidate_qcow, "qcow2")
                qconvert(image_id, candidate_qcow, "qcow2", candidate_verify, "raw")
                errors = experiment.validate_identity(
                    expected, experiment.image_files(candidate_verify))
                if errors:
                    raise RuntimeError("candidate qcow2 readback failed: " + ",".join(errors))
                candidate_verify.unlink()

                qemu_version = docker_tool(
                    image_id, "qemu-system-x86_64", ["--version"], timeout=30
                ).stdout.splitlines()[0]

                # Backups and all metadata are durable before the first publication.
                # Recheck the live preimages at the publication boundary.  The locks
                # exclude cooperating tools; these hashes also reject an external editor
                # that ignored them while the private candidate was being prepared.
                if sha_file(raw_image) != raw_preimage_sha:
                    raise RuntimeError("live raw ESP changed before publication")
                if sha_file(bootdisk) != boot_preimage_sha:
                    raise RuntimeError("live OpenCore.qcow2 changed before publication")
                if sha_file(config_path) != config_preimage_sha:
                    raise RuntimeError("live config.plist changed before publication")
                os.link(raw_image, raw_backup)
                os.link(bootdisk, boot_backup)
                os.link(config_path, config_backup)
                sync_dir(VM)
                sync_dir(VM / "run")

                with config_temp.open("xb") as stream:
                    stream.write(staged_config)
                    stream.flush()
                    os.fsync(stream.fileno())
                with candidate_qcow.open("rb") as stream:
                    os.fsync(stream.fileno())
                with private_raw.open("rb") as stream:
                    os.fsync(stream.fileno())

                candidate_metadata_created = True
                staged_config_sha = expected["config_sha256"]
                write_synced_exclusive(staged_config_path, staged_config)
                staging = dict(
                    expected,
                    backup=str(raw_backup),
                    bootdisk_backup=str(boot_backup),
                    config_backup=str(config_backup),
                    raw_preimage_sha256=raw_preimage_sha,
                    raw_backup_sha256=sha_file(raw_backup),
                    raw_sha256=sha_file(private_raw),
                    bootdisk_preimage_sha256=boot_preimage_sha,
                    bootdisk_backup_sha256=sha_file(boot_backup),
                    bootdisk_sha256=sha_file(candidate_qcow),
                    config_backup_sha256=sha_file(config_backup),
                    candidate_version=CANDIDATE_VERSION,
                    experiment=card["id"],
                    experiment_card_sha256=expected_card_sha256,
                    critical_replay_schema=card["critical_replay_schema"],
                    recovery_lease_schema=card["recovery_lease_schema"],
                    run_id=run_id,
                    nonce_lo=nonce_lo,
                    nonce_hi=nonce_hi,
                    build_id=manifest["build_id"],
                    source_commit=manifest["source_commit"],
                    source_sha256=manifest["source_sha256"],
                    executable_sha256=manifest["executable_sha256"],
                    info_manifest_sha256=manifest["info_sha256"],
                    physical_tested=False,
                    archive_sha256=sha_file(archive),
                    build_identities_sha256=sha_file(IDENTITIES),
                    image_id=image_id,
                    qemu_version=qemu_version,
                    boot_args=boot_args,
                )
                staging_record_bytes = (json.dumps(staging, indent=2) + "\n").encode()
                staging_record_sha = sha_bytes(staging_record_bytes)
                write_synced_exclusive(pending_record, staging_record_bytes)
                sync_dir(CANDIDATE)

                # Both locks exclude launch and preparation while these three atomic
                # replacements publish one already-verified candidate identity.
                # Repeat these hashes after all metadata and backup fsyncs, directly
                # before the first externally visible replace.
                if sha_file(raw_image) != raw_preimage_sha:
                    raise RuntimeError("live raw ESP changed at publication boundary")
                if sha_file(bootdisk) != boot_preimage_sha:
                    raise RuntimeError("live OpenCore.qcow2 changed at publication boundary")
                if sha_file(config_path) != config_preimage_sha:
                    raise RuntimeError("live config.plist changed at publication boundary")
                armed_replace(private_raw, raw_image, published, "raw")
                armed_replace(candidate_qcow, bootdisk, published, "boot")
                armed_replace(config_temp, config_path, published, "config")
                sync_dir(VM)
                sync_dir(VM / "run")

                errors = experiment.validate_identity(
                    expected, experiment.image_files(raw_image))
                if errors or sha_file(config_path) != expected["config_sha256"]:
                    raise RuntimeError("published raw/config identity mismatch")
                qconvert(image_id, bootdisk, "qcow2", final_verify, "raw")
                errors = experiment.validate_identity(
                    expected, experiment.image_files(final_verify))
                if errors:
                    raise RuntimeError("published qcow2 readback failed: " + ",".join(errors))
                final_verify.unlink()

                # Hard-link publication refuses an unexpected existing staging.json.
                # Pre-arm the flag so an interrupt after link(2) is still recoverable.
                if not file_has_sha(staged_config_path, staged_config_sha):
                    raise RuntimeError("staged config metadata changed before publication")
                if not file_has_sha(pending_record, staging_record_sha):
                    raise RuntimeError("pending staging record changed before publication")
                armed_exclusive_link(
                    pending_record, staging_path, metadata_published, "staging")
                if not file_has_sha(staging_path, staging_record_sha):
                    raise RuntimeError("published staging record digest mismatch")
                sync_dir(CANDIDATE)
                pending_record.unlink()
                sync_dir(CANDIDATE)
                print(json.dumps(staging, indent=2))

            except BaseException as original_error:
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                rollback_errors = []
                for name, target, backup in (
                        ("config", config_path, config_backup),
                        ("boot", bootdisk, boot_backup),
                        ("raw", raw_image, raw_backup)):
                    try:
                        if published[name] and backup.exists():
                            os.replace(backup, target)
                        elif backup.exists():
                            backup.unlink()
                    except BaseException as error:
                        rollback_errors.append(f"{name}:{type(error).__name__}:{error}")
                try:
                    sync_dir(VM)
                    sync_dir(VM / "run")
                    if any(published.values()) and original_observed is not None:
                        if sha_file(config_path) != config_preimage_sha:
                            rollback_errors.append("config:identity")
                        errors = experiment.validate_identity(
                            original_observed, experiment.image_files(raw_image))
                        if errors:
                            rollback_errors.append("raw:" + ",".join(errors))
                        qconvert(image_id, bootdisk, "qcow2", rollback_verify, "raw")
                        errors = experiment.validate_identity(
                            original_observed, experiment.image_files(rollback_verify))
                        if errors:
                            rollback_errors.append("boot:" + ",".join(errors))
                except BaseException as error:
                    rollback_errors.append(
                        f"verify:{type(error).__name__}:{error}")

                staged_config_owned = (
                    candidate_metadata_created and staged_config_sha is not None and
                    staged_config_path.exists() and
                    file_has_sha(staged_config_path, staged_config_sha))
                if (candidate_metadata_created and staged_config_path.exists() and
                        not staged_config_owned):
                    rollback_errors.append("metadata:foreign-staged-config")
                pending_owned = (
                    staging_record_sha is not None and pending_record.exists() and
                    file_has_sha(pending_record, staging_record_sha))
                staging_owned = (
                    metadata_published["staging"] and staging_record_sha is not None and
                    staging_path.exists() and
                    file_has_sha(staging_path, staging_record_sha))
                if (metadata_published["staging"] and staging_path.exists() and
                        not staging_owned):
                    rollback_errors.append("metadata:foreign-staging-record")

                if not rollback_errors:
                    if staged_config_owned:
                        staged_config_path.unlink()
                    if pending_owned:
                        pending_record.unlink()
                    if staging_owned:
                        staging_path.unlink()
                    sync_dir(CANDIDATE)
                else:
                    # Preserve the pending record and preimage links for manual audit.
                    # There is no final staging.json, so the reviewed command chain
                    # cannot advance to manifest preparation.
                    if staging_owned:
                        try:
                            if not pending_record.exists():
                                os.link(staging_path, pending_record)
                            elif not pending_owned:
                                raise RuntimeError("foreign pending staging record")
                            staging_path.unlink()
                            sync_dir(CANDIDATE)
                        except BaseException as error:
                            rollback_errors.append(
                                f"metadata:{type(error).__name__}:{error}")
                    raise RuntimeError(
                        f"staging failed ({original_error}); rollback incomplete: " +
                        ";".join(rollback_errors)) from original_error
                raise
            finally:
                signal.signal(signal.SIGTERM, previous_sigterm)
                if private_stage_backup is not None:
                    temporary.append(private_stage_backup)
                for path in temporary:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true",
        help="perform the reviewed staging transaction; absent means refuse")
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-boot-id", required=True)
    parser.add_argument("--expected-card-sha256", required=True)
    parser.add_argument("--expected-identities-sha256", required=True)
    parser.add_argument("--image-id", required=True)
    args = parser.parse_args()
    if not args.execute:
        parser.error("refusing mutation without the reviewed --execute flag")
    stage(args.expected_commit, args.expected_boot_id,
          args.expected_card_sha256, args.expected_identities_sha256,
          args.image_id)


if __name__ == "__main__":
    main()
