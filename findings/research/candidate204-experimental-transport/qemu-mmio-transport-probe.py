#!/usr/bin/env python3
"""Bounded, offline QEMU GDB physical-memory probe (emulated edu only)."""
import argparse, json, re, socket, subprocess, tempfile, time
from pathlib import Path

IMAGE = "sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c"
BAR_GPA, BAR_SIZE, REG = 0x10000000, 0x100000, 4
MAX_SECONDS = 30.0

def checksum(data): return "%02x" % (sum(data) & 255)
def frame(payload):
    data = payload.encode() if isinstance(payload, str) else payload
    return b"$" + data + b"#" + checksum(data).encode()
def parse_frame(data):
    if not data.startswith(b"$") or b"#" not in data: raise ValueError("bad RSP frame")
    i=data.index(b"#")
    if len(data)<i+3: raise ValueError("truncated RSP frame")
    payload=data[1:i]
    if data[i+1:i+3].lower()!=checksum(payload).encode(): raise ValueError("RSP checksum")
    return payload.decode()
def check_range(address, length):
    if not isinstance(address,int) or not isinstance(length,int) or length<0 or address<BAR_GPA or address+length>BAR_GPA+BAR_SIZE:
        raise ValueError("address outside fixed edu BAR")

class RSP:
    def __init__(self, sock, deadline): self.s=sock; self.deadline=deadline; sock.settimeout(.2)
    def command(self, payload):
        self.s.sendall(frame(payload)); buf=b""
        while time.monotonic()<self.deadline:
            try: chunk=self.s.recv(4096)
            except socket.timeout: continue
            if not chunk: raise ConnectionError("GDB closed")
            buf+=chunk
            if buf.startswith(b"+"): buf=buf[1:]
            if buf.startswith(b"-"): raise RuntimeError("GDB NACK")
            if b"#" in buf and len(buf)>=buf.index(b"#")+3:
                reply=parse_frame(buf); self.s.sendall(b"+"); return reply
        raise TimeoutError("RSP deadline")
    def read(self,address,length):
        check_range(address,length); reply=self.command("m%x,%x"%(address,length))
        if reply.startswith("E"): raise RuntimeError("RSP read "+reply)
        if len(reply)!=length*2 or not re.fullmatch("[0-9a-fA-F]*",reply): raise ValueError("bad RSP read")
        return bytes.fromhex(reply)
    def write(self,address,data):
        check_range(address,len(data)); reply=self.command("M%x,%x:%s"%(address,len(data),data.hex()))
        if reply.startswith("E"): raise RuntimeError("RSP write "+reply)
        if reply!="OK": raise ValueError("bad RSP write")

def qmp(sockpath, command, deadline, ident):
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(.2); s.connect(sockpath); buf=b""
        def recv_obj():
            nonlocal buf
            while time.monotonic()<deadline:
                while b"\n" in buf:
                    line,buf=buf.split(b"\n",1)
                    if line.strip(): return json.loads(line)
                try:
                    chunk=s.recv(65536)
                    if not chunk: raise ConnectionError("QMP closed")
                    buf+=chunk
                except socket.timeout: continue
            raise TimeoutError("QMP deadline")
        recv_obj(); s.sendall(b'{"execute":"qmp_capabilities"}\n')
        while True:
            obj=recv_obj()
            if "return" in obj: break
            if "error" in obj: raise RuntimeError("QMP capabilities error")
        s.sendall((json.dumps({"execute":command,"id":ident})+"\n").encode())
        while True:
            obj=recv_obj()
            if obj.get("id")==ident:
                if "error" in obj: raise RuntimeError("QMP command error")
                return obj.get("return")

def qtest_setup(sockpath, deadline):
    commands=("outl 0xcf8 0x80002010", "outl 0xcfc 0x10000000", "outl 0xcf8 0x80002004", "outw 0xcfc 0x0002")
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(.2); s.connect(sockpath)
        buf=b""
        for command in commands:
            if time.monotonic()>=deadline: raise TimeoutError("qtest deadline")
            s.sendall((command+"\n").encode())
            while b"\n" not in buf:
                chunk=s.recv(4096)
                if not chunk: raise ConnectionError("qtest closed")
                buf+=chunk
            line,buf=buf.split(b"\n",1)
            if line.strip().upper()!=b"OK": raise RuntimeError("qtest response "+line.decode(errors="replace"))
    return commands

