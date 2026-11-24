"""JSON-lines transports use UTF-8 independently of the Windows console locale."""
import sys


def configure_utf8():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is not None:
            reconfigure(encoding='utf-8')
