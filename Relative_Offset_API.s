;Relative Offset API
;Version 0.4
;Author: MC68882

;This API provides a means of writing position-independent code.
;It makes use of the fact that CALL instructions leave the return address on the stack,
;which can then be read to determine the address of the calling code.

;The API consists of a setup function and a set of function pointers placed in
;memory from 0x0000-0x001F. They are located there to minimize interference 
;with other code and to have a definite location callable with any code.

;
;Usable Functions: GetMyAddress, GetRelativeOffset, PrepareTable, GetTableValue,
;                  GetSymbol, GetVar, SetupRelativeOffsetAPI


;The assembler.py hardcodes these addresses. Do not change one without changing the other.

;If the API is present, address 0 will be set to 'RC' (0x5243).
ROASigAddr EQU 0x0000
ROASigVal  EQU 0x5243

;public functions at 0x0001-0x000F 
GetMyAddress EQU 0x0001
GetRelativeOffset EQU 0x0002
PrepareTable EQU 0x0003
GetTableValue EQU 0x0004
RestoreOldTable EQU 0x0005
GetSymbol EQU 0x0006
GetVar EQU 0x0007

;internal variables at 0x0010-0x001F
;used for API functions which keep state
TblAddr EQU 0x0010
TblCorrectionVal EQU 0x0011
SymHook1 EQU 0x0012
SymHook2 EQU 0x0013
SymLib1 EQU 0x0014
SymLib1Name EQU 0x0015
SymLib2 EQU 0x0016
SymLib2Name EQU 0x0017
GetDictVal EQU 0x0018
IsPrefix EQU 0x0019
StrEql EQU 0x001A
PIC_Temp EQU 0x001B ; used by the assembler when there are 2 labels in one instruction

;All unused locations in 0x0000-0x001F are reserved.
;I plan on extending this API later.

EndOfList EQU 0
IsLeaf EQU 0


;GetMyAddress()
;Usage:
;    CALL [GetMyAddress]
;Places the address of the code that called it into register D.


;GetRelativeOffset()
;Usage:
;    MOV D, SomeLabel;ugly hack to get the relative offset of SomeLabel
;    SUB D, CallingLocation;if you can do label math at link time, just do a MOV D, offset
;  CallingLocation:
;    CALL [GetRelativeOffset]
;    CALL D;calls SomeLabel
;Adds to register D the address of the code that called it.
;Used to get the address for a jump, branch, or call when
;it is not known in advance where the code is located.


;PrepareTable(), GetTableValue(), RestoreOldTable()
;Usage:
;    MOV D,JumpTable
;    SUB D,PrepareLocation
;  PrepareLocation:
;    CALL [PrepareTable]
;    PUSH D;save old table value
;    MOV D, 2
;    CALL [GetTableValue]
;    CALL D;Calls EvenMoreCode
;    POP D
;    CALL [RestoreOldTable]
;    RET
;  JumpTable:
;    DW JumpTable;first entry MUST point to itself
;    DW SomeCode;0-based index starts here
;    DW MoreCode
;    DW EvenMoreCode
;PrepareTable() takes the offset to a jump table in register D, and prepares it,
;and returns the old table value so it can be restored.
;Later, GetTableValue() returns in D the address indexed by D.
;This way, jump tables can be set up at asm time with minimal changes.
;The principal requirement is that the first entry of a jump table be
;the compiled address of the table itself. This is so GetTableValue()
;knows the correct value by which to adjust the address returned.
;after the current table is done being used, RestoreOldTable() will
;let the previous table be used.


;FindSymbol()
;Usage:
;    MOV D,Symbol
;    SUB D,PrepareLocation
;  PrepareLocation:
;    CALL [FindSymbol]
;    JMP D
;  Symbol: DW 8, "Symbol", 0 ;the 8 is a relative offset to LibName
;                            ;LibName-Symbol is not supported assembly-time yet
;  LibName: "TestLib",0
;FindSymbol() takes an offset to a Symbol entry in D. It returns that symbol in D.
;If the lookup fails, -1 will be returned (will throw an exception once those are
;implemented). 


;GetVar()
;This code:
;   .data
;   var_1: DW 0
;   var_2: DW 0
;   .text
;     MOV A, [var2]
;Gets translated by the assembler into:
;   .data
;   base_of_data:
;   var_1: DW 0
;   var_2: DW 0
;   .text
;     MOV D,var_2 - base_of_data
;     CALL [GetVar]
;     MOV A,[D]
;GetVar() will use register D as an index into a seperate data area created by the Library Manager.
;Once implemented, it will use the caller's address to determine which data area to use.


