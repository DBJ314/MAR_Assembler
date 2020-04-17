#!/usr/bin/env python3
import sys
import getopt
import io
import re
import struct

#Special API pointer addresses
APIGetMyAddress = 0x0001
APIGetRelativeOffset = 0x0002
APIPrepareTable = 0x0003
APIGetTableValue = 0x0004
APIRestoreOldTable = 0x0005
APIGetSymbol = 0x0006
APIGetVar = 0x0007#not implemented yet in Relative Offset API version 0.3
APIPICTemp = 0x001B#not implemented yet either
def printUsage():
    print("assembler.py input_file [--pdc] [--dcl] [--raw_asm]")
    print("    pdc: force code to be position-dependent")
    print("    dcl: give output as DC.L statements so it can be \n         pasted into MAR (defaults to raw output)")
    print("    raw_asm: disable object file and output raw code")

if(len(sys.argv) < 2):
    printUsage()
    sys.exit(2)

pic_default = True
dcl_mode = False
wrap_asm = True

try:
    opts, args = getopt.getopt(sys.argv[2:], "p:d:r", ["pdc", "dcl", "raw_asm"])
except getopt.GetoptError:
    printUsage()
    sys.exit(2)

for opt, arg in opts:
    if opt in ("-p", "--pdc"):
        pic_default = False
    if opt in ("-d", "--dcl"):
        dcl_mode = True
    if opt in ("-r", "--raw_asm"):
        wrap_asm = False
try:
    input = io.open(sys.argv[1], mode='rt')

except IOError:
    print("Input file cannot be opened")
    printUsage()
    sys.exit(2)

#non-MAR assembler directives:
#   pic {on, off, default}:
#       turns position-independent code on, off, or sets it to the default (usally on, but could be off if --pdc is used)
#   name myname:
#       sets the object file name for symbol export purposes
#   importlib libname:
#       sets the next import directives to import from this library
#   import importname [as symbolname]:
#       imports a symbol from a library, optionally giving it a different internal name
#   export symbolname [as exportname]:
#       exports a symbol, optionally giving it a different external name

pic_on = pic_default
obj_name = None     #name of the resulting code
lib_name = None     #name of the library to import from

def eprint(*args, **kwargs):#tiny little stackoverflow snippet to print to stderr
    print(*args, file=sys.stderr, **kwargs)

in_text_section = True

org_value = 0x200
text_array_base = 0
data_array_base = 0
text_array = []
data_array = []
last_used_text_offset = 0#will be used to make sure that the last label points to an actual value
last_used_data_offset = 0

def add_word(word):
    if in_text_section:
        global text_array
        text_array.append(word & 0xFFFF)
    else:
        global data_array
        data_array.append(word & 0xFFFF)

def get_current_offset():
    if in_text_section:
        return len(text_array)
    return len(data_array)

def set_last_used_offset():
    if in_text_section:
        global last_used_text_offset
        last_used_text_offset = len(text_array)
    else:
        global last_used_data_offset
        last_used_data_offset = len(data_array)
lib_name_array = []
equ_dict = {}
import_dict = {}
export_dict = {}

import_magic_prefix = "import:"#special prefix to ensure it can't be defined as a label
resolved_labels = {}
symbol_refs = []    #list of (in_text_section, offset, symbol, needs_API_decision) tuples (symbol can be label, data, or import)

whitespace_re = re.compile(r'^\s+')
comment_re = re.compile(r'^[^";]*("[^"]*"[^";]*)*;')

label_re = re.compile(r'^[a-zA-Z_]\w*:')
dw_seperator_re = re.compile(r',(?=(?:[^"]*"[^"]*")*[^"]*$)')# borrowed from MAR source
mnemonic_re = re.compile(r'^[a-zA-Z]+')

