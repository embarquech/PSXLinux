# The memory card root file system

PSXLinux mounts its root file system from the memory card in slot 1 (the kernel command line is
`root=/dev/bu0 console=ttyS0`). A ready image is in `release/psxlinux_root.mcd`. This page tells how
it is made, how to change it and how to put it on a card.

## What is on the card

The image is a raw copy of a whole 128 KB memory card: 1024 frames of 128 bytes, the same layout as
the `.mcd` / `.mcr` files of emulators and card tools. The kernel's driver
(`kernel/drivers/block/bu.c`) reads it like this:

| Frames | Content |
|---|---|
| 0 | Driver header: `u32 id = 0x1234`, `u32 size = 1024` (frames), `u32 serial`, `u32 number = 0` (first card) |
| 1 to 7 | Unused |
| 8 to 1023 | The block device `/dev/bu0`: 127 KB, here an **ext2** file system (revision 0, 1 KB blocks, 48 inodes) |

There is no "MC" header any more: the PlayStation BIOS sees the card as unformatted, and formatting
it from the BIOS destroys the file system. A second card in slot 2 would be `/dev/bu1`.

The file system holds:

- `/bin/sh`, `/sbin/init` and one hard link per command, all the same program: **psxsh**
  (`rootfs/src/psxsh.c`), a shell and about 30 commands in one binary, without any C library;
- `/etc/rc` (commands run at boot, before the shell) and `/etc/motd` (the welcome text);
- `/dev` (console, `ttyS0`, `null`, `zero`, `mem`, `bu0`, `bu1`...) and an empty `/proc`.

psxsh is a **bFLT** program, the only executable format of this uClinux kernel
(`kernel/fs/binfmt_flat.c`): a flat binary with relocation records, loaded anywhere in RAM.

## Building the image

You need bash, Python 3 and a MIPS GCC (`mipsel-none-elf-gcc` 12 was used; any GCC for MIPS I
little-endian works). Then, from the repository:

```
MIPS_GCC_BIN=/path/to/gcc/bin bash rootfs/build.sh
```

The script:

1. compiles `start.S` and `psxsh.c` (`-march=r3000 -msoft-float`, no libc) and links them with
   `src/flat.ld`, keeping the relocations (`-Wl,-q`);
2. converts the ELF to bFLT (`tools/elf2flt.py`). The PSXLinux loader wants every `LO16`
   relocation right after its own `HI16`: that is why the code is built with `-mno-explicit-relocs
   -mno-split-addresses`, and `elf2flt.py` refuses anything else;
3. checks the relocations: the same program is linked at a fixed address, and
   `tools/flatcheck.py` verifies that the bFLT, relocated the way the kernel does it, gives exactly
   the same bytes;
4. builds the card image (`tools/mkcard.py`) and checks it like `e2fsck` would
   (`tools/cardcheck.py`);
5. copies it to `release/psxlinux_root.mcd`.

The tools can also be used one by one:

```
python rootfs/tools/mkcard.py rootfs/skel rootfs/build/sh mycard.mcd   # tree + shell -> card image
python rootfs/tools/cardcheck.py mycard.mcd                            # check, list the files
python rootfs/tools/flatemu.py rootfs/build/sh rootfs/skel             # run psxsh on the PC
```

`flatemu.py` is a small MIPS emulator that loads the bFLT like the kernel and emulates the system
calls psxsh uses on top of a PC folder: handy to try the shell without a console.

## Adding files

Everything in `rootfs/skel` is copied to the card as is (files and folders). Put your files there
and rebuild. Room is short: 127 KB and 48 inodes in all; the current image uses 49 KB and leaves 78
KB and 15 inodes free. `mkcard.py` stops with "file system full" when it does not fit.

`/etc/rc` runs at boot, one command per line (`;` allowed): for example `cat /etc/motd`.

## Writing the card

**This erases the memory card.** Use a spare card, or save it first and write it back later:

```
nops /mcdown 0 backup.mcd COMx                    # save the card in slot 1
nops /mcup 0 release/psxlinux_root.mcd COMx      # write PSXLinux's root file system
nops /mcup 0 backup.mcd COMx                      # later: give the card its saves back
```

`0` is slot 1. This needs [nops](https://github.com/JonathanDotCel/NOTPSXSerial) on the PC, a serial
cable, and the console running **Unirom** or **OpenPsxRom** (from a cheat cartridge or a boot disc),
both of which accept these commands. Then boot
the kernel (see the README): it prints `VFS: Mounted root (ext2 filesystem)` and starts the shell.

Before you switch the console off, type `sync`, or `reboot` / `halt`, which sync the card first.