;SetupRelativeOffsetAPI()
;This function sets up the function pointers at the top of memory.
;It should be called very early in your Cubot's setup,
;as it sets the stack position to be 0xFFFF on return.
;As a side note, this function is also position-independent. Once assembled, it can be copied
;to any address (except the 0x0000-0x001F range) and still work.
SetupRelativeOffsetAPI:
    MOV [0xFFFF],[SP]
    MOV SP, 0xFFFE;stack will be at 0xFFFF when returning
    PUSH BP
    MOV BP,SP
    
    ;time to get our address...
    PUSH -1
    PUSH 0xF816; RET -1 (return, but leave the return address on the stack)
    CALL SP
SROA_BPoint:
    POP D
    SUB D, SROA_BPoint;get correction factor for labels
    ;place signature magic number
    MOV [ROASigAddr], ROASigVal
    ;setup actual API pointers
    MOV [GetMyAddress],_GetMyAddress
    ADD [GetMyAddress],D
    MOV [GetRelativeOffset],_GetRelativeOffset
    ADD [GetRelativeOffset],D
    MOV [PrepareTable],_PrepareTbl
    ADD [PrepareTable],D
    MOV [GetTableValue],_GetTblVal
    ADD [GetTableValue],D
    MOV [RestoreOldTable],_RestoreOldTable
    ADD [RestoreOldTable],D
    MOV [GetSymbol],_GetSymbol
    ADD [GetSymbol],D
    MOV [GetVar],-1 ;this function will be implemented by the Library Manager once it is ready
    ;set up private variables and functions
    MOV [StrEql],_StrEql
    ADD [StrEql],D
    MOV [IsPrefix],_IsPrefix
    ADD [IsPrefix],D
    MOV [GetDictVal],_GetDictVal
    ADD [GetDictVal],D
    MOV [SymHook1],0
    MOV [SymHook2],0
    MOV [SymLib1],0
    MOV [SymLib2],0
    MOV [SymLib1Name],0
    MOV [SymLib2Name],0
    MOV [PICTemp],0
    ;actually return
    MOV SP,BP
    POP BP
    RET
_GetMyAddress:;returns calling address in D
    PUSHF
    MOV D,[SP+1]
    SUB D,2; CALL instructions are 2 words long
    POPF
    RET
_GetRelativeOffset:;give it a offset in D, it adds the location of your code to it
    PUSHF
    ADD D,[SP+1]
    SUB D,2
    POPF
    RET
_PrepareTbl:;sets up a jump table whos offset is in D
    PUSHF
    ADD D,[SP+1]
    SUB D,2
    PUSH [TblAddr];store old table address
    MOV [TblAddr],D
    SUB D,[D];read the first word of the table to find what address it was linked at.
    MOV [TblCorrectionVal],D;calculate the correction value
    POP D; return old Table Address
    POPF
    RET
_GetTblVal:;returns in D the address of that jump table entry
    PUSHF
    ADD D,[TblAddr]
    MOV D,[D+1];0-based count starting at table_base+1
    ADD D,[TblCorrectionVal]
    POPF
    RET
_RestoreOldTable:;sets up a jump table given it's absolute address in D
    MOV [TblAddr],D
    SUB D,[D];read the first word of the table to find what address it was linked at.
    MOV [TblCorrectionVal],D;calculate the correction value
    RET
_GetSymbol:
    ADD D,[SP]
    SUB D,2
    PUSH A
    PUSH B
    PUSH C
    PUSH X
    PUSH Y
    MOV B,D
    MOV C,D
    ADD B,[B];get the pointer to the Lib name
    INC C;now C is pointer to Symbol Name


    ;setup jump table
    MOV D,GetSymbolJumpTbl
    SUB D,_GetSymTableInitPt
_GetSymTableInitPt:
    CALL [PrepareTable]
    PUSH D
    
    MOV D,0
    CALL [GetTableValue]
    CMP [SymHook1],0
    JZ D
    PUSH B
    PUSH C
    CALL [SymHook1];give SymHook1 chance to decode the symbol first
    MOV D,4
    CALL [GetTableValue]
    CMP A,-1
    JNZ D
_NoSymHook1:
    MOV D,1
    CALL [GetTableValue]
    CMP [SymLib1],0
    JZ D
    MOV X, D
    PUSH [SymLib1Name]
    PUSH B
    CALL [StrEql]
    CMP A,0
    JZ X
    PUSH [SymLib1]
    PUSH C
    CALL [GetDictVal]
    CMP A,-1
    JZ X
    ADD A,[A]
    MOV D,4
    CALL [GetTableValue]
    JMP D
_NoSymLib1:
    MOV D,2
    CALL [GetTableValue]
    CMP [SymLib2],0
    JZ D
    MOV X, D
    PUSH [SymLib2Name]
    PUSH B
    CALL [StrEql]
    CMP A,0
    JZ X
    PUSH [SymLib2]
    PUSH C
    CALL [GetDictVal]
    CMP A,-1
    JZ X
    ADD A,[A]
    MOV D,4
    CALL [GetTableValue]
    JMP D