plus_re = re.compile(r'\+')
minus_re = re.compile(r'-')
#(MEM_OR_REG, IMM, BLANK)
s_dst = (True, False, False)
s_src = (True, True, False)
s_non = (False, False, False)
normal_instructions = {
    #mnemonic : (opcode, src, dest)
    'add'  : (0x02, s_src, s_dst),
    'and'  : (0x04, s_src, s_dst),
    'brk'  : (0x00, s_non, s_non),
    'call' : (0x15, s_src, s_non),
    'cmp'  : (0x0C, s_src, s_dst),
    'dec'  : (0x04, s_dst, s_non),
    'div'  : (0x18, s_src, s_non),
    'hwi'  : (0x09, s_src, s_non),
    'hwq'  : (0x1C, s_src, s_non),
    'inc'  : (0x2A, s_dst, s_non),
    'ja'   : (0x2E, s_src, s_non),
    'jc'   : (0x21, s_src, s_non),
    'jg'   : (0x0F, s_src, s_non),
    'jge'  : (0x10, s_src, s_non),
    'jl'   : (0x11, s_src, s_non),
    'jle'  : (0x12, s_src, s_non),
    'jmp'  : (0x0A, s_src, s_non),
    'jna'  : (0x2F, s_src, s_non),
    'jnc'  : (0x22, s_src, s_non),
    'jno'  : (0x25, s_src, s_non),
    'jns'  : (0x1B, s_src, s_non),
    'jnz'  : (0x0D, s_src, s_non),
    'jo'   : (0x24, s_src, s_non),
    'js'   : (0x1A, s_src, s_non),
    'jz'   : (0x0E, s_src, s_non),
    'mov'  : (0x01, s_src, s_dst),
    'mul'  : (0x17, s_src, s_non),
    'neg'  : (0x19, s_dst, s_non),
    'nop'  : (0x3F, s_non, s_non),
    'not'  : (0x1D, s_dst, s_non),
    'or'   : (0x05, s_src, s_dst),
    'pop'  : (0x14, s_dst, s_non),
    'popf' : (0x2C, s_non, s_non),
    'push' : (0x13, s_src, s_non),
    'pushf': (0x2D, s_non, s_non),
    'rcl'  : (0x27, s_src, s_dst),
    'rcr'  : (0x28, s_src, s_dst),
    'ret'  : (0x16, (False, True, True), s_non),
    'rol'  : (0x23, s_src, s_dst),
    'ror'  : (0x20, s_src, s_dst),
    'sal'  : (0x06, s_src, s_dst),
    'sar'  : (0x29, s_src, s_dst),
    'shl'  : (0x06, s_src, s_dst),
    'shr'  : (0x07, s_src, s_dst),
    'sub'  : (0x03, s_src, s_dst),
    'test' : (0x0B, s_src, s_dst),
    'xchg' : (0x1F, s_dst, s_dst),
    'xor'  : (0x0C, s_src, s_dst),
}

registers = {
    'a' : 1,
    'b' : 2,
    'c' : 3,
    'd' : 4,
    'x' : 5,
    'y' : 6,
    'sp': 7,
    'bp': 8
}

def remove_comments(line):
    comment_match = comment_re.match(line)
    if(comment_match):
        if(comment_match.end()==1):
            return ""
        return line[0:comment_match.end()-1]
    return line

def skip_front_whitespace(line):
    whitespace_match = whitespace_re.match(line)
    if(whitespace_match):
        return line[whitespace_match.end():]
    return line

def process_labels(line):
    global last_used_code_offset
    global resolved_labels
    label_match = label_re.match(line)
    if(label_match):
        label = label_match.group()[:-1]
        set_last_used_offset()
        if label in resolved_labels:
            eprint("error: label '"+label+"' defined twice")
            sys.exit(1)
        resolved_labels[label] = (in_text_section, get_current_offset())
        return skip_front_whitespace(line[label_match.end():])
    return line

def process_equates(line):
    words = line.split()
    if(len(words)==3 and words[1].upper() == "EQU"):
        equ_symbol, equ_equ, equ_value = words
        if equ_symbol in equ_dict:
            eprint("error: equate '"+equ_symbol+"' defined twice")
            sys.exit(1)
        equ_dict[equ_symbol] = int(equ_value,0)
        return True
    return False

