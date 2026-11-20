# PSXLinux

Linux on the original Sony PlayStation: **PSXLinux**, the uClinux 2.4 port by **Runix**, brought
back to life on real hardware in 2026. The kernel boots on a stock console (no modchip, no disc
swap), mounts its root file system from a **memory card** and gives a shell on the **serial port**.

```
  PSXLinux - uClinux 2.4 on the Sony PlayStation
  root file system: ext2 on the memory card in slot 1 (/dev/bu0, 127 KB)
  type 'help' for the commands. 'reboot' syncs the card first.
psx:/#
```

## Credits

PSXLinux is the work of **Runix** (www.runix.ru), a project of **Blokman Trading s.r.o.**
(Vadim V. Veshchezerov, CEO), released in 2001 as kernel alpha 2 and beta 1. It is based on
**uClinux** 2.4 (www.uclinux.org) and the Linux kernel. The SL811H USB host driver was written by
A. Burmistrov. All of the kernel in `kernel/` is theirs and stays under the GNU GPL (`kernel/COPYING`).

What this repository adds: the memory card root file system and its tools, a userland, a kernel
configuration that is safe with cheat cartridges, and the instructions below.

## Repository

| Path | Content |
|---|---|
| `kernel/` | PSXLinux kernel sources. History: the first commit is **alpha 2** as released, the second one the **beta 1** changes on top of it (see below). |
| `release/psxlinux.exe` | The kernel, built from beta 1, as a PS-EXE. |
| `release/psxlinux_root.mcd` | The root file system: a 128 KB memory card image. |
| `rootfs/` | Userland (`psxsh`) and the tools that make the card image. |
| `tools/terminal.ps1` | Serial terminal for the console (Windows). |
| `docs/` | [The memory card](docs/memory-card.md), [`pad`: controller test](docs/pad.md), [`btc`: Bitcoin mining](docs/bitcoin.md). |

### Alpha 2 to beta 1

Beta 1 (74 files changed) brings: the console on the serial port (SIO, 115200 8N1,
`drivers/char/serial_psx.c`); a reworked memory card block driver (`drivers/block/bu.c`: bug fixes,
large cards, two cards joined as one device); an improved GPU virtual console; bFLT loader fixes;
and drivers for Runix's own hardware add-on (a PIO expansion board with an SL811H USB host for a
keyboard and a mouse, and a real-time clock). It also ships two ready configurations, `Config` and
`Config_Addon` (with the add-on).

## The memory card root file system

There was no root file system to download any more, so one was written from the kernel's memory
card driver (`kernel/drivers/block/bu.c`):

- **Format**: a raw image of a whole memory card, 1024 frames of 128 bytes (128 KB): the same
  format as the `.mcd` / `.mcr` files of emulators and card tools. Frame 0 holds the driver's
  header, frames 8 to 1023 are the block device `/dev/bu0`: 127 KB of **ext2**.
- **Userland**: no libc. `psxsh` is a single **bFLT** program (the kernel's executable format):
  `/sbin/init`, `/bin/sh` and about 30 commands (`ls cat cp mv rm mkdir ps kill mount df free
  dmesg hexdump reboot`..., [`pad`](docs/pad.md) for a controller test, [`btc`](docs/bitcoin.md)
  for a Bitcoin mining demo). See `rootfs/src/psxsh.c`.
- **Build**: `bash rootfs/build.sh` (any MIPS GCC; `MIPS_GCC_BIN` = its `bin` folder). It checks
  the relocations, writes the card image and verifies the ext2 file system. Details, and how to add
  your own files: [docs/memory-card.md](docs/memory-card.md).

**Writing the card erases it**, and the PlayStation BIOS no longer sees it as a game card. Use a
spare card, or save it first. Copy the image to the card in slot 1 with
[nops](https://github.com/JonathanDotCel/NOTPSXSerial) and a console running **Unirom** or
**OpenPsxRom** (from a cheat cartridge or a boot disc):

```
nops /mcup 0 release/psxlinux_root.mcd COMx
```

## Booting

You need a PlayStation, a serial cable (SIO port, 115200 bauds) and a way to load an EXE over the
serial port: **Unirom** or **OpenPsxRom** on a cheat cartridge (Action Replay, GameShark, Xplorer...)
or on a boot disc. No modchip and no disc swap are needed.

```
nops /exe release/psxlinux.exe /m COMx
```

The kernel boot log, then the shell, appear on the serial line (115200 8N1, no flow control).
`nops /m` echoes every key locally; `tools/terminal.ps1 -Port COMx` is a terminal without that echo.
Type `reboot` (or `halt`) to stop: the card is synced first. There is no display output: everything
goes through the serial port.

## Safe with cheat cartridges

The original configuration enabled the drivers for Runix's PIO expansion board
(`CONFIG_PSX_PIO_EXTENSION`, the RTC, the SL811H USB host). They move the expansion port window
(registers 1F801000h and 1F801008h) and write to registers that, on a normal console, land on
whatever sits on the expansion port: the cheat cartridge. Booting that kernel twice left an Xplorer
unbootable, its flash firmware overwritten.

`release/psxlinux.exe` is built from beta 1 with those three drivers disabled (and `CONFIG_PC_KEYB`
kept, which the build needs): the kernel never writes to the expansion port, and the Action Replay,
GameShark or Xplorer firmware stays intact.

## Building the kernel

The kernel needs Runix's toolchain: egcs 1.1.2 and binutils 2.9.5 for mipsel, which only run on an
old Linux/i386 (Debian 5 in a virtual machine works). In `kernel/`: `make clean && make dep && make`
gives the ELF `linux`, then:

1. `arch/mipsnommu/boot/elf2ecoff linux linux.ecoff`;
2. `eco2exe linux.ecoff` gives a PS-EXE whose text size field is wrong (0xFFFF0000);
3. fix the header: word at 1Ch = file size - 2048, rounded up to 2048; zero-pad the file to a
   multiple of 2048, and clear everything after `_edata` (eco2exe leaves junk in the BSS).

The kernel runs at 00010000h (KUSEG), entry 00010388h, stack 801FFFF0h.
