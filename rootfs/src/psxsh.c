/* psxsh - init, shell and small utilities for PSXLinux (uClinux 2.4, bFLT binaries), no libc.
 *
 * One binary, several names (hard links): /sbin/init, /bin/sh, /bin/ls, /bin/cat...
 * In the shell every applet is a builtin; a path (/bin/ls) runs it as a real process (vfork+execve).
 * As init (pid 1): mounts /proc, remounts / read-write, takes the serial port as controlling tty
 * (Ctrl-C then kills the foreground programs, init ignores it), runs /etc/rc, then the shell.
 */

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef unsigned int size_t;

extern long __sc(long n, long a, long b, long c, long d, long e);
extern int spawn(const char *path, char **argv, char **envp);

#define S0(n) __sc(n, 0, 0, 0, 0, 0)
#define S1(n, a) __sc(n, (long)(a), 0, 0, 0, 0)
#define S2(n, a, b) __sc(n, (long)(a), (long)(b), 0, 0, 0)
#define S3(n, a, b, c) __sc(n, (long)(a), (long)(b), (long)(c), 0, 0)
#define S4(n, a, b, c, d) __sc(n, (long)(a), (long)(b), (long)(c), (long)(d), 0)
#define S5(n, a, b, c, d, e) __sc(n, (long)(a), (long)(b), (long)(c), (long)(d), (long)(e))

enum {
    NR_exit = 1, NR_read = 3, NR_write = 4, NR_open = 5, NR_close = 6, NR_link = 9, NR_unlink = 10,
    NR_chdir = 12, NR_mknod = 14, NR_chmod = 15, NR_getpid = 20, NR_mount = 21, NR_access = 33,
    NR_sync = 36, NR_kill = 37, NR_rename = 38, NR_mkdir = 39, NR_rmdir = 40, NR_dup = 41,
    NR_umount = 52, NR_dup2 = 63, NR_setsid = 66, NR_sethostname = 74, NR_symlink = 83,
    NR_readlink = 85, NR_reboot = 88, NR_statfs = 99, NR_syslog = 103, NR_stat = 106, NR_lstat = 107,
    NR_wait4 = 114, NR_sysinfo = 116, NR_uname = 122, NR_getdents = 141, NR_nanosleep = 162,
    NR_getcwd = 183
};

#define O_RDONLY 0
#define O_WRONLY 1
#define O_RDWR 2
#define O_APPEND 0x8
#define O_CREAT 0x100
#define O_TRUNC 0x200
#define O_NOCTTY 0x800
#define O_DIRECTORY 0x10000

#define S_IFMT 0170000
#define S_IFSOCK 0140000
#define S_IFLNK 0120000
#define S_IFREG 0100000
#define S_IFBLK 0060000
#define S_IFDIR 0040000
#define S_IFCHR 0020000
#define S_IFIFO 0010000

struct kstat {                      /* asm-mipsnommu/stat.h */
    u32 st_dev; long pad1[3]; u32 st_ino; u32 st_mode; int st_nlink; int st_uid; int st_gid;
    u32 st_rdev; long pad2[2]; long st_size; long pad3; long st_atime, r0, st_mtime, r1, st_ctime, r2;
    long st_blksize, st_blocks; long pad4[14];
};
struct kdirent { long d_ino; long d_off; u16 d_reclen; char d_name[1]; };
struct ksysinfo {
    long uptime; u32 loads[3]; u32 totalram, freeram, sharedram, bufferram, totalswap, freeswap;
    u16 procs; u32 totalhigh, freehigh, mem_unit; char pad[8];
};
struct kstatfs { long f_type, f_bsize, f_frsize, f_blocks, f_bfree, f_files, f_ffree, f_bavail, fsid[2], f_namelen, spare[6]; };
struct timespec_ { long s, ns; };

static char *envp_g[] = { "PATH=/bin:/sbin", "HOME=/", "TERM=vt100", 0 };
static int is_init, laststatus;

/* ------------------------------------------------------------------ libc bits */
void *memcpy(void *d, const void *s, size_t n) { u8 *D = d; const u8 *S = s; while (n--) *D++ = *S++; return d; }
void *memset(void *d, int c, size_t n) { u8 *D = d; while (n--) *D++ = (u8)c; return d; }
size_t strlen(const char *s) { size_t n = 0; while (s[n]) n++; return n; }
static int scmp(const char *a, const char *b) { while (*a && *a == *b) { a++; b++; } return (u8)*a - (u8)*b; }
static int sncmp(const char *a, const char *b, int n) { while (n && *a && *a == *b) { a++; b++; n--; } return n ? (u8)*a - (u8)*b : 0; }
static char *scpy(char *d, const char *s) { while ((*d = *s)) { d++; s++; } return d; }
static int atoi_(const char *s) { int v = 0, neg = 0; if (*s == '-') { neg = 1; s++; } while (*s >= '0' && *s <= '9') v = v * 10 + *s++ - '0'; return neg ? -v : v; }
static int isnum(const char *s) { if (!*s) return 0; while (*s) if (*s < '0' || *s++ > '9') return 0; return 1; }
static const char *base(const char *p) { const char *b = p; while (*p) if (*p++ == '/') b = p; return b; }

static int open_(const char *p, int fl, int mode) { return S3(NR_open, p, fl, mode); }
static int close_(int fd) { return S1(NR_close, fd); }
static int read_(int fd, void *b, int n) { return S3(NR_read, fd, b, n); }
static int write_(int fd, const void *b, int n) { return S3(NR_write, fd, b, n); }
static void sleep_ms(int ms) { struct timespec_ t = { ms / 1000, (ms % 1000) * 1000000 }; S2(NR_nanosleep, &t, 0); }

/* ------------------------------------------------------------------ output */
/* Buffer reached through one "la" (lui+addiu side by side): the bFLT loader needs every LO16
 * right after its own HI16, and GCC would otherwise share one HI16 between olen and obuf. */
static struct { int len, fd; char buf[256]; } ost __attribute__((used)) = { 0, 1, "" };
static inline __typeof__(ost) *O(void) { __typeof__(ost) *p; __asm__("la %0, ost" : "=r"(p)); return p; }
static void flush(void) {
    __typeof__(ost) *p = O();
    int o = 0;
    while (o < p->len) { int r = write_(p->fd, p->buf + o, p->len - o); if (r <= 0) break; o += r; }
    p->len = 0;
}
static void outc(int c) { __typeof__(ost) *p = O(); if (p->len == (int)sizeof p->buf) { flush(); } p->buf[p->len++] = (char)c; }
static void outs(const char *s) { while (*s) outc(*s++); }

