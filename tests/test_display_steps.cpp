#include "../src/DisplaySteps.hpp"
#include <cassert>
using namespace RaphaelSteps;
int main() {
    auto all = [](const Step &) { return true; };
    assert(classFor(3449, 2019) == 1 || classFor(3449, 2019) == 0);   // 1.708: between 16:10 and 16:9
    assert(classFor(1920, 1080) == 0 && classFor(2560, 1600) == 1 && classFor(3440, 1440) == 2);
    assert(classFor(7680, 2160) == 3 && classFor(1500, 1000) == 4 && classFor(1024, 768) == 5);
    // ~1.33 window pixels per point: a 3449-wide window looks like 2560, a 2000-wide one 1920.
    assert(stepFor(0, 3449, 133, all) == 1 && stepFor(0, 2000, 133, all) == 0);
    assert(stepFor(0, 1296, 133, all) == 0);                         // small windows scale down
    // Unusable steps are skipped; none usable gives -1.
    assert(stepFor(2, 4600, 133, [](const Step &s) { return s.width < 3000; }) == 0);
    assert(stepFor(3, 5000, 133, [](const Step &) { return false; }) == -1);
    return 0;
}
