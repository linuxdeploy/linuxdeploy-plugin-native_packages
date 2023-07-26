import os
import shlex
import shutil
import subprocess
from typing import List

from .logging import get_logger


logger = get_logger("util")


def run_command(command: List[str | os.PathLike], **kwargs):
    # a small but valuable improvement for the log message: let's just resolve the path to the command we try to run
    # beforehand
    actual_command = shutil.which(command[0])

    # commands which do not exist (or whose path does not exist) will yield an empty string, so we just replace the
    # command if which() provided us with some output
    if actual_command:
        command[0] = actual_command

    logger.info(f"running command {shlex.join(map(str, command))}")

    return subprocess.check_call(command, **kwargs)