def process_extended_directives(line):
    words = line.split()
    if len(words) < 1:
        return False
    cmd = words[0].lower()
    if cmd == 'pic':
        global pic_on
        if words[1].lower() == 'on':
            pic_on = True
        elif words[1].lower() == 'off':
            pic_on = False
        elif words[1].lower() == 'default':
            pic_on = pic_default
        else:
            eprint("Error: '"+line+"' is not a valid directive")
            sys.exit(1)
        return True
    elif cmd == 'name':
        global obj_name
        if obj_name:
            eprint("Error: NAME directive used multiple times")
            sys.exit(1)
        obj_name = words[1]
        return True
    elif cmd == 'importlib':
        global lib_name
        lib_name = words[1]
        return True
    elif cmd == 'import':
        global import_dict
        global lib_name_array
        import_name = words[1]
        symbol_name = import_name
        if len(words)==4:
            if words[2].lower() == 'as':
                symbol_name == words[3]
        if symbol_name in import_dict:
            eprint("error: import symbol '"+symbol_name+"' defined twice")
            sys.exit(1)
        if lib_name not in lib_name_array:
            lib_name_array.append(lib_name)
        import_dict[symbol_name] = (lib_name, import_name)
        return True
    elif cmd == 'export':
        global export_dict
        symbol_name = words[1]
        export_name = words[1]
        if len(words)==4:
            if words[2].lower() == 'as':
                export_name = words[3]
        if export_name in export_dict:
            eprint("error: export symbol '"+export_name+"' defined twice")
            sys.exit(1)
        export_dict[export_name] = symbol_name
        return True
    else:
        return False


def process_dw(line):
    if len(line) < 2:
        return False
    if line[:2].lower() != 'dw':
        return False
    line = line[2:]
    dw_args = list(map(lambda x: x.strip(), dw_seperator_re.split(line)))
    for dw_arg in dw_args:
        process_dw_arg(dw_arg)
    return True

def process_dw_arg(dw_arg):
    if dw_arg[0] == '"' and dw_arg[-1] == '"':#It's a string
        dw_str = dw_arg[1:-1]
        for c in dw_str:
            add_word(ord(c))
    elif dw_arg[-1]==')':#dup directive
        values = re.split(" |\(", dw_arg[:-1])
        if values[1].lower() != 'equ':
            return#could throw an error, but I won't botherr
        for blah in range(values[0]):
            process_dw_arg(values[2])#adds a few interesting language features, like using dup on a string
    elif dw_arg in equ_dict:
        add_word(equ_dict[dw_arg])
    elif dw_arg in import_dict:
        eprint("Error: equs cannot contain imported symbols")
        sys.exit(1)
    else:#try and parse as an int. If exception, it's a label
        try:
            add_word(int(dw_arg,0))
        except ValueError:
            global symbol_refs
            symbol_refs.append((in_text_section, get_current_offset(), dw_arg, False))
            add_word(0)
            
def process_normal_directives(line):#the prime directives
    global in_text_section
    words = line.split()
    if len(words)<1:
        return False
    cmd = words[0].lower()
    if cmd == 'org':
        global org_value
        org_value = int(words[1],0)
        return True
    elif cmd == '.text':
        in_text_section = True
        return True
    elif cmd == '.data':
        in_text_section = False
        return True
    return False

def decode_operand(op):
    has_ptr = False
    reg_used = None
    imm_used = None
    spc_used = None
    
    if op.lower() in registers:
        reg_used = registers[op.lower()]
    elif op in equ_dict:
        imm_used = equ_dict[op]
    elif op in import_dict:
        spc_used = op
    elif op[0] == '[' and op[-1] == ']':
        op = op[1:-1]
        has_ptr = True
        plus_match = op.split('+')
        minus_match = op.split('-')
        if len(plus_match) == 1 and len(minus_match) == 1:
            if op.lower() in registers:
                reg_used = registers[op.lower()]
            elif op in equ_dict:
                imm_used = equ_dict[op]
            elif op in import_dict:
                spc_used = op
            else:
                try:
                    imm_used = int(op,0)
                except ValueError:
                    spc_used = op#must be symbol
        else:
            if len(plus_match)>1:
                subops = [plus_match[0].strip(), '+', plus_match[1].strip()]
            else:
                subops = [minus_match[0].strip(), '-', minus_match[1].strip()]
            if subops[0].lower() in registers:
                reg_used = registers[subops[0].lower()]
            elif subops[0] in equ_dict:
                imm_used = equ_dict[subops[0]]
            elif subops[0] in import_dict:
                spc_used = subops[0]
            else:
                try:
                    imm_used = int(op,0)
                except ValueError:
                    spc_used = op#must be symbol
            if subops[2].lower() in registers:
                if reg_used:
                    eprint("Error: 2 regs used in one operand")
                    sys.exit(1)
                if subops[1] != '+':
                    eprint("Error: registers can only be added in [] constructs")
                    sys.exit(1)
                reg_used = registers[subops[2].lower()]
            elif subops[2] in equ_dict:
                imm_used = equ_dict[subops[2]]
                if subops[1] == '-':
                    imm_used = (0x10000 - imm_used) & 0xFFFF
            elif subops[2] in import_dict:
                spc_used = subops[2]
            else:
                try:
                    imm_used = int(subops[2],0)
                    if subops[1] == '-':
                        imm_used = (0x10000 - imm_used) & 0xFFFF
                except ValueError:
                    spc_used = subops[2]
    else:#op not ptr
        try:
            imm_used = int(op,0)
        except ValueError:
            spc_used = op#must be symbol
    return (has_ptr, reg_used, imm_used, spc_used)

