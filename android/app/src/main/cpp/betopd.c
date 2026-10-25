/*
 * betopd —— 北通 BTP-V1T 安卓映射守护进程（root 专用）
 *
 * 等于安卓版的 ViGEm：
 *   1. root 直接读 /dev/input/eventN 的物理手柄原始事件
 *      （走 framework 的 KeyEvent 拿不到 FN 这类非标准键）
 *   2. 按映射表翻译：按键换码、轴线性缩放 + 反向 + 丢死区
 *   3. 写进 /dev/uinput，冒出一个标准 Android gamepad，游戏直接认
 *
 * 用法：
 *   betopd --probe <event节点>              列出这设备实际支持的按键/轴范围和名字
 *   betopd <event节点> <映射文件> [--grab] [--name 名字] [--hidraw <hidraw节点>]
 *
 * 跑起来后：
 *   stdout 每行一条文本："K <按键code> <0|1>" / "A <轴code> <值>" / "READY <名字>"
 *   （不用结构体传，是因为 input_event 在 32/64 位上大小不一样，容易对不上）
 *   stdin  收 "R <大马达0-255> <小马达0-255>\n"，转发给物理手柄 HID
 *          （命令格式是 PC 上实测出来的那条：report id 2 / b1=0x08 / b3=大 / b4=小）
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <linux/input.h>
#include <linux/uinput.h>

#ifndef BUS_VIRTUAL
#define BUS_VIRTUAL 0x06
#endif
#ifndef BTN_SOUTH
#define BTN_SOUTH 0x130
#define BTN_EAST  0x131
#define BTN_NORTH 0x133
#define BTN_WEST  0x134
#define BTN_TL    0x136
#define BTN_TR    0x137
#define BTN_TL2   0x138
#define BTN_TR2   0x139
#define BTN_SELECT 0x13a
#define BTN_START  0x13b
#define BTN_MODE   0x13c
#define BTN_THUMBL 0x13d
#define BTN_THUMBR 0x13e
#define BTN_DPAD_UP    0x220
#define BTN_DPAD_DOWN  0x221
#define BTN_DPAD_LEFT  0x222
#define BTN_DPAD_RIGHT 0x223
#endif

#define MAX_KEY 0x400
#define MAX_ABS 0x40

static int kmap[MAX_KEY];
static int amap[MAX_ABS];
static int ainvert[MAX_ABS];
static int pmin[MAX_ABS], pmax[MAX_ABS];       /* 物理设备的实际量程 */
static int vmin[MAX_ABS], vmax[MAX_ABS];       /* 输出轴的量程 */
static int last_out[MAX_ABS];
static volatile sig_atomic_t running = 1;

static void on_signal(int s) { (void)s; running = 0; }

/* 虚拟手柄支持的标准 gamepad 按键 */
static const int VKEYS[] = {
    BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST,
    BTN_TL, BTN_TR, BTN_TL2, BTN_TR2,
    BTN_SELECT, BTN_START, BTN_MODE,
    BTN_THUMBL, BTN_THUMBR,
    BTN_DPAD_UP, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT,
};
#define NVKEYS (int)(sizeof(VKEYS) / sizeof(VKEYS[0]))

static struct { int code, lo, hi, flat, fuzz; } VABS[] = {
    { ABS_X,    0, 65535, 4096, 16 },
    { ABS_Y,    0, 65535, 4096, 16 },
    { ABS_RX,   0, 65535, 4096, 16 },
    { ABS_RY,   0, 65535, 4096, 16 },
    { ABS_Z,    0, 255,   0,    0  },    /* LT */
    { ABS_RZ,   0, 255,   0,    0  },    /* RT */
    { ABS_HAT0X, -1, 1,   0,    0  },
    { ABS_HAT0Y, -1, 1,   0,    0  },
};
#define NVABS (int)(sizeof(VABS) / sizeof(VABS[0]))

static int vrange(int code, int *lo, int *hi) {
    for (int i = 0; i < NVABS; i++)
        if (VABS[i].code == code) { *lo = VABS[i].lo; *hi = VABS[i].hi; return 1; }
    return 0;
}

