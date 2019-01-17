# MAR_Assembler

A standalone assembler for [Much Assembly Required](https://muchassemblyrequired.com).

It will eventually enable shared libraries to be used in MAR.

The recommended usage is `./assembler.py input_file --raw_asm --pdc --dcl`.
This outputs raw code instead of an object file, uses position-dependent code (with a base address of 0x200), and prints in a format which can be pasted directly into the MAR editor.