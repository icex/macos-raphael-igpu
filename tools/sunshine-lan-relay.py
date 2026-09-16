#!/usr/bin/env python3
"""Small, user-level Sunshine LAN relay.

The relay deliberately has no privileged networking or guest control.  It
forwards Sunshine's TCP/UDP port family from one explicitly selected local
IPv4 address to an explicitly selected Docker IPv4 address, and exits when the
identified container is no longer the same running instance.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
from datetime import datetime, timezone
import ipaddress
import json
import math
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from typing import Any

CID_RE = re.compile(r"[0-9a-f]{64}\Z")
TCP_OFFSETS = (-5, 0, 21)
UDP_OFFSETS = (9, 10, 11)
WEB_OFFSET = 1


def full_cid(value: str) -> str:
    value = value.strip().lower()
    if not CID_RE.fullmatch(value):
        raise ValueError("--cid must be a full 64-digit hexadecimal Docker ID")
    return value


def ipv4(value: str, option: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError(f"{option} must be an IPv4 address") from exc
    if address.version != 4 or address.is_unspecified:
        raise ValueError(f"{option} must be an explicit, non-wildcard IPv4 address")
    return str(address)


def parse_started(value: str) -> tuple[str, float]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Docker StartedAt is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("Docker StartedAt has no timezone")
    epoch = parsed.timestamp()
    if epoch <= 0 or epoch > time.time() + 2:
        raise ValueError("Docker StartedAt is invalid or in the future")
    return value, epoch


def inspect_identity(cid: str, runner=subprocess.run) -> dict[str, Any]:
    """Read only the exact Docker identity fields used by supervision."""
    fmt = '{"Id":{{json .Id}},"StartedAt":{{json .State.StartedAt}},"Running":{{json .State.Running}},"Networks":{{json .NetworkSettings.Networks}}}'
    result = runner(["docker", "inspect", "--format", fmt, cid],
                    text=True, capture_output=True, timeout=3, check=False)
    if result.returncode:
        raise RuntimeError("docker inspect failed")
    try:
        data = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("docker inspect returned malformed identity") from exc
    if data.get("Id") != cid or data.get("Running") is not True:
        raise RuntimeError("identified container is not the same running instance")
    started_at, epoch = parse_started(str(data.get("StartedAt", "")))
    networks = data.get("Networks")
    if not isinstance(networks, dict):
        raise RuntimeError("docker inspect returned malformed network identity")
    ips = {str(v.get("IPAddress")) for v in networks.values()
           if isinstance(v, dict) and v.get("IPAddress")}
    return {"cid": cid, "started_at": started_at, "started_epoch": epoch,
            "network_ips": ips}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n")
    temporary.replace(path)


class TcpRelay:
    def __init__(self, target: tuple[str, int], connections: set[asyncio.Task[Any]]):
        self.target = target
        self.connections = connections

    async def __call__(self, reader: asyncio.StreamReader,
                       writer: asyncio.StreamWriter) -> None:
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(*self.target)
        except Exception:
            writer.close()
            await writer.wait_closed()
            return
        async def pipe(source: asyncio.StreamReader, sink: asyncio.StreamWriter) -> None:
            try:
                while data := await source.read(256 * 1024):
                    sink.write(data)
                    await sink.drain()
            except (ConnectionError, asyncio.IncompleteReadError, OSError):
                pass

        tasks = {asyncio.create_task(pipe(reader, upstream_writer)),
                 asyncio.create_task(pipe(upstream_reader, writer))}
        self.connections.update(tasks)
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (ConnectionError, OSError):
            pass
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            upstream_writer.close()
            writer.close()
            await asyncio.gather(upstream_writer.wait_closed(), writer.wait_closed(),
                                 return_exceptions=True)
            self.connections.difference_update(tasks)


class UdpRelay(asyncio.DatagramProtocol):
    def __init__(self, loop: asyncio.AbstractEventLoop, target: tuple[str, int],
                 idle_seconds: float):
        self.loop, self.target, self.idle_seconds = loop, target, idle_seconds
        self.transport: asyncio.DatagramTransport | None = None
        self.peers: dict[tuple[str, int], tuple[asyncio.DatagramTransport, float]] = {}
        self.pending: dict[tuple[str, int], asyncio.Task[Any]] = {}
        self.pending_data: dict[tuple[str, int], deque[bytes]] = {}

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        current = self.peers.get(addr)
        if current is None:
            # Endpoint creation is asynchronous; the first datagram is retained
            # until the connected per-client socket exists.
            if addr in self.pending:
                queued = self.pending_data[addr]
                if len(queued) < 64:
                    queued.append(data)
                return
            if len(self.pending) < 512:
                self.pending_data[addr] = deque([data])
                self.pending[addr] = self.loop.create_task(self._open_peer(addr))
            return
        transport, _ = current
        transport.sendto(data)
        self.peers[addr] = (transport, time.monotonic())

    async def _open_peer(self, addr: tuple[str, int]) -> None:
        try:
            protocol = _UdpPeer(self, addr)
            transport, _ = await self.loop.create_datagram_endpoint(
                lambda: protocol, remote_addr=self.target)
            self.peers[addr] = (transport, time.monotonic())
            for data in self.pending_data.pop(addr, ()):
                transport.sendto(data)
        except OSError:
            self.pending_data.pop(addr, None)
        finally:
            self.pending.pop(addr, None)

    def from_target(self, data: bytes, addr: tuple[str, int]) -> None:
        if self.transport is not None:
            self.transport.sendto(data, addr)

    async def reap(self) -> None:
        while True:
            await asyncio.sleep(min(5.0, self.idle_seconds))
            await self.reap_once()

    async def reap_once(self) -> None:
        """Run one idle sweep (also useful for deterministic tests)."""
        now = time.monotonic()
        for addr, (transport, touched) in list(self.peers.items()):
            if now - touched > self.idle_seconds:
                transport.close()
                self.peers.pop(addr, None)

    def close(self) -> None:
        if self.transport:
            self.transport.close()
        for transport, _ in self.peers.values():
            transport.close()
        self.peers.clear()
        for task in self.pending.values():
            task.cancel()
        self.pending.clear()
        self.pending_data.clear()


class _UdpPeer(asyncio.DatagramProtocol):
    def __init__(self, parent: UdpRelay, addr: tuple[str, int]):
        self.parent, self.addr = parent, addr

    def datagram_received(self, data: bytes, _addr: tuple[str, int]) -> None:
        self.parent.from_target(data, self.addr)
        if self.addr in self.parent.peers:
            transport, _ = self.parent.peers[self.addr]
            self.parent.peers[self.addr] = (transport, time.monotonic())


async def run(args: argparse.Namespace) -> int:
    loop = asyncio.get_running_loop()
    state_path = Path(args.supervision_json)
    if state_path.resolve() in {Path(args.vm_supervision).resolve(),
                                Path(args.interactive_ready).resolve()}:
        raise RuntimeError("--supervision-json must be distinct from input receipts")
    started = await asyncio.to_thread(inspect_identity, args.cid)
    if args.target not in started["network_ips"]:
        raise RuntimeError("--target is not an IPv4 address on the identified Docker network")
    try:
        vm_receipt = json.loads(Path(args.vm_supervision).read_text())
        ready_receipt = json.loads(Path(args.interactive_ready).read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError("input supervision receipts are unreadable or malformed") from exc
    if vm_receipt.get("cid") != args.cid or vm_receipt.get("started_at") != started["started_at"]:
        raise RuntimeError("vm supervision identity does not match Docker")
    if ready_receipt.get("run_id") != args.run_id:
        raise RuntimeError("interactive-ready run identity does not match")
    stop_file = Path(ready_receipt["stop_file"])
    if stop_file.exists() or (args.stop_file and Path(args.stop_file).exists()):
        raise RuntimeError("the session is already stopping")
    try:
        deadlines = [float(receipt["deadline_epoch"]) for receipt in (vm_receipt, ready_receipt)]
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("input receipts must contain numeric deadline_epoch") from exc
    deadlines.append(started["started_epoch"] + args.max_seconds)
    if any(not math.isfinite(d) or d <= time.time() for d in deadlines):
        raise RuntimeError("an input supervision deadline has already expired")
    absolute_deadline = min(deadlines)
    ready_deadline = time.monotonic() + args.ready_deadline
    state: dict[str, Any] = {"schema": 1, "kind": "sunshine-lan-relay",
        "cid": args.cid, "started_at": started["started_at"],
        "target_ipv4": args.target, "bind_ipv4": args.bind,
        "base_port": args.base_port, "web_ui": args.web_ui,
        "tcp_offsets": list(TCP_OFFSETS), "udp_offsets": list(UDP_OFFSETS),
        "deadline_epoch": absolute_deadline, "ready": False, "outcome": "starting"}
    write_json(state_path, state)
    servers: list[asyncio.AbstractServer] = []
    udps: list[UdpRelay] = []
    connections: set[asyncio.Task[Any]] = set()
    try:
        tcp_offsets = TCP_OFFSETS + ((WEB_OFFSET,) if args.web_ui else ())
        for offset in tcp_offsets:
            port = args.base_port + offset
            relay = TcpRelay((args.target, port), connections)
            servers.append(await asyncio.start_server(relay, args.bind, port))
        for offset in UDP_OFFSETS:
            port = args.base_port + offset
            protocol = UdpRelay(loop, (args.target, port), args.udp_idle)
            await loop.create_datagram_endpoint(lambda p=protocol: p,
                                                local_addr=(args.bind, port))
            udps.append(protocol)
    except OSError as exc:
        for server in servers: server.close()
        for protocol in udps: protocol.close()
        await asyncio.gather(*(server.wait_closed() for server in servers), return_exceptions=True)
        state.update(outcome="bind-failed", error=str(exc))
        write_json(state_path, state)
        return 2
    if time.monotonic() > ready_deadline:
        for server in servers:
            server.close()
        for protocol in udps:
            protocol.close()
        await asyncio.gather(*(server.wait_closed() for server in servers), return_exceptions=True)
        state.update(outcome="ready-deadline-expired")
        write_json(state_path, state)
        return 3
    state.update(ready=True, outcome="ready", ready_epoch=time.time(),
                 listening_tcp=[args.base_port + x for x in tcp_offsets],
                 listening_udp=[args.base_port + x for x in UDP_OFFSETS])
    write_json(state_path, state)
    reaper_tasks = [asyncio.create_task(p.reap()) for p in udps]
    try:
        while True:
            await asyncio.sleep(1)
            if time.time() >= absolute_deadline:
                state["outcome"] = "deadline-expired"; break
            if stop_file.exists() or (args.stop_file and Path(args.stop_file).exists()):
                state["outcome"] = "stop-file"; break
            try:
                current = await asyncio.to_thread(inspect_identity, args.cid)
                if args.target not in current["network_ips"]:
                    raise RuntimeError("target Docker network address changed")
            except Exception as exc:
                state.update(outcome="identity-failed", error=str(exc)); break
            if current["started_at"] != started["started_at"]:
                state["outcome"] = "identity-changed"; break
    finally:
        for task in reaper_tasks: task.cancel()
        for server in servers: server.close()
        for protocol in udps: protocol.close()
        for task in connections: task.cancel()
        await asyncio.gather(*(server.wait_closed() for server in servers), return_exceptions=True)
        state["ready"] = False
        state["stopped_epoch"] = time.time()
        write_json(state_path, state)
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bind", required=True, help="explicit local LAN IPv4")
    p.add_argument("--target", required=True, help="explicit Docker container IPv4")
    p.add_argument("--cid", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--vm-supervision", required=True)
    p.add_argument("--interactive-ready", required=True)
    p.add_argument("--supervision-json", required=True)
    p.add_argument("--stop-file")
    p.add_argument("--base-port", type=int, default=48989)
    p.add_argument("--max-seconds", type=float, required=True)
    p.add_argument("--ready-deadline", type=float, default=30)
    p.add_argument("--udp-idle", type=float, default=60)
    p.add_argument("--web-ui", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        args.cid = full_cid(args.cid)
        args.bind = ipv4(args.bind, "--bind")
        args.target = ipv4(args.target, "--target")
        if not 1024 <= args.base_port <= 65514 or any(args.base_port + x > 65535 for x in TCP_OFFSETS + UDP_OFFSETS + (WEB_OFFSET,)):
            raise ValueError("--base-port produces an invalid port")
        if any(not math.isfinite(v) or v <= 0 for v in (args.max_seconds, args.ready_deadline, args.udp_idle)):
            raise ValueError("absolute exposure and relay deadlines must be positive")
        return asyncio.run(run(args))
    except (ValueError, RuntimeError) as exc:
        print(f"sunshine-lan-relay: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
