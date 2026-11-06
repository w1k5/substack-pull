"""Windows Credential Manager storage for the shared Substack session."""

import ctypes
from ctypes import wintypes
import sys


class CredentialError(Exception):
    pass


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialStore:
    def __init__(self, service: str):
        if sys.platform != "win32":
            raise CredentialError("Windows Credential Manager is only available on Windows.")
        self.service = service
        self.api = ctypes.WinDLL("Advapi32", use_last_error=True)
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                       ctypes.POINTER(ctypes.POINTER(_Credential))]
        self.api.CredReadW.restype = wintypes.BOOL
        self.api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        self.api.CredWriteW.restype = wintypes.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]

    def _target(self, account: str) -> str:
        return f"{self.service}:{account}"

    def lookup(self, account: str) -> str | None:
        pointer = ctypes.POINTER(_Credential)()
        if not self.api.CredReadW(self._target(account), 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
                return None
            raise CredentialError("Windows could not read the saved connection.")
        try:
            credential = pointer.contents
            blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return blob.decode("utf-8") or None
        finally:
            self.api.CredFree(pointer)

    def save(self, account: str, token: str) -> None:
        if not token or "\r" in token or "\n" in token:
            raise CredentialError("The session value is invalid.")
        blob = token.encode("utf-8")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = _Credential()
        credential.Type = 1  # CRED_TYPE_GENERIC
        credential.TargetName = self._target(account)
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = buffer
        credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = account
        if not self.api.CredWriteW(ctypes.byref(credential), 0):
            raise CredentialError("Windows could not save the connection.")
