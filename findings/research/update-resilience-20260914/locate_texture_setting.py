"""Read-only structural discovery experiment. Never writes an image or guest memory.
One-code-shape prototype, not an assertion of cross-OS compatibility.
"""
import json,re,struct,sys,hashlib
from pathlib import Path
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
from capstone.x86 import X86_OP_REG,X86_OP_IMM,X86_OP_MEM

class Refused(ValueError): pass

def sections(b):
    if len(b)<32 or struct.unpack_from('<I',b)[0]!=0xfeedfacf:raise Refused('Mach-O header')
    n,total=struct.unpack_from('<II',b,16)
    if n>128 or total>len(b)-32:raise Refused('load commands')
    o=32;out={};base=None
    for _ in range(n):
        if o+8>32+total:raise Refused('command bounds')
        cmd,size=struct.unpack_from('<II',b,o)
        if size<8 or o+size>32+total:raise Refused('command size')
        if cmd==0x19:
            if size<72:raise Refused('segment')
            name=b[o+8:o+24].split(b'\0')[0]
            if name==b'__TEXT':
                base=struct.unpack_from('<Q',b,o+24)[0];count=struct.unpack_from('<I',b,o+64)[0]
                if count>(size-72)//80:raise Refused('section count')
                for j in range(count):
                    at=o+72+j*80;nm=b[at:at+16].split(b'\0')[0].decode();addr,sz=struct.unpack_from('<QQ',b,at+32)
                    if addr<base or addr-base+sz>len(b):raise Refused('section extent')
                    if nm in out:raise Refused('duplicate section')
                    out[nm]=(addr-base,sz)
        o+=size
    if o!=32+total or base is None:raise Refused('text segment')
    return out

def setting_bit(b,secs):
    off,n=secs['__objc_methtype'];blob=b[off:off+n]
    layouts=[]
    for m in re.finditer(rb'\{AMD_DeviceSettings=',blob):
        p=m.end();bit=0;named=None;seen=set()
        while True:
            field=re.match(rb'"([^"\x00]+)"b([0-9]+)',blob[p:])
            if field is None:break
            name,width=field[1],int(field[2]);p+=field.end()
            if name in seen or width<1 or width>64:raise Refused('bitfield metadata')
            seen.add(name)
            if name==b'enableTexturePipeBankXor':
                if width!=1:raise Refused('target not boolean')
                named=bit
            bit+=width
        if named is not None:layouts.append(named)
    if not layouts or len(set(layouts))!=1 or layouts[0]>=64:raise Refused('missing/conflicting first-word field')
    return layouts[0]

def locate(b):
    secs=sections(b);bit=setting_bit(b,secs);mask=1<<bit;off,size=secs['__text'];code=b[off:off+size]
    md=Cs(CS_ARCH_X86,CS_MODE_64);md.detail=True
    candidates=[]
    # movabs reg64, imm64. Decode the three-instruction operation and its preceding
    # register dataflow, rather than matching the old full immediate or its offset.
    for m in re.finditer(rb'[\x48\x49][\xb8-\xbf]',code):
        pos=off+m.start();ins=list(md.disasm(b[pos:pos+24],pos,count=3))
        if len(ins)!=3:continue
        a,o,s=ins
        if a.mnemonic!='movabs' or len(a.operands)!=2 or a.operands[1].type!=X86_OP_IMM:continue
        imm=a.operands[1].imm & ((1<<64)-1)
        if o.mnemonic!='or' or len(o.operands)!=2 or any(x.type!=X86_OP_REG for x in o.operands):continue
        if o.operands[0].reg!=a.operands[0].reg:continue
        if s.mnemonic!='mov' or len(s.operands)!=2 or s.operands[0].type!=X86_OP_MEM or s.operands[1].type!=X86_OP_REG:continue
        dest=s.operands[0].mem
        if dest.disp or dest.index or s.reg_name(dest.base)!='rdi' or s.operands[1].reg!=a.operands[0].reg:continue
        # Conservative known constructor family: preceding AND/OR supplies the
        # other bits, followed by hardware-capability synthesis and another store.
        pre=list(md.disasm(b[pos-6:pos],pos-6));post=list(md.disasm(b[s.address+s.size:s.address+s.size+64],s.address+s.size,count=7))
        if len(pre)!=2 or [x.mnemonic for x in pre]!=['and','or']:continue
        reg=o.operands[1].reg
        if any(len(x.operands)!=2 or x.operands[0].type!=X86_OP_REG or x.operands[0].reg!=reg for x in pre):continue
        if [x.mnemonic for x in post]!=['mov','shr','and','shl','and','or','mov']:continue
        if post[-1].op_str!=s.op_str:continue
        # Require high-word defaults later in the same initialization sequence.
        tail=list(md.disasm(b[s.address+s.size:s.address+s.size+96],s.address+s.size))
        if not any(x.mnemonic=='movabs' and len(x.operands)==2 and x.operands[1].type==X86_OP_IMM and (x.operands[1].imm&0xffffffff)==0 and x.operands[1].imm!=0 for x in tail):continue
        candidates.append({'instruction_offset':pos,'byte_offset':pos+a.imm_offset+bit//8,'bit_in_byte':bit%8,'bit':bit,'old_immediate':hex(imm),'new_immediate':hex(imm & ~mask),'already_clear':not bool(imm&mask),'instruction':a.bytes.hex()})
    if len(candidates)!=1:raise Refused('candidate count '+str(len(candidates)))
    return candidates[0]

if __name__=='__main__':
    b=Path(sys.argv[1]).read_bytes();r=locate(b);r.update(image_sha256=hashlib.sha256(b).hexdigest(),read_only=True,scope='one real image; structural family only');print(json.dumps(r,indent=2))