def cleanup(cidfile, deadline):
    cid=cidfile.read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{64}",cid): raise RuntimeError("invalid container CID")
    for args in (("docker","stop","--time","0",cid),("docker","rm","-f",cid)):
        subprocess.run(args,check=True,capture_output=True,text=True,timeout=max(1,deadline-time.monotonic()))
    try:
        state=subprocess.run(("docker","inspect","--format","{{.State.Running}}",cid),capture_output=True,text=True,check=False,timeout=max(1,deadline-time.monotonic()))
    except subprocess.TimeoutExpired as exc: raise RuntimeError("cleanup inspect timed out") from exc
    if state.returncode==0: raise RuntimeError("container still exists after cleanup")
    if state.returncode!=1 or "no such object" not in state.stderr.lower():
        raise RuntimeError("cleanup inspect could not confirm absence: "+state.stderr.strip())
    return cid

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,required=True); ap.add_argument("--deadline",type=float,default=MAX_SECONDS)
    a=ap.parse_args(); a.output.mkdir(parents=False,exist_ok=False); deadline=time.monotonic()+min(max(a.deadline,1),MAX_SECONDS)
    result={"transport_only":True,"complete":False}; proc=None; out=err=None; cidfile=a.output/".cid"
    try:
        with tempfile.TemporaryDirectory(prefix="qemu-mmio-") as td:
            root=Path(td); qmp_sock=root/"qmp"; qtest_sock=root/"qtest"; gdb_sock=root/"gdb"
            qargs=["-accel","tcg","-machine","q35","-m","64M","-nodefaults","-display","none","-S","-qmp","unix:/tmp/qemu-mmio/qmp,server=on,wait=off","-qtest","unix:/tmp/qemu-mmio/qtest,server=on,wait=off","-gdb","unix:/tmp/qemu-mmio/gdb,server=on,wait=off","-device","edu,id=edu0,bus=pcie.0,addr=4.0"]
            create=["docker","create","--cidfile",str(cidfile),"--network","none","--cap-drop","ALL","--security-opt","no-new-privileges","-v",str(root)+":/tmp/qemu-mmio:rw","--entrypoint","qemu-system-x86_64",IMAGE]+qargs
            subprocess.run(create,check=True,capture_output=True,text=True,timeout=max(1,deadline-time.monotonic()))
            cid=cidfile.read_text().strip()
            if not re.fullmatch(r"[0-9a-f]{64}",cid): raise RuntimeError("invalid container CID")
            out=(a.output/"qemu.stdout").open("w"); err=(a.output/"qemu.stderr").open("w")
            proc=subprocess.Popen(["docker","start","-a",cid],stdout=out,stderr=err,text=True)
            while not all(p.exists() for p in (qmp_sock,qtest_sock,gdb_sock)):
                if proc.poll() is not None: raise RuntimeError("QEMU exited before sockets")
                if time.monotonic()>=deadline: raise TimeoutError("socket deadline")
                time.sleep(.05)
            setup=qtest_setup(str(qtest_sock),deadline); pci=qmp(str(qmp_sock),"query-pci",deadline,"pci"); devices=[d for bus in pci for d in bus.get("devices",[]) if d.get("qdev_id")=="edu0"]
            ident=devices[0].get("id",{}) if len(devices)==1 else {}
            if len(devices)!=1 or ident.get("vendor")!=0x1234 or ident.get("device")!=0x11e8: raise RuntimeError("edu identity")
            bar=next((r for r in devices[0].get("regions",[]) if r.get("bar")==0),None)
            if not bar or bar.get("address")!=BAR_GPA or bar.get("size")!=BAR_SIZE: raise RuntimeError("edu BAR layout")
            status=qmp(str(qmp_sock),"query-status",deadline,"status")
            if status.get("status") not in ("prelaunch","paused") or status.get("running") is True: raise RuntimeError("QEMU not paused/prelaunch")
            with socket.socket(socket.AF_UNIX) as gs:
                gs.settimeout(.2); gs.connect(str(gdb_sock)); rsp=RSP(gs,deadline); mode=rsp.command("Qqemu.PhyMemMode:1"); phy=rsp.command("qqemu.PhyMemMode")
                if mode!="OK" or phy!="1": raise RuntimeError("physical mode")
                before=rsp.read(BAR_GPA+REG,4); fixed=(0x12345678).to_bytes(4,"little"); rsp.write(BAR_GPA+REG,fixed); inverted=rsp.read(BAR_GPA+REG,4)
                if inverted!=(0xedcba987).to_bytes(4,"little"): raise RuntimeError("edu inversion")
                rsp.write(BAR_GPA+REG,bytes((x^0xff) for x in before)); restored=rsp.read(BAR_GPA+REG,4)
                if restored!=before: raise RuntimeError("edu restore")
            result.update({"complete":True,"edu_bar_gpa":hex(BAR_GPA),"before":before.hex(),"inverted":inverted.hex(),"restored":restored.hex(),"qtest":setup,"qmp_pci":pci,"qmp_status":status,"gdb_mode":phy})
    except Exception as exc: result["error"]=str(exc)
    finally:
        if cidfile and cidfile.exists():
            try: cleanup(cidfile,deadline)
            except Exception as exc: result["cleanup_error"]=str(exc)
        if proc is not None:
            try: proc.wait(timeout=2)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        if out is not None: out.close()
        if err is not None: err.close()
        a.output.joinpath("result.json").write_text(json.dumps(result,indent=2)+"\n")
    if result.get("cleanup_error"): raise RuntimeError(result["cleanup_error"])
    if not result.get("complete"): raise RuntimeError(result.get("error","probe failed"))

if __name__=="__main__": main()