static void vpf(const char *f, __builtin_va_list ap) {
    for (; *f; f++) {
        if (*f != '%') { outc(*f); continue; }
        f++;
        int left = 0, zero = 0, w = 0, n = 0;
        if (*f == '-') { left = 1; f++; }
        if (*f == '0') { zero = 1; f++; }
        while (*f >= '0' && *f <= '9') w = w * 10 + *f++ - '0';
        char tmp[12];
        const char *s = tmp;
        switch (*f) {
        case 's': s = __builtin_va_arg(ap, const char *); if (!s) s = "(null)"; n = strlen(s); break;
        case 'c': tmp[0] = (char)__builtin_va_arg(ap, int); n = 1; break;
        case 'd': case 'u': case 'x': case 'o': {
            u32 v = __builtin_va_arg(ap, u32), b = *f == 'x' ? 16 : *f == 'o' ? 8 : 10;
            int neg = *f == 'd' && (int)v < 0;
            if (neg) v = -v;
            char *p = tmp + 12;
            do { *--p = "0123456789abcdef"[v % b]; v /= b; } while (v);
            if (neg) *--p = '-';
            s = p; n = tmp + 12 - p;
            break;
        }
        default: tmp[0] = *f; n = 1; break;
        }
        if (!left) while (w > n) { outc(zero ? '0' : ' '); w--; }
        for (int i = 0; i < n; i++) outc(s[i]);
        if (left) while (w > n) { outc(' '); w--; }
    }
}
static void pf(const char *f, ...) { __builtin_va_list ap; __builtin_va_start(ap, f); vpf(f, ap); __builtin_va_end(ap); }

static const char *errstr(int e) {
    switch (e) {
    case 1: return "operation not permitted";   case 2: return "no such file or directory";
    case 3: return "no such process";           case 4: return "interrupted";
    case 5: return "I/O error";                 case 6: return "no such device or address";
    case 7: return "argument list too long";    case 8: return "exec format error";
    case 9: return "bad file descriptor";       case 10: return "no child processes";
    case 11: return "try again";                case 12: return "out of memory";
    case 13: return "permission denied";        case 14: return "bad address";
    case 16: return "device or resource busy";  case 17: return "file exists";
    case 18: return "cross-device link";        case 19: return "no such device";
    case 20: return "not a directory";          case 21: return "is a directory";
    case 22: return "invalid argument";         case 24: return "too many open files";
    case 25: return "not a tty";                case 26: return "text file busy";
    case 27: return "file too large";           case 28: return "no space left on device";
    case 30: return "read-only file system";    case 31: return "too many links";
    case 78: return "file name too long";       case 89: return "function not implemented";
    case 90: return "too many symbolic links";  case 93: return "directory not empty";
    }
    return "error";
}
static int perr(const char *what, int e) {        /* e: positive errno or negative syscall result */
    if (e < 0) e = -e;
    flush();
    O()->fd = 2;
    pf("%s: %s\n", what, errstr(e));
    flush();
    O()->fd = 1;
    return 1;
}

static char big[8192];                            /* shared scratch buffer (dmesg, cp, scripts) */

static int copyfd(int in, int out) {
    int n;
    flush();
    while ((n = read_(in, big, sizeof big)) > 0) {
        int o = 0;
        while (o < n) { int w = write_(out, big + o, n - o); if (w <= 0) return w ? w : -5; o += w; }
    }
    return n;
}
static int readfile(const char *path, char *buf, int max) {   /* whole small file, NUL-terminated */
    int fd = open_(path, O_RDONLY, 0), n = 0, r;
    if (fd < 0) return fd;
    while (n < max - 1 && (r = read_(fd, buf + n, max - 1 - n)) > 0) n += r;
    close_(fd);
    buf[n] = 0;
    return n;
}

/* ------------------------------------------------------------------ applets */
static int a_echo(int c, char **v) {
    int i = 1, nl = 1;
    if (c > 1 && !scmp(v[1], "-n")) { nl = 0; i++; }
    for (; i < c; i++) { outs(v[i]); if (i < c - 1) outc(' '); }
    if (nl) outc('\n');
    return 0;
}

static int a_cat(int c, char **v) {
    int rc = 0;
    if (c < 2) return copyfd(0, 1) < 0;
    for (int i = 1; i < c; i++) {
        int fd = open_(v[i], O_RDONLY, 0);
        if (fd < 0) { rc = perr(v[i], fd); continue; }
        int r = copyfd(fd, 1);
        if (r < 0) rc = perr(v[i], r);
        close_(fd);
    }
    return rc;
}

static void mode_str(u32 m, char *s) {
    u32 t = m & S_IFMT;
    s[0] = t == S_IFDIR ? 'd' : t == S_IFLNK ? 'l' : t == S_IFCHR ? 'c' : t == S_IFBLK ? 'b' : t == S_IFIFO ? 'p' : t == S_IFSOCK ? 's' : '-';
    const char *rwx = "rwxrwxrwx";
    for (int i = 0; i < 9; i++) s[1 + i] = (m & (0400 >> i)) ? rwx[i] : '-';
    s[10] = 0;
}

static char dbuf[1024];
static char names[2048];
static char *nameptr[128];

static int list_dir(const char *path, int all) {      /* fills nameptr[], sorted; returns count or -errno */
    int fd = open_(path, O_RDONLY | O_DIRECTORY, 0), cnt = 0, used = 0;
    if (fd < 0) return fd;
    for (;;) {
        int n = S3(NR_getdents, fd, dbuf, sizeof dbuf);
        if (n <= 0) break;
        for (int p = 0; p < n;) {
            struct kdirent *d = (struct kdirent *)(dbuf + p);
            p += d->d_reclen;
            const char *nm = d->d_name;
            if (!all && nm[0] == '.') continue;
            int l = strlen(nm) + 1;
            if (cnt == 128 || used + l > (int)sizeof names) continue;
            char *dst = names + used;
            scpy(dst, nm);
            used += l;
            int j = cnt++;
            while (j > 0 && scmp(nameptr[j - 1], dst) > 0) { nameptr[j] = nameptr[j - 1]; j--; }
            nameptr[j] = dst;
        }
    }
    close_(fd);
    return cnt;
}

