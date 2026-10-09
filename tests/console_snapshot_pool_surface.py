#!/usr/bin/env python3
"""Bounded software witness using exact pinned QEMU surface ownership functions.
Only trace calls are stubbed. Non-GL Linux DisplaySurface layout; not full device teardown.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess


def function(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 0
    for pos in range(brace, len(text)):
        if text[pos] == '{': depth += 1
        if text[pos] == '}': depth -= 1
        if not depth: return text[start:pos+1]+'\n'
    raise ValueError('unterminated function')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qemu-source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1]
    pins=json.loads((root/'findings/research/console-snapshot-recycling-source-pins-20261010.json').read_text())
    texts={}
    for name in ('ui/console.c','ui/qemu-pixman.c','include/ui/surface.h','include/ui/qemu-pixman.h'):
        data=(a.qemu_source/name).read_bytes()
        assert hashlib.sha256(data).hexdigest()==pins['files'][name], name
        texts[name]=data.decode()
    surface=texts['include/ui/surface.h']
    assert 'typedef int qemu_pixman_shareable;' in texts['include/ui/qemu-pixman.h']
    assert '#define SHAREABLE_NONE (-1)' in texts['include/ui/qemu-pixman.h']
    typedef=surface[surface.index('typedef struct DisplaySurface {'):surface.index('} DisplaySurface;')+len('} DisplaySurface;')]
    assert '#ifdef CONFIG_OPENGL' in typedef
    patch=(root/'findings/research/patches/qemu-10.1.2-bochs-snapshot-pool.patch').read_text()
    added=patch.split('+++ b/hw/display/bochs-snapshot-pool.h\n',1)[1]
    (a.output/'bochs-snapshot-pool.h').write_text('\n'.join(x[1:] for x in added.splitlines() if x.startswith('+'))+'\n')
    source='#include "bochs-snapshot-pool.h"\n#include <assert.h>\n#include <string.h>\ntypedef int qemu_pixman_shareable;\n#define SHAREABLE_NONE -1\n#define trace_displaysurface_create_pixman(s) ((void)0)\n#define trace_displaysurface_free(s) ((void)0)\n'+typedef+'\n'
    source+=function(texts['ui/qemu-pixman.c'], 'void qemu_pixman_image_unref(')
    source+=function(texts['ui/console.c'], 'DisplaySurface *qemu_create_displaysurface_pixman(')
    source+=function(texts['ui/console.c'], 'void qemu_free_displaysurface(')
    source+=r'''
int main(void) {
    BochsSnapshotPool *pool=bsp_new();
    pixman_image_t *image=bsp_image(pool, 801, 601);
    assert(image);
    memset(pixman_image_get_data(image), 0x73, 801*601*4);
    DisplaySurface *surface=qemu_create_displaysurface_pixman(image);
    assert(surface->share_handle==SHAREABLE_NONE);
    pixman_image_unref(image); // Original lease reference; surface now owns it.
    pixman_image_t *listener=pixman_image_ref(surface->image);
    qemu_free_displaysurface(surface);
    assert(pool->slots==1 && !pool->idle); // Actual surface destruction did not reclaim.
    bsp_close(pool); // Device owner detached; listener must still preserve backing.
    const unsigned char *bytes=(unsigned char *)pixman_image_get_data(listener);
    for(size_t i=0;i<801*601*4;i++) assert(bytes[i]==0x73);
    pixman_image_unref(listener); // Final callback frees block and independent pool.
    return 0;
}
'''
    c=a.output/'surface-test.c';c.write_text(source)
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','glib-2.0','pixman-1'],text=True))
    cmd=['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-g',str(c),'-o',str(a.output/'surface-test'),*flags]
    subprocess.run(cmd,check=True)
    subprocess.run([str(a.output/'surface-test')],check=True,timeout=10)
    (a.output/'result.json').write_text(json.dumps({'passed':True,'scope':'exact pinned non-GL QEMU surface create/free + production private-pool final-reference lifetime; no full device/unrealize qualification','compile':cmd,'source_sha256':hashlib.sha256(c.read_bytes()).hexdigest(),'patch_sha256':hashlib.sha256(patch.encode()).hexdigest(),'qemu_files':{n:pins['files'][n] for n in texts}},indent=2)+'\n')

if __name__=='__main__':main()