/* ---------------------------------------------------------- 探头模式 */
static int probe(const char *dev) {
    int fd = open(dev, O_RDONLY);
    if (fd < 0) { fprintf(stderr, "E open %s: %s\n", dev, strerror(errno)); return 1; }
    char name[256] = "", phys[256] = "", uniq[256] = "";
    struct input_id id;
    ioctl(fd, EVIOCGNAME(sizeof(name)), name);
    ioctl(fd, EVIOCGPHYS(sizeof(phys)), phys);
    ioctl(fd, EVIOCGUNIQ(sizeof(uniq)), uniq);
    ioctl(fd, EVIOCGID, &id);

    unsigned char bits[(MAX_KEY + 7) / 8];
    memset(bits, 0, sizeof(bits));
    ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(bits)), bits);
    unsigned char sbits[64];
    memset(sbits, 0, sizeof(sbits));
    ioctl(fd, EVIOCGBIT(EV_ABS, sizeof(sbits)), sbits);

    printf("NAME\t%s\n", name);
    printf("PHYS\t%s\n", phys);
    printf("UNIQ\t%s\n", uniq);
    printf("ID\tb%04x v%04x p%04x\n", id.bustype, id.vendor, id.product);
    for (int c = 0; c < MAX_KEY; c++)
        if (bits[c / 8] & (1u << (c % 8))) printf("KEY\t%d\n", c);
    for (int c = 0; c < MAX_ABS; c++) {
        if (!(sbits[c / 8] & (1u << (c % 8)))) continue;
        struct input_absinfo ai;
        if (ioctl(fd, EVIOCGABS(c), &ai) >= 0)
            printf("ABS\t%d\t%d\t%d\n", c, ai.minimum, ai.maximum);
    }
    printf("END\n");
    fflush(stdout);
    close(fd);
    return 0;
}

/* ---------------------------------------------------------- 读配置 */
static void load_conf(const char *path) {
    FILE *f = fopen(path, "r");
    char line[256];
    for (int i = 0; i < MAX_KEY; i++) kmap[i] = -2;
    for (int i = 0; i < MAX_ABS; i++) { amap[i] = -2; ainvert[i] = 0; }
    if (!f) return;
    while (fgets(line, sizeof(line), f)) {
        char t; int a, b;
        if (line[0] == '#' || line[0] == '\n') continue;
        if (sscanf(line, " %c %d %d", &t, &a, &b) != 3) continue;
        if (t == 'k' && a >= 0 && a < MAX_KEY) kmap[a] = b;
        else if (t == 'i' && a >= 0 && a < MAX_ABS) ainvert[a] = b;
        else if (t == 'a' && a >= 0 && a < MAX_ABS) amap[a] = b;
    }
    fclose(f);
}

/* ---------------------------------------------------------- uinput */
static void dpad_key(int ufd, int code, int down) {
    struct input_event e;
    memset(&e, 0, sizeof(e));
    e.type = EV_KEY; e.code = code; e.value = down ? 1 : 0;
    write(ufd, &e, sizeof(e));
    printf("K %d %d\n", code, down ? 1 : 0);
}

static int create_uinput(const char *name) {
    struct uinput_user_dev ud;
    int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    if (fd < 0) fd = open("/dev/input/uinput", O_WRONLY | O_NONBLOCK);
    if (fd < 0) return -1;

    ioctl(fd, UI_SET_EVBIT, EV_KEY);
    ioctl(fd, UI_SET_EVBIT, EV_ABS);
    ioctl(fd, UI_SET_EVBIT, EV_SYN);
    for (int i = 0; i < NVKEYS; i++) ioctl(fd, UI_SET_KEYBIT, VKEYS[i]);
    for (int i = 0; i < NVABS; i++) ioctl(fd, UI_SET_ABSBIT, VABS[i].code);

    memset(&ud, 0, sizeof(ud));
    strncpy(ud.name, name, UINPUT_MAX_NAME_SIZE - 1);
    ud.id.bustype = BUS_VIRTUAL;
    ud.id.vendor = 0x20bc; ud.id.product = 0x503c; ud.id.version = 1;
    for (int i = 0; i < NVABS; i++) {
        int c = VABS[i].code;
        if (c > ABS_MAX) continue;
        ud.absmax[c] = VABS[i].hi;
        ud.absmin[c] = VABS[i].lo;
        ud.absflat[c] = VABS[i].flat;
        ud.absfuzz[c] = VABS[i].fuzz;
    }
    if (write(fd, &ud, sizeof(ud)) < 0) { perror("write uinput_user_dev"); close(fd); return -1; }
    if (ioctl(fd, UI_DEV_CREATE) < 0) { perror("UI_DEV_CREATE"); close(fd); return -1; }
    return fd;
}

