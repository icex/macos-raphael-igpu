#include "../src/DmubRingProbe.hpp"
#include <cassert>
int main() {
    uint32_t memory[16] = {};
    auto read = [&](uint64_t off) { assert(off < sizeof(memory)); return memory[off/4]; };
    auto write = [&](uint64_t off, uint32_t v) { assert(off < sizeof(memory)); memory[off/4] = v; };
    auto r = RaphaelDmubRing::probe(0, read, write);
    assert(r.matched && r.restored);
    for (unsigned i=0;i<16;i++) { assert(memory[i]==0); memory[i]=i*42; }
    r = RaphaelDmubRing::probe(0, read, write);
    assert(r.matched && r.restored);
    for (unsigned i=0;i<16;i++) assert(memory[i]==i*42);
    r = RaphaelDmubRing::probe(0, read, [](uint64_t, uint32_t) {});
    assert(!r.matched && r.restored);
    r = RaphaelDmubRing::probe(0, read, [&](uint64_t off, uint32_t v) { if(off!=28) write(off,v); });
    assert(!r.matched && r.restored);
    for (unsigned i=0;i<16;i++) assert(memory[i]==i*42);
    unsigned writes=0;
    r = RaphaelDmubRing::probe(0, read, [&](uint64_t off, uint32_t v) { if(writes++<32) write(off,v); });
    assert(r.matched && !r.restored);
}
