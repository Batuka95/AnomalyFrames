#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <signal.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#define UINPUT_SOCKET_NAME "uinputd"
#define MAX_EVENT_SCAN 256
#define MAX_LINE 256
#define MT_SLOT 0
#define MT_SLOT_MAX 31
#define TRACKING_ID_MAX 65535
#define ARRAY_LEN(a) (sizeof(a) / sizeof((a)[0]))

#define BITS_PER_LONG (sizeof(unsigned long) * 8U)
#define NBITS(x) ((((x) - 1U) / BITS_PER_LONG) + 1U)
#define BIT_WORD(x) ((x) / BITS_PER_LONG)
#define BIT_MASK(x) (1UL << ((x) % BITS_PER_LONG))

typedef struct AbsRange {
    int32_t x_min;
    int32_t x_max;
    int32_t y_min;
    int32_t y_max;
} AbsRange;

typedef struct TouchState {
    int down;
    int32_t x;
    int32_t y;
    int32_t next_tracking_id;
} TouchState;

static const uint16_t g_supported_keys[] = {
    KEY_A, KEY_B, KEY_C, KEY_D, KEY_E, KEY_F, KEY_G, KEY_H, KEY_I, KEY_J, KEY_K, KEY_L, KEY_M,
    KEY_N, KEY_O, KEY_P, KEY_Q, KEY_R, KEY_S, KEY_T, KEY_U, KEY_V, KEY_W, KEY_X, KEY_Y, KEY_Z,
    KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9, KEY_0,
    KEY_MINUS, KEY_SPACE, KEY_ENTER, KEY_BACKSPACE, KEY_LEFTSHIFT
};

static volatile sig_atomic_t g_stop = 0;
static int g_uinput_fd = -1;
static int g_device_created = 0;

static void on_signal(int signo) {
    (void) signo;
    g_stop = 1;
}

static int bit_is_set(const unsigned long *bits, int code) {
    return (bits[BIT_WORD((unsigned) code)] & BIT_MASK((unsigned) code)) != 0UL;
}

static int clamp_i32(int v, int lo, int hi) {
    if (v < lo) {
        return lo;
    }
    if (v > hi) {
        return hi;
    }
    return v;
}

static int emit_event(int fd, uint16_t type, uint16_t code, int32_t value) {
    struct input_event ev;
    memset(&ev, 0, sizeof(ev));
    ev.type = type;
    ev.code = code;
    ev.value = value;
    if (write(fd, &ev, sizeof(ev)) != (ssize_t) sizeof(ev)) {
        return -1;
    }
    return 0;
}

