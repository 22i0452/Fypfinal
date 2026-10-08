"""Run synthetic unit/API regressions with outbound network connections blocked.

Usage: python -m tests.run_offline_regressions tests.test_medicine_context ...
The app's optional TTS warmup is deliberately unable to contact external speech
services. TestClient runs in-process; all tested LLM/audio responses are mocks.
"""
import socket
import sys
import unittest


def main():
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded(method):
        def connect(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                raise RuntimeError('Outbound network disabled in synthetic regression tests')
            return method(sock, address)
        return connect

    socket.socket.connect = guarded(original_connect)
    socket.socket.connect_ex = guarded(original_connect_ex)
    try:
        suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:])
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex


if __name__ == '__main__':
    raise SystemExit(main())
