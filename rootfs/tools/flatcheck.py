#!/usr/bin/env python3
"""Check a bFLT file against the same program linked at a fixed address.

  python flatcheck.py prog.flt prog_at_BASE.elf BASE

Applies the relocations exactly like do_reloc() in PSXLinux fs/binfmt_flat.c with the file loaded at
BASE, then compares text+rodata+data with the sections of an ELF linked with `. = BASE + 0x40`.
"""
import struct, sys


def load_elf(path, base, size):
    elf = open(path, "rb").read()
    e_shoff, = struct.unpack_from("<I", elf, 32)
    shentsize, shnum = struct.unpack_from("<HH", elf, 46)
    img = bytearray(size)
    for i in range(shnum):
        s = struct.unpack_from("<IIIIIIIIII", elf, e_shoff + i * shentsize)
        typ, flags, addr, off, sz = s[1], s[2], s[3], s[4], s[5]
        if flags & 2 and typ != 8 and sz:
            img[addr - base:addr - base + sz] = elf[off:off + sz]
    return img


def main():
    flt_path, elf_path, base = sys.argv[1], sys.argv[2], int(sys.argv[3], 0)
    f = open(flt_path, "rb").read()
    magic, rev, entry, text_start, data_start, data_end, bss_end, stack, rstart, rcount = struct.unpack_from("<4sIIIIIIIII", f)
    assert magic == b"bFLT" and rev == 2 and text_start == 0
    mem = bytearray(f[:data_end])
    start_code = base + text_start

    def rd(a): return struct.unpack_from("<I", mem, a - base)[0]
    def wr(a, v): struct.pack_into("<I", mem, a - base, v & 0xFFFFFFFF)

    hi = None
    for k in range(rcount):
        r, = struct.unpack_from("<I", f, rstart + 4 * k)
        assert r & 0xF0800000 == 0, "only in=text rel=text sign=+ expected"
        ptr = start_code + (r & 0x7FFFFF)
        typ = r & 0xF000000
        if typ == 0x0000000:
            wr(ptr, rd(ptr) + start_code)
        elif typ == 0x1000000:
            hi = ptr
        elif typ == 0x2000000:
            assert hi is not None, "LO16 without HI16"
            lo = rd(ptr) & 0xFFFF
            res = ((rd(hi) & 0xFFFF) << 16) + (lo - 0x10000 if lo & 0x8000 else lo) + start_code
            res &= 0xFFFFFFFF
            s16 = res & 0xFFFF
            s16 = s16 - 0x10000 if s16 & 0x8000 else s16
            wr(hi, (rd(hi) & 0xFFFF0000) | (((res - s16) >> 16) & 0xFFFF))
            wr(ptr, (rd(ptr) & 0xFFFF0000) | (res & 0xFFFF))
            hi = None
        elif typ == 0x3000000:
            v = rd(ptr)
            res = ((v & 0x3FFFFFF) << 2) + start_code
            wr(ptr, (v & 0xFC000000) | ((res >> 2) & 0x3FFFFFF))
        else:
            raise SystemExit("bad type %x" % typ)
    ref = load_elf(elf_path, base, data_end)
    bad = [i for i in range(0x40, data_end) if mem[i] != ref[i]]
    if bad:
        print("MISMATCH: %d bytes differ, first at offset %#x (%02x vs %02x)" % (len(bad), bad[0], mem[bad[0]], ref[bad[0]]))
        sys.exit(1)
    print("OK: %d relocations, %d bytes identical to the image linked at %#x" % (rcount, data_end - 0x40, base))


main()
