"""Read-only and loopback coverage for the Sunshine LAN relay."""
import asyncio
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import socket
from types import SimpleNamespace
import unittest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "sunshine-lan-relay.py"
spec = importlib.util.spec_from_file_location("sunshine_lan_relay", TOOL)
relay = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(relay)
CID = "a" * 64


class RelayTests(unittest.TestCase):
    def test_bind_must_be_specific_ipv4(self):
        with self.assertRaises(ValueError):
            relay.ipv4("0.0.0.0", "--bind")
        self.assertEqual(relay.ipv4("192.0.2.7", "--bind"), "192.0.2.7")

    def test_identity_requires_exact_cid_and_running_started_at(self):
        started = datetime.now(timezone.utc).isoformat()
        def runner(argv, **_):
            self.assertEqual(argv[0:3], ["docker", "inspect", "--format"])
            return SimpleNamespace(returncode=0, stdout=(
                '{"Id":"' + CID + '","StartedAt":"' + started + '","Running":true,'
                '"Networks":{"net":{"IPAddress":"192.0.2.7"}}}\n'))
        data = relay.inspect_identity(CID, runner)
        self.assertEqual(data["cid"], CID)
        self.assertEqual(data["started_at"], started)
        def stale(argv, **_):
            return SimpleNamespace(returncode=0, stdout=(
                '{"Id":"' + "b" * 64 + '","StartedAt":"' + started + '","Running":true,'
                '"Networks":{"net":{"IPAddress":"192.0.2.7"}}}\n'))
        with self.assertRaises(RuntimeError):
            relay.inspect_identity(CID, stale)

    def test_tcp_relay_round_trip(self):
        async def exercise():
            async def target(reader, writer):
                writer.write(await reader.read(4096))
                await writer.drain()
                writer.close()
                await writer.wait_closed()
            target_server = await asyncio.start_server(target, "127.0.0.1", 0)
            target_port = target_server.sockets[0].getsockname()[1]
            tasks = set()
            relay_server = await asyncio.start_server(
                relay.TcpRelay(("127.0.0.1", target_port), tasks), "127.0.0.1", 0)
            port = relay_server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"sunshine"); await writer.drain()
            self.assertEqual(await reader.read(64), b"sunshine")
            writer.close(); await writer.wait_closed()
            relay_server.close(); target_server.close()
            await relay_server.wait_closed(); await target_server.wait_closed()
        asyncio.run(exercise())

    def test_udp_burst_uses_one_mapping_and_preserves_order(self):
        async def exercise():
            class Echo(asyncio.DatagramProtocol):
                def connection_made(self, transport):
                    self.transport = transport
                def datagram_received(self, data, addr):
                    self.transport.sendto(data, addr)

            loop = asyncio.get_running_loop()
            target_transport, _ = await loop.create_datagram_endpoint(
                Echo, local_addr=("127.0.0.1", 0))
            target_port = target_transport.get_extra_info("sockname")[1]
            protocol = relay.UdpRelay(loop, ("127.0.0.1", target_port), 0.05)
            relay_transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol, local_addr=("127.0.0.1", 0))
            client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            client.setblocking(False)
            addr = relay_transport.get_extra_info("sockname")
            for value in range(10):
                client.sendto(value.to_bytes(1, "big"), addr)
            received = []
            for _ in range(10):
                data, _ = await loop.sock_recvfrom(client, 16)
                received.append(data)
            self.assertEqual(received, [bytes([x]) for x in range(10)])
            self.assertEqual(len(protocol.peers), 1)
            await asyncio.sleep(0.08)
            await protocol.reap_once()
            self.assertFalse(protocol.peers)
            protocol.close()
            self.assertFalse(protocol.peers)
            self.assertFalse(protocol.pending)
            client.close(); relay_transport.close(); target_transport.close()
        asyncio.run(exercise())