def handle_symbol_lookup(has_ptr, reg_used, imm_used, spc_used, prev_spc_used, prev_has_ptr):
    global symbol_refs
    if (not pic_on) or (spc_used is None):
        return (has_ptr, reg_used, imm_used, spc_used, False)
    if has_ptr:
        if prev_spc_used is not None:
            if prev_has_ptr:
                add_word(0x6781)#compile a MOV [APIPICTemp],[D]
            else:
                add_word(0x2781)#compile a MOV [APIPICTemp],D
            add_word(APIPICTemp)
        add_word(0xF901)#MOV offset -> D
        fixup_pt = get_current_offset()
        add_word(0x10000-(fixup_pt+1))
        add_word(0xF015)#CALL [IMM16]
        if spc_used in import_dict:
            symbol_refs.append((in_text_section, fixup_pt, spc_used, False))
            add_word(APIGetSymbol)
        else:
            symbol_refs.append((in_text_section, fixup_pt, spc_used, True))
            add_word(0)
        if reg_used is not None:
            add_word(0x2002 | (reg_used << 6 ))#compile a ADD D, reg_used
        return (True, registers['d'], None, None, True)
    else:#simpler code path. Just a single label
        if prev_spc_used is not None:
            if prev_has_ptr:
                add_word(0x6781)#compile a MOV [APIPICTemp],[D]
            else:
                add_word(0x2781)#compile a MOV [APIPICTemp],D
            add_word(APIPICTemp)
        add_word(0xF901)#MOV offset -> D
        fixup_pt = get_current_offset()
        add_word(0x10000-(fixup_pt+1))
        add_word(0xF015)#CALL [IMM16]
        if spc_used in import_dict:
            symbol_refs.append((in_text_section, fixup_pt, spc_used, False))
            add_word(APIGetSymbol)
        else:
            symbol_refs.append((in_text_section, fixup_pt, spc_used, True))
            add_word(0)
        return (False, registers['d'], None, None, True)

def validate_operand_mode(mode_tuple, has_ptr, reg_used, imm_used, spc_used):
    mem_or_reg, imm, blank = mode_tuple
    if has_ptr and mem_or_reg:
        return False
    if (reg_used is not None) and mem_or_reg:
        return False
    if (imm or (has_ptr and mem_or_reg)) and ((imm_used is not None) or spc_used is not None):
        return False
    if (blank or ((not mem_or_reg) and (not imm))) and (not has_ptr) and (reg_used is None) and (imm_used is None) and (spc_used is None):
        return False
    eprint("Error: invalid operand mode")
    return True

def assemble_operand(has_ptr, reg_used, imm_used, spc_used):
    operand = 0
    if reg_used is not None:
        operand = reg_used
        if has_ptr:
            operand = operand + 8
            if imm_used is not None or spc_used is not None:
                operand = operand + 8
    elif imm_used is not None or spc_used is not None:
        if has_ptr:
            operand = 0x1E
        else:
            operand = 0x1F
    return operand
        
        
