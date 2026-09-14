"""Synthetic mutation checks; these are NOT other OS builds or GPU evidence."""
import json,sys,struct
from pathlib import Path
from locate_texture_setting import locate,sections,Refused
original=Path(sys.argv[1]).read_bytes();base=locate(original);site=base['instruction_offset'];results=[]
def check(name,b,predicate):
 try:r=locate(bytes(b));ok=predicate(r)
 except Refused as e:r={'refused':str(e)};ok=predicate(r)
 assert ok,(name,r)
 results.append({'name':name,'result':r,'pass':True,'synthetic':name!='real-image'})
check('real-image',original,lambda r:r['bit']==27 and r['instruction_offset']==site)
b=bytearray(original);o=32
for _ in range(struct.unpack_from('<I',b,16)[0]):
 c,n=struct.unpack_from('<II',b,o)
 if c==0x1b:b[o+8:o+24]=bytes(range(16))
 o+=n
check('different-uuid',b,lambda r:r['instruction_offset']==site)
b=bytearray(original);imm=int.from_bytes(b[site+2:site+10],'little');b[site+2:site+10]=(imm^(1<<26)).to_bytes(8,'little')
check('unrelated-default-bit-changed',b,lambda r:int(r['new_immediate'],16)==((imm^(1<<26))&~(1<<27)))
b=bytearray(original);b[site+5]&=~8
check('already-disabled',b,lambda r:r['already_clear'])
b=bytearray(original);mo,ms=sections(b)['__objc_methtype'];needle=b'"allowVRAM"b1';p=b.find(needle,mo,mo+ms);assert p>=0;b[p+len(needle)-1]=ord('2')
check('metadata-bit-layout-shift',b,lambda r:r['bit']==28 and int(r['new_immediate'],16)==imm&~(1<<28))
b=bytearray(original);a,z=site-128,site+192;delta=0x2000;chunk=b[a:z];b[a:z]=b'\x90'*(z-a);b[a+delta:z+delta]=chunk
check('moved-constructor-window',b,lambda r:r['instruction_offset']==site+delta)
b=bytearray(original);b[a+delta:z+delta]=b[a:z]
check('ambiguous-two-windows',b,lambda r:r.get('refused')=='candidate count 2')
b=bytearray(original);p=b.find(b'enableTexturePipeBankXor',mo,mo+ms);b[p]=ord('X')
check('missing-named-metadata',b,lambda r:'refused' in r)
b=bytearray(original);b[site+11]=0x31
check('changed-dataflow-xor-instead-of-or',b,lambda r:r.get('refused')=='candidate count 0')
b=bytearray(original);co,cs=sections(b)['__cstring'];b[co:co+z-a]=b[a:z]
check('lookalike-in-noncode-section',b,lambda r:r['instruction_offset']==site)
check('truncated-image',original[:2000000],lambda r:'refused' in r)
print(json.dumps({'scope':'one real image and synthetic mutations, read-only, no OS update validation','checks':results},indent=2))
