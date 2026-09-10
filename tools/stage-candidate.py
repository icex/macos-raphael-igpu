#!/usr/bin/env python3
"""Stage a narrowly reviewed candidate transaction without launching a VM.

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
import struct
import subprocess
import sys
import tempfile
import uuid


VM = Path.home() / "macos-vm"
ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_VERSION = "1.0.186"
CARD_ID = "metal-019"
SUPPORTED_CARD_DIAGNOSTICS = {
    ("1.0.180", "metal-013"): "rgpusubmit=1",
    ("1.0.181", "metal-014"): "rgpusubmit=1",
    ("1.0.182", "metal-015"): "rgpusubmit=1",
    ("1.0.183", "metal-016"): "rgpusubmit=1",
    ("1.0.184", "metal-017"): "rgpuvmdiag=1",
    ("1.0.185", "metal-018"): "rgpuvmdiag=1",
    ("1.0.186", "metal-019"): "rgpuvmdiag=1",
}


def configure(version, card_id):
    """Select the exact reviewed candidate/card pair; defaults are 1.0.185."""
    global CANDIDATE_VERSION, CARD_ID, NUMBER, WT, CANDIDATE, DIST, IDENTITIES
    global RUN_ID_FILE, CARD
    if not re.fullmatch(r"1\.0\.(1[0-9]{2})", version):
        raise RuntimeError("candidate version must be 1.0.1NN")
    if not re.fullmatch(r"metal-[0-9]{3}", card_id):
        raise RuntimeError("card id must be metal-NNN")
    CANDIDATE_VERSION = version
    CARD_ID = card_id
    NUMBER = version.rsplit(".", 1)[1]
    WT = VM / f"run/worktrees/candidate-{NUMBER}"
    CANDIDATE = VM / f"run/candidate-{NUMBER}"
    DIST = VM / f"run/candidate-{NUMBER}-dist"
    IDENTITIES = VM / f"run/candidate-{NUMBER}-build-identities.json"
    RUN_ID_FILE = VM / f"run/candidate{NUMBER}-qualification-run-id.txt"
    CARD = ROOT / f"experiments/{card_id}.json"


configure(CANDIDATE_VERSION, CARD_ID)


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
    pair = (CANDIDATE_VERSION, CARD_ID)
    requested_diagnostic = SUPPORTED_CARD_DIAGNOSTICS.get(pair)
    if requested_diagnostic is None:
        raise RuntimeError("unsupported candidate card pair")
    exact = {
        "id": CARD_ID,
        "candidate_version": CANDIDATE_VERSION,
        "requested_diagnostic": requested_diagnostic,
        "max_seconds": 180,
        "run_probe_only_after_native_start": True,
        "critical_replay_schema": 2,
        "recovery_lease_schema": 3,
    }
    if not isinstance(card, dict) or any(
            type(card.get(key)) is not type(value) or card.get(key) != value
            for key, value in exact.items()):
        raise RuntimeError("candidate card contract mismatch")
    if pair in (("1.0.184", "metal-017"), ("1.0.185", "metal-018"),
                ("1.0.186", "metal-019")):
        candidate_contract = {
            "critical_replay_tolerance": "terminal-prefix",
            "recovery_critical_replay_tolerance": "terminal-prefix-open",
            "conditional_diagnostic_observations": [
                "vmid1_fault_walk", "vmid1_fault_walk_view",
                "vmid1_fault_walk_entry",
            ],
            "launch_options": {
                "BOOTDISK_MODE": "custom",
                "NVRAM": "stock",
                "GENERIC_GRAPHICS": "off",
            },
        }
        if any(card.get(key) != value for key, value in candidate_contract.items()):
            raise RuntimeError("candidate card contract mismatch")
    if pair in (("1.0.184", "metal-017"), ("1.0.185", "metal-018")) and \
            card.get("functional_boot_arguments") != {"rgpuvmroot": "4"}:
        raise RuntimeError("candidate card contract mismatch")
    if pair == ("1.0.186", "metal-019"):
        candidate186_contract = {
            "functional_boot_arguments": {"rgpuvmroot": "4", "rgpudump": "5000"},
            "required_boot_flags": ["-liluheadless"],
            "raphael_source_sha256":
                "db511634c6d292ef3a65285e56bd5cf5f9e03cf4c20680a27b96c46a18f2e9b0",
        }
        if any(card.get(key) != value
               for key, value in candidate186_contract.items()):
            raise RuntimeError("candidate card contract mismatch")
    transport_path = Path(__file__).with_name("critical-transport.py")
    spec = importlib.util.spec_from_file_location("critical_transport", transport_path)
    transport = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transport)
    try:
        transport.validate(card)
    except ValueError as error:
        raise RuntimeError(str(error)) from error
    picker_timeout = card.get("guest_picker_timeout_seconds")
    if (picker_timeout is not None and
            (type(picker_timeout) is not int or
             not 1 <= picker_timeout <= 300)):
        raise RuntimeError("guest picker timeout must be an integer from 1 to 300 seconds")
    return card


def apply_guest_picker_timeout(config, card):
    """Apply an optional candidate-pinned OpenCore picker timeout in memory."""
    timeout = card.get("guest_picker_timeout_seconds")
    if timeout is None:
        return
    if type(timeout) is not int or not 1 <= timeout <= 300:
        raise RuntimeError("guest picker timeout must be an integer from 1 to 300 seconds")
    try:
        boot = config["Misc"]["Boot"]
    except (KeyError, TypeError):
        raise RuntimeError("OpenCore Misc.Boot section is missing")
    if boot.get("ShowPicker") is not True:
        raise RuntimeError("guest picker timeout requires ShowPicker=true")
    boot["Timeout"] = timeout


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
    archive = DIST / f"RaphaelGPU-{CANDIDATE_VERSION}-experimental.zip"
    sums = DIST / "SHA256SUMS"
    build_log = VM / f"run/candidate-{NUMBER}-build.log"

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


def candidate_boot_argument_updates(card, nonce_lo, nonce_hi):
    """Return the exact reviewed functional and diagnostic boot-argument map."""
    pair = (card.get("candidate_version"), card.get("id"))
    requested = SUPPORTED_CARD_DIAGNOSTICS.get(pair)
    if requested is None or card.get("requested_diagnostic") != requested:
        raise RuntimeError("unsupported candidate card diagnostic")
    diagnostic_key, diagnostic_value = requested.split("=", 1)
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
    if "critical_replay_transport" in card:
        updates["rgpucr2uart"] = "2"
    functional = card.get("functional_boot_arguments", {})
    if not isinstance(functional, dict) or any(
            not re.fullmatch(r"rgpu[a-z]+", key) or key in updates or
            not isinstance(value, str) or not re.fullmatch(r"[0-9a-fx]+", value)
            for key, value in functional.items()):
        raise RuntimeError("candidate card functional boot arguments are invalid")
    if diagnostic_key in functional:
        raise RuntimeError("candidate diagnostic must not be duplicated")
    updates.update(functional)
    if diagnostic_key in updates and updates[diagnostic_key] != diagnostic_value:
        raise RuntimeError("candidate diagnostic conflicts with functional baseline")
    updates[diagnostic_key] = diagnostic_value
    return updates


def candidate_boot_flags(card):
    flags = card.get("required_boot_flags", [])
    if (not isinstance(flags, list) or
            any(not isinstance(flag, str) or
                not re.fullmatch(r"-[a-z][a-z0-9]*", flag) for flag in flags) or
            len(set(flags)) != len(flags)):
        raise RuntimeError("candidate card boot flags are invalid")
    return flags


def make_staged_config(experiment, card, run_id):
    original = (VM / "config.plist").read_bytes()
    xml = original.index(b"<?xml")
    header = original[:xml]
    config = plistlib.loads(original[xml:])
    apply_guest_picker_timeout(config, card)
    nvram = config["NVRAM"]["Add"][experiment.BOOT_GUID]
    old_words = nvram["boot-args"].split()
    retired = {"rgpucp", "rgpureset", "rgpuic", "rgpurlc", "rgpufb"}
    if any(word.split("=", 1)[0] in retired for word in old_words):
        raise RuntimeError("retired rgpu boot argument remains")

    nonce_lo, nonce_hi = experiment.recovery_nonce_words(run_id)
    updates = candidate_boot_argument_updates(card, nonce_lo, nonce_hi)
    flags = candidate_boot_flags(card)
    words = [word for word in old_words
             if word.split("=", 1)[0] not in updates and
             word.split("=", 1)[0] not in flags]
    words.extend(flags)
    words.extend(f"{key}={value}" for key, value in updates.items())
    boot_args = " ".join(words)
    nvram["boot-args"] = boot_args
    if not experiment.raphael_target_marked(config):
        raise RuntimeError("Raphael device marker missing")
    errors = experiment.boot_argument_errors(
        boot_args, card["requested_diagnostic"], run_id)
    if errors:
        raise RuntimeError("numeric nonce config rejected: " + ",".join(errors))
    try:
        experiment.helper('critical-transport').validate_boot_args(boot_args, card)
    except ValueError as error:
        raise RuntimeError(str(error)) from error
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


def validate_lilu_inputs(bundle, executable_sha256, info_sha256,
                         build_manifest_sha256):
    if bundle is None:
        raise RuntimeError("Lilu bundle is required for candidate 186")
    bundle = Path(bundle).resolve()
    executable = bundle / "Contents/MacOS/Lilu"
    info_path = bundle / "Contents/Info.plist"
    manifest_path = bundle.parent / "build-manifest.json"
    if not bundle.is_dir():
        raise RuntimeError("Lilu bundle is missing")
    for label, path in (("executable", executable), ("Info.plist", info_path),
                        ("build manifest", manifest_path)):
        if not path.is_file():
            raise RuntimeError(f"Lilu {label} is missing")
    for value, label in ((executable_sha256, "Lilu executable digest"),
                         (info_sha256, "Lilu Info.plist digest"),
                         (build_manifest_sha256, "Lilu build manifest digest")):
        exact_hex(value, 64, label)
    if sha_file(executable) != executable_sha256:
        raise RuntimeError("Lilu executable changed")
    if sha_file(info_path) != info_sha256:
        raise RuntimeError("Lilu Info.plist changed")
    if sha_file(manifest_path) != build_manifest_sha256:
        raise RuntimeError("Lilu build manifest changed")
    info = plistlib.loads(info_path.read_bytes())
    if (info.get("CFBundleIdentifier"), info.get("CFBundleExecutable"),
            info.get("CFBundleVersion")) != ("as.vit9696.Lilu", "Lilu", "1.6.8"):
        raise RuntimeError("Lilu bundle identity mismatch")
    data = executable.read_bytes()
    if len(data) < 32 or struct.unpack_from("<4I", data)[:2] != (
            0xFEEDFACF, 0x1000007) or struct.unpack_from("<4I", data)[3] != 11:
        raise RuntimeError("Lilu executable is not an x86_64 MH_KEXT_BUNDLE")
    manifest = json.loads(manifest_path.read_text())
    exact = {
        "product": "Lilu", "version": "1.6.8",
        "bundle_id": "as.vit9696.Lilu", "architecture": "x86_64",
        "macho_type": "MH_KEXT_BUNDLE", "signed": False,
        "executable_sha256": executable_sha256,
        "info_plist_sha256": info_sha256,
    }
    if any(type(manifest.get(key)) is not type(value) or manifest.get(key) != value
           for key, value in exact.items()):
        raise RuntimeError("Lilu build manifest identity mismatch")
    return {
        "lilu_bundle": str(bundle),
        "lilu_build_manifest": str(manifest_path.resolve()),
        "lilu_build_manifest_sha256": build_manifest_sha256,
        "lilu_executable_sha256": executable_sha256,
        "lilu_info_sha256": info_sha256,
    }


def candidate_image_files(experiment, image, lilu=False, offset=1048576):
    observed = experiment.image_files(image, offset)
    if lilu:
        address = str(image) + (f"@@{offset}" if offset else "")
        env = dict(os.environ, MTOOLS_SKIP_CHECK="1")
        def read(name):
            return subprocess.check_output(
                ["mtype", "-i", address, "::/EFI/OC/" + name],
                env=env, timeout=15)
        observed.update({
            "lilu_executable_sha256": sha_bytes(read(
                "Kexts/Lilu.kext/Contents/MacOS/Lilu")),
            "lilu_info_sha256": sha_bytes(read(
                "Kexts/Lilu.kext/Contents/Info.plist")),
        })
    return observed


def stage_lilu_image(experiment, image, bundle, expected, offset=1048576):
    """Replace Lilu on a private image and publish only a complete readback."""
    with tempfile.TemporaryDirectory(prefix="lilu-stage-", dir=image.parent) as temporary:
        staged = Path(temporary) / image.name
        shutil.copyfile(image, staged)
        address = str(staged) + (f"@@{offset}" if offset else "")
        env = dict(os.environ, MTOOLS_SKIP_CHECK="1")
        subprocess.run(
            ["mdeltree", "-i", address, "::/EFI/OC/Kexts/Lilu.kext"],
            env=env, capture_output=True, timeout=15)
        subprocess.run(
            ["mcopy", "-s", "-o", "-i", address, str(bundle),
             "::/EFI/OC/Kexts/"], env=env, check=True,
            capture_output=True, timeout=30)
        errors = experiment.validate_identity(
            expected, candidate_image_files(experiment, staged, lilu=True,
                                            offset=offset))
        if errors:
            raise RuntimeError("Lilu ESP readback mismatch: " + ",".join(errors))
        backup = image.with_name(image.name + ".backup-" + uuid.uuid4().hex)
        os.link(image, backup)
        with staged.open("rb") as stream:
            os.fsync(stream.fileno())
        staged.replace(image)
        sync_dir(image.parent)
    return {"backup": str(backup)}


class StageInterrupted(Exception):
    pass


def stage(expected_commit, expected_boot_id, expected_card_sha256,
          expected_identities_sha256, image_id, lilu_bundle=None,
          expected_lilu_executable_sha256=None, expected_lilu_info_sha256=None,
          expected_lilu_build_manifest_sha256=None):
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
    candidate186 = (CANDIDATE_VERSION, CARD_ID) == ("1.0.186", "metal-019")
    if candidate186 and identities["source_sha256"] != card["raphael_source_sha256"]:
        raise RuntimeError("candidate 186 changed the candidate 185 Raphael source")
    lilu = (validate_lilu_inputs(
        lilu_bundle, expected_lilu_executable_sha256,
        expected_lilu_info_sha256, expected_lilu_build_manifest_sha256)
            if candidate186 else None)

    if RUN_ID_FILE.exists():
        raise RuntimeError(f"candidate-{NUMBER} run ID already selected; automatic retry refused")
    staged_config_path = CANDIDATE / "staged-config.plist"
    staging_path = CANDIDATE / "staging.json"
    if staged_config_path.exists() or staging_path.exists():
        raise RuntimeError(f"candidate-{NUMBER} was already staged")

    raw_image = VM / "run/oc-raw.img"
    bootdisk = VM / "OpenCore.qcow2"
    config_path = VM / "config.plist"
    token = uuid.uuid4().hex
    private_raw = VM / f"run/.candidate{NUMBER}-private-{token}.img"
    preimage_verify = VM / f"run/.candidate{NUMBER}-preimage-{token}.raw"
    candidate_qcow = VM / f".OpenCore-candidate{NUMBER}-{token}.qcow2"
    candidate_verify = VM / f"run/.candidate{NUMBER}-candidate-{token}.raw"
    final_verify = VM / f"run/.candidate{NUMBER}-final-{token}.raw"
    rollback_verify = VM / f"run/.candidate{NUMBER}-rollback-{token}.raw"
    config_temp = VM / f".config-candidate{NUMBER}-{token}.plist"
    pending_record = CANDIDATE / f".staging-pending-{token}.json"
    raw_backup = raw_image.with_name(raw_image.name + ".backup-" + token)
    boot_backup = bootdisk.with_name(bootdisk.name + ".backup-" + token)
    config_backup = config_path.with_name(config_path.name + ".backup-" + token)
    temporary = [private_raw, preimage_verify, candidate_qcow, candidate_verify,
                 final_verify, rollback_verify, config_temp]
    private_stage_backups = []
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
                raise RuntimeError(f"candidate-{NUMBER} boot authority no longer matches")
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
                if candidate186:
                    expected.update({key: lilu[key] for key in (
                        "lilu_executable_sha256", "lilu_info_sha256")})

                # Never let mtools touch the published raw ESP.  stage_image performs
                # its own copy/verify/replace transaction on this private copy only.
                shutil.copyfile(raw_image, private_raw)
                with private_raw.open("rb") as stream:
                    os.fsync(stream.fileno())
                private_stage = experiment.stage_image(
                    private_raw, CANDIDATE / "RaphaelGPU.kext", staged_config)
                private_stage_backups.append(Path(private_stage["backup"]))
                if candidate186:
                    lilu_stage = stage_lilu_image(
                        experiment, private_raw, Path(lilu["lilu_bundle"]), expected)
                    private_stage_backups.append(Path(lilu_stage["backup"]))
                errors = experiment.validate_identity(
                    expected, candidate_image_files(
                        experiment, private_raw, lilu=candidate186))
                if errors:
                    raise RuntimeError("private raw ESP readback failed: " + ",".join(errors))

                qconvert(image_id, private_raw, "raw", candidate_qcow, "qcow2")
                qconvert(image_id, candidate_qcow, "qcow2", candidate_verify, "raw")
                errors = experiment.validate_identity(
                    expected, candidate_image_files(
                        experiment, candidate_verify, lilu=candidate186))
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
                if candidate186:
                    staging.update(lilu)
                if "critical_replay_transport" in card:
                    staging["critical_replay_transport"] = card[
                        "critical_replay_transport"]
                    staging["critical_transport_validator_sha256"] = sha_file(
                        ROOT / "tools/critical-transport.py")
                if "launch_options" in card:
                    staging["launch_options"] = card["launch_options"]
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
                    expected, candidate_image_files(
                        experiment, raw_image, lilu=candidate186))
                if errors or sha_file(config_path) != expected["config_sha256"]:
                    raise RuntimeError("published raw/config identity mismatch")
                qconvert(image_id, bootdisk, "qcow2", final_verify, "raw")
                errors = experiment.validate_identity(
                    expected, candidate_image_files(
                        experiment, final_verify, lilu=candidate186))
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
                temporary.extend(private_stage_backups)
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
    parser.add_argument("--candidate-version", default=CANDIDATE_VERSION)
    parser.add_argument("--card-id", default=CARD_ID)
    parser.add_argument("--lilu-bundle", type=Path)
    parser.add_argument("--expected-lilu-executable-sha256")
    parser.add_argument("--expected-lilu-info-sha256")
    parser.add_argument("--expected-lilu-build-manifest-sha256")
    args = parser.parse_args()
    if not args.execute:
        parser.error("refusing mutation without the reviewed --execute flag")
    configure(args.candidate_version, args.card_id)
    stage(args.expected_commit, args.expected_boot_id,
          args.expected_card_sha256, args.expected_identities_sha256,
          args.image_id, args.lilu_bundle,
          args.expected_lilu_executable_sha256,
          args.expected_lilu_info_sha256,
          args.expected_lilu_build_manifest_sha256)


if __name__ == "__main__":
    main()
