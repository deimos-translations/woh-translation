"""Ask the Windows loader whether files are valid PE images, without executing them (SEC_IMAGE mapping).

Usage: python -I pipeline/check/image_check.py <exe> [<exe> ...]   (error 193 = malformed image)
"""
import ctypes
import sys
from ctypes import wintypes

if sys.platform != "win32":
    print("skipped: asks the Windows loader")
    sys.exit(0)

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
k32.CreateFileMappingW.restype = wintypes.HANDLE
k32.CreateFileMappingW.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR]
k32.CloseHandle.argtypes = [wintypes.HANDLE]

GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING = 0x80000000, 1, 3
PAGE_READONLY, SEC_IMAGE = 0x02, 0x1000000
INVALID = wintypes.HANDLE(-1).value

for path in sys.argv[1:]:
    handle = k32.CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, None, OPEN_EXISTING, 0, None)
    if handle == INVALID:
        print(f"{path}: cannot open (error {ctypes.get_last_error()})")
        continue
    mapping = k32.CreateFileMappingW(handle, None, PAGE_READONLY | SEC_IMAGE, 0, 0, None)
    if mapping:
        print(f"{path}: VALID image")
        k32.CloseHandle(mapping)
    else:
        print(f"{path}: REJECTED by loader, error {ctypes.get_last_error()}")
    k32.CloseHandle(handle)
