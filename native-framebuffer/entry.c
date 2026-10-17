#include <mach/mach_types.h>
#include <IOKit/IOLib.h>
#include "NativeBuildIdentity.h"
kern_return_t RaphaelFramebuffer_kern_start(kmod_info_t *info, void *data) {
    (void)info; (void)data;
    IOLog("RaphaelFramebuffer bundle: build=%s version=0.1.0 loaded; native probe remains opt-in\n", RGPU_NATIVE_BUILD_ID);
    return KERN_SUCCESS;
}
kern_return_t RaphaelFramebuffer_kern_stop(kmod_info_t *info, void *data) {
    (void)info; (void)data;
    // Instances own timers/callbacks; module unload is not qualified yet.
    return KERN_FAILURE;
}
