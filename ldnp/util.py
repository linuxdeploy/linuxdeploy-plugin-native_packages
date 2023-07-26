import os
import shlex
import subprocess
from typing import List

from .logging import get_logger


logger = get_logger("util")


def run_command(command: List[str | os.PathLike], **kwargs):
    logger.debug(f"running command {shlex.join(map(str, command))}")
    return subprocess.check_call(command, **kwargs)
