#!/usr/bin/env python3
"""Stage a narrowly reviewed candidate transaction without launching a VM.

This preserves the reviewed candidate-179 transaction boundaries. It refuses
to do anything unless --execute and every candidate-specific identity pin are
supplied. The clean candidate worktree, experiment card, and build-identity
record are immutable inputs; no policy, activation, manifest, or launch is
created.
"""

import argparse
import copy
import fcntl
import gzip
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
CANDIDATE_VERSION = "1.0.188"
CARD_ID = "metal-021"
SUPPORTED_CARD_DIAGNOSTICS = {
    ("1.0.180", "metal-013"): "rgpusubmit=1",
    ("1.0.181", "metal-014"): "rgpusubmit=1",
    ("1.0.182", "metal-015"): "rgpusubmit=1",
    ("1.0.183", "metal-016"): "rgpusubmit=1",
    ("1.0.184", "metal-017"): "rgpuvmdiag=1",
    ("1.0.185", "metal-018"): "rgpuvmdiag=1",
    ("1.0.186", "metal-019"): "rgpuvmdiag=1",
    ("1.0.187", "metal-020"): "rgpuvmdiag=1",
    ("1.0.188", "metal-021"): "rgpuvmdiag=1",
    ("1.0.188", "metal-022"): "rgpuvmdiag=1",
    ("1.0.189", "metal-023"): "rgpuvmdiag=1",
    ("1.0.190", "metal-024"): "rgpuvmdiag=1",
    ("1.0.191", "metal-025"): "rgpuvmdiag=1",
    ("1.0.192", "metal-026"): "rgpuvmdiag=1",
    ("1.0.193", "metal-027"): "rgpuvmdiag=1",
    ("1.0.194", "metal-028"): "rgpuvmdiag=1",
    # candidate-195 offline contract (no authority or reseal profile yet).
    # Candidate 195 is observation-only: allocator and page-table commit
    # diagnostics are captured without changing GPU programming policy.
    ("1.0.195", "metal-029"): "rgpuvmdiag=1",
    ("1.0.196", "metal-030"): "rgpuvmdiag=1",
    ("1.0.197", "metal-031"): "rgpuvmdiag=1",
    ("1.0.198", "metal-032"): "rgpuvmdiag=1",
    ("1.0.199", "metal-033"): "rgpuvmdiag=1",
    ("1.0.200", "metal-034"): "rgpuvmdiag=1",
    ("1.0.201", "metal-035"): "rgpuvmdiag=1",
    ("1.0.203", "metal-037"): "rgpuvmdiag=1",
    ("1.0.204", "metal-038"): "rgpuvmdiag=1",
    ("1.0.205", "metal-039"): "rgpuvmdiag=1",
    ("1.0.206", "metal-040"): "rgpuvmdiag=1",
    ("1.0.207", "metal-041"): "rgpuvmdiag=1",
    ("1.0.208", "metal-042"): "rgpuvmdiag=1",
    ("1.0.209", "metal-043"): "rgpuvmdiag=1",
    ("1.0.210", "metal-044"): "rgpuvmdiag=1",
    ("1.0.211", "metal-045"): "rgpuvmdiag=1",
    ("1.0.212", "metal-046"): "rgpuvmdiag=1",
    ("1.0.213", "metal-047"): "rgpuvmdiag=1",
    ("1.0.214", "metal-048"): "rgpuvmdiag=1",
    ("1.0.215", "metal-049"): "rgpuvmdiag=1",
    ("1.0.215", "metal-050"): "rgpuvmdiag=1",
    ("1.0.216", "metal-051"): "rgpuvmdiag=1",
    ("1.0.216", "metal-052"): "rgpuvmdiag=1",
    ("1.0.217", "metal-053"): "rgpuvmdiag=1",
    ("1.0.218", "metal-054"): "rgpuvmdiag=1",
    ("1.0.218", "metal-055"): "rgpuvmdiag=1",
    ("1.0.218", "metal-056"): "rgpuvmdiag=1",
    ("1.0.218", "metal-057"): "rgpuvmdiag=1",
    ("1.0.218", "metal-058"): "rgpuvmdiag=1",
    ("1.0.218", "metal-059"): "rgpuvmdiag=1",
    ("1.0.218", "metal-060"): "rgpuvmdiag=1",
    ("1.0.218", "metal-061"): "rgpuvmdiag=1",
    ("1.0.218", "metal-062"): "rgpuvmdiag=1",
    ("1.0.218", "metal-063"): "rgpuvmdiag=1",
    ("1.0.219", "metal-064"): "rgpuvmdiag=1",
    ("1.0.220", "metal-065"): "rgpuvmdiag=1",
    ("1.0.220", "metal-066"): "rgpuvmdiag=1",
    ("1.0.220", "metal-067"): "rgpuvmdiag=1",
    ("1.0.221", "metal-068"): "rgpuvmdiag=1",
    ("1.0.222", "metal-069"): "rgpuvmdiag=1",
    ("1.0.223", "metal-070"): "rgpuvmdiag=1",
    ("1.0.224", "metal-071"): "rgpuvmdiag=1",
    ("1.0.225", "metal-072"): "rgpuvmdiag=1",
    ("1.0.225", "metal-073"): "rgpuvmdiag=1",
    ("1.0.226", "metal-074"): "rgpuvmdiag=1",
    ("1.0.227", "metal-075"): "rgpuvmdiag=1",
    ("1.0.228", "metal-076"): "rgpuvmdiag=1",
    ("1.0.229", "metal-077"): "rgpuvmdiag=1",
    ("1.0.230", "metal-078"): "rgpuvmdiag=1",
    ("1.0.242", "metal-088"): "rgpuvmdiag=1",
    ("1.0.243", "metal-089"): "rgpuvmdiag=1",
    ("1.0.244", "metal-090"): "rgpuvmdiag=1",
    ("1.0.245", "metal-091"): "rgpuvmdiag=1",
    ("1.0.246", "metal-092"): "rgpuvmdiag=1",
    ("1.0.247", "metal-093"): "rgpuvmdiag=1",
    ("1.0.248", "metal-094"): "rgpuvmdiag=1",
    ("1.0.249", "metal-095"): "rgpuvmdiag=1",
    ("1.0.250", "metal-096"): "rgpuvmdiag=1",
    ("1.0.251", "metal-097"): "rgpuvmdiag=1",
    ("1.0.252", "metal-098"): "rgpuvmdiag=1",
    ("1.0.253", "metal-099"): "rgpuvmdiag=1",
    ("1.0.254", "metal-100"): "rgpuvmdiag=1",
    ("1.0.262", "metal-108"): "rgpuvmdiag=1",
    ("1.0.263", "metal-109"): "rgpuvmdiag=1",
    ("1.0.264", "metal-110"): "rgpuvmdiag=1",
    ("1.0.265", "metal-111"): "rgpuvmdiag=1",
    ("1.0.266", "metal-112"): "rgpuvmdiag=1",
    ("1.0.267", "metal-113"): "rgpuvmdiag=1",
    ("1.0.268", "metal-114"): "rgpuvmdiag=1",
    ("1.0.269", "metal-115"): "rgpuvmdiag=1",
    ("1.0.269", "metal-116"): "rgpuvmdiag=1",
    ("1.0.270", "metal-117"): "rgpuvmdiag=1",
    ("1.0.271", "metal-118"): "rgpuvmdiag=1",
    ("1.0.272", "metal-119"): "rgpuvmdiag=1",
    ("1.0.274", "metal-121"): "rgpuvmdiag=1",
    ("1.0.273", "metal-120"): "rgpuvmdiag=1",
    ("1.0.275", "metal-122"): "rgpuvmdiag=1",
    ("1.0.276", "metal-123"): "rgpuvmdiag=1",
    ("1.0.277", "metal-124"): "rgpuvmdiag=1",
    ("1.0.279", "metal-126"): "rgpuvmdiag=1",
    ("1.0.280", "metal-127"): "rgpuvmdiag=1",
    ("1.0.280", "metal-128"): "rgpuvmdiag=1",
    ("1.0.281", "metal-129"): "rgpuvmdiag=1",
    ("1.0.282", "metal-130"): "rgpuvmdiag=1",
    ("1.0.283", "metal-131"): "rgpuvmdiag=1",
    ("1.0.284", "metal-132"): "rgpuvmdiag=1",
    ("1.0.285", "metal-133"): "rgpuvmdiag=1",
    ("1.0.286", "metal-134"): "rgpuvmdiag=1",
    ("1.0.287", "metal-135"): "rgpuvmdiag=1",
    ("1.0.288", "metal-136"): "rgpuvmdiag=1",
    ("1.0.289", "metal-137"): "rgpuvmdiag=1",
    ("1.0.290", "metal-138"): "rgpuvmdiag=1",
    ("1.0.291", "metal-139"): "rgpuvmdiag=1",
    ("1.0.292", "metal-140"): "rgpuvmdiag=1",
    ("1.0.293", "metal-141"): "rgpuvmdiag=1",
    ("1.0.294", "metal-142"): "rgpuvmdiag=1",
    ("1.0.295", "metal-143"): "rgpuvmdiag=1",
    ("1.0.296", "metal-144"): "rgpuvmdiag=1",
    ("1.0.297", "metal-145"): "rgpuvmdiag=1",
    ("1.0.298", "metal-146"): "rgpuvmdiag=1",
    ("1.0.299", "metal-147"): "rgpuvmdiag=1",
    ("1.0.300", "metal-148"): "rgpuvmdiag=1",
    ("1.0.301", "metal-149"): "rgpuvmdiag=1",
    ("1.0.302", "metal-150"): "rgpuvmdiag=1",
    ("1.0.303", "metal-151"): "rgpuvmdiag=1",
    ("1.0.304", "metal-152"): "rgpuvmdiag=1",
    ("1.0.305", "metal-153"): "rgpuvmdiag=1",
    ("1.0.306", "metal-154"): "rgpuvmdiag=1",
    ("1.0.307", "metal-155"): "rgpuvmdiag=1",
    ("1.0.308", "metal-156"): "rgpuvmdiag=1",
    ("1.0.309", "metal-157"): "rgpuvmdiag=1",
    ("1.0.310", "metal-158"): "rgpuvmdiag=1",
    ("1.0.311", "metal-159"): "rgpuvmdiag=1",
    ("1.0.312", "metal-160"): "rgpuvmdiag=1",
    ("1.0.313", "metal-161"): "rgpuvmdiag=1",
    ("1.0.314", "metal-162"): "rgpuvmdiag=1",
    ("1.0.315", "metal-163"): "rgpuvmdiag=1",
    ("1.0.317", "metal-165"): "rgpuvmdiag=1",
    ("1.0.322", "metal-170"): "rgpuvmdiag=1",
    ("1.0.323", "metal-171"): "rgpuvmdiag=1",
    ("1.0.324", "metal-172"): "rgpuvmdiag=1",
    ("1.0.325", "metal-173"): "rgpuvmdiag=1",
    ("1.0.326", "metal-174"): "rgpuvmdiag=1",
    ("1.0.327", "metal-175"): "rgpuvmdiag=1",
    ("1.0.328", "metal-176"): "rgpuvmdiag=1",
    ("1.0.321", "metal-169"): "rgpuvmdiag=1",
    ("1.0.320", "metal-168"): "rgpuvmdiag=1",
    ("1.0.319", "metal-167"): "rgpuvmdiag=1",
    ("1.0.318", "metal-166"): "rgpuvmdiag=1",
    ("1.0.316", "metal-164"): "rgpuvmdiag=1",
    ("1.0.261", "metal-107"): "rgpuvmdiag=1",
    ("1.0.260", "metal-106"): "rgpuvmdiag=1",
    ("1.0.259", "metal-105"): "rgpuvmdiag=1",
    ("1.0.258", "metal-104"): "rgpuvmdiag=1",
    ("1.0.257", "metal-103"): "rgpuvmdiag=1",
    ("1.0.256", "metal-102"): "rgpuvmdiag=1",
    ("1.0.255", "metal-101"): "rgpuvmdiag=1",
    ("1.0.241", "metal-087"): "rgpuvmdiag=1",
    ("1.0.240", "metal-086"): "rgpuvmdiag=1",
    ("1.0.239", "metal-085"): "rgpuvmdiag=1",
    ("1.0.238", "metal-084"): "rgpuvmdiag=1",
    ("1.0.237", "metal-083"): "rgpuvmdiag=1",
    ("1.0.236", "metal-082"): "rgpuvmdiag=1",
    ("1.0.235", "metal-081"): "rgpuvmdiag=1",
    ("1.0.234", "metal-080"): "rgpuvmdiag=1",
    ("1.0.233", "metal-079"): "rgpuvmdiag=1",
}

