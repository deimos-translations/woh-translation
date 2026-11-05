# Test double for the hooked built-in: records what the hook passes on. Used only by pipeline/check/test_hook.py.
.intel_syntax noprefix
.text
.globl orig_capture
orig_capture:
    mov  rax, [rsp+0x28]            # args
    lea  r10, [rip + cap]
    mov  r11, [rax]
    mov  [r10], r11                 # args[0].value as the callee sees it
    mov  r11, [rax+0x10]
    mov  [r10+8], r11               # args[1].value
    mov  r11, [rax+0x20]
    mov  [r10+16], r11              # args[2].value
    mov  [r10+24], rcx
    mov  [r10+32], rdx
    mov  [r10+40], r8
    mov  [r10+48], r9
    mov  [r10+56], rax
    mov  [r10+64], rsp              # stack alignment at entry
    mov  rax, 0x1234
    ret
cap:
    .space 80
