/* bFLT v2 layout for the PSXLinux loader (fs/binfmt_flat.c, non-separate mode):
   the file is loaded contiguously, so link address == file offset. 0..3Fh is the header
   written by elf2flt.py; every relocation is "relative to text" (load address). */
OUTPUT_FORMAT("elf32-littlemips")
OUTPUT_ARCH(mips)
ENTRY(_start)
SECTIONS
{
    . = 0x801e8040;
    .text : { *(.text.start) *(.text .text.*) }
    .rodata : { *(.rodata .rodata.* .rodata1) }
    . = ALIGN(16);
    _data_start = .;
    .data : { *(.data .data.*) *(.sdata .sdata.*) }
    . = ALIGN(16);
    _data_end = .;
    .bss : { *(.sbss .sbss.* .scommon) *(.bss .bss.*) *(COMMON) }
    . = ALIGN(16);
    _bss_end = .;
    /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.MIPS.options) *(.comment) *(.pdr) *(.gnu.attributes) *(.mdebug.*) *(.note*) }
}
