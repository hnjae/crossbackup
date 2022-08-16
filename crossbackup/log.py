import logging
import logging.config
from typing import Any, Dict

from .config import CONFIG

# TODO: levelno does not match rclone fix this <2022-07-23, Hyunjae Kim>
LOGGING_CONFIG: Dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "<%(levelno)s>%(levelname)s : %(module)s: %(funcName)s: %(message)s",
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "default": {"handlers": ["default"], "level": CONFIG.log_level},
    },
}


def setup_logger():
    logging.config.dictConfig(LOGGING_CONFIG)