static void join(char *out, const char *dir, const char *name) {
    char *p = scpy(out, dir);
    if (p > out && p[-1] != '/') *p++ = '/';
    scpy(p, name);
}

static void ls_long(const char *path, const char *name) {
    struct kstat st;
    char ms[11];
    int r = S2(NR_lstat, path, &st);
    if (r < 0) { perr(path, r); return; }
    mode_str(st.st_mode, ms);
    u32 t = st.st_mode & S_IFMT;
    if (t == S_IFCHR || t == S_IFBLK) pf("%s %2d %3u, %3u %s", ms, st.st_nlink, (st.st_rdev >> 8) & 0xff, st.st_rdev & 0xff, name);
    else pf("%s %2d %8u %s", ms, st.st_nlink, (u32)st.st_size, name);
    if (t == S_IFLNK) {
        char lk[128];
        int n = S3(NR_readlink, path, lk, sizeof lk - 1);
        if (n > 0) { lk[n] = 0; pf(" -> %s", lk); }
    }
    outc('\n');
}

static int a_ls(int c, char **v) {
    int lng = 0, all = 0, rc = 0, npaths = 0;
    for (int i = 1; i < c; i++)
        if (v[i][0] == '-') { for (const char *o = v[i] + 1; *o; o++) { if (*o == 'l') lng = 1; else if (*o == 'a') all = 1; } }
        else npaths++;
    for (int i = 0; i < c; i++) {
        const char *p;
        if (i == 0) { if (npaths) continue; p = "."; }
        else { if (v[i][0] == '-') continue; p = v[i]; }
        struct kstat st;
        int r = S2(NR_lstat, p, &st);
        if (r < 0) { rc = perr(p, r); continue; }
        if ((st.st_mode & S_IFMT) != S_IFDIR) { if (lng) ls_long(p, p); else pf("%s\n", p); continue; }
        if (npaths > 1) pf("%s:\n", p);
        int n = list_dir(p, all);
        if (n < 0) { rc = perr(p, n); continue; }
        if (lng) {
            char full[160];
            for (int k = 0; k < n; k++) { join(full, p, nameptr[k]); ls_long(full, nameptr[k]); }
        } else {
            int w = 1;
            for (int k = 0; k < n; k++) { int l = strlen(nameptr[k]); if (l > w) w = l; }
            w += 2;
            int cols = 79 / w;
            if (cols < 1) cols = 1;
            for (int k = 0; k < n; k++) {
                outs(nameptr[k]);
                if (k % cols == cols - 1 || k == n - 1) outc('\n');
                else for (int l = strlen(nameptr[k]); l < w; l++) outc(' ');
            }
        }
    }
    return rc;
}

static int each_arg(int c, char **v, int (*fn)(const char *)) {
    int rc = 0;
    if (c < 2) { pf("usage: %s FILE...\n", v[0]); return 1; }
    for (int i = 1; i < c; i++) { int r = fn(v[i]); if (r < 0) rc = perr(v[i], r); }
    return rc;
}
static int do_mkdir(const char *p) { return S2(NR_mkdir, p, 0755); }
static int do_rmdir(const char *p) { return S1(NR_rmdir, p); }
static int do_rm(const char *p) { return S1(NR_unlink, p); }
static int do_touch(const char *p) { int fd = open_(p, O_WRONLY | O_CREAT, 0644); if (fd < 0) return fd; close_(fd); return 0; }
static int a_mkdir(int c, char **v) { return each_arg(c, v, do_mkdir); }
static int a_rmdir(int c, char **v) { return each_arg(c, v, do_rmdir); }
static int a_rm(int c, char **v) { return each_arg(c, v, do_rm); }
static int a_touch(int c, char **v) { return each_arg(c, v, do_touch); }

