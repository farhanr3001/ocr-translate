"""Local build entry point; no changes to the installed Python runtime."""
import dis
import sys
import os
from pathlib import Path

# Keep unrelated tools' DLLs (Poppler, FFmpeg, etc.) out of dependency discovery.
os.environ['PATH'] = os.pathsep.join([str(Path(sys.executable).parent),
    str(Path(os.environ['SystemRoot']) / 'System32'), os.environ['SystemRoot']])

if sys.version_info[:3] == (3, 10, 0):
    # CPython bpo-45757: reset EXTENDED_ARG on no-argument opcodes. Fixed in
    # later Python releases. Apply only inside this packaging process.
    def unpack_opargs(code):
        extended_arg = 0
        for i in range(0, len(code), 2):
            op = code[i]
            if op >= dis.HAVE_ARGUMENT:
                arg = code[i + 1] | extended_arg
                extended_arg = (arg << 8) if op == dis.EXTENDED_ARG else 0
            else:
                arg = None
                extended_arg = 0
            yield i, op, arg
    dis._unpack_opargs = unpack_opargs

from PyInstaller.__main__ import run
run(["--noconfirm", "ArabicLens.spec", *sys.argv[1:]])