static int emit_syn(int fd) {
    return emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

static int has_touch_capabilities(int fd) {
    unsigned long prop_bits[NBITS(INPUT_PROP_MAX + 1)];
    unsigned long abs_bits[NBITS(ABS_MAX + 1)];
    memset(prop_bits, 0, sizeof(prop_bits));
    memset(abs_bits, 0, sizeof(abs_bits));

    if (ioctl(fd, EVIOCGPROP(sizeof(prop_bits)), prop_bits) < 0) {
        return 0;
    }
    if (!bit_is_set(prop_bits, INPUT_PROP_DIRECT)) {
        return 0;
    }
    if (ioctl(fd, EVIOCGBIT(EV_ABS, sizeof(abs_bits)), abs_bits) < 0) {
        return 0;
    }
    if (!bit_is_set(abs_bits, ABS_MT_POSITION_X) || !bit_is_set(abs_bits, ABS_MT_POSITION_Y)) {
        return 0;
    }
    return 1;
}

static int discover_abs_range(AbsRange *out) {
    char path[64];

    for (int i = 0; i < MAX_EVENT_SCAN; i++) {
        int fd;
        struct input_absinfo abs_x;
        struct input_absinfo abs_y;

        snprintf(path, sizeof(path), "/dev/input/event%d", i);
        fd = open(path, O_RDONLY | O_CLOEXEC);
        if (fd < 0) {
            continue;
        }

        if (!has_touch_capabilities(fd)) {
            close(fd);
            continue;
        }

        memset(&abs_x, 0, sizeof(abs_x));
        memset(&abs_y, 0, sizeof(abs_y));
        if (ioctl(fd, EVIOCGABS(ABS_MT_POSITION_X), &abs_x) == 0 &&
            ioctl(fd, EVIOCGABS(ABS_MT_POSITION_Y), &abs_y) == 0 &&
            abs_x.maximum > abs_x.minimum &&
            abs_y.maximum > abs_y.minimum) {
            out->x_min = abs_x.minimum;
            out->x_max = abs_x.maximum;
            out->y_min = abs_y.minimum;
            out->y_max = abs_y.maximum;
            close(fd);
            return 0;
        }

        close(fd);
    }

    return -1;
}

static int create_uinput_device(const AbsRange *range) {
    struct uinput_user_dev dev;

    g_uinput_fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK | O_CLOEXEC);
    if (g_uinput_fd < 0) {
        fprintf(stderr, "fatal: open /dev/uinput failed: %s\n", strerror(errno));
        return -1;
    }

    if (ioctl(g_uinput_fd, UI_SET_EVBIT, EV_SYN) < 0 ||
        ioctl(g_uinput_fd, UI_SET_EVBIT, EV_KEY) < 0 ||
        ioctl(g_uinput_fd, UI_SET_EVBIT, EV_ABS) < 0 ||
        ioctl(g_uinput_fd, UI_SET_ABSBIT, ABS_MT_SLOT) < 0 ||
        ioctl(g_uinput_fd, UI_SET_ABSBIT, ABS_MT_TRACKING_ID) < 0 ||
        ioctl(g_uinput_fd, UI_SET_ABSBIT, ABS_MT_POSITION_X) < 0 ||
        ioctl(g_uinput_fd, UI_SET_ABSBIT, ABS_MT_POSITION_Y) < 0 ||
        ioctl(g_uinput_fd, UI_SET_ABSBIT, ABS_X) < 0 ||
        ioctl(g_uinput_fd, UI_SET_ABSBIT, ABS_Y) < 0) {
        fprintf(stderr, "fatal: uinput bit configuration failed: %s\n", strerror(errno));
        return -1;
    }

    if (ioctl(g_uinput_fd, UI_SET_KEYBIT, BTN_TOUCH) < 0 ||
        ioctl(g_uinput_fd, UI_SET_KEYBIT, BTN_TOOL_FINGER) < 0) {
        fprintf(stderr, "fatal: touch key-bit configuration failed: %s\n", strerror(errno));
        return -1;
    }
    for (size_t i = 0; i < ARRAY_LEN(g_supported_keys); i++) {
        if (ioctl(g_uinput_fd, UI_SET_KEYBIT, g_supported_keys[i]) < 0) {
            fprintf(stderr, "fatal: key-bit configuration failed for code %u: %s\n",
                    (unsigned) g_supported_keys[i], strerror(errno));
            return -1;
        }
    }

#ifdef UI_SET_PROPBIT
    (void) ioctl(g_uinput_fd, UI_SET_PROPBIT, INPUT_PROP_DIRECT);
#endif

    memset(&dev, 0, sizeof(dev));
    snprintf(dev.name, UINPUT_MAX_NAME_SIZE, "uinputd-virtual-touchscreen");
    dev.id.bustype = BUS_VIRTUAL;
    dev.id.vendor = 0x18d1;
    dev.id.product = 0x4ee0;
    dev.id.version = 1;

    dev.absmin[ABS_MT_SLOT] = 0;
    dev.absmax[ABS_MT_SLOT] = MT_SLOT_MAX;
    dev.absmin[ABS_MT_TRACKING_ID] = 0;
    dev.absmax[ABS_MT_TRACKING_ID] = TRACKING_ID_MAX;
    dev.absmin[ABS_MT_POSITION_X] = range->x_min;
    dev.absmax[ABS_MT_POSITION_X] = range->x_max;
    dev.absmin[ABS_MT_POSITION_Y] = range->y_min;
    dev.absmax[ABS_MT_POSITION_Y] = range->y_max;
    dev.absmin[ABS_X] = range->x_min;
    dev.absmax[ABS_X] = range->x_max;
    dev.absmin[ABS_Y] = range->y_min;
    dev.absmax[ABS_Y] = range->y_max;

    if (write(g_uinput_fd, &dev, sizeof(dev)) != (ssize_t) sizeof(dev)) {
        fprintf(stderr, "fatal: write uinput_user_dev failed: %s\n", strerror(errno));
        return -1;
    }

    if (ioctl(g_uinput_fd, UI_DEV_CREATE) < 0) {
        fprintf(stderr, "fatal: UI_DEV_CREATE failed: %s\n", strerror(errno));
        return -1;
    }

    g_device_created = 1;
    return 0;
}

static void destroy_uinput_device(void) {
    if (g_uinput_fd >= 0) {
        if (g_device_created) {
            (void) ioctl(g_uinput_fd, UI_DEV_DESTROY);
        }
        close(g_uinput_fd);
    }
    g_uinput_fd = -1;
    g_device_created = 0;
}

