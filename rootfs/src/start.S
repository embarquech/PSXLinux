# Entry point and raw system calls for PSXLinux (uClinux 2.4 MIPS, bFLT, no libc).
# Syscall ABI of this kernel: number in v0 (i386 numbering, __NR_Linux = 0), args a0-a3 and
# 16(sp) for the 5th; on return a3 != 0 means error and v0 holds the positive errno.

	.set	noreorder
	.set	noat
	.text
	.section .text.start, "ax"
	.globl	_start
_start:
	# stack set by binfmt_flat: argc, argv[0..argc-1], NULL, envp..., NULL
	lw	$a0, 0($sp)
	addiu	$a1, $sp, 4
	sll	$t0, $a0, 2
	addu	$a2, $a1, $t0
	addiu	$a2, $a2, 4
	addiu	$sp, $sp, -32
	jal	main
	nop
	move	$a0, $v0
	li	$v0, 1			# exit
	syscall
	nop
1:	b	1b
	nop

	.text
# long __sc(long nr, long a, long b, long c, long d, long e) -> result or -errno
	.globl	__sc
	.ent	__sc
__sc:
	move	$v0, $a0
	move	$a0, $a1
	move	$a1, $a2
	move	$a2, $a3
	lw	$a3, 16($sp)
	lw	$t0, 20($sp)
	nop
	sw	$t0, 16($sp)		# 5th argument where the kernel reads it
	syscall
	beqz	$a3, 1f
	nop
	subu	$v0, $zero, $v0
1:	jr	$ra
	nop
	.end	__sc

# int spawn(const char *path, char **argv, char **envp) -> child pid or -errno
# vfork + execve without touching the (shared) stack in the child.
	.globl	spawn
	.ent	spawn
spawn:
	addiu	$sp, $sp, -16
	sw	$s0, 0($sp)
	sw	$s1, 4($sp)
	sw	$s2, 8($sp)
	move	$s0, $a0
	move	$s1, $a1
	move	$s2, $a2
	li	$v0, 190		# vfork
	syscall
	bnez	$a3, 3f
	nop
	bnez	$v0, 2f
	nop
	# child
	move	$a0, $s0
	move	$a1, $s1
	move	$a2, $s2
	li	$v0, 11			# execve
	syscall
	li	$a0, 127
	li	$v0, 1			# exit(127)
	syscall
	nop
3:	subu	$v0, $zero, $v0
2:	lw	$s0, 0($sp)
	lw	$s1, 4($sp)
	lw	$s2, 8($sp)
	jr	$ra
	addiu	$sp, $sp, 16
	.end	spawn