RESEAL_PROFILES = {
    ("1.0.188", "metal-022"): {
        "candidate_version":"1.0.188", "card_id":"metal-022",
        "prior_run_id":"cb1d0aadd8186205d867a23fe175c336",
        "record_kind":"candidate188-nonce-reseal",
        "staging_sha256":None, "card_sha256":None,
        "build_manifest_sha256":None, "prelaunch_refusal":None,
    },
    ("1.0.194", "metal-028"): {
        "candidate_version":"1.0.194", "card_id":"metal-028",
        "allow_cross_boot_reseal":True,
        "prior_run_id":"b4a41ca47553618a58bab320b3b0c2fb",
        "record_kind":"candidate194-nonce-reseal",
        "staging_sha256":"640409b94b4613a62710705c431e44115c052d4e6bcb7fa81ae7d408a92b7c9d",
        "card_sha256":"e634925aff338ddc5d6d21279b02414c4801b4ee56937eb05787b61c42c47090",
        "build_manifest_sha256":"e5e6014ba1151e1c28bad7f14c482115d5c4e48ef9282e53680bdecde94ad28d",
        "experiment_sha256":"ee39d6022e358d1edd3f5f0970389e614270a8e3b7d13954edc25c84f2de800c",
        # Verified from the immutable backup set captured by reseal token
        # 670e12c05ea14d5cb4936b2b5284d562.  The config preimage carries the
        # nonce for prior_run_id below; raw and OpenCore are the corresponding
        # byte-for-byte ESP pair before publication.
        "preimage_backup_token":"670e12c05ea14d5cb4936b2b5284d562",
        "raw_preimage_sha256":"e372943b5fdd780c7792b8c1915dcfdc655465528d19bbea00b0916e7361608f",
        "bootdisk_preimage_sha256":"7191d77d2d72edc78269a804ecbbed12310c13c6565fe2436e15dbec5ec2720f",
        "config_preimage_sha256":"6e1269eacd9277f3ac3a0e80cb35824046208371acf96bf8aabadf5b7702ca45",
        "preimage_nonce":{"run_id":"b4a41ca47553618a58bab320b3b0c2fb",
                          "nonce_lo":"0x8a615375a41ca4b4",
                          "nonce_hi":"0xfbc2b0b320b3ba58"},
        "prelaunch_refusal":{
            "boot_id":"f828eb26-9cb7-4fac-bff2-bc87515fa2ba",
            "directory":"run/metal-028-194",
            "files":{
                "agent-server-events.jsonl":"a77554adae652310415043f2a11139e35dbb7ef5886249a6a6c5d13146787824",
                "capture-sha256.json":"cd32bca5d36ab1be79d57330434e1b2397a698126bc19a871e2cae7144a38c4b",
                "critical.txt":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "events.jsonl":"1fe98291e65f1fd1343e4d553821a95494daa71ac9e46d1b2b9b87201c9046e0",
                "host-after.json":"ed791c4c9324466410aabec95f320beaadedf049b2951450873f01682cee34ef",
                "host-before.json":"ed791c4c9324466410aabec95f320beaadedf049b2951450873f01682cee34ef",
                "host-kernel-messages.json":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570",
                "manifest.json":"1bf833eb9a10ea9ec8ad05d154f4d5cf6ec0e33b13268fb9abe214b629145d6a",
                "serial.txt":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "shutdown.json":"38e0b9de817f645c4bec37c0d4a3e58baecccb040f5718dc069a72c7385a0bed",
                "verdict.json":"aded197bbba5254101c66d3f795909c66df2876821fdfe0747143e3bea24bf6d",
            },
            "manifest_copy":"run/metal-028-194-manifest.json",
            "manifest_copy_sha256":"1bf833eb9a10ea9ec8ad05d154f4d5cf6ec0e33b13268fb9abe214b629145d6a",
            "ledger":"run/used-gpu-boots/f828eb26-9cb7-4fac-bff2-bc87515fa2ba.json",
            "ledger_sha256":"5677d5419592ccf3cead52f834de1f4c412934ea3eaa6c570ee1708f1a35fab2",
            "policy":"run/one-run-qualification-authorities/f828eb26-9cb7-4fac-bff2-bc87515fa2ba/b4a41ca47553618a58bab320b3b0c2fb.policy.json",
            "policy_sha256":"c85bd0c874ec677238dd0675983bc140e3979973a323e478655bf3ca54320829",
            "activation":"run/one-run-qualification-authorities/f828eb26-9cb7-4fac-bff2-bc87515fa2ba/b4a41ca47553618a58bab320b3b0c2fb.json",
            "activation_sha256":"20f7c7d774bf2c35d5050fc1aef6fb496b3b0f2d260ee3ce4ad67f1dd51150d5",
            "run_id_file":"run/candidate194-qualification-run-id.txt",
            "run_id_file_sha256":"4fc3e52e17d3b7da95f23b59f2864c6ea2cfd9eaa873aba562396d4b5e2e644b",
        },
    },
}


def configure(version, card_id, attempt=None):
    """Select the exact reviewed candidate/card pair; defaults are 1.0.185."""
    global CANDIDATE_VERSION, CARD_ID, NUMBER, WT, CANDIDATE, DIST, IDENTITIES
    global RUN_ID_FILE, CARD
    if not re.fullmatch(r"1\.0\.((?:1[0-9]{2}|2[0-5][0-9]|2[67][0-9]|280|281|282|283|284|285|286|287|288|289|290|291|292|293|294|295|296|297|298|299|300|301|302|303|304|305|306|307|308|309|310|311|312|313|314|315|316|317|318|319|320|321|322|323|324|325|326|327|328))", version):
        raise RuntimeError("candidate version must be in the reviewed 1.0.100–1.0.328 range")
    if not re.fullmatch(r"metal-[0-9]{3}", card_id):
        raise RuntimeError("card id must be metal-NNN")
    if attempt is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}", attempt):
        raise RuntimeError("attempt must be a short identifier")
    CANDIDATE_VERSION = version
    CARD_ID = card_id
    NUMBER = version.rsplit(".", 1)[1]
    WT = VM / f"run/worktrees/candidate-{NUMBER}"
    suffix = "" if attempt is None else f"-attempt-{attempt}"
    CANDIDATE = VM / f"run/candidate-{NUMBER}{suffix}"
    DIST = VM / f"run/candidate-{NUMBER}-dist"
    IDENTITIES = VM / f"run/candidate-{NUMBER}{suffix}-build-identities.json"
    RUN_ID_FILE = VM / f"run/candidate{NUMBER}{suffix}-qualification-run-id.txt"
    CARD = ROOT / f"experiments/{card_id}.json"


configure(CANDIDATE_VERSION, CARD_ID)