static int a_mv(int c, char **v) {
    if (c != 3) { pf("usage: mv OLD NEW\n"); return 1; }
    int r = S2(NR_rename, v[1], v[2]);
    return r < 0 ? perr(v[1], r) : 0;
}
static int a_ln(int c, char **v) {
    int s = c > 1 && !scmp(v[1], "-s");
    if (c != 3 + s) { pf("usage: ln [-s] TARGET NAME\n"); return 1; }
    int r = S2(s ? NR_symlink : NR_link, v[1 + s], v[2 + s]);
    return r < 0 ? perr(v[2 + s], r) : 0;
}
static int a_cp(int c, char **v) {
    if (c != 3) { pf("usage: cp SRC DST\n"); return 1; }
    int in = open_(v[1], O_RDONLY, 0);
    if (in < 0) return perr(v[1], in);
    int out = open_(v[2], O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (out < 0) { close_(in); return perr(v[2], out); }
    int r = copyfd(in, out);
    close_(in);
    close_(out);
    return r < 0 ? perr(v[2], r) : 0;
}
static int a_chmod(int c, char **v) {
    if (c < 3) { pf("usage: chmod OCTAL FILE...\n"); return 1; }
    int m = 0, rc = 0;
    for (const char *s = v[1]; *s >= '0' && *s <= '7'; s++) m = m * 8 + *s - '0';
    for (int i = 2; i < c; i++) { int r = S2(NR_chmod, v[i], m); if (r < 0) rc = perr(v[i], r); }
    return rc;
}
static int a_mknod(int c, char **v) {
    if (c != 5 || (v[2][0] != 'c' && v[2][0] != 'b')) { pf("usage: mknod NAME c|b MAJOR MINOR\n"); return 1; }
    int mode = (v[2][0] == 'c' ? S_IFCHR : S_IFBLK) | 0666;
    int r = S3(NR_mknod, v[1], mode, (atoi_(v[3]) << 8) | atoi_(v[4]));
    return r < 0 ? perr(v[1], r) : 0;
}
static int a_pwd(int c, char **v) {
    char b[160];
    (void)c; (void)v;
    int r = S2(NR_getcwd, b, sizeof b);
    if (r < 0) return perr("pwd", r);
    pf("%s\n", b);
    return 0;
}

static int a_ps(int c, char **v) {
    (void)c; (void)v;
    int n = list_dir("/proc", 0);
    if (n < 0) return perr("/proc", n);
    /* numeric sort */
    for (int i = 1; i < n; i++) { char *x = nameptr[i]; int j = i; while (j > 0 && atoi_(nameptr[j - 1]) > atoi_(x)) { nameptr[j] = nameptr[j - 1]; j--; } nameptr[j] = x; }
    pf("  PID  PPID S CMD\n");
    for (int i = 0; i < n; i++) {
        if (!isnum(nameptr[i])) continue;
        char path[32], st[256], cmd[128];
        join(path, "/proc", nameptr[i]);
        char *e = path + strlen(path);
        scpy(e, "/stat");
        if (readfile(path, st, sizeof st) <= 0) continue;
        char *lp = st, *rp = st;
        for (char *q = st; *q; q++) { if (*q == '(' && lp == st) lp = q; if (*q == ')') rp = q; }
        *rp = 0;
        char state = rp[2];
        int ppid = atoi_(rp + 4);
        scpy(e, "/cmdline");
        int m = readfile(path, cmd, sizeof cmd);
        for (int k = 0; k < m - 1; k++) if (!cmd[k]) cmd[k] = ' ';
        if (m > 0) pf("%5s %5d %c %s\n", nameptr[i], ppid, state, cmd);
        else pf("%5s %5d %c [%s]\n", nameptr[i], ppid, state, lp + 1);
    }
    return 0;
}

static int a_kill(int c, char **v) {
    int sig = 15, i = 1, rc = 0;
    if (c > 1 && v[1][0] == '-') { sig = atoi_(v[1] + 1); i++; }
    if (i >= c) { pf("usage: kill [-SIG] PID...\n"); return 1; }
    for (; i < c; i++) { int r = S2(NR_kill, atoi_(v[i]), sig); if (r < 0) rc = perr(v[i], r); }
    return rc;
}

static int a_mount(int c, char **v) {
    const char *type = "ext2";
    int flags = 0, i = 1;
    char *args[2];
    int na = 0;
    if (c == 1) { char *a[] = { "cat", "/proc/mounts", 0 }; return a_cat(2, a); }
    for (; i < c; i++) {
        if (!scmp(v[i], "-t") && i + 1 < c) type = v[++i];
        else if (!scmp(v[i], "-o") && i + 1 < c) {
            const char *o = v[++i];
            while (*o) {
                if (!sncmp(o, "ro", 2)) flags |= 1;
                else if (!sncmp(o, "remount", 7)) flags |= 32;
                while (*o && *o != ',') o++;
                if (*o) o++;
            }
        } else if (na < 2) args[na++] = v[i];
    }
    if (na == 1 && (flags & 32)) { args[1] = args[0]; args[0] = "none"; na = 2; }
    if (na != 2) { pf("usage: mount [-t TYPE] [-o ro|rw|remount] DEV DIR\n"); return 1; }
    int r = S5(NR_mount, args[0], args[1], type, flags, 0);
    return r < 0 ? perr(args[0], r) : 0;
}
static int a_umount(int c, char **v) {
    if (c != 2) { pf("usage: umount DIR\n"); return 1; }
    int r = S2(NR_umount, v[1], 0);
    return r < 0 ? perr(v[1], r) : 0;
}

static int a_df(int c, char **v) {
    char *def[] = { "df", "/", 0 };
    if (c < 2) { c = 2; v = def; }
    pf("    1K-blocks  Used Avail  Inodes Free Mount\n");
    for (int i = 1; i < c; i++) {
        struct kstatfs s;
        int r = S2(NR_statfs, v[i], &s);
        if (r < 0) { perr(v[i], r); continue; }
        u32 k = s.f_bsize / 1024 ? s.f_bsize / 1024 : 1;
        pf("    %9u %5u %5u  %6u %4u %s\n", s.f_blocks * k, (s.f_blocks - s.f_bfree) * k, s.f_bavail * k, s.f_files, s.f_ffree, v[i]);
    }
    return 0;
}

static int a_free(int c, char **v) {
    struct ksysinfo si;
    (void)c; (void)v;
    memset(&si, 0, sizeof si);
    S1(NR_sysinfo, &si);
    u32 u = si.mem_unit ? si.mem_unit : 1;
    pf("        total    used    free  shared buffers\n");
    pf("Mem: %8u %7u %7u %7u %7u  (KB)\n", si.totalram * u / 1024, (si.totalram - si.freeram) * u / 1024,
       si.freeram * u / 1024, si.sharedram * u / 1024, si.bufferram * u / 1024);
    return 0;
}

static int a_uptime(int c, char **v) {
    struct ksysinfo si;
    (void)c; (void)v;
    S1(NR_sysinfo, &si);
    u32 t = si.uptime;
    pf("up %u day(s) %02u:%02u:%02u, %u procs, load %u.%02u %u.%02u %u.%02u\n", t / 86400, t / 3600 % 24, t / 60 % 60, t % 60,
       si.procs, si.loads[0] >> 16, (si.loads[0] & 0xffff) * 100 >> 16, si.loads[1] >> 16, (si.loads[1] & 0xffff) * 100 >> 16,
       si.loads[2] >> 16, (si.loads[2] & 0xffff) * 100 >> 16);
    return 0;
}

static int a_uname(int c, char **v) {
    static char u[6][65];
    S1(NR_uname, u);
    if (c > 1 && !scmp(v[1], "-a")) pf("%s %s %s %s %s\n", u[0], u[1], u[2], u[3], u[4]);
    else if (c > 1 && !scmp(v[1], "-n")) pf("%s\n", u[1]);
    else if (c > 1 && !scmp(v[1], "-r")) pf("%s\n", u[2]);
    else pf("%s\n", u[0]);
    return 0;
}
static int a_hostname(int c, char **v) {
    if (c < 2) { char *a[] = { "uname", "-n", 0 }; return a_uname(2, a); }
    int r = S2(NR_sethostname, v[1], strlen(v[1]));
    return r < 0 ? perr("hostname", r) : 0;
}

static int a_dmesg(int c, char **v) {
    (void)c; (void)v;
    int n = S3(NR_syslog, 3, big, sizeof big);
    if (n < 0) return perr("dmesg", n);
    flush();
    write_(1, big, n);
    return 0;
}

static int a_sync(int c, char **v) { (void)c; (void)v; S0(NR_sync); return 0; }
static int a_reboot(int c, char **v) {
    (void)c;
    pf("sync...\n");
    flush();
    S0(NR_sync);
    sleep_ms(500);
    int r = S4(NR_reboot, 0xfee1dead, 672274793, v[0][0] == 'h' ? 0xCDEF0123 : 0x01234567, 0);
    return perr(v[0], r);
}
static int a_sleep(int c, char **v) { if (c > 1) sleep_ms(atoi_(v[1]) * 1000); return 0; }
static int a_clear(int c, char **v) { (void)c; (void)v; outs("\033[H\033[2J"); return 0; }
static int a_true(int c, char **v) { (void)c; (void)v; return 0; }
static int a_false(int c, char **v) { (void)c; (void)v; return 1; }

static int a_hexdump(int c, char **v) {
    int fd = c > 1 ? open_(v[1], O_RDONLY, 0) : 0;
    if (fd < 0) return perr(v[1], fd);
    u8 b[16];
    u32 off = 0;
    int n;
    while ((n = read_(fd, b, 16)) > 0) {
        pf("%08x ", off);
        for (int i = 0; i < 16; i++) { if (i == 8) outc(' '); if (i < n) pf(" %02x", b[i]); else outs("   "); }
        outs("  |");
        for (int i = 0; i < n; i++) outc(b[i] >= 32 && b[i] < 127 ? b[i] : '.');
        outs("|\n");
        off += n;
    }
    if (fd) close_(fd);
    return 0;
}

/* ------------------------------------------------------------------ pad (controller test)
 * Polls the controllers directly on SIO0 (the port is shared with the memory card driver bu.c:
 * sync first, the card stays idle while nothing is written). The ACK interrupt (IRQ7, the card
 * driver's) is never enabled: the bytes are timed by polling. START+SELECT on a pad quits. */
#define PADR(o) (*(volatile u32 *)(0x1F801040 + (o)))
#define PAD_DATA (*(volatile u8 *)0x1F801040)
#define PAD_STAT PADR(4)
#define PAD_CTRL (*(volatile u16 *)0x1F80104A)
static void pdelay(int n) { for (volatile int i = 0; i < n; i++); }
static int pad_x(int o) {
    int t = 0;
    while (!(PAD_STAT & 1)) if (++t > 20000) return -1;
    PAD_DATA = (u8)o;
    t = 0;
    while (!(PAD_STAT & 2)) if (++t > 20000) return -1;
    int r = PAD_DATA;
    pdelay(60);                                         /* let the pad get the next byte ready */
    return r;
}
static int pad_poll(int port, u8 *d) {                  /* d[0] id, d[1..] data; returns bytes */
    while (PAD_STAT & 2) (void)PAD_DATA;
    PAD_CTRL = 0x0003 | (port << 13);                   /* TX, /JOY select, RX; no ACK irq */
    pdelay(300);
    int n = 0, id;
    if (pad_x(0x01) < 0 || (id = pad_x(0x42)) < 0 || id == 0xFF || pad_x(0) != 0x5A) goto out;
    d[0] = (u8)id;
    int len = (id & 15) * 2;
    if (!len) len = 32;
    for (n = 1; n <= len && n < 20; n++) { int r = pad_x(0); if (r < 0) break; d[n] = (u8)r; }
out:
    PAD_CTRL = 0;
    pdelay(300);
    return n;
}
static const char *const pad_names[16] = {
    "SEL", "L3", "R3", "START", "UP", "RIGHT", "DOWN", "LEFT", "L2", "R2", "L1", "R1", "/\\", "O", "X", "[]"
};
static const char *pad_kind(int id) {
    switch (id >> 4) {
    case 4: return "digital"; case 7: return "analog (DualShock)"; case 5: return "analog joystick";
    case 1: return "mouse"; case 2: return "neGcon"; case 6: return "Guncon"; default: return "unknown";
    }
}
static int a_pad(int c, char **v) {
    (void)c; (void)v;
    S0(NR_sync);
    pf("controller test - START+SELECT to quit\n");
    flush();
    char last[2][160];
    last[0][0] = last[1][0] = 0;
    for (;;) {
        int quit = 0;
        for (int port = 0; port < 2; port++) {
            u8 d[20];
            int n = pad_poll(port, d);
            char line[160], *q = line;
            q = scpy(q, port ? "pad 2: " : "pad 1: ");
            if (n < 3) q = scpy(q, "-");
            else {
                u16 b = (u16)~(d[1] | (d[2] << 8));
                if ((b & 9) == 9) quit = 1;
                q = scpy(q, pad_kind(d[0]));
                *q++ = ' ';
                int any = 0;
                for (int i = 0; i < 16; i++)
                    if (b & (1 << i)) { *q++ = ' '; q = scpy(q, pad_names[i]); any = 1; }
                if (!any) q = scpy(q, " (no button)");
                if (n >= 7 && ((d[0] >> 4) == 7 || (d[0] >> 4) == 5)) {
                    static const char hx[] = "0123456789ABCDEF";
                    q = scpy(q, "   R:");
                    for (int k = 3; k <= 6; k++) {
                        if (k == 5) q = scpy(q, " L:");
                        *q++ = hx[d[k] >> 4]; *q++ = hx[d[k] & 15]; if (k == 3 || k == 5) *q++ = ',';
                    }
                }
            }
            *q = 0;
            if (scmp(line, last[port])) { scpy(last[port], line); pf("%s\n", line); flush(); }
        }
        if (quit) break;
        sleep_ms(20);
    }
    return 0;
}

/* ------------------------------------------------------------------ btc (Bitcoin mining demo)
 * Real Bitcoin proof of work: double SHA-256 of the 80-byte block header, with the midstate
 * trick (the first 64 bytes are hashed once). No network on a PS1: "btc genesis" re-mines the
 * 2009 genesis block from just below its real nonce; "btc [seconds]" mines a header for the
 * given time and reports the hash rate and the best hash (leading zero bits). */
static const u32 sha_k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};
static const u32 sha_iv[8] = { 0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19 };
#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))
static void sha_block(u32 *h, const u32 *in) {             /* one 64-byte block, words big-endian */
    u32 w[64];
    for (int i = 0; i < 16; i++) w[i] = in[i];
    for (int i = 16; i < 64; i++) {
        u32 a = w[i - 15], b = w[i - 2];
        w[i] = w[i - 16] + (ROR(a, 7) ^ ROR(a, 18) ^ (a >> 3)) + w[i - 7] + (ROR(b, 17) ^ ROR(b, 19) ^ (b >> 10));
    }
    u32 a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 64; i++) {
        u32 t1 = hh + (ROR(e, 6) ^ ROR(e, 11) ^ ROR(e, 25)) + ((e & f) ^ (~e & g)) + sha_k[i] + w[i];
        u32 t2 = (ROR(a, 2) ^ ROR(a, 13) ^ ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
}
static u32 bswap(u32 x) { return (x >> 24) | ((x >> 8) & 0xff00) | ((x << 8) & 0xff0000) | (x << 24); }
/* genesis block header, 80 bytes as 20 big-endian words (bytes in file order) */
static const u32 genesis_hdr[20] = {
    0x01000000, 0, 0, 0, 0, 0, 0, 0, 0,
    0x3ba3edfd, 0x7a7b12b2, 0x7ac72c3e, 0x67768f61, 0x7fc81bc3, 0x888a5132, 0x3a9fb8aa, 0x4b1e5e4a,
    0x29ab5f49, 0xffff001d, 0x1dac2b7c,
};
#define GENESIS_NONCE 2083236893u
struct miner { u32 mid[8], tail[3]; };
static void miner_init(struct miner *m, const u32 *hdr) {
    for (int i = 0; i < 8; i++) m->mid[i] = sha_iv[i];
    sha_block(m->mid, hdr);                                /* midstate: header bytes 0..63 */
    m->tail[0] = hdr[16]; m->tail[1] = hdr[17]; m->tail[2] = hdr[18];
}
static void miner_hash(const struct miner *m, u32 nonce, u32 *out) {   /* nonce: header value */
    u32 blk[16], h[8];
    blk[0] = m->tail[0]; blk[1] = m->tail[1]; blk[2] = m->tail[2]; blk[3] = bswap(nonce);
    blk[4] = 0x80000000;
    for (int i = 5; i < 15; i++) blk[i] = 0;
    blk[15] = 640;
    for (int i = 0; i < 8; i++) h[i] = m->mid[i];
    sha_block(h, blk);
    for (int i = 0; i < 8; i++) blk[i] = h[i];
    blk[8] = 0x80000000;
    for (int i = 9; i < 15; i++) blk[i] = 0;
    blk[15] = 256;
    for (int i = 0; i < 8; i++) out[i] = sha_iv[i];
    sha_block(out, blk);
}
static int zero_bits(const u32 *d) {                       /* leading zeros of the displayed hash */
    int n = 0;
    for (int i = 7; i >= 0; i--) {
        u32 x = bswap(d[i]);
        if (!x) { n += 32; continue; }
        while (!(x & 0x80000000)) { n++; x <<= 1; }
        break;
    }
    return n;
}
static void print_hash(const u32 *d) {                     /* display order: digest bytes reversed */
    for (int i = 7; i >= 0; i--) pf("%08x", bswap(d[i]));
}
static u32 uptime_s(void) { struct ksysinfo si; S1(NR_sysinfo, &si); return si.uptime; }
static int hexv(int ch) { return ch >= '0' && ch <= '9' ? ch - '0' : ch >= 'a' && ch <= 'f' ? ch - 'a' + 10 : ch >= 'A' && ch <= 'F' ? ch - 'A' + 10 : -1; }
static u32 hex32(const char **pp) {                      /* parse hex digits up to a space */
    const char *q = *pp; u32 v = 0;
    while (*q == ' ') q++;
    while (hexv(*q) >= 0) v = v << 4 | hexv(*q++);
    *pp = q; return v;
}
static int read_line(char *b, int max) {                  /* one line from stdin (tty, canonical) */
    int n = 0;
    while (n < max - 1) {
        char ch;
        if (read_(0, &ch, 1) <= 0) return -1;
        if (ch == '\n') break;
        if (ch != '\r') b[n++] = ch;
    }
    b[n] = 0; return n;
}
/* "btc stratum": work from the PC (tools/stratum_bridge.py) over the console line.
 *   PS1 -> PC  R                         ready for work
 *   PC -> PS1  W <152 hex: header bytes 0..75> <first nonce> <count> <zero bits>   (hex numbers)
 *   PS1 -> PC  S <nonce>                 a hash with at least <zero bits> leading zeros
 *              Z <nonce> <bits>          any other hash with <minz> (default 10, "btc stratum N") or more
 *              D <count> <seconds>       range done
 *   PC -> PS1  Q                         quit */
static int btc_stratum(u32 minz) {
    static char line[256];
    struct miner m;
    u32 hdr[20], d[8];
    pf("stratum mode: waiting for work from the PC\n");
    for (;;) {
        pf("R\n"); flush();
        if (read_line(line, sizeof line) < 0) return 1;
        if (line[0] == 'Q') { pf("bye\n"); return 0; }
        if (line[0] != 'W') continue;
        const char *q = line + 1;
        while (*q == ' ') q++;
        int ok = 1;
        for (int i = 0; i < 19; i++) {
            u32 w = 0;
            for (int k = 0; k < 8; k++) { int x = hexv(*q++); if (x < 0) { ok = 0; break; } w = w << 4 | x; }
            if (!ok) break;
            hdr[i] = w;
        }
        if (!ok) { pf("E bad work\n"); continue; }
        u32 start = hex32(&q), count = hex32(&q), zb = hex32(&q);
        miner_init(&m, hdr);
        u32 t0 = uptime_s(), n = start;
        for (u32 k = 0; k < count; k++, n++) {
            miner_hash(&m, n, d);
            u32 z = zero_bits(d);
            if (z >= zb) { pf("S %x\n", n); flush(); }
            else if (z >= minz) { pf("Z %x %u\n", n, z); flush(); }
        }
        pf("D %x %u\n", count, uptime_s() - t0); flush();
    }
}
static int a_btc(int c, char **v) {
    struct miner m;
    u32 d[8];
    if (c > 1 && !scmp(v[1], "stratum")) return btc_stratum(c > 2 ? (u32)atoi_(v[2]) : 10);
    if (c > 1 && !scmp(v[1], "genesis")) {
        u32 back = c > 2 ? (u32)atoi_(v[2]) : 20000;
        pf("re-mining the Bitcoin genesis block (3 Jan 2009), starting %u nonces below the answer\n", back);
        flush();
        miner_init(&m, genesis_hdr);
        u32 t0 = uptime_s();
        for (u32 n = GENESIS_NONCE - back; ; n++) {
            miner_hash(&m, n, d);
            if (zero_bits(d) >= 32) {
                u32 dt = uptime_s() - t0;
                pf("FOUND nonce %u after %u hashes in %u s\nhash ", n, n - (GENESIS_NONCE - back) + 1, dt);
                print_hash(d);
                pf("\n%s\n", zero_bits(d) >= 40 && n == GENESIS_NONCE ? "= block 0 of the Bitcoin blockchain, mined on a PlayStation" : "");
                return 0;
            }
            if (n == GENESIS_NONCE + 1000) { pf("not found?!\n"); return 1; }
        }
    }
    /* btc [zeros] [seconds]: show every hash with at least <zeros> leading zero bits */
    u32 minbits = c > 1 ? (u32)atoi_(v[1]) : 10;
    u32 secs = c > 2 ? (u32)atoi_(v[2]) : 60;
    u32 hdr[20];
    for (int i = 0; i < 20; i++) hdr[i] = genesis_hdr[i];
    u32 t0 = uptime_s();
    hdr[17] = bswap(0x60000000u + t0);                    /* a fresh timestamp: new work */
    miner_init(&m, hdr);
    pf("mining for %u s (double SHA-256), showing hashes with %u+ leading zero bits\n", secs, minbits);
    flush();
    u32 best = 0, bestn = 0, n = 0, last = t0;
    u32 bestd[8];
    for (int i = 0; i < 8; i++) bestd[i] = 0xffffffff;
    for (;;) {
        miner_hash(&m, n, d);
        int z = zero_bits(d);
        if ((u32)z >= minbits) { pf("nonce %08x  %2u zeros  ", n, z); print_hash(d); pf("\n"); flush(); }
        if ((u32)z > best) { best = z; bestn = n; for (int i = 0; i < 8; i++) bestd[i] = d[i]; }
        n++;
        if (!(n & 1023)) {
            u32 t = uptime_s();
            if (t - last >= 5 || t - t0 >= secs) {
                last = t;
                u32 dt = t - t0 ? t - t0 : 1;
                pf("%4u s  %6u hashes  %u H/s  best %u zero bits (nonce %u)\n", t - t0, n, n / dt, best, bestn);
                flush();
                if (t - t0 >= secs) break;
            }
        }
    }
    pf("best hash: ");
    print_hash(bestd);
    pf("\na real block today needs ~78 zero bits: at this speed, about 10^19 years\n");
    return 0;
}

static int a_help(int c, char **v);
struct applet { const char *name; int (*fn)(int, char **); };
static const struct applet applets[] = {
    { "btc", a_btc }, { "cat", a_cat }, { "chmod", a_chmod }, { "clear", a_clear }, { "cp", a_cp }, { "df", a_df },
    { "dmesg", a_dmesg }, { "echo", a_echo }, { "false", a_false }, { "free", a_free }, { "halt", a_reboot },
    { "help", a_help }, { "hexdump", a_hexdump }, { "hostname", a_hostname }, { "kill", a_kill }, { "ln", a_ln },
    { "ls", a_ls }, { "mkdir", a_mkdir }, { "mknod", a_mknod }, { "mount", a_mount }, { "mv", a_mv }, { "pad", a_pad },
    { "ps", a_ps }, { "pwd", a_pwd }, { "reboot", a_reboot }, { "rm", a_rm }, { "rmdir", a_rmdir },
    { "sleep", a_sleep }, { "sync", a_sync }, { "touch", a_touch }, { "true", a_true }, { "umount", a_umount },
    { "uname", a_uname }, { "uptime", a_uptime },
};
#define NAPPLETS (int)(sizeof applets / sizeof applets[0])

static int a_help(int c, char **v) {
    (void)c; (void)v;
    pf("shell: cd exit sh   redirections: > >> <   background: &   sequence: ;\napplets:");
    for (int i = 0; i < NAPPLETS; i++) pf("%s %s", i % 12 ? "" : "\n ", applets[i].name);
    pf("\nany other name is looked up in /bin and /sbin (bFLT binaries)\n");
    return 0;
}
static const struct applet *find_applet(const char *n) {
    for (int i = 0; i < NAPPLETS; i++) if (!scmp(applets[i].name, n)) return &applets[i];
    return 0;
}

/* ------------------------------------------------------------------ shell */
#define MAXARGS 32
struct cmd { int argc; char *argv[MAXARGS]; char *in, *out; int append, bg; };
static char tokbuf[512];

static void parse(const char *s, struct cmd *c) {
    char *d = tokbuf, *end = tokbuf + sizeof tokbuf - 2;
    memset(c, 0, sizeof *c);
    for (;;) {
        while (*s == ' ' || *s == '\t') s++;
        if (!*s || *s == '#') break;
        if (*s == '&') { c->bg = 1; s++; continue; }
        int kind = 0;
        if (*s == '>') { kind = 1; s++; if (*s == '>') { kind = 2; s++; } }
        else if (*s == '<') { kind = 3; s++; }
        while (*s == ' ' || *s == '\t') s++;
        char *t = d, q = 0;
        while (*s && d < end) {
            char ch = *s;
            if (q) { s++; if (ch == q) q = 0; else *d++ = ch; continue; }
            if (ch == '"' || ch == '\'') { q = ch; s++; continue; }
            if (ch == ' ' || ch == '\t' || ch == '>' || ch == '<' || ch == '&') break;
            if (ch == '\\' && s[1]) s++;
            *d++ = *s++;
        }
        *d++ = 0;
        if (t[0] == '$' && t[1] == '?' && !t[2]) {       /* $? */
            u32 x = laststatus & 0xff;
            char *p = t;
            if (x >= 100) *p++ = '0' + x / 100;
            if (x >= 10) *p++ = '0' + x / 10 % 10;
            *p++ = '0' + x % 10;
            *p = 0;
            d = p + 1;
        }
        if (kind == 1 || kind == 2) { c->out = t; c->append = kind == 2; }
        else if (kind == 3) c->in = t;
        else if (c->argc < MAXARGS - 1) c->argv[c->argc++] = t;
    }
    c->argv[c->argc] = 0;
}

static int resolve(const char *n, char *out) {
    static const char *dirs[] = { "/bin", "/sbin", 0 };
    if (n[0] == '/' || (n[0] == '.' && n[1] == '/')) { scpy(out, n); return 1; }
    for (int i = 0; dirs[i]; i++) { join(out, dirs[i], n); if (!S2(NR_access, out, 1)) return 1; }
    return 0;
}

static void reap(int verbose) {
    int st, pid;
    while ((pid = S4(NR_wait4, -1, &st, 1 /* WNOHANG */, 0)) > 0)
        if (verbose) pf("[%d] done (status %d)\n", pid, (st >> 8) & 0xff);
}

static void run_script(const char *path);

static void exec_cmd(struct cmd *c) {
    if (!c->argc) return;
    const char *n = c->argv[0];
    if (!scmp(n, "cd")) {
        int r = S1(NR_chdir, c->argc > 1 ? c->argv[1] : "/");
        laststatus = r < 0 ? perr(c->argv[1], r) : 0;
        return;
    }
    if (!scmp(n, "exit")) {
        if (is_init) { pf("this shell is init (pid 1): use reboot or halt\n"); return; }
        flush();
        S1(NR_exit, c->argc > 1 ? atoi_(c->argv[1]) : laststatus);
    }
    int sv_in = -1, sv_out = -1;
    if (c->in) {
        int fd = open_(c->in, O_RDONLY, 0);
        if (fd < 0) { laststatus = perr(c->in, fd); return; }
        sv_in = S1(NR_dup, 0); S2(NR_dup2, fd, 0); close_(fd);
    }
    if (c->out) {
        flush();
        int fd = open_(c->out, O_WRONLY | O_CREAT | (c->append ? O_APPEND : O_TRUNC), 0644);
        if (fd < 0) { laststatus = perr(c->out, fd); goto restore; }
        sv_out = S1(NR_dup, 1); S2(NR_dup2, fd, 1); close_(fd);
    }
    const struct applet *a = find_applet(n);
    if (a) {
        laststatus = a->fn(c->argc, c->argv);
    } else if (!scmp(n, "sh") && c->argc > 1) {
        run_script(c->argv[1]);
    } else {
        char path[160];
        if (!resolve(n, path)) { pf("%s: command not found\n", n); laststatus = 127; goto restore; }
        flush();
        int pid = spawn(path, c->argv, envp_g);
        if (pid < 0) { laststatus = perr(n, pid); goto restore; }
        if (c->bg) { pf("[%d]\n", pid); laststatus = 0; }
        else {
            int st = 0;
            S4(NR_wait4, pid, &st, 0, 0);
            laststatus = (st >> 8) & 0xff;
            if (st & 0x7f) { pf("%s: killed by signal %d\n", n, st & 0x7f); laststatus = 128 + (st & 0x7f); }
        }
    }
restore:
    flush();
    if (sv_out >= 0) { S2(NR_dup2, sv_out, 1); close_(sv_out); }
    if (sv_in >= 0) { S2(NR_dup2, sv_in, 0); close_(sv_in); }
}

static void run_line(const char *s) {
    static char seg[256];
    while (*s) {
        int n = 0;
        char q = 0;
        while (*s && (q || *s != ';') && n < (int)sizeof seg - 1) {
            if (q) { if (*s == q) q = 0; }
            else if (*s == '"' || *s == '\'') q = *s;
            seg[n++] = *s++;
        }
        seg[n] = 0;
        if (*s == ';') s++;
        struct cmd c;
        parse(seg, &c);
        exec_cmd(&c);
        flush();
    }
}

static void run_script(const char *path) {
    static char sbuf[2048];
    char *buf = sbuf;
    static int depth;
    if (depth) buf = big;                          /* one nested level (rc calling a script) */
    int n = readfile(path, buf, depth ? (int)sizeof big : (int)sizeof sbuf);
    if (n < 0) { laststatus = perr(path, n); return; }
    depth++;
    for (char *l = buf; *l;) {
        char *e = l;
        while (*e && *e != '\n') e++;
        char save = *e;
        *e = 0;
        if (*l && *l != '#') run_line(l);
        if (!save) break;
        l = e + 1;
    }
    depth--;
}

static void shell_loop(void) {
    static char line[256];
    for (;;) {
        reap(1);
        char cwd[128];
        if (S2(NR_getcwd, cwd, sizeof cwd) < 0) scpy(cwd, "?");
        pf("psx:%s# ", cwd);
        flush();
        int n = read_(0, line, sizeof line - 1);
        if (n <= 0) {
            if (!is_init) S1(NR_exit, 0);
            sleep_ms(1000);
            continue;
        }
        while (n > 0 && (line[n - 1] == '\n' || line[n - 1] == '\r')) n--;
        line[n] = 0;
        run_line(line);
    }
}

static void init_main(void) {
    is_init = 1;
    int r = S5(NR_mount, "proc", "/proc", "proc", 0, 0);
    if (r < 0) perr("init: mount /proc", r);
    r = S5(NR_mount, "/dev/bu0", "/", "ext2", 32 /* MS_REMOUNT, rw */, 0);
    if (r < 0) perr("init: remount / rw", r);
    S2(NR_sethostname, "psx", 3);
    /* own session + serial port as controlling tty: Ctrl-C reaches the programs started here */
    if (S0(NR_setsid) >= 0) {
        int fd = open_("/dev/ttyS0", O_RDWR, 0);
        if (fd >= 0) { S2(NR_dup2, fd, 0); S2(NR_dup2, fd, 1); S2(NR_dup2, fd, 2); if (fd > 2) close_(fd); }
    }
    int tv = open_("/dev/tty0", O_WRONLY | O_NOCTTY, 0);
    if (tv >= 0) {
        static const char msg[] = "\n PSXLinux: root on memory card, shell on the serial port (115200 8N1)\n";
        write_(tv, msg, sizeof msg - 1);
        close_(tv);
    }
    if (!S2(NR_access, "/etc/rc", 4)) run_script("/etc/rc");
    shell_loop();
}

int main(int argc, char **argv, char **envp) {
    (void)envp;
    const char *b = argc > 0 ? base(argv[0]) : "sh";
    if (S0(NR_getpid) == 1 || !scmp(b, "init")) init_main();
    if (!scmp(b, "sh") || !scmp(b, "psxsh")) {
        if (argc > 2 && !scmp(argv[1], "-c")) run_line(argv[2]);
        else if (argc > 1) run_script(argv[1]);
        else shell_loop();
        flush();
        return laststatus;
    }
    const struct applet *a = find_applet(b);
    if (a) { int r = a->fn(argc, argv); flush(); return r; }
    pf("%s: unknown applet\n", b);
    flush();
    return 127;
}