/* ---------------------------------------------------------- 震动转发 */
static int hid_fd = -1;
static unsigned char r_big = 0, r_small = 0;
static int r_active = 0;

static void rumble_send(int again) {
    if (hid_fd < 0) return;
    unsigned char buf[64];
    memset(buf, 0, sizeof(buf));
    buf[0] = 0x02;                 /* HID report id —— 写别的 id 会报 err 87 */
    buf[1] = 0x08;                 /* 命令头，PC 上穷举出来的唯一有效值 */
    buf[3] = r_big;
    buf[4] = r_small;
    ssize_t n = write(hid_fd, buf, sizeof(buf));
    (void)again;
    if (n < 0 && errno != EAGAIN) fprintf(stderr, "W rumble write: %s\n", strerror(errno));
}

/* ---------------------------------------------------------- 主流程 */
int main(int argc, char **argv) {
    if (argc >= 3 && !strcmp(argv[1], "--probe")) return probe(argv[2]);
    if (argc < 3) {
        fprintf(stderr,
            "usage: %s <event节点> <映射文件> [--grab] [--name 名字] [--hidraw 节点]\n"
            "       %s --probe <event节点>\n", argv[0], argv[0]);
        return 2;
    }

    const char *dev = argv[1];
    load_conf(argv[2]);
    int grab = 0;
    const char *name = "Betop Virtual Gamepad";
    for (int i = 3; i < argc; i++) {
        if (!strcmp(argv[i], "--grab")) grab = 1;
        else if (!strcmp(argv[i], "--name") && i + 1 < argc) name = argv[++i];
        else if (!strcmp(argv[i], "--hidraw") && i + 1 < argc) {
            hid_fd = open(argv[++i], O_WRONLY | O_NONBLOCK);
            if (hid_fd < 0) fprintf(stderr, "W hidraw %s: %s\n", argv[i], strerror(errno));
        }
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGPIPE, SIG_IGN);

    int pfd = open(dev, O_RDONLY | O_CLOEXEC);
    if (pfd < 0) { fprintf(stderr, "E open %s: %s\n", dev, strerror(errno)); return 1; }

    /* 物理量程：摇杆是 0..255，虚拟轴是 0..65535，必须按各自量程线性换算 */
    for (int c = 0; c < MAX_ABS; c++) {
        struct input_absinfo ai;
        pmin[c] = 0; pmax[c] = 255;
        if (ioctl(pfd, EVIOCGABS(c), &ai) >= 0) { pmin[c] = ai.minimum; pmax[c] = ai.maximum; }
        int dst = (amap[c] == -2) ? c : amap[c];
        if (dst == -1 || !vrange(dst, &vmin[c], &vmax[c])) { vmin[c] = 0; vmax[c] = 255; }
        last_out[c] = 1 << 30;
    }
    for (int c = 0; c < MAX_KEY; c++) if (kmap[c] == -2) kmap[c] = c;
    for (int c = 0; c < MAX_ABS; c++) if (amap[c] == -2) amap[c] = c;

    if (grab) ioctl(pfd, EVIOCGRAB, 1);

    int ufd = create_uinput(name);
    if (ufd < 0) {
        fprintf(stderr, "E uinput: %s（内核没开 CONFIG_INPUT_UINPUT 就不行）\n", strerror(errno));
        ioctl(pfd, EVIOCGRAB, 0); close(pfd);
        return 1;
    }
    fprintf(stderr, "betopd up: %s -> %s%s\n", dev, name,
            hid_fd >= 0 ? " (hidraw 震动已接)" : "");
    fflush(stderr);
    printf("READY\t%s\n", name); fflush(stdout);

    struct input_event ev[32];
    struct pollfd pfds[2];
    char cmd[64]; size_t cmdlen = 0;
    int dead = 0;

    while (running) {
        pfds[0].fd = pfd; pfds[0].events = POLLIN; pfds[0].revents = 0;
        pfds[1].fd = STDIN_FILENO; pfds[1].events = POLLIN; pfds[1].revents = 0;
        int r = poll(pfds, 2, 100);          /* 100ms 给rumble 心跳留机会 */
        if (r < 0) { if (errno == EINTR) continue; break; }

        /* 震动脉冲：固件收到命令震一下就衰减，得一直补发 */
        if (r_active) {
            if (dead++ >= 1) { rumble_send(1); dead = 0; }
        }

        if (pfds[1].revents & POLLIN) {
            ssize_t n = read(STDIN_FILENO, cmd + cmdlen, sizeof(cmd) - 1 - cmdlen);
            if (n <= 0) break;
            cmdlen += n;
            cmd[cmdlen] = 0;
            char *nl;
            while ((nl = strchr(cmd, '\n'))) {
                *nl = 0;
                int big = 0, small = 0;
                if (sscanf(cmd, "R %d %d", &big, &small) == 2) {
                    r_big = big & 0xff; r_small = small & 0xff;
                    r_active = (big > 0 || small > 0);
                    rumble_send(0);
                    if (!r_active) { r_big = r_small = 0; rumble_send(0); }
                }
                size_t left = strlen(nl + 1);
                memmove(cmd, nl + 1, left + 1);
                cmdlen = left;
            }
            if (cmdlen >= sizeof(cmd) - 2) cmdlen = 0;
        }

        if (pfds[0].revents & POLLIN) {
            ssize_t n = read(pfd, ev, sizeof(ev));
            if (n <= 0) { if (errno == EINTR) continue; break; }
            int cnt = (int)(n / sizeof(struct input_event));
            struct input_event out[64]; int osrc[64]; int no = 0;
            for (int i = 0; i < cnt; i++) {
                struct input_event *e = &ev[i];
                if (e->type == EV_KEY) {
                    int src = e->code, dst = (src < MAX_KEY) ? kmap[src] : -1;
                    if (dst == -1) continue;
                    out[no] = *e; out[no].code = dst; osrc[no] = src; no++;
                } else if (e->type == EV_ABS) {
                    int src = e->code;
                    if (src >= MAX_ABS) continue;
                    int dst = amap[src];
                    if (dst == -1) continue;
                    long span = (long)pmax[src] - pmin[src];
                    long vlo = vmin[src], vhi = vmax[src];
                    long vv;
                    if (span <= 0) vv = e->value;
                    else {
                        double t = (double)(e->value - pmin[src]) / (double)span;
                        if (t < 0) t = 0; if (t > 1) t = 1;
                        if (ainvert[src]) t = 1.0 - t;
                        vv = vlo + (long)(t * (double)(vhi - vlo) + 0.5);
                    }
                    if (last_out[src] == vv) continue;
                    last_out[src] = (int)vv;
                    out[no].type = EV_ABS; out[no].code = dst; out[no].value = (int)vv;
                    osrc[no] = src; no++;
                }
                if (no >= 60) break;
            }
            /* 真正的输出 + 同步 + 回传给 App 画界面 */
            struct input_event syn;
            memset(&syn, 0, sizeof(syn));
            syn.type = EV_SYN; syn.code = SYN_REPORT; syn.value = 0;
            int need_syn = 0;
            for (int i = 0; i < no; i++) {
                if (write(ufd, &out[i], sizeof(out[i])) < 0) { running = 0; break; }
                need_syn = 1;
                /* 回传给 App 画界面：文本，别用结构体（32/64 位大小不一样）。
                   这里刻意报【原始】键码 —— App 拿着映射表自己换算，
                   改键时才能知道按下的是物理上哪个键 */
                printf("%c %d %d\n", out[i].type == EV_KEY ? 'K' : 'A',
                       osrc[i], out[i].value);
                /* 十字键：物理是 HAT 轴，顺手合成一组 DPAD 按键，
                   有些游戏只读按键不读轴 */
                if (out[i].type == EV_ABS &&
                    (out[i].code == ABS_HAT0X || out[i].code == ABS_HAT0Y)) {
                    int v = out[i].value;
                    if (out[i].code == ABS_HAT0X) {
                        dpad_key(ufd, BTN_DPAD_LEFT,  v < 0);
                        dpad_key(ufd, BTN_DPAD_RIGHT, v > 0);
                    } else {
                        dpad_key(ufd, BTN_DPAD_UP,    v < 0);
                        dpad_key(ufd, BTN_DPAD_DOWN,  v > 0);
                    }
                    need_syn = 1;
                }
            }
            if (need_syn) write(ufd, &syn, sizeof(syn));
            fflush(stdout);
        }
    }

    if (r_active) { r_big = r_small = 0; r_active = 0; rumble_send(0); }
    ioctl(pfd, EVIOCGRAB, 0);
    close(pfd);
    ioctl(ufd, UI_DEV_DESTROY);
    close(ufd);
    if (hid_fd >= 0) close(hid_fd);
    return 0;
}