static int touch_down(TouchState *state, const AbsRange *range, int x, int y) {
    x = clamp_i32(x, range->x_min, range->x_max);
    y = clamp_i32(y, range->y_min, range->y_max);

    if (state->next_tracking_id <= 0 || state->next_tracking_id > TRACKING_ID_MAX) {
        state->next_tracking_id = 1;
    }

    if (emit_event(g_uinput_fd, EV_ABS, ABS_MT_SLOT, MT_SLOT) < 0 ||
        emit_event(g_uinput_fd, EV_ABS, ABS_MT_TRACKING_ID, state->next_tracking_id++) < 0 ||
        emit_event(g_uinput_fd, EV_ABS, ABS_MT_POSITION_X, x) < 0 ||
        emit_event(g_uinput_fd, EV_ABS, ABS_MT_POSITION_Y, y) < 0 ||
        emit_event(g_uinput_fd, EV_ABS, ABS_X, x) < 0 ||
        emit_event(g_uinput_fd, EV_ABS, ABS_Y, y) < 0 ||
        emit_event(g_uinput_fd, EV_KEY, BTN_TOUCH, 1) < 0 ||
        emit_event(g_uinput_fd, EV_KEY, BTN_TOOL_FINGER, 1) < 0 ||
        emit_syn(g_uinput_fd) < 0) {
        return -1;
    }

    state->down = 1;
    state->x = x;
    state->y = y;
    return 0;
}

static int touch_move(TouchState *state, const AbsRange *range, int x, int y) {
    if (!state->down) {
        return -1;
    }

    x = clamp_i32(x, range->x_min, range->x_max);
    y = clamp_i32(y, range->y_min, range->y_max);

    if (emit_event(g_uinput_fd, EV_ABS, ABS_MT_SLOT, MT_SLOT) < 0 ||
        emit_event(g_uinput_fd, EV_ABS, ABS_MT_POSITION_X, x) < 0 ||
        emit_event(g_uinput_fd, EV_ABS, ABS_MT_POSITION_Y, y) < 0 ||
        emit_event(g_uinput_fd, EV_ABS, ABS_X, x) < 0 ||
        emit_event(g_uinput_fd, EV_ABS, ABS_Y, y) < 0 ||
        emit_syn(g_uinput_fd) < 0) {
        return -1;
    }

    state->x = x;
    state->y = y;
    return 0;
}

static int touch_up(TouchState *state) {
    if (!state->down) {
        return 0;
    }

    if (emit_event(g_uinput_fd, EV_ABS, ABS_MT_SLOT, MT_SLOT) < 0 ||
        emit_event(g_uinput_fd, EV_ABS, ABS_MT_TRACKING_ID, -1) < 0 ||
        emit_event(g_uinput_fd, EV_KEY, BTN_TOUCH, 0) < 0 ||
        emit_event(g_uinput_fd, EV_KEY, BTN_TOOL_FINGER, 0) < 0 ||
        emit_syn(g_uinput_fd) < 0) {
        return -1;
    }

    state->down = 0;
    return 0;
}

static int key_event(int key_code, int value) {
    if (key_code < 0 || key_code > KEY_MAX) {
        return -1;
    }
    if (value < 0 || value > 2) {
        return -1;
    }
    if (emit_event(g_uinput_fd, EV_KEY, (uint16_t) key_code, value) < 0 ||
        emit_syn(g_uinput_fd) < 0) {
        return -1;
    }
    return 0;
}

