"""Tasks the job tests run in child processes (importable by module path)."""
import os
import signal
import time


def sleepy(args, directory, report):
    report(0.2, "sleeping")
    time.sleep(float(args.get("seconds", 30)))
    return {}


def crash(args, directory, report):
    os.kill(os.getpid(), signal.SIGKILL)        # what an out-of-memory kill looks like


def fail(args, directory, report):
    raise ValueError("this model is broken")


def fast(args, directory, report):
    report(0.5, "halfway")
    (directory / "out.txt").write_text("done")
    return {"artifact": "out.txt", "value": args.get("value")}
