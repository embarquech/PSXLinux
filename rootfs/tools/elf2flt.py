#!/usr/bin/env python3
"""ELF (linked with flat.ld and -Wl,-q) -> bFLT rev 2 for the PSXLinux kernel (include/asm-mipsnommu/flat.h).

  python elf2flt.py prog.elf prog [--stack 8192]

The PSXLinux loader has its own MIPS relocation records: |in:2|rel:2|type:4|sign:1|offset:23|
with types 32, HI16, LO16 (must directly follow its HI16) and 26. The program is linked at 0 with
the header in 0..3Fh, so every record is "in text, relative to text" and offset = link address.
"""
import struct, sys

R_MIPS_NONE, R_MIPS_16, R_MIPS_32, R_MIPS_REL32, R_MIPS_26, R_MIPS_HI16, R_MIPS_LO16, R_MIPS_GPREL16 = range(8)
R_MIPS_PC16 = 10
FT = {R_MIPS_32: 0x0000000, R_MIPS_HI16: 0x1000000, R_MIPS_LO16: 0x2000000, R_MIPS_26: 0x3000000}
SHT_SYMTAB, SHT_NOBITS, SHT_REL, SHT_RELA = 2, 8, 9, 4
SHF_ALLOC = 2
SHN_ABS = 0xFFF1


def die(msg):
    sys.exit("elf2flt: " + msg)


def main():
    args = sys.argv[1:]
    stack = 8192
    if "--stack" in args:
        i = args.index("--stack")
        stack = int(args[i + 1], 0)
        del args[i:i + 2]
    src, dst = args
    elf = open(src, "rb").read()
    if elf[:4] != b"\x7fELF" or elf[4] != 1 or elf[5] != 1:
        die("not a 32-bit little-endian ELF")
    e_entry, e_phoff, e_shoff = struct.unpack_from("<III", elf, 24)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", elf, 46)
    secs = []
    for i in range(e_shnum):
        secs.append(struct.unpack_from("<IIIIIIIIII", elf, e_shoff + i * e_shentsize))
    shstr = secs[e_shstrndx]

    def name(off, strsec):
        b = elf[strsec[4] + off:]
        return b[:b.index(0)].decode()

    names = [name(s[0], shstr) for s in secs]

    # symbols
    symtab = next((i for i, s in enumerate(secs) if s[1] == SHT_SYMTAB), None)
    if symtab is None:
        die("no symbol table")
    st = secs[symtab]
    syms = []
    for k in range(st[5] // 16):
        st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack_from("<IIIBBH", elf, st[4] + k * 16)
        syms.append((name(st_name, secs[st[6]]), st_value, st_shndx))
    sym = {n: v for n, v, _ in syms if n}
    data_start, data_end, bss_end = sym["_data_start"], sym["_data_end"], sym["_bss_end"]

    # image: header + everything up to _data_end
    img = bytearray(data_end)
    for i, s in enumerate(secs):
        sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size = s[:6]
        if not (sh_flags & SHF_ALLOC) or sh_size == 0:
            continue
        if sh_type == SHT_NOBITS:
            if sh_addr < data_end:
                die("bss section %s below _data_end" % names[i])
            continue
        if sh_addr < 0x40 or sh_addr + sh_size > data_end:
            die("section %s at %#x+%#x outside 40h.._data_end" % (names[i], sh_addr, sh_size))
        img[sh_addr:sh_addr + sh_size] = elf[sh_offset:sh_offset + sh_size]

    # relocations
    relocs = []
    for i, s in enumerate(secs):
        if s[1] == SHT_RELA:
            die("RELA relocations are not supported")
        if s[1] != SHT_REL:
            continue
        target = secs[s[7]]
        if not (target[2] & SHF_ALLOC):
            continue                                   # debug sections
        ents = [struct.unpack_from("<II", elf, s[4] + k * 8) for k in range(s[5] // 8)]
        used = [False] * len(ents)
        for k, (off, info) in enumerate(ents):
            typ, sidx = info & 0xFF, info >> 8
            if typ in (R_MIPS_NONE, R_MIPS_PC16):
                continue
            if syms[sidx][2] == SHN_ABS:
                continue                               # absolute value: nothing to move
            if typ not in FT:
                die("unsupported relocation type %d at %#x (%s)" % (typ, off, names[s[7]]))
            if not (0x40 <= off < data_end):
                die("relocation at %#x outside the image" % off)
            if typ == R_MIPS_LO16:
                if not used[k]:
                    die("LO16 at %#x without its own HI16 (compile with -mno-explicit-relocs)" % off)
                continue
            relocs.append(FT[typ] | off)
            if typ == R_MIPS_HI16:
                for m in range(k + 1, len(ents)):
                    o2, i2 = ents[m]
                    if (i2 & 0xFF) == R_MIPS_LO16 and (i2 >> 8) == sidx:
                        if used[m]:
                            die("two HI16 share the LO16 at %#x" % o2)
                        used[m] = True
                        relocs.append(FT[R_MIPS_LO16] | o2)
                        break
                else:
                    die("HI16 at %#x without LO16" % off)

    hdr = struct.pack("<4sIIIIIIIII", b"bFLT", 2, e_entry, 0, data_start, data_end, bss_end, stack,
                      data_end, len(relocs))
    hdr += b"\0" * (0x40 - len(hdr))
    img[0:0x40] = hdr
    out = bytes(img) + b"".join(struct.pack("<I", r) for r in relocs)
    open(dst, "wb").write(out)
    print("%s: text+rodata %d, data %d, bss %d, stack %d, %d relocs -> %d bytes" % (
        dst, data_start - 0x40, data_end - data_start, bss_end - data_end, stack, len(relocs), len(out)))


main()