def process_instructions(line):
    mnemonic_match = mnemonic_re.match(line)
    if not mnemonic_match:
        return False
    instruction = line[:mnemonic_match.end()].lower()
    if instruction not in normal_instructions:
        return False
    ops = line[mnemonic_match.end():].split(',')
    ops = list(map(lambda x: x.strip(), ops))
    src = ops[0]
    dst = None
    if len(ops)==2:
        dst = ops[0]
        src = ops[1]
    if len(src) > 0:
        src_has_ptr, src_reg_used, src_imm_used, src_spc_used = decode_operand(src)
    else:
        src_has_ptr, src_reg_used, src_imm_used, src_spc_used = (False, None, None, None)
    if dst and len(dst)>0:
        dst_has_ptr, dst_reg_used, dst_imm_used, dst_spc_used = decode_operand(dst)
    else:
        dst_has_ptr, dst_reg_used, dst_imm_used, dst_spc_used = (False, None, None, None)

    src_has_ptr, src_reg_used, src_imm_used, src_spc_used, src_used_pic = handle_symbol_lookup(src_has_ptr, src_reg_used, src_imm_used, src_spc_used, None, False)

    dst_has_ptr, dst_reg_used, dst_imm_used, dst_spc_used, dst_used_pic = handle_symbol_lookup(dst_has_ptr, dst_reg_used, dst_imm_used, dst_spc_used, src_used_pic, src_has_ptr)

    if src_used_pic and dst_used_pic:
        src_has_ptr, src_reg_used, src_imm_used, src_spc_used = (True, None, APIPICTemp, None)
    opcode, src_mode, dst_mode = normal_instructions[instruction]

    if validate_operand_mode(src_mode, src_has_ptr, src_reg_used, src_imm_used, src_spc_used) or validate_operand_mode(dst_mode, dst_has_ptr, dst_reg_used, dst_imm_used, dst_spc_used):
        print(line)
        print(ops)
        print((src_mode,(src_has_ptr, src_reg_used, src_imm_used, src_spc_used, src_used_pic)))
        print((dst_mode,(dst_has_ptr, dst_reg_used, dst_imm_used, dst_spc_used, dst_used_pic)))

    final_instruction = opcode | (assemble_operand(src_has_ptr, src_reg_used, src_imm_used, src_spc_used) << 11) | (assemble_operand(dst_has_ptr, dst_reg_used, dst_imm_used, dst_spc_used) << 6)
    add_word(final_instruction)
    global symbol_refs
    if(src_spc_used is not None):
        symbol_refs.append((in_text_section, get_current_offset(), src_spc_used, False))
        add_word(0)
    if(src_imm_used is not None):
        add_word(src_imm_used)
    if(dst_spc_used is not None):
        symbol_refs.append((in_text_section, get_current_offset(), dst_spc_used, False))
        add_word(0)
    if(dst_imm_used is not None):
        add_word(dst_imm_used)
    return True

def parse_line(line):
    line = skip_front_whitespace(line)
    line = remove_comments(line)
    if not (line):#the end of the line
        return
    line = process_labels(line)
    if process_dw(line):
        return
    if process_equates(line):
        return
    if process_extended_directives(line):
        return
    if process_normal_directives(line):
        return
    if process_instructions(line):
        return
    #print(line)

line = input.readline()
while(line):
    parse_line(line)
    line = input.readline()

lib_magic = '%lib_'

in_text_section = True
for lib in lib_name_array:
    resolved_labels[lib_magic + lib] = (True,get_current_offset())
    for c in lib:
        add_word(ord(c))
    add_word(0)

for symbol_name, value in import_dict.items():
    lib_name, import_name = value
    fixup_pt = get_current_offset()
    resolved_labels[symbol_name] = (True,fixup_pt)
    symbol_refs.append((True, fixup_pt, lib_magic + lib_name, False))
    add_word(0x10000 - fixup_pt)
    for c in import_name:
        add_word(ord(c))
    add_word(0)

if last_used_text_offset == len(text_array):
    text_array.append(0)
if last_used_data_offset == len(data_array):
    data_array.append(0)

final_array = []

obj_export_struct_ptr_offset = 1

text_array_base = org_value

if wrap_asm:#set up object file
    final_array.append(0xCB07)
    final_array.append(0xFFFF)
    if obj_name:
        for c in obj_name:
            final_array.append(ord(c))
    final_array.append(0)
    text_array_base = text_array_base + len(final_array)
else:
    data_array_base = text_array_base + len(text_array)

if pic_default:
    text_array_base = 0
    data_array_base = 0

data_text_relocs = []
data_data_relocs = []

#symbol_refs = []    #list of (in_text_section, offset, symbol, needs_API_decision) tuples (symbol can be label, data, or import)
def fix_reference(reference_tuple):
    global text_array
    global data_array
    in_text, offset, symbol_name, needs_API_decision = reference_tuple
    symbol_in_text, symbol_offset = resolved_labels[symbol_name]
    if symbol_in_text:
        symbol_address = symbol_offset + text_array_base
    else:
        symbol_address = symbol_offset + data_array_base
    if needs_API_decision:
        if symbol_in_text or ((not symbol_in_text) and not in_text):
            api_choice = APIGetRelativeOffset
        else:
            api_choice = APIGetVar
            if pic_default:
                symbol_address = symbol_address + offset + 1#undo the relative changes
        if in_text:
            text_array[offset+2] = api_choice
        else:
            data_array[offset+2] = api_choice
    if in_text:
        text_array[offset] = (text_array[offset]+symbol_address)&0xFFFF
    else:
        data_array[offset] = (data_array[offset]+symbol_address)&0xFFFF
        if symbol_in_text:
            data_text_relocs.append(offset)
        else:
            data_data_relocs.append(offset)
