#ifndef RAPHAEL_ENGINE_LIFECYCLE_HPP
#define RAPHAEL_ENGINE_LIFECYCLE_HPP

#include <stddef.h>

namespace RaphaelLifecycle {

inline bool customPowerUpReady(bool enabled, const void *hardware,
                               bool cleanupRouteAvailable) {
    return enabled && hardware != nullptr && cleanupRouteAvailable;
}

// Apple returns immediately when one engine's powerUp fails and does not call
// powerOffHWEngines on that partial initialization path.  Keep cleanup coupled
// to the failure while the guest's DMA mappings still exist.
template <typename PowerUp, typename Cleanup>
bool powerUpAll(void *const *engines, size_t count, PowerUp powerUp,
                Cleanup cleanup, size_t &failedIndex) {
    for (size_t index = 0; index < count; index++) {
        if (engines[index] != nullptr && !powerUp(engines[index], index)) {
            failedIndex = index;
            cleanup();
            return false;
        }
    }
    failedIndex = count;
    return true;
}

} // namespace RaphaelLifecycle

#endif
