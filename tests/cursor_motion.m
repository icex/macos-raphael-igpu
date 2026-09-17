// Continuous deterministic cursor motion on the desktop, used to reproduce a
// "cursor motion makes streaming slow" condition while a remote-desktop
// stream is measured. Posts kCGEventMouseMoved only; never warps the cursor.
// CLI: cursor_motion SECONDS [HZ] [RADIUS]   (defaults 30 60 300)
// Build: clang -fobjc-arc -framework ApplicationServices -framework Foundation \
//        tests/cursor_motion.m -o /var/tmp/cursor_motion
#import <ApplicationServices/ApplicationServices.h>
#import <Foundation/Foundation.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
static void fail(const char *msg) {
    printf("{\"status\":\"error\",\"message\":\"%s\"}\n", msg);
    exit(1);
}
static void onAlarm(int signalNumber) {
    (void)signalNumber;
    const char json[] = "{\"status\":\"error\",\"message\":\"alarm bound exceeded\"}\n";
    write(STDOUT_FILENO, json, sizeof(json) - 1);
    _exit(1);
}
static double monotonicSeconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}
static void preciseSleepUntil(double targetSeconds) {
    double remaining = targetSeconds - monotonicSeconds();
    if (remaining <= 0) return;
    struct timespec req;
    req.tv_sec = (time_t)remaining;
    req.tv_nsec = (long)((remaining - (double)req.tv_sec) * 1e9);
    nanosleep(&req, NULL);
}
int main(int argc, const char *argv[]) {
    double seconds = argc > 1 ? atof(argv[1]) : 30.0;
    double hz = argc > 2 ? atof(argv[2]) : 60.0;
    double radius = argc > 3 ? atof(argv[3]) : 300.0;
    if (seconds <= 0 || hz <= 0) fail("invalid SECONDS/HZ");
    signal(SIGALRM, onAlarm);
    alarm((unsigned)seconds + 10);
    CGDirectDisplayID display = CGMainDisplayID();
    CGRect bounds = CGDisplayBounds(display);
    double width = CGRectGetWidth(bounds);
    double height = CGRectGetHeight(bounds);
    if (width <= 0 || height <= 0) fail("display size is zero");
    double centerX = bounds.origin.x + width / 2.0;
    double centerY = bounds.origin.y + height / 2.0;
    double period = 1.0 / hz;
    double angularVelocity = 2.0 * M_PI / 2.0; // one revolution per 2 seconds
    double start = monotonicSeconds();
    double deadline = start + seconds;
    double nextTick = start;
    uint64_t events = 0;
    while (monotonicSeconds() < deadline) {
        double angle = (monotonicSeconds() - start) * angularVelocity;
        CGPoint point = CGPointMake(centerX + radius * cos(angle),
                                     centerY + radius * sin(angle));
        CGEventRef event = CGEventCreateMouseEvent(NULL, kCGEventMouseMoved,
                                                    point, kCGMouseButtonLeft);
        if (!event) fail("event creation failed");
        CGEventPost(kCGHIDEventTap, event);
        CFRelease(event);
        events++;
        nextTick += period;
        preciseSleepUntil(nextTick);
    }
    double elapsed = monotonicSeconds() - start;
    double actualHz = elapsed > 0 ? (double)events / elapsed : 0.0;
    printf("{\"status\":\"result\",\"events\":%llu,\"seconds\":%.3f,"
           "\"hz\":%.3f,\"actual_hz\":%.3f,\"display\":\"%dx%d\"}\n",
           (unsigned long long)events, elapsed, hz, actualHz, (int)width,
           (int)height);
    return 0;
}