for reference in symbol_refs:
    fix_reference(reference)

if wrap_asm:#set up the object file's data init symbol
    resolved_labels['%data'] = (True, len(text_array))
    add_word(len(data_array))
text_offset_in_final = len(final_array)
final_array.extend(text_array)
data_offset_in_final = len(final_array)
final_array.extend(data_array)
if wrap_asm:
    for reloc in data_text_relocs:
        final_array.append(reloc)
    final_array.append(0xFFFF)
    for reloc in data_data_relocs:
        final_array.append(reloc)
    final_array.append(0xFFFF)

#   %data:
#   DW data_len
#   ;data
#   offsets for data locations which point to text section
#   DW 0xFFFF
#   offsets for data locations which point to data section
#   DW 0xFFFF

class Trie:
    children = {}
    value = None
    def __init__(self, k_str, value):
        self.children = {}
        self.add(k_str, value)
    def add(self, k_str, value):
        if len(k_str) == 0:
            if self.value is not None:
                eprint("Error: duplicate symbol definition")
                sys.exit(1)
            self.value = value
            return
        c = k_str[0]
        if c in self.children:
            self.children[c].add(k_str[1:], value)        
        else:
            self.children[c] = Trie(k_str[1:],value)
root_trie = Trie('%data', '%data')
for export_name, symbol_name in export_dict.items():
    root_trie.add(export_name, symbol_name)

def get_symbol_final_offset(symbol):
    in_text, offset = resolved_labels[symbol]
    if in_text:
        return offset + text_offset_in_final
    return offset + data_offset_in_final

def form_trie(node, continues = False):
    global final_array
    c_len = len(node.children)
    if continues and c_len > 1:
        final_array.append(0)
        final_array.append(1)
    my_base = len(final_array)
    if c_len == 0:
        final_array.append(0)#end of string
        final_array.append(0)#leaf node
        final_array.append((get_symbol_final_offset(node.value) - len(final_array))&0xFFFF)
        return my_base
    if c_len == 1:
        if not continues:
            final_array.append(0)#replaced by placeholder later
        key = list(node.children.keys())[0]
        
        final_array.append(ord(key))
        form_trie(node.children[key], True)
        return my_base
    prev_offset = None
    for key, sub_node in node.children.items():
        sub_offset = form_trie(sub_node)
        if prev_offset is not None:
            final_array[prev_offset] = (sub_offset-prev_offset)&0xFFFF
        prev_offset = sub_offset
    if node.value is not None:
        if prev_offset is not None:
            final_array[prev_offset] = (len(final_array)-prev_offset)&0xFFFF
        final_array.append(0)#no next entry
        final_array.append(0)#empty name string
        final_array.append(0)#leaf node
        final_array.append((get_symbol_final_offset(node.value) - len(final_array))&0xFFFF)
    return my_base

if wrap_asm:
    final_array[obj_export_struct_ptr_offset] = (len(final_array) - obj_export_struct_ptr_offset)&0xFFFF
    form_trie(root_trie)


if dcl_mode:
    div_len = int((len(final_array)&0xFFFC)/4)
    mod_len = len(final_array)&3#mod by 4
    for index in range(div_len):
        base = index*4
        print("DW {0:#06x}, {1:#06x}, {2:#06x}, {3:#06x}".format(final_array[base]&0xFFFF,final_array[base+1]&0xFFFF,final_array[base+2]&0xFFFF,final_array[base+3]&0xFFFF))
    for index in range(mod_len):
        print("DW {0:#06x}".format(final_array[div_len*4 + index]&0xFFFF))
else:
    byteout = bytearray(len(final_array)*2)
    for index in range(len(final_array)):
        byteout[index*2]= (final_array[index]>>8) & 0xFF
        byteout[(index*2) + 1]= final_array[index] & 0xFF
    sys.stdout.buffer.write(byteout)
