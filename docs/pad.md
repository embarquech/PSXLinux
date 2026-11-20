# `pad`: controller test

`pad` shows the buttons and sticks of both controllers, live, on the serial console. It works with
digital pads, DualShock and analog controllers, and names the mouse, neGcon and Guncon (for those,
only the buttons are decoded).

```
psx:/# pad
controller test - START+SELECT to quit
pad 1: digital  (no button)
pad 2: -
pad 1: digital  X
pad 1: digital  UP X
pad 1: analog (DualShock)  R1   R:80,7F L:80,80
```

- A line is printed only when something changes on that port.
- `-` means no controller answered on that port.
- Analog controllers also show the right (`R:x,y`) and left (`L:x,y`) sticks, in hex: `80` is the
  middle, `00` and `FF` the ends.
- **START + SELECT** together on a controller quits.

## How it works

PSXLinux has no driver for the controllers, so `pad` talks to them itself, from user space (no MMU:
a program can reach the hardware registers). Every 20 ms, for port 1 then port 2, it runs the
standard exchange on SIO0 (the controller and memory card port, registers at 1F801040h):
`01h` (address the controller), `42h` (read; the answer is the controller's ID: type and length),
then the button bytes, then the stick bytes. Buttons are active low.

The same port is used by the kernel's memory card driver. `pad` first syncs the file system (no card
access is pending after that), never enables the ACK interrupt the card driver uses, and times every
byte by polling the status register. The card stays untouched while `pad` runs.

The code is `a_pad()` in `rootfs/src/psxsh.c`.
