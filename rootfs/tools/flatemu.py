#!/usr/bin/env python3
"""Minimal user-mode MIPS I emulator for PSXLinux bFLT binaries (test harness, not a PlayStation).

  python flatemu.py prog.flt HOSTROOT [argv0 [args...]] < input

Loads like fs/binfmt_flat.c (non-separate mode, relocations via do_reloc semantics), builds the
argc/argv/envp stack, runs, and emulates the system calls psxsh uses on top of HOSTROOT. Runs as pid 1.
"""
import os, stat, struct, sys

LOAD = 0x80100000
MASK = 0xFFFFFFFF


def s32(v): return v - (1 << 32) if v & 0x80000000 else v
def s16(v): return v - 0x10000 if v & 0x8000 else v


class Emu:
    def __init__(self, flt, root, argv):
        self.root = os.path.abspath(root)
        self.cwd = "/"
        f = open(flt, "rb").read()
        magic, rev, entry, ts, ds, de, be, stack, rs, rc = struct.unpack_from("<4sIIIIIIIII", f)
        assert magic == b"bFLT" and rev == 2
        total = be + stack
        self.mem = bytearray(0x200000)
        self.base = LOAD
        self.mem[0x100000:0x100000 + de] = f[:de]
        hi = None
        for k in range(rc):
            r, = struct.unpack_from("<I", f, rs + 4 * k)
            ptr = LOAD + (r & 0x7FFFFF)
            t = r & 0xF000000
            if t == 0:
                self.sw(ptr, self.lw(ptr) + LOAD)
            elif t == 0x1000000:
                hi = ptr
            elif t == 0x2000000:
                res = (((self.lw(hi) & 0xFFFF) << 16) + s16(self.lw(ptr) & 0xFFFF) + LOAD) & MASK
                self.sw(hi, (self.lw(hi) & 0xFFFF0000) | (((res - s16(res & 0xFFFF)) >> 16) & 0xFFFF))
                self.sw(ptr, (self.lw(ptr) & 0xFFFF0000) | (res & 0xFFFF))
            elif t == 0x3000000:
                v = self.lw(ptr)
                self.sw(ptr, (v & 0xFC000000) | ((((v & 0x3FFFFFF) << 2) + LOAD) >> 2 & 0x3FFFFFF))
        # stack like create_flat_tables
        p = LOAD + total - 4
        env = [b"PATH=/bin:/sbin", b"HOME=/"]
        def puts(p, s):
            p -= len(s) + 1
            self.mem[p - 0x80000000 - 0x100000 + 0x100000 - (LOAD - 0x80100000):p - 0x80000000 + 1 + len(s) - 1 - 0x0] if False else None
            self.wbytes(p, s + b"\0")
            return p
        p = puts(p, argv[0])
        envp_a = []
        for e in reversed(env): p = puts(p, e); envp_a.insert(0, p)
        argv_a = []
        for a in reversed(argv): p = puts(p, a); argv_a.insert(0, p)
        sp = p & ~3
        sp -= 4 * (len(env) + 1)
        for i, a in enumerate(envp_a + [0]): self.sw(sp + 4 * i, a)
        sp -= 4 * (len(argv) + 1)
        for i, a in enumerate(argv_a + [0]): self.sw(sp + 4 * i, a)
        sp -= 4
        self.sw(sp, len(argv))
        self.r = [0] * 32
        self.r[29] = sp
        self.pc = LOAD + entry
        self.hi = self.lo = 0
        self.fds = {0: ("stdin", None), 1: ("stdout", None), 2: ("stdout", None)}
        self.steps = 0

    # memory
    def a(self, addr):
        o = (addr & 0x1FFFFFFF)
        if not 0 <= o < len(self.mem): raise RuntimeError("bad address %08x pc=%08x" % (addr, self.pc))
        return o
    def lw(self, x): return struct.unpack_from("<I", self.mem, self.a(x))[0]
    def sw(self, x, v): struct.pack_into("<I", self.mem, self.a(x), v & MASK)
    def wbytes(self, x, b): o = self.a(x); self.mem[o:o + len(b)] = b
    def rbytes(self, x, n): o = self.a(x); return bytes(self.mem[o:o + n])
    def cstr(self, x):
        o = self.a(x); e = self.mem.index(0, o); return self.mem[o:e].decode()

    def host(self, path):
        if not path.startswith("/"): path = self.cwd.rstrip("/") + "/" + path
        parts = []
        for c in path.split("/"):
            if c in ("", "."): continue
            if c == "..":
                if parts: parts.pop()
            else: parts.append(c)
        return os.path.join(self.root, *parts), "/" + "/".join(parts)

    def syscall(self):
        n, a0, a1, a2, a3 = self.r[2], self.r[4], self.r[5], self.r[6], self.r[7]
        try:
            v = self.sys(n, a0, a1, a2, a3)
        except OSError as e:
            v = -{2: 2, 13: 13, 17: 17, 20: 20, 21: 21, 39: 93, 41: 93}.get(e.errno, 5)
        if v < 0:
            self.r[2] = -v; self.r[7] = 1
        else:
            self.r[2] = v & MASK; self.r[7] = 0

    def sys(self, n, a0, a1, a2, a3):
        if n == 1: raise SystemExit("[emu] exit(%d)" % s32(a0))
        if n == 3:
            if a0 == 0:                      # tty-like: a line is read once, then handed out in pieces
                pend = getattr(self, "pending", b"")
                if not pend:
                    line = sys.stdin.readline()
                    if not line:
                        self.eof = True; return 0
                    sys.stdout.write("\x1b[33m" + line + "\x1b[0m")
                    pend = line.encode()
                chunk, self.pending = pend[:a2], pend[a2:]
                self.wbytes(a1, chunk); return len(chunk)
            kind, f = self.fds[a0]
            if kind == "dir": return -21
            d = os.read(f, a2); self.wbytes(a1, d); return len(d)
        if n == 4:
            data = self.rbytes(a1, a2)
            kind, f = self.fds[a0]
            if kind == "stdout": sys.stdout.write(data.decode("latin1")); sys.stdout.flush(); return a2
            return os.write(f, data)
        if n == 5:
            hp, vp = self.host(self.cstr(a0))
            if os.path.isdir(hp):
                fd = max(self.fds) + 1; self.fds[fd] = ("dir", (hp, False)); return fd
            if a1 & 0x10000: return -20
            fl = (os.O_WRONLY if a1 & 1 else os.O_RDWR if a1 & 2 else os.O_RDONLY) | os.O_BINARY
            if a1 & 0x100: fl |= os.O_CREAT
            if a1 & 0x200: fl |= os.O_TRUNC
            if a1 & 0x8: fl |= os.O_APPEND
            if vp.startswith("/dev/"): return -6 if "tty" in vp else -2
            h = os.open(hp, fl, 0o644)
            fd = 3
            while fd in self.fds: fd += 1
            self.fds[fd] = ("file", h); return fd
        if n == 6:
            kind, f = self.fds.pop(a0)
            if kind == "file": os.close(f)
            return 0
        if n in (9, 83): return -1
        if n == 10: os.unlink(self.host(self.cstr(a0))[0]); return 0
        if n == 12:
            hp, vp = self.host(self.cstr(a0))
            if not os.path.isdir(hp): return -2 if not os.path.exists(hp) else -20
            self.cwd = vp; return 0
        if n in (14, 15, 21, 36, 52, 74, 66): return 0
        if n == 20: return 1
        if n == 33: return 0 if os.path.exists(self.host(self.cstr(a0))[0]) else -2
        if n == 37: return -3
        if n == 38: os.rename(self.host(self.cstr(a0))[0], self.host(self.cstr(a1))[0]); return 0
        if n == 39: os.mkdir(self.host(self.cstr(a0))[0]); return 0
        if n == 40: os.rmdir(self.host(self.cstr(a0))[0]); return 0
        if n == 41:
            fd = 3
            while fd in self.fds: fd += 1
            self.fds[fd] = self.fds[a0]; return fd
        if n == 63: self.fds[a1] = self.fds[a0]; return a1
        if n == 85: return -22
        if n == 88: raise SystemExit("[emu] reboot(%x)" % a2)
        if n == 99:
            self.wbytes(a1, struct.pack("<8I", 0xEF53, 1024, 1024, 127, 84, 48, 15, 84)); return 0
        if n == 103:
            t = b"<6>Linux version 2.4.x (emulated dmesg)\n"; self.wbytes(a1, t); return len(t)
        if n in (106, 107):
            hp, _ = self.host(self.cstr(a0))
            st = os.lstat(hp)
            mode = (0o040755 if stat.S_ISDIR(st.st_mode) else 0o100644)
            if os.path.basename(hp) in ("sh", "init"): mode = 0o100755
            b = bytearray(144)
            struct.pack_into("<I", b, 16, st.st_ino & MASK)
            struct.pack_into("<IiiiI", b, 20, mode, 1, 0, 0, 0)
            struct.pack_into("<i", b, 48, st.st_size)
            self.wbytes(a1, bytes(b)); return 0
        if n == 114: return -10
        if n == 116:
            self.wbytes(a0, struct.pack("<lIIIIIIIIH", 42, 0, 0, 0, 2048 * 1024, 900 * 1024, 0, 0, 0, 3)); return 0
        if n == 122:
            u = b""
            for s in (b"Linux", b"psx", b"2.4.x-beta1", b"#1", b"mips"): u += s.ljust(65, b"\0")
            self.wbytes(a0, u); return 0
        if n == 141:
            kind, (hp, done) = self.fds[a0]
            if done: return 0
            out = b""
            for nm in [".", ".."] + sorted(os.listdir(hp)):
                e = nm.encode()
                rec = (10 + len(e) + 1 + 3) & ~3
                out += struct.pack("<iiH", 1, 0, rec) + e + b"\0" * (rec - 10 - len(e))
            self.fds[a0] = ("dir", (hp, True))
            self.wbytes(a1, out[:a2]); return len(out[:a2])
        if n == 162:
            if getattr(self, "eof", False): raise SystemExit("[emu] stdin closed, init idles")
            return 0
        if n == 183:
            c = self.cwd.encode() + b"\0"; self.wbytes(a0, c); return len(c)
        if n == 190: return -89
        raise RuntimeError("[emu] unhandled syscall %d" % n)

    def run(self):
        r = self.r
        delay = None
        while True:
            pc = self.pc
            ins = self.lw(pc)
            npc = delay if delay is not None else (pc + 4) & MASK
            delay = None
            op, rs, rt, rd, sa, fn = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31, (ins >> 11) & 31, (ins >> 6) & 31, ins & 63
            imm = ins & 0xFFFF
            simm = s16(imm)
            br = None
            if op == 0:
                if fn == 0: r[rd] = (r[rt] << sa) & MASK
                elif fn == 2: r[rd] = r[rt] >> sa
                elif fn == 3: r[rd] = (s32(r[rt]) >> sa) & MASK
                elif fn == 4: r[rd] = (r[rt] << (r[rs] & 31)) & MASK
                elif fn == 6: r[rd] = r[rt] >> (r[rs] & 31)
                elif fn == 7: r[rd] = (s32(r[rt]) >> (r[rs] & 31)) & MASK
                elif fn == 8: br = r[rs]
                elif fn == 9: t = r[rs]; r[rd] = (pc + 8) & MASK; br = t
                elif fn == 12: self.pc = npc; self.syscall(); r[0] = 0; continue
                elif fn == 13: raise RuntimeError("break at %08x" % pc)
                elif fn == 16: r[rd] = self.hi
                elif fn == 17: self.hi = r[rs]
                elif fn == 18: r[rd] = self.lo
                elif fn == 19: self.lo = r[rs]
                elif fn == 24: p = s32(r[rs]) * s32(r[rt]); self.lo = p & MASK; self.hi = (p >> 32) & MASK
                elif fn == 25: p = r[rs] * r[rt]; self.lo = p & MASK; self.hi = (p >> 32) & MASK
                elif fn == 26:
                    if r[rt]: a, b = s32(r[rs]), s32(r[rt]); q = abs(a) // abs(b) * (1 if (a < 0) == (b < 0) else -1); self.lo = q & MASK; self.hi = (a - q * b) & MASK
                elif fn == 27:
                    if r[rt]: self.lo = r[rs] // r[rt]; self.hi = r[rs] % r[rt]
                elif fn in (32, 33): r[rd] = (r[rs] + r[rt]) & MASK
                elif fn in (34, 35): r[rd] = (r[rs] - r[rt]) & MASK
                elif fn == 36: r[rd] = r[rs] & r[rt]
                elif fn == 37: r[rd] = r[rs] | r[rt]
                elif fn == 38: r[rd] = r[rs] ^ r[rt]
                elif fn == 39: r[rd] = ~(r[rs] | r[rt]) & MASK
                elif fn == 42: r[rd] = int(s32(r[rs]) < s32(r[rt]))
                elif fn == 43: r[rd] = int(r[rs] < r[rt])
                else: raise RuntimeError("special %d at %08x" % (fn, pc))
            elif op == 1:
                c = s32(r[rs]) < 0 if rt & 1 == 0 else s32(r[rs]) >= 0
                if rt & 0x10: r[31] = (pc + 8) & MASK
                if c: br = (pc + 4 + (simm << 2)) & MASK
            elif op == 2: br = ((pc + 4) & 0xF0000000) | ((ins & 0x3FFFFFF) << 2)
            elif op == 3: r[31] = (pc + 8) & MASK; br = ((pc + 4) & 0xF0000000) | ((ins & 0x3FFFFFF) << 2)
            elif op == 4:
                if r[rs] == r[rt]: br = (pc + 4 + (simm << 2)) & MASK
            elif op == 5:
                if r[rs] != r[rt]: br = (pc + 4 + (simm << 2)) & MASK
            elif op == 6:
                if s32(r[rs]) <= 0: br = (pc + 4 + (simm << 2)) & MASK
            elif op == 7:
                if s32(r[rs]) > 0: br = (pc + 4 + (simm << 2)) & MASK
            elif op in (8, 9): r[rt] = (r[rs] + simm) & MASK
            elif op == 10: r[rt] = int(s32(r[rs]) < simm)
            elif op == 11: r[rt] = int(r[rs] < (simm & MASK))
            elif op == 12: r[rt] = r[rs] & imm
            elif op == 13: r[rt] = r[rs] | imm
            elif op == 14: r[rt] = r[rs] ^ imm
            elif op == 15: r[rt] = imm << 16
            elif op in (32, 33, 35, 36, 37, 34, 38):
                ad = (r[rs] + simm) & MASK
                o = self.a(ad)
                if op == 32: r[rt] = s32(self.mem[o] << 24) >> 24 & MASK
                elif op == 36: r[rt] = self.mem[o]
                elif op == 33: r[rt] = s16(self.mem[o] | self.mem[o + 1] << 8) & MASK
                elif op == 37: r[rt] = self.mem[o] | self.mem[o + 1] << 8
                elif op == 35:
                    if ad & 3: raise RuntimeError("unaligned lw %08x at %08x" % (ad, pc))
                    r[rt] = struct.unpack_from("<I", self.mem, o)[0]
                else:
                    al = ad & ~3; w = self.lw(al); k = ad & 3
                    if op == 34: r[rt] = ((w << (8 * (3 - k))) | (r[rt] & ((1 << (8 * (3 - k))) - 1))) & MASK
                    else: r[rt] = (w >> (8 * k)) | (r[rt] & ~(MASK >> (8 * k)) & MASK)
            elif op in (40, 41, 43, 42, 46):
                ad = (r[rs] + simm) & MASK
                o = self.a(ad)
                if op == 40: self.mem[o] = r[rt] & 0xFF
                elif op == 41: self.mem[o] = r[rt] & 0xFF; self.mem[o + 1] = (r[rt] >> 8) & 0xFF
                elif op == 43:
                    if ad & 3: raise RuntimeError("unaligned sw %08x at %08x" % (ad, pc))
                    struct.pack_into("<I", self.mem, o, r[rt])
                else:
                    al = ad & ~3; w = self.lw(al); k = ad & 3
                    if op == 42: m = MASK >> (8 * (3 - k)); w = (w & ~m & MASK) | (r[rt] >> (8 * (3 - k)))
                    else: m = (MASK << (8 * k)) & MASK; w = (w & ~m & MASK) | ((r[rt] << (8 * k)) & MASK)
                    self.sw(al, w)
            else:
                raise RuntimeError("opcode %d at %08x" % (op, pc))
            r[0] = 0
            self.pc = npc
            if br is not None: delay = br
            self.steps += 1


def main():
    flt, root = sys.argv[1], sys.argv[2]
    argv = [a.encode() for a in (sys.argv[3:] or ["/sbin/init"])]
    e = Emu(flt, root, argv)
    try:
        e.run()
    except SystemExit as x:
        print("\n%s  (%d instructions)" % (x, e.steps))


main()
