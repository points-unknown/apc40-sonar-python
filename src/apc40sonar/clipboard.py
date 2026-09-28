"""Read MIDI that Cakewalk / Sonar copied to the Windows clipboard.

Copying a clip in Sonar puts three formats on the clipboard: its private
``CF_CAKEWALK_SONAR``, a registered ``Standard MIDI File`` format holding a
plain SMF, and ``CF_RIFF`` holding the same SMF wrapped as RIFF RMID. Paste
reads the SMF (or unwraps the RMID).

There is no copy in the other direction: tested on 2026-09-27, Sonar pastes
from its own internal copy and ignores what other programs put on the
clipboard (even with its private format gone, Ctrl+V pasted its last clip).

Windows only (ctypes on user32/kernel32); elsewhere every call reports
"unavailable". Clipboard blocks may be longer than the data they hold
(``GlobalSize`` rounds up), so readers must use the SMF's own chunk lengths.
"""

from __future__ import annotations

import sys

SMF_FORMAT_NAME = "Standard MIDI File"
CF_RIFF = 11


class ClipboardError(RuntimeError):
    pass


def unwrap_rmid(riff: bytes) -> bytes | None:
    """The SMF inside a RIFF RMID file, or None."""

    if riff[:4] != b"RIFF" or riff[8:12] != b"RMID":
        return None
    i = 12
    while i + 8 <= len(riff):
        size = int.from_bytes(riff[i + 4:i + 8], "little")
        if riff[i:i + 4] == b"data":
            return riff[i + 8:i + 8 + size]
        i += 8 + size + (size & 1)
    return None


def _api():
    if sys.platform != "win32":
        raise ClipboardError("the clipboard is only supported on Windows")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    return ctypes, user32, kernel32


def _open(user32) -> None:
    import time

    for _ in range(10):  # another program may hold it for a moment
        if user32.OpenClipboard(None):
            return
        time.sleep(0.02)
    raise ClipboardError("the clipboard is busy; try again")


def get_midi() -> bytes | None:
    """The MIDI file on the clipboard (Sonar's copy), or None when there is none."""

    ctypes, user32, kernel32 = _api()
    smf_format = user32.RegisterClipboardFormatW(SMF_FORMAT_NAME)
    _open(user32)
    try:
        for fmt in (smf_format, CF_RIFF):
            handle = user32.GetClipboardData(fmt)
            if not handle:
                continue
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                continue
            try:
                data = ctypes.string_at(ptr, kernel32.GlobalSize(handle))
            finally:
                kernel32.GlobalUnlock(handle)
            if fmt == CF_RIFF:
                data = unwrap_rmid(data) or b""
            if data[:4] == b"MThd":
                return data
        return None
    finally:
        user32.CloseClipboard()
