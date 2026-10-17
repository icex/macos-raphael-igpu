#!/usr/bin/env python3
"""Read-only display ancestry; intentionally excludes arbitrary registry properties."""
import json, plistlib, subprocess

def inventory(nodes):
    if isinstance(nodes,dict): nodes=[nodes]
    if not isinstance(nodes,list) or any(not isinstance(n,dict) for n in nodes):
        raise ValueError("registry root must be dictionary or list of dictionaries")
    out=[]
    keys=('vendor-id','device-id','class-code','assigned-addresses','reg','IODeviceMemory')
    def safe(v):
        if isinstance(v,bytes): return v.hex()
        if isinstance(v,int): return v
        if isinstance(v,list): return [safe(x) for x in v[:16]]
        if isinstance(v,dict): return {k:safe(v[k]) for k in ('address','length') if k in v}
        return None
    def walk(n,path,selected):
        name=n.get('IORegistryEntryName','')
        cls=n.get('IOObjectClass','')
        ident={'name':str(name)[:100],'class':str(cls)[:100]}
        vid=n.get('vendor-id',b'');cc=n.get('class-code',b'')
        num=lambda v:int.from_bytes(v[:4],'little') if isinstance(v,bytes) else v
        pci=num(vid) in (0x15ad,0x80ee) and isinstance(num(cc),int) and num(cc)>>16==3
        fb='Framebuffer' in str(cls) or 'Framebuffer' in str(name)
        if pci or fb:
            out.append(dict(matching_pci_ancestor=selected,ancestry=(path+[ident])[-12:],properties={k:safe(n[k]) for k in keys if k in n}))
        for child in n.get('IORegistryEntryChildren',[]):walk(child,path+[ident],selected or pci)
    for n in nodes:walk(n,[],False)
    return out
if __name__=='__main__':
    p=subprocess.run(['/usr/sbin/ioreg','-a','-l','-p','IOService'],capture_output=True,timeout=10,check=True)
    if len(p.stdout)>64*1024*1024:raise ValueError('oversized registry')
    print(json.dumps({'scope':'ancestry only; no exclusive ownership or mapping proof','displays':inventory(plistlib.loads(p.stdout))},separators=(',',':')))