static int read_line_fd(int fd, char *buf, size_t cap) {
    size_t n = 0;

    while (n + 1 < cap) {
        char c;
        ssize_t r = read(fd, &c, 1);
        if (r == 0) {
            if (n == 0) {
                return 0;
            }
            break;
        }
        if (r < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        if (c == '\n') {
            break;
        }
        if (c != '\r') {
            buf[n++] = c;
        }
    }

    buf[n] = '\0';
    return (int) n;
}

static int handle_client(int cfd, const AbsRange *range) {
    TouchState state;
    char line[MAX_LINE];

    memset(&state, 0, sizeof(state));
    state.next_tracking_id = 1;

    for (;;) {
        int len = read_line_fd(cfd, line, sizeof(line));
        int x = 0;
        int y = 0;
        int key_code = 0;
        int key_value = 0;

        if (len == 0) {
            return 0;
        }
        if (len < 0) {
            return -1;
        }

        if (strcmp(line, "HELLO") == 0) {
            dprintf(cfd, "OK %d %d %d %d\n", range->x_min, range->x_max, range->y_min, range->y_max);
            continue;
        }
        if (sscanf(line, "DOWN %d %d", &x, &y) == 2) {
            if (touch_down(&state, range, x, y) == 0) {
                dprintf(cfd, "OK\n");
            } else {
                dprintf(cfd, "ERR down\n");
            }
            continue;
        }
        if (sscanf(line, "MOVE %d %d", &x, &y) == 2) {
            if (touch_move(&state, range, x, y) == 0) {
                dprintf(cfd, "OK\n");
            } else {
                dprintf(cfd, "ERR move\n");
            }
            continue;
        }
        if (strcmp(line, "UP") == 0) {
            if (touch_up(&state) == 0) {
                dprintf(cfd, "OK\n");
            } else {
                dprintf(cfd, "ERR up\n");
            }
            continue;
        }
        if (sscanf(line, "KEY %d %d", &key_code, &key_value) == 2) {
            if (key_event(key_code, key_value) == 0) {
                dprintf(cfd, "OK\n");
            } else {
                dprintf(cfd, "ERR key\n");
            }
            continue;
        }
        if (strcmp(line, "QUIT") == 0) {
            (void) touch_up(&state);
            dprintf(cfd, "BYE\n");
            return 1;
        }

        dprintf(cfd, "ERR unknown\n");
    }
}

static int create_server_socket(void) {
    int sfd;
    struct sockaddr_un addr;
    size_t name_len = strlen(UINPUT_SOCKET_NAME);
    socklen_t addr_len;

    sfd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (sfd < 0) {
        return -1;
    }

    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    addr.sun_path[0] = '\0';
    memcpy(addr.sun_path + 1, UINPUT_SOCKET_NAME, name_len);
    addr_len = (socklen_t) (offsetof(struct sockaddr_un, sun_path) + 1 + name_len);

    if (bind(sfd, (struct sockaddr *) &addr, addr_len) < 0) {
        close(sfd);
        return -1;
    }
    if (listen(sfd, 1) < 0) {
        close(sfd);
        return -1;
    }

    return sfd;
}

static int run_server(const AbsRange *range) {
    int sfd = create_server_socket();
    if (sfd < 0) {
        fprintf(stderr, "fatal: socket setup failed: %s\n", strerror(errno));
        return -1;
    }

    while (!g_stop) {
        int cfd = accept(sfd, NULL, NULL);
        if (cfd < 0) {
            if (errno == EINTR) {
                continue;
            }
            close(sfd);
            fprintf(stderr, "fatal: accept failed: %s\n", strerror(errno));
            return -1;
        }

        int rc = handle_client(cfd, range);
        close(cfd);
        if (rc > 0) {
            break;
        }
    }

    close(sfd);
    return 0;
}

static int daemonize_process(void) {
    pid_t pid = fork();
    int nullfd;

    if (pid < 0) {
        return -1;
    }
    if (pid > 0) {
        _exit(0);
    }

    if (setsid() < 0) {
        return -1;
    }

    pid = fork();
    if (pid < 0) {
        return -1;
    }
    if (pid > 0) {
        _exit(0);
    }

    if (chdir("/") < 0) {
        return -1;
    }

    nullfd = open("/dev/null", O_RDWR);
    if (nullfd < 0) {
        return -1;
    }

    if (dup2(nullfd, STDIN_FILENO) < 0 ||
        dup2(nullfd, STDOUT_FILENO) < 0 ||
        dup2(nullfd, STDERR_FILENO) < 0) {
        close(nullfd);
        return -1;
    }

    if (nullfd > STDERR_FILENO) {
        close(nullfd);
    }

    return 0;
}

static int run_selftest(void) {
    AbsRange range;

    if (discover_abs_range(&range) < 0) {
        fprintf(stderr, "fatal: could not discover touchscreen abs ranges\n");
        return 1;
    }
    if (create_uinput_device(&range) < 0) {
        destroy_uinput_device();
        return 1;
    }

    destroy_uinput_device();
    return 0;
}

int main(int argc, char **argv) {
    int opt_daemon = 0;
    int opt_selftest = 0;
    AbsRange range;
    int rc;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--selftest") == 0) {
            opt_selftest = 1;
        } else if (strcmp(argv[i], "--daemon") == 0) {
            opt_daemon = 1;
        } else {
            fprintf(stderr, "fatal: unknown option: %s\n", argv[i]);
            return 2;
        }
    }

    if (opt_selftest) {
        return run_selftest();
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGPIPE, SIG_IGN);

    if (discover_abs_range(&range) < 0) {
        fprintf(stderr, "fatal: could not discover touchscreen abs ranges\n");
        return 1;
    }

    if (opt_daemon && daemonize_process() < 0) {
        fprintf(stderr, "fatal: daemonize failed: %s\n", strerror(errno));
        return 1;
    }

    if (create_uinput_device(&range) < 0) {
        destroy_uinput_device();
        return 1;
    }

    if (!opt_daemon) {
        printf("ready\n");
        fflush(stdout);
    }

    rc = run_server(&range);
    destroy_uinput_device();

    return rc == 0 ? 0 : 1;
}
