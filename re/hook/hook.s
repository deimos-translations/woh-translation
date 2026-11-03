# Draw-time translation hook for worldofhorror.exe. Assembled by re/hook/build.py (clang), injected by re/patch.py.
#
# Each hooked built-in (draw_text, string_width, ...) is registered at startup with `LEA RDX,[function]`. patch.py points that
# at a 16-byte stub: `lea r10,[info]; jmp common`. `info` = { int32 displacement from info to the original function;
# int32 index of the text argument }. `common` replaces the text argument by its translation (if the table has one), calls the
# original, and puts the original argument back, so the game never sees a changed value outside the draw call.
#
# Built-in ABI (Microsoft x64): rcx = Result*, rdx = self, r8 = other, r9d = argc, [rsp+0x28] on entry = RValue* args.
# RValue = { value @0, flags @8, kind @0xc (low 24 bits) }, kind 1 = string, value = RefString* = { char* @0, refcount @8,
# size @0xc }. A static RefString has refcount 1 and size = length | 0x80000000, like the game's own string constants.
#
# Table (g_table, resolved by patch.py): { uint32 mask; uint32 pad[3]; entry[mask+1] }, entry = { uint32 fnv1a(key);
# uint32 keyOffset (0 = empty); uint32 refStringOffset; uint32 textOffset }, all offsets from g_table. Open addressing,
# linear probing. The hook stores the translated text address into the RefString on every hit, so the table holds no absolute
# pointers and survives address-space randomisation.
.intel_syntax noprefix
.text
.globl common
common:
    sub  rsp, 0x48                  # frame: [rsp+0x20] 5th arg, 0x28 info, 0x30 slot to restore, 0x38 arg slot, 0x40 hash/original
    mov  [rsp+0x50], rcx            # spill the register arguments into the caller's home area
    mov  [rsp+0x58], rdx
    mov  [rsp+0x60], r8
    mov  [rsp+0x68], r9
    mov  [rsp+0x28], r10
    mov  qword ptr [rsp+0x30], 0    # nothing replaced yet
    mov  eax, [r10+4]               # index of the text argument
    cmp  dword ptr [rsp+0x68], eax  # argc must be greater than the index, or the argument does not exist
    jle  call_original
    mov  rcx, [rsp+0x70]            # RValue* args
    shl  rax, 4
    add  rax, rcx                   # &args[index]
    mov  [rsp+0x38], rax
    mov  ecx, [rax+0xc]
    and  ecx, 0xffffff
    cmp  ecx, 1                     # only strings
    jne  call_original
    mov  rdx, [rax]                 # RefString*
    test rdx, rdx
    jz   call_original
    mov  rdx, [rdx]                 # char*
    test rdx, rdx
    jz   call_original
    mov  ecx, 0x811c9dc5            # FNV-1a over the text
    mov  r8, rdx
hash_loop:
    movzx r9d, byte ptr [r8]
    test r9d, r9d
    jz   hashed
    xor  ecx, r9d
    imul ecx, ecx, 0x01000193
    inc  r8
    jmp  hash_loop
hashed:
    mov  [rsp+0x40], ecx
    lea  r9, [rip + g_table]
    mov  r11d, [r9]                 # mask
    and  r11d, ecx                  # first probe
probe:
    mov  eax, r11d
    shl  rax, 4
    lea  r8, [r9 + rax + 16]        # entry
    mov  r10d, [r8+4]               # key offset
    test r10d, r10d
    jz   call_original              # empty slot: not translated
    mov  eax, [rsp+0x40]
    cmp  [r8], eax
    jne  next
    add  r10, r9                    # key
    mov  rcx, rdx                   # text
cmp_loop:
    movzx eax, byte ptr [r10]
    cmp  al, byte ptr [rcx]
    jne  next
    test al, al
    jz   hit
    inc  r10
    inc  rcx
    jmp  cmp_loop
next:
    inc  r11d
    mov  eax, [r9]
    and  r11d, eax
    jmp  probe
hit:
    mov  eax, [r8+8]                # RefString offset
    add  rax, r9
    mov  ecx, [r8+12]               # translated text offset
    add  rcx, r9
    mov  [rax], rcx                 # RefString.text = translation
    mov  rcx, [rsp+0x38]            # &args[index]
    mov  rdx, [rcx]
    mov  [rsp+0x40], rdx            # original value, to put back
    mov  [rcx], rax
    mov  [rsp+0x30], rcx
call_original:
    mov  rcx, [rsp+0x50]
    mov  rdx, [rsp+0x58]
    mov  r8, [rsp+0x60]
    mov  r9, [rsp+0x68]
    mov  rax, [rsp+0x70]
    mov  [rsp+0x20], rax            # 5th argument
    mov  r10, [rsp+0x28]
    movsxd rax, dword ptr [r10]
    add  rax, r10                   # original function
    call rax
    mov  rcx, [rsp+0x30]
    test rcx, rcx
    jz   done
    mov  rdx, [rsp+0x40]
    mov  [rcx], rdx                 # put the original argument back
done:
    add  rsp, 0x48
    ret
.globl common_end
common_end:
