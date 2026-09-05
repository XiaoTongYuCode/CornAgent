"""Run both development processes and clean up their process groups on exit."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
processes = []

def stop(_signum=None, _frame=None):
    raise KeyboardInterrupt

signal.signal(signal.SIGTERM, stop)
try:
    processes.append(subprocess.Popen([sys.executable, "-m", "app.serve"], cwd=root / "server", start_new_session=True))
    processes.append(subprocess.Popen(["npm", "run", "dev"], cwd=root / "frontend", start_new_session=True))
    while all(process.poll() is None for process in processes):
        time.sleep(0.25)
except KeyboardInterrupt:
    pass
finally:
    for process in processes:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
