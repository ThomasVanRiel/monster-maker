"""A GPU step that takes its time, for test_gpu.py (imported by the worker's child process)."""

import time


def run(inputs, out, params):
    time.sleep(30)
    return {}
