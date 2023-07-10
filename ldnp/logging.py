import coloredlogs
import logging


def get_logger() -> logging.Logger:
    return logging.getLogger("ldnp")


def get_logger(child_name: str = None):
    logger = logging.getLogger("ldnp")

    if child_name:
        logger = logger.getChild(child_name)

    return logger


def set_up_logging(debug: bool):
    if debug:
        level = logging.DEBUG
    else:
        level = logging.INFO

    fmt = "%(name)s [%(levelname)s] %(message)s"

    # black levels on a dark terminal background are unreadable
    styles = coloredlogs.DEFAULT_FIELD_STYLES
    styles["levelname"] = {
        "color": "yellow",
    }

    kwargs = dict(fmt=fmt, styles=styles)

    coloredlogs.install(level, **kwargs)

    # basic setup of our own loggers
    logger = get_logger()
    logger.setLevel(logging.DEBUG)
