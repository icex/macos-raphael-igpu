/* Exact-device transport ownership discriminator. No protocol/device I/O.
 * Build on macOS: clang -Wall -Wextra -Werror -O2 console-vdagent-probe.c -o probe
 * Caller must first establish no existing owner using IOKit/open-fd inventory.
 * EBUSY on another open proves exclusion of later ordinary non-root opens,
 * not absence of pre-existing owners or protection against privileged opens.
 */
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

static const char *device_path = "/dev/tty.com.redhat.spice.0";
static void timeout_handler(int sig)
{
    static const char msg[] = "{\"passed\":false,\"stage\":\"deadline\",\"timeout_seconds\":10}\n";
    (void)sig;
    (void)write(STDOUT_FILENO, msg, sizeof(msg)-1);
    _exit(124); /* Kernel closes only this process's descriptors. */
}
static void child_timeout_handler(int sig) {(void)sig;_exit(124);}
static int same_device(const struct stat *a, const struct stat *b)
{
    return S_ISCHR(a->st_mode) && S_ISCHR(b->st_mode) &&
        a->st_dev == b->st_dev && a->st_ino == b->st_ino && a->st_rdev == b->st_rdev;
}
static int result(const char *stage, int error, int second_error, int passed)
{
    printf("{\"passed\":%s,\"stage\":\"%s\",\"errno\":%d,\"second_open_errno\":%d,"
           "\"euid\":%lu,\"path\":\"/dev/tty.com.redhat.spice.0\","
           "\"device_bytes_read\":0,\"device_bytes_written\":0,"
           "\"scope\":\"exact node and later nonroot open exclusion only; prior owners not excluded\"}\n",
           passed ? "true" : "false", stage, error, second_error, (unsigned long)geteuid());
    return passed ? 0 : 2;
}
int main(int argc, char **argv)
{
    struct stat before, opened, after;
    struct sigaction action;
    int fd=-1, pipes[2], flags=O_RDWR|O_NONBLOCK|O_NOCTTY|O_CLOEXEC|O_NOFOLLOW;
    int rc, saved, child_status, second_error=-1;
    pid_t child;
    (void)argv;
    if (argc!=1) return result("arguments", EINVAL, -1, 0);
    if (geteuid()==0 || getuid()!=geteuid()) return result("requires-ordinary-nonroot-uid", EPERM, -1, 0);
    memset(&action,0,sizeof(action));action.sa_handler=timeout_handler;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGALRM,&action,NULL)) return result("alarm-handler",errno,-1,0);
    alarm(10);
    if (lstat(device_path,&before)) return result("lstat",errno,-1,0);
    if (!S_ISCHR(before.st_mode)) return result("not-character-device",EINVAL,-1,0);
    fd=open(device_path,flags);
    if (fd<0) return result("open",errno,-1,0);
    if (fstat(fd,&opened) || lstat(device_path,&after)) {
        saved=errno;close(fd);return result("identity-stat",saved,-1,0);
    }
    if (!same_device(&before,&opened) || !same_device(&opened,&after)) {
        close(fd);return result("identity-changed",ESTALE,-1,0);
    }
    if (ioctl(fd,TIOCEXCL)<0) {
        saved=errno;close(fd);return result("exclusive-unsupported-or-refused",saved,-1,0);
    }
    if (pipe(pipes)) {saved=errno;close(fd);return result("pipe",saved,-1,0);}
    child=fork();
    if (child<0) {
        saved=errno;close(pipes[0]);close(pipes[1]);close(fd);
        return result("fork",saved,-1,0);
    }
    if (child==0) {
        int other, outcome;
        close(pipes[0]);close(fd); /* Parent retains the exclusive descriptor. */
        action.sa_handler=child_timeout_handler;
        if (sigaction(SIGALRM,&action,NULL)) _exit(3);
        alarm(2); /* Child has an independent bound; no inherited parent alarm. */
        other=open(device_path,flags);outcome=other<0 ? errno : 0;
        if (other>=0) close(other);
        rc=write(pipes[1],&outcome,sizeof(outcome))==(ssize_t)sizeof(outcome) ? 0 : 3;
        close(pipes[1]);_exit(rc);
    }
    close(pipes[1]);
    ssize_t got;
    do {got=read(pipes[0],&second_error,sizeof(second_error));} while(got<0 && errno==EINTR);
    close(pipes[0]);
    do {rc=waitpid(child,&child_status,0);} while(rc<0 && errno==EINTR);
    if (got!=(ssize_t)sizeof(second_error) || rc!=child || !WIFEXITED(child_status) || WEXITSTATUS(child_status)!=0) {
        close(fd);return result("second-open-child-failed",EIO,second_error,0);
    }
    if (lstat(device_path,&after) || fstat(fd,&opened)) {
        saved=errno;close(fd);return result("final-identity-stat",saved,second_error,0);
    }
    if (!same_device(&before,&opened) || !same_device(&opened,&after)) {
        close(fd);return result("final-identity-changed",ESTALE,second_error,0);
    }
    rc=close(fd);saved=errno;alarm(0);
    if (rc) return result("close",saved,second_error,0);
    return result(second_error==EBUSY ? "exclusive-second-open-refused" : "exclusive-not-demonstrated",
                  0,second_error,second_error==EBUSY);
}