def prepare_attempt_copy(attempt):
    """Prepare an isolated retry namespace from an existing build artifact."""
    source = VM / f"run/candidate-{NUMBER}"
    if CANDIDATE == source:
        return
    if CANDIDATE.exists() or IDENTITIES.exists():
        raise RuntimeError("attempt output already exists")
    if not source.is_dir():
        raise RuntimeError("base candidate artifact is missing")
    identity_path = VM / f"run/candidate-{NUMBER}-build-identities.json"
    if not identity_path.is_file():
        raise RuntimeError("base build identity record is missing")
    CANDIDATE.mkdir(parents=True)
    allowed = {"RaphaelGPU.kext", "build-manifest.json"}
    for path in source.iterdir():
        if path.name not in allowed:
            continue
        destination = CANDIDATE / path.name
        if path.is_dir():
            shutil.copytree(path, destination)
        else:
            shutil.copy2(path, destination)
    identity = json.loads(identity_path.read_text())
    identity["extracted_candidate"] = str(CANDIDATE)
    IDENTITIES.write_text(json.dumps(identity, indent=2) + "\n")
    sync_dir(IDENTITIES.parent)
    return sha_file(IDENTITIES)


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
    if pair == ("1.0.280", "metal-128") and card.get("lifecycle_test") != "supervised-qemu-quit":
        raise RuntimeError("closure card must declare its exact lifecycle action")
    exact = {
        "id": CARD_ID,
        "candidate_version": CANDIDATE_VERSION,
        "requested_diagnostic": requested_diagnostic,
        "run_probe_only_after_native_start": True,
        "critical_replay_schema": 2,
        "recovery_lease_schema": 3,
    }
    max_seconds = card.get("max_seconds")
    if type(max_seconds) is not int or not 1 <= max_seconds <= 43200:
        raise RuntimeError("candidate max_seconds must be an integer from 1 to 43200")
    if not isinstance(card, dict) or any(
            type(card.get(key)) is not type(value) or card.get(key) != value
            for key, value in exact.items()):
        raise RuntimeError("candidate card contract mismatch")
    if pair in (("1.0.184", "metal-017"), ("1.0.185", "metal-018"),
                ("1.0.186", "metal-019"), ("1.0.187", "metal-020"),
                ("1.0.188", "metal-021"), ("1.0.188", "metal-022"),
                ("1.0.189", "metal-023"), ("1.0.190", "metal-024"),
                ("1.0.191", "metal-025"), ("1.0.192", "metal-026"), ("1.0.193", "metal-027"), ("1.0.194", "metal-028"), ("1.0.195", "metal-029"), ("1.0.196", "metal-030"), ("1.0.197", "metal-031"), ("1.0.198", "metal-032"), ("1.0.199", "metal-033"), ("1.0.200", "metal-034"), ("1.0.201", "metal-035")):
        candidate_contract = {
            "critical_replay_tolerance": "terminal-prefix",
            "recovery_critical_replay_tolerance": "terminal-prefix-open",
            "conditional_diagnostic_observations": ([
                "vmid1_fault_walk", "vmid1_fault_walk_view",
                "vmid1_fault_walk_entry",
                "gdb_vmid1_wrap_vmm_prepare_original_info",
                "gdb_vmid1_wrap_vmm_prepare_native_info",
                "gdb_vmid1_prepared_root", "gdb_hub0_vmid1_reprogram1",
            ] if pair == ("1.0.191", "metal-025") else ([
                "vmid1_fault_walk", "vmid1_fault_walk_view",
                "vmid1_fault_walk_entry", "client_fault_walk",
                "client_fault_walk_view", "client_fault_walk_entry",
                "gdb_vmid1_wrap_vmm_prepare_original_info",
                "gdb_vmid1_wrap_vmm_prepare_native_info",
                "gdb_vmid1_prepared_root", "gdb_hub0_vmid1_reprogram1",
            ] + (["map_process_summary"]
                 if pair in (("1.0.193", "metal-027"), ("1.0.194", "metal-028"), ("1.0.195", "metal-029"), ("1.0.196", "metal-030"), ("1.0.197", "metal-031"), ("1.0.198", "metal-032"), ("1.0.199", "metal-033"), ("1.0.200", "metal-034"), ("1.0.201", "metal-035")) else [])
              if pair in (("1.0.192", "metal-026"),
                          ("1.0.193", "metal-027"), ("1.0.194", "metal-028"),
                          ("1.0.195", "metal-029"), ("1.0.196", "metal-030"), ("1.0.197", "metal-031"), ("1.0.198", "metal-032"), ("1.0.199", "metal-033"), ("1.0.200", "metal-034"), ("1.0.201", "metal-035")) else [
                "vmid1_fault_walk", "vmid1_fault_walk_view",
                "vmid1_fault_walk_entry",
            ])),
            "launch_options": ({
                "BOOTDISK_MODE": "custom", "NVRAM": "stock",
                "GENERIC_GRAPHICS": "off", "GDB": "on",
            } if pair in (("1.0.188", "metal-021"),
                          ("1.0.188", "metal-022"),
                          ("1.0.189", "metal-023"),
                          ("1.0.190", "metal-024"),
                          ("1.0.191", "metal-025"),
                          ("1.0.192", "metal-026"), ("1.0.193", "metal-027"), ("1.0.194", "metal-028"), ("1.0.195", "metal-029"), ("1.0.196", "metal-030"), ("1.0.197", "metal-031"), ("1.0.198", "metal-032"), ("1.0.199", "metal-033"), ("1.0.200", "metal-034"), ("1.0.201", "metal-035")) else {
                "BOOTDISK_MODE": "custom", "NVRAM": "stock",
                "GENERIC_GRAPHICS": "off",
            }),
        }
        if any(card.get(key) != value for key, value in candidate_contract.items()):
            raise RuntimeError("candidate card contract mismatch")
    if pair in (("1.0.184", "metal-017"), ("1.0.185", "metal-018")) and \
            card.get("functional_boot_arguments") != {"rgpuvmroot": "4"}:
        raise RuntimeError("candidate card contract mismatch")
    if pair in (("1.0.186", "metal-019"), ("1.0.187", "metal-020"),
                ("1.0.188", "metal-021"), ("1.0.188", "metal-022"),
                ("1.0.189", "metal-023"), ("1.0.190", "metal-024"),
                ("1.0.191", "metal-025"), ("1.0.192", "metal-026"), ("1.0.193", "metal-027"), ("1.0.194", "metal-028"), ("1.0.195", "metal-029"), ("1.0.196", "metal-030"), ("1.0.197", "metal-031"), ("1.0.198", "metal-032"), ("1.0.199", "metal-033"), ("1.0.200", "metal-034"), ("1.0.201", "metal-035")):
        candidate186_contract = {
            "functional_boot_arguments": (
                {"rgpuvmroot": "5", "rgpudump": "5000"}
                if pair in (("1.0.193", "metal-027"), ("1.0.194", "metal-028"), ("1.0.195", "metal-029"), ("1.0.196", "metal-030"), ("1.0.197", "metal-031"), ("1.0.198", "metal-032"), ("1.0.199", "metal-033"), ("1.0.200", "metal-034"), ("1.0.201", "metal-035")) else
                {"rgpuvmroot": "4", "rgpudump": "5000"}),
            "required_boot_flags": ["-liluheadless"],
            "raphael_source_sha256": (
                "e9debe05adee92e88d0a8077bc25d13ef389d00187a02886bbbb27e5b5b6834c"
                if pair == ("1.0.195", "metal-029") else
                "7047142cc2ff9b97c7f9cabf90c97e821eaf1c2b0163d295f118b08d4fe733b5"
                if pair in (("1.0.200", "metal-034"), ("1.0.201", "metal-035")) else
                "08eeb8d32d62b694cce27f62fe196e06aa6104b45555cb56fa4e56308582e3e5"
                if pair == ("1.0.199", "metal-033") else
                "21322441a50375280dad1bdffa319eca7a7bddebda004dbda23066f903e109ff"
                if pair in (("1.0.197", "metal-031"), ("1.0.198", "metal-032")) else
                "21322441a50375280dad1bdffa319eca7a7bddebda004dbda23066f903e109ff"
                if pair in (("1.0.197", "metal-031"), ("1.0.198", "metal-032"), ("1.0.199", "metal-033"), ("1.0.200", "metal-034"), ("1.0.201", "metal-035")) else
                "c798dfd66c14c5d14160141586062ea5624f5314d14604f9d12abb40945e202d"
                if pair == ("1.0.194", "metal-028") else
                "73bbfdcefa406e38d4206e1870b6dcaf96a0f8555f0795e48d83055220157e5e"
                if pair == ("1.0.193", "metal-027") else
                "e2eb4769e41af10dcbb48f315446030fdd8af0632fa5f6de8ec8f9abba630526"
                if pair == ("1.0.192", "metal-026") else
                "7515f121230fbd26e32b198bd622e106155708e4108d9def96dcc7daa9d173f3"
                if pair in (("1.0.189", "metal-023"),
                            ("1.0.190", "metal-024"),
                            ("1.0.191", "metal-025")) else
                "db511634c6d292ef3a65285e56bd5cf5f9e03cf4c20680a27b96c46a18f2e9b0"),
        }
        if any(card.get(key) != value
               for key, value in candidate186_contract.items()):
            raise RuntimeError("candidate card contract mismatch")
    CANDIDATE203_FUNCTIONAL = {
        ("1.0.203", "metal-037"): {"rgpuvmroot": "5", "rgpudump": "5000"},
        ("1.0.204", "metal-038"): {"rgpuvmroot": "5", "rgpudump": "5000"},
        ("1.0.205", "metal-039"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpumqdrestore": "1"},
        ("1.0.206", "metal-040"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpumqdrestore": "2"},
        ("1.0.207", "metal-041"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpumqdrestore": "3"},
        ("1.0.208", "metal-042"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpumqdrestore": "3"},
        ("1.0.209", "metal-043"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpumqdrestore": "3"},
        ("1.0.210", "metal-044"): {"rgpuvmroot": "5", "rgpudump": "5000"},
        ("1.0.211", "metal-045"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1"},
        ("1.0.212", "metal-046"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1"},
        ("1.0.213", "metal-047"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1"},
        ("1.0.214", "metal-048"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1"},
        ("1.0.215", "metal-049"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpucpfw": "1"},
        ("1.0.215", "metal-050"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1"},
        ("1.0.216", "metal-051"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpucpfw": "1"},
        ("1.0.216", "metal-052"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1"},
        ("1.0.217", "metal-053"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1"},
        ("1.0.218", "metal-054"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1"},
        ("1.0.218", "metal-055"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1"},
        ("1.0.218", "metal-056"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1"},
        ("1.0.218", "metal-057"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1"},
        ("1.0.218", "metal-058"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1"},
        ("1.0.218", "metal-059"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1"},
        ("1.0.218", "metal-060"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1"},
        ("1.0.218", "metal-061"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1"},
        ("1.0.218", "metal-062"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1"},
        ("1.0.218", "metal-063"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1"},
        ("1.0.219", "metal-064"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpuaddrcfg": "2"},
        ("1.0.220", "metal-065"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpuswlog": "1",
                                   "rgpuvgpr": "3"},
        ("1.0.220", "metal-066"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpuswlog": "2",
                                   "rgpuvgpr": "3"},
        ("1.0.220", "metal-067"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpuswlog": "2",
                                   "rgpuvgpr": "3"},
        ("1.0.221", "metal-068"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpugbread": "2"},
        ("1.0.222", "metal-069"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpuaddrcfg": "3"},
        ("1.0.223", "metal-070"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2"},
        ("1.0.224", "metal-071"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2"},
        ("1.0.225", "metal-072"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2"},
        ("1.0.225", "metal-073"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2"},
        ("1.0.226", "metal-074"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputilelog": "1"},
        ("1.0.227", "metal-075"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgpunotexxor": "1"},
        ("1.0.228", "metal-076"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgpunotexxor": "1"},
        ("1.0.229", "metal-077"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "1"},
    ("1.0.230", "metal-078"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2"},
    ("1.0.233", "metal-079"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1"},
    ("1.0.234", "metal-080"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1"},
    ("1.0.235", "metal-081"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1"},
    ("1.0.236", "metal-082"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1"},
    ("1.0.237", "metal-083"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnstatic": "1"},
    ("1.0.238", "metal-084"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnstatic": "1"},
    ("1.0.239", "metal-085"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnstatic": "1"},
    ("1.0.240", "metal-086"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnstatic": "1"},
    ("1.0.241", "metal-087"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnstatic": "1", "rgpuvcnsmu": "1"},
    ("1.0.242", "metal-088"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnstatic": "1", "rgpuvcnsmu": "1", "rgpuvcnreset": "1"},
    ("1.0.243", "metal-089"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnstatic": "1", "rgpuvcnsmu": "1", "rgpuvcnreset": "1"},
    ("1.0.244", "metal-090"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnstatic": "1", "rgpuvcnsmu": "1", "rgpuvcnreset": "1"},
    ("1.0.245", "metal-091"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnstatic": "1", "rgpuvcnsmu": "1", "rgpuvcnreset": "1"},
    ("1.0.246", "metal-092"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnstatic": "1", "rgpuvcnsmu": "1", "rgpuvcnreset": "1"},
    ("1.0.247", "metal-093"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnstatic": "1", "rgpuvcnsmu": "1", "rgpuvcnreset": "1"},
    ("1.0.248", "metal-094"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1"},
    ("1.0.249", "metal-095"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1"},
    ("1.0.250", "metal-096"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1"},
    ("1.0.251", "metal-097"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1"},
    ("1.0.252", "metal-098"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1"},
    ("1.0.253", "metal-099"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1"},
    ("1.0.254", "metal-100"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1"},
    ("1.0.255", "metal-101"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1"},
    ("1.0.256", "metal-102"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1"},
    ("1.0.257", "metal-103"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1"},
    ("1.0.258", "metal-104"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1"},
    ("1.0.259", "metal-105"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1"},
    ("1.0.263", "metal-109"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1"},
    ("1.0.264", "metal-110"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1"},
    ("1.0.265", "metal-111"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1"},
    ("1.0.266", "metal-112"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1"},
    ("1.0.267", "metal-113"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1"},
    ("1.0.268", "metal-114"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1"},
    ("1.0.269", "metal-115"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1"},
    ("1.0.269", "metal-116"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1"},
    ("1.0.270", "metal-117"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1"},
    ("1.0.271", "metal-118"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1"},
    ("1.0.272", "metal-119"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1"},
    ("1.0.274", "metal-121"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1"},
    ("1.0.273", "metal-120"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1"},
    ("1.0.275", "metal-122"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1"},
    ("1.0.276", "metal-123"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1"},
    ("1.0.277", "metal-124"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1"},
    ("1.0.279", "metal-126"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1"},
    ("1.0.280", "metal-127"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1"},
    ("1.0.280", "metal-128"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1"},
    ("1.0.281", "metal-129"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1"},
    ("1.0.282", "metal-130"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1"},
    ("1.0.283", "metal-131"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1"},
    ("1.0.284", "metal-132"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1"},
    ("1.0.285", "metal-133"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "31", "rgpudcntrace": "6000"},
    ("1.0.286", "metal-134"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "23", "rgpudcntrace": "6000"},
    ("1.0.287", "metal-135"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "23", "rgpudcntrace": "6000"},
    ("1.0.288", "metal-136"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "55", "rgpudcntrace": "6000"},
    ("1.0.289", "metal-137"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "55", "rgpudcntrace": "6000"},
    ("1.0.290", "metal-138"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "119", "rgpudcntrace": "6000"},
    ("1.0.291", "metal-139"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "151", "rgpudcntrace": "6000"},
    ("1.0.292", "metal-140"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "407", "rgpudcntrace": "6000"},
    ("1.0.293", "metal-141"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "407", "rgpudcntrace": "6000", "rgpudallog": "0xa3eb149cb"},
    ("1.0.294", "metal-142"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "407", "rgpudcntrace": "6000", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.295", "metal-143"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "919", "rgpudcntrace": "6000", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.296", "metal-144"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "1943", "rgpudcntrace": "6000", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.297", "metal-145"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "1943", "rgpudcntrace": "6000", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.298", "metal-146"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "1431", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.299", "metal-147"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpudcn": "1431", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.300", "metal-148"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1431", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.301", "metal-149"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.302", "metal-150"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.303", "metal-151"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1431", "rgpudmubquery": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.304", "metal-152"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1431", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.305", "metal-153"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.306", "metal-154"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1431", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.307", "metal-155"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1431", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.308", "metal-156"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1431", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.309", "metal-157"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1431", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.310", "metal-158"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1431", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.311", "metal-159"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1431", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.312", "metal-160"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1431", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.313", "metal-161"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1431", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.314", "metal-162"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1431", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.315", "metal-163"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.317", "metal-165"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcnnostutter": "1", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.318", "metal-166"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcnnostutter": "1", "rgpudcnpattern": "1", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.319", "metal-167"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcnnostutter": "1", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.320", "metal-168"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcnnostutter": "1", "rgpudcndet": "1", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.321", "metal-169"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcnnostutter": "1", "rgpudcndet": "1", "rgpuvpgwake": "1", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.322", "metal-170"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcnnostutter": "1", "rgpudcndet": "1", "rgpuvpgwake": "1", "rgpuhdmideep": "1", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.323", "metal-171"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcnnostutter": "1", "rgpudcndet": "1", "rgpuvpgwake": "1", "rgpuhdmideep": "1", "rgpuhdmiaudio": "1", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.324", "metal-172"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcnnostutter": "1", "rgpudcndet": "1", "rgpuvpgwake": "1", "rgpuhdmideep": "1", "rgpuhdmiaudio": "1", "rgpuhdmitrace": "1", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.325", "metal-173"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcnnostutter": "1", "rgpudcndet": "1", "rgpuvpgwake": "1", "rgpuhdmideep": "1", "rgpuhdmiaudio": "1", "rgpuhdmitrace": "1", "rgpuhdminativeclk": "1", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},    ("1.0.326", "metal-174"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcnnostutter": "1", "rgpudcndet": "1", "rgpuvpgwake": "1", "rgpuhdmideep": "1", "rgpuhdmiaudio": "1", "rgpuhdmitrace": "1", "rgpuhdminativeclk": "1", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},    ("1.0.327", "metal-175"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcnnostutter": "1", "rgpudcndet": "1", "rgpuvpgwake": "1", "rgpuhdmideep": "1", "rgpuhdmiaudio": "1", "rgpuhdmitrace": "1", "rgpuhdminativeclk": "1", "rgpufrlcaps": "1", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},    ("1.0.328", "metal-176"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcnnostutter": "1", "rgpudcndet": "1", "rgpuvpgwake": "1", "rgpuhdmideep": "1", "rgpuhdmiaudio": "1", "rgpuhdmitrace": "1", "rgpuhdminativeclk": "1", "rgpufrlcaps": "1", "rgpufrlclock": "1", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.316", "metal-164"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1", "rgpuvcndecfirst": "1", "rgpuvcnnodpm": "1", "rgpuvcnwptr": "1", "rgpualloclog": "1",
                                   "rgpuvcnclk": "1200", "rgpudclk": "1028", "rgpugfxclk": "2200", "rgpusmuquery": "1", "rgpuvcnpreset": "1",
                                   "rgpuhostreserve": "1", "rgpudcn": "1943", "rgpudcncolor": "1", "rgpudmubquery": "1", "rgpudisplaywake": "1", "rgpudmubreinit": "1", "rgpudmubresume": "1", "rgpudmubpsp": "1", "rgpudcntrace": "600", "rgpudallog": "0xa3eb149cb", "rgpuagdp": "1"},
    ("1.0.260", "metal-106"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcndpg": "1"},
    ("1.0.261", "metal-107"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcnstatic": "1", "rgpuvcnreset": "1"},
    ("1.0.262", "metal-108"): {"rgpuvmroot": "5", "rgpudump": "5000", "rgpugolden": "1",
                                   "rgpuhangdump": "1", "rgpunobin": "1", "rgpusdmacfg": "2",
                                   "rgputexdiag": "2", "rgpummhub": "1", "rgpuvcnfw": "1", "rgpuvcnapu": "1", "rgpuvcnsmu": "1", "rgpuvcnstatic": "1", "rgpuvcnreset": "1"},
    }
    if pair in CANDIDATE203_FUNCTIONAL:
        card_launch = dict(card.get("launch_options") or {})
        if pair in (("1.0.323", "metal-171"), ("1.0.324", "metal-172"), ("1.0.325", "metal-173"), ("1.0.326", "metal-174"), ("1.0.327", "metal-175"), ("1.0.328", "metal-176")):
            if card_launch.pop("HDMI_AUDIO", None) != "on" or card_launch.get("AUDIO") != "usb":
                raise RuntimeError("candidate HDMI audio contract mismatch")
        if (card.get("critical_replay_tolerance") != "terminal-prefix" or
                card.get("recovery_critical_replay_tolerance") != "terminal-prefix-open" or
                card.get("functional_boot_arguments") != CANDIDATE203_FUNCTIONAL[pair] or
                card.get("required_boot_flags") != ["-liluheadless"] or
                card_launch not in ({
                    "BOOTDISK_MODE": "custom", "NVRAM": "stock",
                    "GENERIC_GRAPHICS": "off", "GDB": "on"}, {
                    "BOOTDISK_MODE": "custom", "NVRAM": "stock",
                    "GENERIC_GRAPHICS": "off", "GDB": "on", "AUDIO": "usb"}) or
                not re.fullmatch(r"[0-9a-f]{64}", str(card.get("raphael_source_sha256", ""))) or
                not re.fullmatch(r"[0-9a-f]{40}", str(card.get("raphael_source_commit", "")))):
            raise RuntimeError("candidate card contract mismatch")
    if pair in (("1.0.188", "metal-021"), ("1.0.188", "metal-022"),
                ("1.0.189", "metal-023"), ("1.0.190", "metal-024"),
                ("1.0.191", "metal-025"), ("1.0.192", "metal-026"), ("1.0.193", "metal-027"), ("1.0.194", "metal-028"), ("1.0.195", "metal-029"), ("1.0.196", "metal-030"), ("1.0.197", "metal-031"), ("1.0.198", "metal-032"), ("1.0.199", "metal-033"), ("1.0.200", "metal-034"), ("1.0.201", "metal-035")):
        required = card.get("required_observations", [])
        prerequisites = card.get("prerequisites", [])
        expected_gdb = ({"gdb_vmid1_wrap_vmm_update_entries_inputs",
                         "gdb_vmid1_wrap_vmm_update_entries_native_output"}
                        if pair == ("1.0.188", "metal-021") else
                        {"gdb_vmid1_wrap_vmm_prepare_original_info",
                         "gdb_vmid1_wrap_vmm_prepare_native_info",
                         "gdb_vmid1_prepared_root", "gdb_hub0_vmid1_reprogram1"})
        observed = (card.get("conditional_diagnostic_observations", [])
                    if pair in (("1.0.191", "metal-025"),
                                ("1.0.192", "metal-026"), ("1.0.193", "metal-027"), ("1.0.194", "metal-028"), ("1.0.195", "metal-029"), ("1.0.196", "metal-030"), ("1.0.197", "metal-031"), ("1.0.198", "metal-032"), ("1.0.199", "metal-033"), ("1.0.200", "metal-034"), ("1.0.201", "metal-035")) else required)
        if (not expected_gdb.issubset(observed) or
                "gdb_debug_artifact_and_symbol_provenance_pinned" not in prerequisites):
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
    flags = command(["git", "-C", str(WT), "ls-files", "-v"]).splitlines()
    if any(line[:1].islower() or line[:1] == "S" for line in flags):
        raise RuntimeError("candidate worktree has hidden index flag")
    if command(["git", "-C", str(WT), "status", "--porcelain"]):
        raise RuntimeError("candidate worktree is dirty")


def verify_source_commit(source_commit):
    """Bind a card's source pin to a real commit and the current source bytes."""
    exact_hex(source_commit, 40, "card source commit")
    resolved = subprocess.run(
        ["git", "-C", str(WT), "rev-parse", "--verify",
         source_commit + "^{commit}"], capture_output=True, text=True,
        check=False)
    if resolved.returncode != 0 or resolved.stdout.strip() != source_commit:
        raise RuntimeError("card source commit does not exist")
    result = subprocess.run(
        ["git", "-C", str(WT), "diff", "--quiet", source_commit, "--", "src"],
        check=False)
    if result.returncode != 0:
        raise RuntimeError("candidate source differs from card source commit")


def validate_debug_symbols(manifest, builder, executable, debug_dir,
                           source_sha256, canonical_root=ROOT):
    """Authenticate the retained private debug bundle against the staged kext."""
    debug = manifest.get("debug_symbols")
    if not isinstance(debug, dict):
        raise RuntimeError("debug symbol provenance is missing")
    exact_flags = ["-O2", "-g", "-gdwarf-4"]
    if debug.get("schema") != 1 or debug.get("flags") != exact_flags:
        raise RuntimeError("debug symbol flags mismatch")
    dsym = debug_dir / "RaphaelGPU.dSYM"
    source_dir = debug_dir / "source"
    dwarf = dsym / "Contents/Resources/DWARF/RaphaelGPU"
    private_script = debug_dir / "build-kext-debug.sh"
    debug_manifest = debug_dir / "debug-manifest.json"
    for label, path in (("dSYM", dsym), ("debug source", source_dir), ("dSYM DWARF", dwarf),
                        ("private build script", private_script),
                        ("debug manifest", debug_manifest)):
        if not path.exists():
            raise RuntimeError(f"retained {label} is missing")
    try:
        before = debug["canonical_inputs_before"]
        after = debug["canonical_inputs_after"]
        private_sha = debug["private_build_script_sha256"]
        dwarf_sha = debug["dsym_dwarf_sha256"]
        executable_sha = debug["executable_sha256"]
        debug_source_sha = debug["debug_source_sha256"]
        executable_uuid = exact_hex(debug["executable_uuid"], 32,
                                    "debug executable UUID")
        dsym_uuid = exact_hex(debug["dsym_uuid"], 32, "debug dSYM UUID")
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("debug symbol provenance is malformed") from error
    if not isinstance(before, dict) or before != after:
        raise RuntimeError("canonical debug inputs changed")
    canonical_script = canonical_root / "tools/build-kext.sh"
    canonical_inputs = canonical_root / "build-support/inputs.json"
    expected_before = {
        "build_script_sha256": sha_file(canonical_script),
        "tracked_source_sha256": source_sha256,
        "inputs_sha256": sha_file(canonical_inputs),
    }
    if before != expected_before:
        raise RuntimeError("canonical debug inputs do not match repository")
    if sha_file(private_script) != private_sha:
        raise RuntimeError("private debug build script changed")
    try:
        expected_script = builder.debug_build_script(canonical_script.read_bytes())
    except (OSError, ValueError) as error:
        raise RuntimeError("canonical debug build script unavailable") from error
    if private_script.read_bytes() != expected_script:
        raise RuntimeError("private debug build script content mismatch")
    if sha_file(dwarf) != dwarf_sha:
        raise RuntimeError("debug DWARF changed")
    if sha_file(executable) != executable_sha:
        raise RuntimeError("debug executable differs from staged kext")
    if before.get("tracked_source_sha256") != source_sha256:
        raise RuntimeError("debug source provenance mismatch")
    # The debug build source includes two generated inputs in addition to
    # tracked src; authenticate both views separately.
    try:
        if builder.tree_digest(source_dir) != debug_source_sha:
            raise RuntimeError("debug source artifact changed")
        tracked = hashlib.sha256()
        for path in sorted(source_dir.rglob('*')):
            if path.is_file() and path.name not in ("BuildIdentity.hpp", "rlc_fw.h"):
                tracked.update(path.relative_to(source_dir).as_posix().encode() + b'\0' +
                               hashlib.sha256(path.read_bytes()).digest())
        if tracked.hexdigest() != source_sha256:
            raise RuntimeError("debug source provenance mismatch")
    except OSError as error:
        raise RuntimeError("debug source artifact unavailable") from error
    build_identity = source_dir / "BuildIdentity.hpp"
    firmware = source_dir / "rlc_fw.h"
    if (build_identity.read_text() !=
            '#define RGPU_BUILD_ID "' + manifest.get("build_id", "") + '"\n'):
        raise RuntimeError("debug build identity source mismatch")
    try:
        expected_firmware = gzip.decompress(
            (canonical_root / "build-support/rlc_fw.h.gz").read_bytes())
    except (OSError, EOFError, gzip.BadGzipFile) as error:
        raise RuntimeError("pinned firmware source unavailable") from error
    if firmware.read_bytes() != expected_firmware:
        raise RuntimeError("debug firmware source mismatch")
    try:
        observed_uuid = builder.verify_debug_uuids(executable, dsym)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise RuntimeError("debug UUID authentication failed") from error
    if observed_uuid != executable_uuid or observed_uuid != dsym_uuid:
        raise RuntimeError("debug UUID provenance mismatch")
    retained = json.loads(debug_manifest.read_text())
    if retained != debug:
        raise RuntimeError("retained debug manifest differs from build manifest")
    return debug


def verify_build_inputs(experiment, builder, expected_commit,
                        expected_identities_sha256, image_id,
                        card_source_sha256, card_source_commit=None, card=None):
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

    source_commit = card_source_commit or expected_commit
    if card_source_sha256 is not None and not re.fullmatch(
            r"[0-9a-f]{64}", str(card_source_sha256)):
        raise RuntimeError("card source digest is not an exact source identity")
    verify_source_commit(source_commit)
    exact = {
        "schema": 1,
        "version": CANDIDATE_VERSION,
        "source_commit": source_commit,
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

    if card_source_sha256 is not None and observed["source_sha256"] != card_source_sha256:
        raise RuntimeError("candidate source differs from its experiment card")
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
    launch_options = card.get("launch_options") if isinstance(card, dict) else None
    if (isinstance(launch_options, dict) and launch_options.get("GDB") == "on") or (
            CANDIDATE_VERSION, CARD_ID) in (
            ("1.0.188", "metal-021"), ("1.0.189", "metal-023"),
            ("1.0.190", "metal-024"), ("1.0.191", "metal-025"),
            ("1.0.192", "metal-026"), ("1.0.193", "metal-027"), ("1.0.194", "metal-028"), ("1.0.195", "metal-029"), ("1.0.196", "metal-030"), ("1.0.197", "metal-031"), ("1.0.198", "metal-032"), ("1.0.199", "metal-033"), ("1.0.200", "metal-034"), ("1.0.201", "metal-035"), ("1.0.203", "metal-037"), ("1.0.204", "metal-038"), ("1.0.205", "metal-039"), ("1.0.206", "metal-040")):
        validate_debug_symbols(manifest, builder, executable,
                               DIST / "debug-symbols",
                               card_source_sha256)

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
        # The reviewed producer quiesce (critical-transport.py) needs its boot
        # argument whenever the card selects it; the name contains a digit, so
        # it cannot travel through functional_boot_arguments.
        if "critical_replay_quiesce" in card:
            updates["rgpucr2quiesce"] = "1"
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


def card_managed_boot_argument_keys(cards_dir=None):
    """Keys any experiment card sets through functional_boot_arguments."""
    keys = set()
    for path in sorted((cards_dir or ROOT / "experiments").glob("metal-*.json")):
        try:
            other = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        functional = other.get("functional_boot_arguments") if isinstance(other, dict) else None
        if isinstance(functional, dict):
            keys.update(key for key in functional if isinstance(key, str))
    return keys


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
    # A previous card's functional argument (candidate 209 left rgpumqdrestore=3
    # in the live config) must not leak into a card that does not set it: drop
    # every key any experiment card manages unless this card re-adds it.
    stale = card_managed_boot_argument_keys() - set(updates)
    words = [word for word in old_words
             if word.split("=", 1)[0] not in updates and
             word.split("=", 1)[0] not in flags and
             word.split("=", 1)[0] not in stale]
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


def validate_reseal_preimages(paths, expected):
    """Refuse before publication unless every named live preimage is exact."""
    if set(paths) != set(expected) or any(
            not re.fullmatch(r"[0-9a-f]{64}", str(expected.get(name, ""))) or
            sha_file(path) != expected[name] for name, path in paths.items()):
        raise RuntimeError("candidate 188 reseal preimage changed")


def validate_nonce_only_reseal(original, replacement, old_run_id, new_run_id):
    """Prove that a prepared config changes only the two recovery nonce words."""
    experiment = load_module("reseal_experiment", ROOT / "tools/experiment.py")
    old_lo, old_hi = experiment.recovery_nonce_words(old_run_id)
    new_lo, new_hi = experiment.recovery_nonce_words(new_run_id)
    if old_run_id == new_run_id:
        raise RuntimeError("candidate 188 reseal requires a fresh run ID")
    copies = []
    for config, lo, hi in ((original, old_lo, old_hi),
                           (replacement, new_lo, new_hi)):
        try:
            value = copy.deepcopy(config)
            nvram = value["NVRAM"]["Add"][experiment.BOOT_GUID]
            words = nvram["boot-args"].split()
            switches = dict(word.split("=", 1) for word in words if "=" in word)
            if (switches.get("rgpurnlo") != f"0x{lo:x}" or
                    switches.get("rgpurnhi") != f"0x{hi:x}"):
                raise RuntimeError("nonce mismatch")
            nvram["boot-args"] = " ".join(word for word in words
                if word.split("=", 1)[0] not in ("rgpurnlo", "rgpurnhi"))
            copies.append(value)
        except (KeyError, TypeError, ValueError, RuntimeError):
            raise RuntimeError("candidate 188 reseal is not nonce-only") from None
    if copies[0] != copies[1]:
        raise RuntimeError("candidate 188 reseal is not nonce-only")


def rollback_reseal(rows, published):
    """Restore exact hard-linked preimages for a partially published reseal."""
    errors = []
    for name, target, backup in rows:
        try:
            if published.get(name) and Path(backup).exists():
                os.replace(backup, target)
            elif Path(backup).exists():
                Path(backup).unlink()
        except BaseException as error:
            errors.append(f"{name}:{type(error).__name__}:{error}")
    if errors:
        raise RuntimeError("candidate 188 reseal rollback incomplete: " + ";".join(errors))


def reseal_profile():
    """Select one explicitly reviewed nonce-only reseal, never an arbitrary card."""
    profile = RESEAL_PROFILES.get((CANDIDATE_VERSION, CARD_ID))
    if profile is None:
        raise RuntimeError("reseal requires an exact reviewed candidate/card pair")
    return copy.deepcopy(profile)


def validate_reseal_profile_preimages(profile, raw_sha256, bootdisk_sha256,
                                      config_sha256):
    """Keep CLI preimage arguments bound to the reviewed backup set."""
    for value, key, label in (
            (raw_sha256, "raw_preimage_sha256", "raw preimage"),
            (bootdisk_sha256, "bootdisk_preimage_sha256", "bootdisk preimage"),
            (config_sha256, "config_preimage_sha256", "config preimage")):
        if profile.get(key) is not None and value != profile[key]:
            raise RuntimeError(f"reseal {label} is not the reviewed value")


def validate_prelaunch_refusal(profile, staging):
    """Bind candidate 194's reseal to its immutable no-launch refusal evidence."""
    expected = profile.get("prelaunch_refusal")
    if expected is None:
        return None
    try:
        if (profile.get("experiment_sha256") is not None and
                sha_file(ROOT/"tools/experiment.py") != profile["experiment_sha256"]):
            raise RuntimeError
        failed = VM / expected["directory"]
        entries = list(failed.iterdir())
        if any(not path.is_file() or path.is_symlink() for path in entries):
            raise RuntimeError
        files = {path.name:path for path in entries}
        if (set(files) != set(expected["files"]) or
                any(sha_file(files[name]) != digest
                    for name,digest in expected["files"].items())):
            raise RuntimeError
        if "supervision.json" in files:
            raise RuntimeError
        manifest = json.loads(files["manifest.json"].read_text())
        verdict = json.loads(files["verdict.json"].read_text())
        if json.loads(files["shutdown.json"].read_text()) is not None:
            raise RuntimeError
        if (files["serial.txt"].read_bytes() != b"" or
                files["critical.txt"].read_bytes() != b""):
            raise RuntimeError
        prior_run_id = profile["prior_run_id"]
        identity = {
            "run_id":prior_run_id,
            "source_commit":staging["source_commit"],
            "source_sha256":staging["source_sha256"],
            "build_id":staging["build_id"],
            "binary_sha256":staging["executable_sha256"],
            "info_sha256":staging["info_manifest_sha256"],
        }
        if (staging.get("candidate_version") != profile["candidate_version"] or
                manifest.get("spec", {}).get("candidate_version") !=
                    profile["candidate_version"] or
                staging.get("run_id") != prior_run_id or
                any(manifest.get(key) != value for key,value in identity.items())):
            raise RuntimeError
        if (manifest.get("source_clean") is not True or
                verdict.get("valid") is not False or
                verdict.get("verdict") != "INVALID" or
                verdict.get("termination_reason") !=
                    "ValueError: admission refused: source_clean" or
                verdict.get("error") != verdict.get("termination_reason") or
                verdict.get("warm_reuse") != "not-attempted"):
            raise RuntimeError
        build_path = CANDIDATE / "build-manifest.json"
        if sha_file(build_path) != profile["build_manifest_sha256"]:
            raise RuntimeError
        build = json.loads(build_path.read_text())
        build_identity = {
            "version":profile["candidate_version"],
            "source_commit":staging["source_commit"],
            "source_sha256":staging["source_sha256"],
            "build_id":staging["build_id"],
            "executable_sha256":staging["executable_sha256"],
        }
        if any(build.get(key) != value for key,value in build_identity.items()):
            raise RuntimeError
        for path_key, digest_key in (("manifest_copy", "manifest_copy_sha256"),
                                     ("policy", "policy_sha256"),
                                     ("activation", "activation_sha256"),
                                     ("run_id_file", "run_id_file_sha256")):
            if path_key in expected and sha_file(VM/expected[path_key]) != expected[digest_key]:
                raise RuntimeError
        ledger_path = VM / expected["ledger"]
        if sha_file(ledger_path) != expected["ledger_sha256"]:
            raise RuntimeError
        ledger = json.loads(ledger_path.read_text())
        if (ledger.get("schema") != 2 or
                ledger.get("boot_id") != expected["boot_id"] or
                any(row.get("run_id") == prior_run_id
                    for row in ledger.get("launches", []))):
            raise RuntimeError
    except (KeyError, TypeError, ValueError, OSError, RuntimeError,
            json.JSONDecodeError):
        raise RuntimeError("candidate 194 prelaunch refusal proof changed") from None
    return {
        "reason":"source_clean", "prior_run_id":prior_run_id,
        "qemu_started":False, "ledger_consumed":False,
        "failed_output":expected["directory"],
        "failed_manifest_sha256":expected["files"]["manifest.json"],
        "failed_verdict_sha256":expected["files"]["verdict.json"],
        "ledger_sha256":expected["ledger_sha256"],
        "policy_sha256":expected["policy_sha256"],
        "activation_sha256":expected["activation_sha256"],
        "source_sha256":staging["source_sha256"],
        "build_id":staging["build_id"],
        "executable_sha256":staging["executable_sha256"],
    }


def validate_fresh_reseal_run_id(run_id, boot_id, record_path, prior_run_id=None):
    """Refuse a nonce already consumed or carrying another authority/output."""
    if run_id == prior_run_id:
        raise RuntimeError("reseal requires a fresh run ID")
    collisions = [Path(record_path), VM/f"run/launch-pending/{run_id}"]
    authority = VM/f"run/one-run-qualification-authorities/{boot_id}"
    collisions += [authority/(run_id+".policy.json"), authority/(run_id+".json")]
    if any(path.exists() for path in collisions):
        raise RuntimeError("reseal requires a fresh run ID without existing authority")
    try:
        for ledger_path in (VM/"run/used-gpu-boots").glob("*.json"):
            ledger = json.loads(ledger_path.read_text())
            if any(row.get("run_id") == run_id for row in ledger.get("launches", [])):
                raise RuntimeError
    except (AttributeError, TypeError, ValueError, OSError, json.JSONDecodeError,
            RuntimeError):
        raise RuntimeError("reseal requires a fresh run ID without ledger use") from None


def validate_reseal_boot_identity(profile, expected_boot_id):
    """Allow candidate 194's reviewed refusal to be resealed only after reboot."""
    if not profile.get("allow_cross_boot_reseal"):
        return
    refusal = profile.get("prelaunch_refusal") or {}
    historical_boot_id = refusal.get("boot_id")
    if not historical_boot_id or expected_boot_id == historical_boot_id:
        raise RuntimeError("reseal requires a fresh cross-boot identity")
    if Path("/proc/sys/kernel/random/boot_id").read_text().strip() != expected_boot_id:
        raise RuntimeError("reseal boot ID is not the current host boot")


def reseal_authority(profile, boot_id, run_id, prelaunch_refusal,
                     prior_run_id=None):
    """Describe fresh launch authority separately from historical refusal evidence."""
    if not profile.get("allow_cross_boot_reseal"):
        raise RuntimeError("reseal authority is not a reviewed cross-boot reseal")
    historical_boot_id = (profile.get("prelaunch_refusal") or {}).get("boot_id")
    if not historical_boot_id or boot_id == historical_boot_id:
        raise RuntimeError("reseal authority requires a fresh cross-boot identity")
    exact_hex(run_id, 32, "run ID")
    if prior_run_id is not None and run_id == prior_run_id:
        raise RuntimeError("reseal authority requires a fresh run ID")
    if not isinstance(prelaunch_refusal, dict):
        raise RuntimeError("reseal authority requires historical refusal evidence")
    return {
        "cross_boot_reseal": True,
        "authority_boot_id": boot_id,
        "authority_run_id": run_id,
        "authorizes_launch": True,
        "historical_prelaunch_refusal": copy.deepcopy(prelaunch_refusal),
    }


def reseal_candidate(expected_commit, expected_boot_id, expected_card_sha256,
                     run_id, image_id, expected_staging_sha256,
                     expected_raw_sha256, expected_bootdisk_sha256,
                     expected_config_sha256):
    """Reseal one reviewed candidate for a fresh nonce; preserve original staging."""
    profile = reseal_profile()
    if (profile.get("prelaunch_refusal") is not None and
            expected_boot_id != profile["prelaunch_refusal"]["boot_id"]):
        if not profile.get("allow_cross_boot_reseal"):
            raise RuntimeError("reseal boot ID is not the reviewed prelaunch boot")
        validate_reseal_boot_identity(profile, expected_boot_id)
    exact_hex(run_id, 32, "run ID")
    exact_hex(expected_commit, 40, "coordinator commit")
    for value, label in ((expected_staging_sha256, "staging digest"),
                         (expected_raw_sha256, "raw preimage"),
                         (expected_bootdisk_sha256, "bootdisk preimage"),
                         (expected_config_sha256, "config preimage")):
        exact_hex(value, 64, label)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(image_id or "")):
        raise RuntimeError("Docker image must be an exact sha256 identity")
    if ROOT.resolve() != Path(command(["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"])).resolve():
        raise RuntimeError("reseal tool is outside its repository")
    if (command(["git", "-C", str(ROOT), "rev-parse", "HEAD"]) != expected_commit or
            command(["git", "-C", str(ROOT), "status", "--porcelain"])):
        raise RuntimeError("reseal coordinator worktree is not the reviewed clean commit")
    if (profile.get("card_sha256") is not None and
            expected_card_sha256 != profile["card_sha256"]):
        raise RuntimeError("reseal card digest is not the reviewed value")
    if (profile.get("staging_sha256") is not None and
            expected_staging_sha256 != profile["staging_sha256"]):
        raise RuntimeError("reseal staging digest is not the reviewed value")
    validate_reseal_profile_preimages(
        profile, expected_raw_sha256, expected_bootdisk_sha256,
        expected_config_sha256)
    card = validate_card(CARD.read_bytes(), expected_card_sha256)
    if command(["docker", "image", "inspect", "--format", "{{.Id}}", image_id]) != image_id:
        raise RuntimeError("Docker image identity changed")
    experiment = load_module(f"candidate{NUMBER}_reseal_experiment", ROOT / "tools/experiment.py")
    staging_path = CANDIDATE / "staging.json"
    if sha_file(staging_path) != expected_staging_sha256:
        raise RuntimeError(f"candidate {NUMBER} staging record changed")
    staging = json.loads(staging_path.read_text())
    prelaunch_proof = validate_prelaunch_refusal(profile, staging)
    bundle = CANDIDATE / "RaphaelGPU.kext"
    if (staging.get("candidate_version") != profile["candidate_version"] or
            staging.get("run_id") != profile["prior_run_id"] or
            (profile.get("prelaunch_refusal") is not None and
             staging.get("image_id") != image_id) or
            sha_file(bundle/"Contents/MacOS/RaphaelGPU") != staging.get("executable_sha256") or
            sha_file(bundle/"Contents/Info.plist") != staging.get("info_manifest_sha256")):
        raise RuntimeError(f"candidate {NUMBER} artifact differs from its staging record")
    build_root = Path(staging.get("worktree", WT))
    if (command(["git", "-C", str(build_root), "rev-parse", "HEAD"]) !=
            staging.get("source_commit") or
            command(["git", "-C", str(build_root), "status", "--porcelain"])):
        raise RuntimeError(f"candidate {NUMBER} build worktree provenance changed")
    build_manifest = json.loads((CANDIDATE / "build-manifest.json").read_text())
    builder = load_module(f"candidate{NUMBER}_reseal_builder",
                          build_root / "tools/build-release.py")
    validate_debug_symbols(
        build_manifest, builder, bundle / "Contents/MacOS/RaphaelGPU",
        DIST / "debug-symbols", staging["source_sha256"], build_root)
    record_dir = VM / f"run/candidate-{NUMBER}-reseals"
    record_path = record_dir / (run_id + ".json")
    validate_fresh_reseal_run_id(
        run_id, expected_boot_id, record_path, profile["prior_run_id"])
    raw_image, bootdisk, config_path = (VM/"run/oc-raw.img", VM/"OpenCore.qcow2", VM/"config.plist")
    expected_preimages = {"raw":expected_raw_sha256, "boot":expected_bootdisk_sha256,
                          "config":expected_config_sha256}
    paths = {"raw":raw_image, "boot":bootdisk, "config":config_path}
    token = uuid.uuid4().hex
    private_raw = VM/f"run/.candidate{NUMBER}-reseal-{token}.raw"
    candidate_qcow = VM/f".OpenCore-candidate{NUMBER}-reseal-{token}.qcow2"
    verify_raw = VM/f"run/.candidate{NUMBER}-reseal-verify-{token}.raw"
    config_temp = VM/f".config-candidate{NUMBER}-reseal-{token}.plist"
    backups = {name:path.with_name(path.name+f".backup-reseal-{token}")
               for name,path in paths.items()}
    published = {name:False for name in paths}
    with (VM/"run/experiment.lock").open("a") as experiment_lock:
      fcntl.flock(experiment_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
      with (VM/"run/redeploy.lock").open("a") as media_lock:
        fcntl.flock(media_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if Path("/proc/sys/kernel/random/boot_id").read_text().strip() != expected_boot_id:
            raise RuntimeError("reseal boot authority changed")
        if active_or_pending_vm(): raise RuntimeError("active or pending VM prevents reseal")
        prelaunch_proof = validate_prelaunch_refusal(profile, staging)
        validate_fresh_reseal_run_id(
            run_id, expected_boot_id, record_path, profile["prior_run_id"])
        validate_reseal_preimages(paths, expected_preimages)
        try:
            original_bytes, staged_bytes, boot_args, nonce_lo, nonce_hi = \
                make_staged_config(experiment, card, run_id)
            xml = original_bytes.index(b"<?xml"); staged_xml = staged_bytes.index(b"<?xml")
            validate_nonce_only_reseal(plistlib.loads(original_bytes[xml:]),
                                       plistlib.loads(staged_bytes[staged_xml:]),
                                       staging["run_id"], run_id)
            shutil.copyfile(raw_image, private_raw)
            experiment.stage_image(private_raw, bundle, staged_bytes)
            qconvert(image_id, private_raw, "raw", candidate_qcow, "qcow2")
            qconvert(image_id, candidate_qcow, "qcow2", verify_raw, "raw")
            intended = dict(binary_sha256=staging["executable_sha256"],
                            info_sha256=staging["info_manifest_sha256"],
                            config_sha256=sha_bytes(staged_bytes))
            for image in (private_raw, verify_raw):
                errors = experiment.validate_identity(intended, experiment.image_files(image))
                if errors: raise RuntimeError("resealed media readback failed: "+",".join(errors))
            validate_reseal_preimages(paths, expected_preimages)
            for path in (private_raw, candidate_qcow):
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
            for name,path in paths.items(): os.link(path, backups[name])
            write_synced_exclusive(config_temp, staged_bytes)
            validate_reseal_preimages(paths, expected_preimages)
            armed_replace(private_raw, raw_image, published, "raw")
            armed_replace(candidate_qcow, bootdisk, published, "boot")
            armed_replace(config_temp, config_path, published, "config")
            errors = experiment.validate_identity(intended, experiment.image_files(raw_image))
            if errors or sha_file(config_path) != intended["config_sha256"]:
                raise RuntimeError("published reseal raw/config readback failed")
            verify_raw.unlink(missing_ok=True)
            qconvert(image_id, bootdisk, "qcow2", verify_raw, "raw")
            errors = experiment.validate_identity(intended, experiment.image_files(verify_raw))
            if errors: raise RuntimeError("published reseal qcow readback failed: "+",".join(errors))
            sync_dir(VM); sync_dir(VM/"run")
            record_dir.mkdir(parents=True, exist_ok=True)
            record = {"schema":1,"kind":profile["record_kind"],
                "boot_id":expected_boot_id,"run_id":run_id,"prior_run_id":staging["run_id"],
                "coordinator_commit":expected_commit,
                "experiment_card_sha256":expected_card_sha256,
                "image_id":image_id,
                "candidate_staging_sha256":expected_staging_sha256,
                "preimages":expected_preimages,"boot_args":boot_args,
                "nonce_lo":nonce_lo,"nonce_hi":nonce_hi,
                "binary_sha256":intended["binary_sha256"],
                "info_sha256":intended["info_sha256"],
                "config_sha256":intended["config_sha256"],
                "raw_sha256":sha_file(raw_image),"bootdisk_sha256":sha_file(bootdisk),
                "backups":{name:str(path) for name,path in backups.items()}}
            if prelaunch_proof is not None:
                record["prelaunch_refusal"] = prelaunch_proof
                record.update(reseal_authority(
                    profile, expected_boot_id, run_id, prelaunch_proof,
                    prior_run_id=staging["run_id"]))
            write_synced_exclusive(record_path, json.dumps(record, indent=2)+"\n")
            sync_dir(record_dir)
            return record
        except BaseException:
            rollback_reseal([(name,paths[name],backups[name]) for name in paths], published)
            sync_dir(VM); sync_dir(VM/"run")
            raise
        finally:
            for path in (private_raw,candidate_qcow,verify_raw,config_temp): path.unlink(missing_ok=True)


def reseal_candidate188(*args, **kwargs):
    """Compatibility entry point for the historical candidate-188 reseal."""
    return reseal_candidate(*args, **kwargs)


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
        image_id, card.get("raphael_source_sha256"),
        card.get("raphael_source_commit"), card=card)
    candidate186 = (CANDIDATE_VERSION, CARD_ID) in (
        ("1.0.186", "metal-019"), ("1.0.187", "metal-020"),
        ("1.0.188", "metal-021"), ("1.0.189", "metal-023"),
        ("1.0.190", "metal-024"), ("1.0.191", "metal-025"),
        ("1.0.192", "metal-026"), ("1.0.193", "metal-027"), ("1.0.194", "metal-028"), ("1.0.195", "metal-029"), ("1.0.196", "metal-030"), ("1.0.197", "metal-031"), ("1.0.198", "metal-032"), ("1.0.199", "metal-033"), ("1.0.200", "metal-034"), ("1.0.201", "metal-035"), ("1.0.203", "metal-037"), ("1.0.204", "metal-038"), ("1.0.205", "metal-039"), ("1.0.206", "metal-040"), ("1.0.207", "metal-041"), ("1.0.208", "metal-042"), ("1.0.209", "metal-043"), ("1.0.210", "metal-044"), ("1.0.211", "metal-045"), ("1.0.212", "metal-046"), ("1.0.213", "metal-047"), ("1.0.214", "metal-048"), ("1.0.215", "metal-049"), ("1.0.215", "metal-050"), ("1.0.216", "metal-051"), ("1.0.216", "metal-052"), ("1.0.217", "metal-053"), ("1.0.218", "metal-054"), ("1.0.218", "metal-055"), ("1.0.218", "metal-056"), ("1.0.218", "metal-057"), ("1.0.218", "metal-058"),
                               ("1.0.218", "metal-059"), ("1.0.218", "metal-060"),
                               ("1.0.218", "metal-061"), ("1.0.218", "metal-062"),
                               ("1.0.218", "metal-063"), ("1.0.219", "metal-064"),
                               ("1.0.220", "metal-065"), ("1.0.220", "metal-066"),
                               ("1.0.220", "metal-067"), ("1.0.221", "metal-068"),
                               ("1.0.222", "metal-069"), ("1.0.223", "metal-070"),
                               ("1.0.224", "metal-071"), ("1.0.225", "metal-072"),
                               ("1.0.225", "metal-073"), ("1.0.226", "metal-074"), ("1.0.227", "metal-075"), ("1.0.228", "metal-076"), ("1.0.229", "metal-077"), ("1.0.230", "metal-078"), ("1.0.269", "metal-115"), ("1.0.269", "metal-116"), ("1.0.270", "metal-117"), ("1.0.271", "metal-118"), ("1.0.272", "metal-119"), ("1.0.273", "metal-120"), ("1.0.274", "metal-121"), ("1.0.275", "metal-122"), ("1.0.276", "metal-123"), ("1.0.277", "metal-124"), ("1.0.279", "metal-126"), ("1.0.280", "metal-127"), ("1.0.280", "metal-128"), ("1.0.281", "metal-129"), ("1.0.282", "metal-130"), ("1.0.283", "metal-131"), ("1.0.284", "metal-132"), ("1.0.285", "metal-133"), ("1.0.286", "metal-134"), ("1.0.287", "metal-135"), ("1.0.288", "metal-136"), ("1.0.289", "metal-137"), ("1.0.290", "metal-138"), ("1.0.291", "metal-139"), ("1.0.292", "metal-140"), ("1.0.293", "metal-141"), ("1.0.294", "metal-142"), ("1.0.295", "metal-143"), ("1.0.296", "metal-144"), ("1.0.297", "metal-145"), ("1.0.298", "metal-146"), ("1.0.299", "metal-147"), ("1.0.300", "metal-148"), ("1.0.301", "metal-149"), ("1.0.302", "metal-150"), ("1.0.303", "metal-151"), ("1.0.304", "metal-152"), ("1.0.305", "metal-153"), ("1.0.306", "metal-154"), ("1.0.307", "metal-155"), ("1.0.308", "metal-156"), ("1.0.309", "metal-157"), ("1.0.310", "metal-158"), ("1.0.311", "metal-159"), ("1.0.312", "metal-160"), ("1.0.313", "metal-161"), ("1.0.314", "metal-162"), ("1.0.315", "metal-163"), ("1.0.316", "metal-164"), ("1.0.317", "metal-165"), ("1.0.318", "metal-166"), ("1.0.319", "metal-167"), ("1.0.320", "metal-168"), ("1.0.321", "metal-169"), ("1.0.322", "metal-170"), ("1.0.323", "metal-171"), ("1.0.324", "metal-172"), ("1.0.325", "metal-173"), ("1.0.326", "metal-174"), ("1.0.327", "metal-175"), ("1.0.328", "metal-176"), ("1.0.268", "metal-114"), ("1.0.267", "metal-113"), ("1.0.266", "metal-112"), ("1.0.265", "metal-111"), ("1.0.264", "metal-110"), ("1.0.263", "metal-109"), ("1.0.262", "metal-108"), ("1.0.261", "metal-107"), ("1.0.260", "metal-106"), ("1.0.259", "metal-105"), ("1.0.258", "metal-104"), ("1.0.257", "metal-103"), ("1.0.256", "metal-102"), ("1.0.255", "metal-101"), ("1.0.254", "metal-100"), ("1.0.253", "metal-099"), ("1.0.252", "metal-098"), ("1.0.251", "metal-097"), ("1.0.250", "metal-096"), ("1.0.249", "metal-095"), ("1.0.248", "metal-094"), ("1.0.247", "metal-093"), ("1.0.246", "metal-092"), ("1.0.245", "metal-091"), ("1.0.244", "metal-090"), ("1.0.243", "metal-089"), ("1.0.242", "metal-088"), ("1.0.241", "metal-087"), ("1.0.240", "metal-086"), ("1.0.239", "metal-085"), ("1.0.238", "metal-084"), ("1.0.237", "metal-083"), ("1.0.236", "metal-082"), ("1.0.235", "metal-081"), ("1.0.234", "metal-080"), ("1.0.233", "metal-079"))
    if candidate186 and identities["source_sha256"] != card["raphael_source_sha256"]:
        raise RuntimeError("candidate source differs from its experiment card")
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
    parser.add_argument("--attempt", help="prepare an isolated retry artifact namespace")
    parser.add_argument("--lilu-bundle", type=Path)
    parser.add_argument("--expected-lilu-executable-sha256")
    parser.add_argument("--expected-lilu-info-sha256")
    parser.add_argument("--expected-lilu-build-manifest-sha256")
    parser.add_argument("--reseal-run-id")
    parser.add_argument("--expected-staging-sha256")
    parser.add_argument("--expected-raw-sha256")
    parser.add_argument("--expected-bootdisk-sha256")
    parser.add_argument("--expected-config-sha256")
    args = parser.parse_args()
    if not args.execute:
        parser.error("refusing mutation without the reviewed --execute flag")
    configure(args.candidate_version, args.card_id, args.attempt)
    if args.reseal_run_id:
        result = reseal_candidate(
            args.expected_commit, args.expected_boot_id,
            args.expected_card_sha256, args.reseal_run_id, args.image_id,
            args.expected_staging_sha256, args.expected_raw_sha256,
            args.expected_bootdisk_sha256, args.expected_config_sha256)
        print(json.dumps(result, indent=2))
        return
    stage(args.expected_commit, args.expected_boot_id,
          args.expected_card_sha256, args.expected_identities_sha256,
          args.image_id, args.lilu_bundle,
          args.expected_lilu_executable_sha256,
          args.expected_lilu_info_sha256,
          args.expected_lilu_build_manifest_sha256)


if __name__ == "__main__":
    main()
