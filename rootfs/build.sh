#!/bin/bash
# Build psxsh (bFLT) and the memory card rootfs image: build/psxlinux_root.mcr (+ copy in ../release).
# -mno-split-addresses: GCC must not share one %hi between several %lo (the PSXLinux bFLT loader
# needs every LO16 right after its own HI16; elf2flt.py rejects anything else).
set -e
cd "$(dirname "$0")"
export PATH=${MIPS_GCC_BIN:-../../tools/gcc/bin}:$PATH   # mipsel-none-elf-gcc 12.x (any MIPS GCC)
CF="-march=r3000 -mabi=32 -EL -msoft-float -mno-abicalls -fno-pic -G0 -mno-gpopt -mno-explicit-relocs \
-mno-split-addresses -Os -ffreestanding -fno-builtin -fno-tree-loop-distribute-patterns -fno-stack-protector \
-Wall -Wextra -Wno-unused-parameter"
mipsel-none-elf-gcc $CF -c src/start.S -o build/start.o
mipsel-none-elf-gcc $CF -c src/psxsh.c -o build/psxsh.o
mipsel-none-elf-gcc $CF -nostdlib -nostartfiles -T src/flat.ld -Wl,-q -Wl,--no-relax -o build/psxsh.elf build/start.o build/psxsh.o
python tools/elf2flt.py build/psxsh.elf build/sh
# relocation check: same program linked at 0x801E8000 must match the relocated bFLT
mipsel-none-elf-gcc $CF -nostdlib -nostartfiles -T build/flat_test.ld -Wl,--no-relax -o build/psxsh_test.elf build/start.o build/psxsh.o
python tools/flatcheck.py build/sh build/psxsh_test.elf 0x801e8000
python tools/mkcard.py skel build/sh build/psxlinux_root.mcr
python tools/cardcheck.py build/psxlinux_root.mcr | tail -2
cp build/psxlinux_root.mcr ../release/psxlinux_root.mcd