_NoSymLib2:
    MOV D,3
    CALL [GetTableValue]
    CMP [SymHook2],0
    JZ D
    PUSH B
    PUSH C
    CALL [SymHook2]
    MOV D,4
    CALL [GetTableValue]
    JMP D
_NoSymHook2:
    MOV A,-1
_GetSymbolReturn:
    POP D
    CALL [RestoreOldTable]
    MOV D,A
    POP Y
    POP X
    POP C
    POP B
    POP A
    RET

GetSymbolJumpTbl:
    DW GetSymbolJumpTbl
    DW _NoSymHook1
    DW _NoSymLib1
    DW _NoSymLib2
    DW _NoSymHook2
    DW _GetSymbolReturn

_GetDictVal:;not an API function
    PUSH BP
    MOV BP,SP
    PUSH B
    PUSH C
    PUSH X
    PUSH Y
    MOV D,_GetDictVal_JmpTbl
    SUB D,_GetDictVal_JTSPt
_GetDictVal_JTSPt:
    CALL [PrepareTable]
    PUSH D
    MOV X, [BP+3]
    MOV D,0
    CALL [GetTableValue]
    JMP D
_GetDictVal_TryNextEntry:
    CMP C, EndOfList
    MOV D,2
    CALL [GetTableValue]
    JZ D
    MOV X,C
    ADD X,B
_GetDictVal_TryEntry:
    MOV B,X
    MOV C,[B] ;get next list if this one fails
    INC X
    PUSH [BP+2]
    PUSH X
    CALL [IsPrefix]
    CMP A, 0
    MOV D,1
    CALL [GetTableValue]
    JZ D
    ADD X, A; get past the end of the string to the other data
    ADD [BP+2],A ;move the string forward by the right amount
    DEC [BP+2]
    MOV B,X
    MOV C,[B]
    CMP C,IsLeaf
    JNZ D; move vertically
    INC X
    MOV A,X
    MOV D,3
    CALL [GetTableValue]
    JMP D
_GetDictVal_Fail:
    MOV A, -1
_GetDictVal_Return:
    POP D
    CALL [RestoreOldTable]
    POP Y
    POP X
    POP C
    POP B
    MOV SP,BP
    POP BP
    RET 2
_GetDictVal_JmpTbl:
    DW _GetDictVal_JmpTbl
    DW _GetDictVal_TryEntry
    DW _GetDictVal_TryNextEntry
    DW _GetDictVal_Fail
    DW _GetDictVal_Return



_IsPrefix:
    PUSH BP
    MOV BP,SP
    PUSH B
    PUSH C
    PUSH X
    PUSH Y
    MOV D,_IsPrefixJmpTbl
    SUB D,_IsPrefixJTSPt
_IsPrefixJTSPt:
    CALL [PrepareTable]
    PUSH D
    MOV D,2;index to _IsPrefix_NotEqual
    CALL [GetTableValue]
    MOV B,D
    MOV D,1;index to _IsPrefix_Return
    CALL [GetTableValue]
    MOV C,D
    MOV D,0;index to _IsPrefix_Loop
    CALL [GetTableValue]
    MOV X,[BP+3]
    MOV Y,[BP+2]
    MOV A, 1
_IsPrefix_Loop:
    CMP [X],[Y]
    JNZ B
    INC X
    INC Y
    INC A
    CMP [Y], 0 ;if they reach the end at the same time, they are equal
    JNZ D
_IsPrefix_Return:
    POP D
    CALL [RestoreOldTable]
    POP Y
    POP X
    POP C
    POP B
    MOV SP,BP
    POP BP
    RET 2
_IsPrefix_NotEqual:
    CMP [Y], 0
    JZ C; if the prefix ends here, then it is a prefix of the string
    MOV A, 0
    JMP C; otherwise, it is not
_IsPrefixJmpTbl:
    DW _IsPrefixJmpTbl
    DW _IsPrefix_Loop
    DW _IsPrefix_Return
    DW _IsPrefix_NotEqual

_StrEql:
    PUSH B
    PUSH C
_StrEql_AdjPt:
    CALL [GetMyAddress]
    SUB D,_StrEql_AdjPt
    MOV B,_StrEql_F
    ADD B,D
    MOV C,_StrEql_T
    ADD C,D
    ADD D,_StrEql_Loop
_StrEql_Loop:
    CMP [BP+2],[BP+3]
    JNZ B
    CMP [BP+2],0
    JZ C
    INC [BP+2]
    INC [BP+3]
    JMP D
_StrEql_T:
    MOV A,1
    POP C
    POP B
    RET 2
_StrEql_F:
    MOV A,0
    POP C
    POP B
    RET 2
SROA_End: