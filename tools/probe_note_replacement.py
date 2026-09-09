"""Ensayo aislado de reemplazo en Windows. Solo usa un directorio temporal propio.

Ejecutar con PYTHONPATH=src y Python del proyecto. No es un backend de publicación.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

from knowledge_orchestrator.services.filesystem import write_synced
from knowledge_orchestrator.services.semantic_maintenance import SemanticMaintenanceService


def external_write(path: Path) -> dict:
    code = (
        "import json,pathlib,sys\n"
        "try:\n"
        " pathlib.Path(sys.argv[1]).write_bytes(b'human edit')\n"
        " print(json.dumps({'written':True}))\n"
        "except OSError as error:\n"
        " print(json.dumps({'written':False,'winerror':getattr(error,'winerror',None)}))\n"
    )
    child = subprocess.run(
        [sys.executable, "-B", "-c", code, str(path)], check=True, capture_output=True,
        text=True, timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    return json.loads(child.stdout)


def retired_protocol(root: Path) -> dict:
    """Historical counterexample, copied here after removing it from production."""
    path, temporary = root / "note.md", root / "note.tmp"
    path.write_bytes(b"base")
    write_synced(temporary, b'proposed')
    assert SemanticMaintenanceService._hash_text(path.read_text()) == SemanticMaintenanceService._hash_text('base')
    writer = external_write(path)
    if not writer['written']:
        raise RuntimeError('El escritor de prueba no pudo ejecutarse')
    os.replace(temporary, path)
    return {'case': 'retired_protocol', 'writer': writer,
            'human_edit_preserved': path.read_bytes() == b'human edit',
            'final_content': path.read_text()}


def sharing_probe(root: Path) -> list[dict]:
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL

    class RenameInfo(ctypes.Structure):
        _fields_ = [('Flags', wintypes.DWORD), ('RootDirectory', wintypes.HANDLE),
                    ('FileNameLength', wintypes.DWORD), ('FileName', wintypes.WCHAR * 1)]

    results = []
    invalid = ctypes.c_void_p(-1).value
    for share in (1, 5):  # READ; READ | DELETE. Neither permits write handles.
        for flags in (1, 3):  # REPLACE; REPLACE | POSIX_SEMANTICS.
            path, temporary = root / f'base-{share}-{flags}.md', root / f'new-{share}-{flags}.md'
            path.write_bytes(b'base')
            temporary.write_bytes(b'proposed')
            held = kernel.CreateFileW(str(path), 0x80000000, share, None, 3, 0, None)
            if held == invalid:
                raise ctypes.WinError(ctypes.get_last_error())
            source = None
            try:
                writer = external_write(path)
                source = kernel.CreateFileW(str(temporary), 0x10000, 7, None, 3, 0, None)
                if source == invalid:
                    raise ctypes.WinError(ctypes.get_last_error())
                name = str(path).encode('utf-16-le')
                buffer = ctypes.create_string_buffer(RenameInfo.FileName.offset + len(name) + 2)
                info = ctypes.cast(buffer, ctypes.POINTER(RenameInfo)).contents
                info.Flags, info.RootDirectory, info.FileNameLength = flags, None, len(name)
                ctypes.memmove(ctypes.addressof(buffer) + RenameInfo.FileName.offset, name, len(name))
                succeeded = bool(kernel.SetFileInformationByHandle(source, 22, buffer, len(buffer)))
                error = 0 if succeeded else ctypes.get_last_error()
            finally:
                if source is not None and source != invalid:
                    kernel.CloseHandle(source)
                kernel.CloseHandle(held)
            results.append({'case': 'sharing', 'share': share, 'rename_flags': flags,
                            'writer': writer, 'rename_succeeded': succeeded, 'winerror': error,
                            'final_content': path.read_text()})
    return results


def main() -> None:
    if os.name != 'nt':
        raise SystemExit('Este ensayo requiere Windows; no modifica ningún archivo de usuario.')
    with tempfile.TemporaryDirectory(prefix='ko-replace-probe-') as directory:
        root = Path(directory).resolve()
        report = [retired_protocol(root), *sharing_probe(root)]
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
