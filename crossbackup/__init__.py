import argparse
import logging
import sys
from typing import List
from pathlib import Path
from pprint import pp

import yaml

from .data_type import SingleBackupConfig
from .config import update_program_config
from .log import setup_logger
from .sync import Sync

# TODO: use BaseModel to approve yaml  <2022-07-22, Hyunjae Kim>

logger = logging.getLogger("default")
logger_debug = logging.getLogger("debug")


def get_argparser() -> argparse.ArgumentParser:
    """
    return ArgumentParser
    """

    parser = argparse.ArgumentParser(
        description="cross-backup between ZFS, BTRFS and rclone",
        allow_abbrev=True,
    )

    # TODO: get input from stdin <2022-07-23, Hyunjae Kim>
    parser.add_argument(
        "yaml", type=Path, help="Backup config file written in YAML format"
    )

    parser.add_argument(
        "-c",
        "--clean",
        action="store_true",
        default=False,
        help="""Clean old backups""",
    )
    parser.add_argument(
        "-b",
        "--backup",
        action="store_true",
        default=False,
        help="Run backup",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        default=False,
        help="List backups",
    )
    parser.add_argument("--create-sample-config")
    # TODO: dry-run options <2022-07-22, Hyunjae Kim>

    return parser


def check_condition(args: argparse.Namespace) -> bool:
    if args.list:
        # TODO: make it happen <2022-07-23, Hyunjae Kim>
        raise NotImplementedError("List option is not implemented")

    if not args.clean != args.backup:
        logger.error("Use either --clean or --backup.")
        return False

    # TODO: allow stdin input <2022-07-23, Hyunjae Kim>
    if not args.yaml.is_file():
        logger.error("Input file does not exist or is not a file")
        return False

    return True


def run(args: argparse.Namespace) -> int:

    syncs: List[Sync] = []
    with open(args.yaml, encoding="UTF-8") as yml_io:
        yaml_ = yaml.safe_load(yml_io)

        if "config" in yaml_:
            update_program_config(yaml_["config"])
        if "backups" in yaml_:
            # TODO: check same-name? <2022-07-22, Hyunjae Kim>
            syncs.extend(
                [
                    Sync(SingleBackupConfig.parse_obj(item))
                    for item in yaml_["backups"]
                ]
            )

    if not syncs:
        print("Nothing to do", file=sys.stderr)
        return 0

    if args.clean:
        for sync in syncs:
            sync.clean()
        return 0

    if args.backup:
        for sync in syncs:
            try:
                sync.backup()
            except KeyboardInterrupt:
                sync.undo()
                print("KeyboardInterrupt", file=sys.stderr)
                return 1
            except Exception as err:
                sync.undo()
                raise err
        return 0

    return 1


def main():
    setup_logger()
    args: argparse.Namespace = get_argparser().parse_args()

    if not check_condition(args):
        return 1

    return run(args)
