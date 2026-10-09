"""Execute production pool policy with real Pixman final-reference callbacks.
This is not a QEMU device or external-listener qualification; run the image oracle too.
"""
import pathlib
import shlex
import shutil
import subprocess
import tempfile
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]

class SnapshotPoolTests(unittest.TestCase):
    def test_real_pixman_lifetime_and_bounds(self):
        compiler = shutil.which('cc')
        pkg = shutil.which('pkg-config')
        if not compiler or not pkg:
            self.skipTest('C compiler/pkg-config unavailable')
        flags = subprocess.run([pkg, '--cflags', '--libs', 'glib-2.0', 'pixman-1'], capture_output=True, text=True)
        if flags.returncode:
            self.skipTest('GLib/Pixman development files unavailable')
        patch = (ROOT/'findings/research/patches/qemu-10.1.2-bochs-snapshot-pool.patch').read_text()
        added = patch.split('+++ b/hw/display/bochs-snapshot-pool.h\n', 1)[1]
        header = '\n'.join(line[1:] for line in added.splitlines() if line.startswith('+'))+'\n'
        source = r'''
#include "bochs-snapshot-pool.h"
#include <assert.h>
#include <string.h>
static gpointer delayed_unref(gpointer p) {
    pixman_image_unref(p);
    return NULL;
}
static void fill(pixman_image_t *image, unsigned char value) {
    memset(pixman_image_get_data(image), value,
           pixman_image_get_stride(image)*pixman_image_get_height(image));
}
static void check(pixman_image_t *image, unsigned char value) {
    const unsigned char *p=(unsigned char *)pixman_image_get_data(image);
    size_t size=pixman_image_get_stride(image)*pixman_image_get_height(image);
    for(size_t i=0;i<size;i++) assert(p[i]==value);
}
int main(void) {
    BochsSnapshotPool *p=bsp_new();
    assert(!bsp_image(p, 0, 1) && !bsp_image(p, 3841, 2160));
    pixman_image_t *a=bsp_image(p, 801, 601);
    assert(a && pixman_image_get_stride(a)==801*4);
    fill(a, 0x31);
    uint32_t *a_data=pixman_image_get_data(a);
    // Listener retains a reference after the owning surface drops its reference.
    pixman_image_ref(a);
    pixman_image_unref(a);
    assert(p->slots==1 && !p->idle);
    pixman_image_t *b=bsp_image(p, 3840, 2160);
    pixman_image_t *c=bsp_image(p, 640, 480);
    assert(b && c && p->slots==BSP_SLOTS && p->bytes==BSP_SLOTS*(size_t)BSP_BYTES);
    fill(b, 0x42); fill(c, 0x53);
    assert(pixman_image_get_data(b)!=a_data && pixman_image_get_data(c)!=a_data);
    assert(!bsp_image(p, 1920, 1080)); // Caller must use unchanged fresh fallback.
    check(a, 0x31);
    uint32_t *b_data=pixman_image_get_data(b);
    pixman_image_unref(b); // Final ref, now reusable at different odd geometry.
    pixman_image_t *d=bsp_image(p, 1235, 743);
    assert(d && pixman_image_get_data(d)==b_data && pixman_image_get_stride(d)==1235*4);
    fill(d, 0x64); check(a, 0x31); check(c, 0x53);
    assert(p->slots==3 && p->bytes==3*(size_t)BSP_BYTES);
    // Extra inspection ref lets the test examine closed state after device close.
    g_atomic_int_inc(&p->refs);
    bsp_close(p);
    assert(p->closed && !bsp_image(p, 640, 480));
    check(a, 0x31); check(c, 0x53); check(d, 0x64);
    pixman_image_unref(c); pixman_image_unref(d);
    assert(p->slots==1 && p->bytes==BSP_BYTES);
    GThread *thread=g_thread_new("late-listener", delayed_unref, a);
    g_thread_join(thread);
    assert(!p->slots && !p->bytes && !p->idle);
    bsp_unref(p); // Frees independent pool after final observer.
    p=bsp_new();
    a=bsp_image(p, 640, 480); assert(a);
    pixman_image_unref(a); assert(p->idle);
    bsp_close(p); // Idle close, no outstanding image.
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            d=pathlib.Path(temp)
            (d/'bochs-snapshot-pool.h').write_text(header)
            (d/'test.c').write_text(source)
            subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', str(d/'test.c'), '-o', str(d/'test'), *shlex.split(flags.stdout)], check=True)
            subprocess.run([str(d/'test')], check=True, timeout=10)
