import collections
import itertools
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import yaml

from .archive import Archive
from .data_type import SrcType, DstType, SingleBackupConfig
from .config import CONFIG
from .snapshot import Snapshot

logger = logging.getLogger("default")


def _get_rclone_configs() -> Set[str]:
    args: List[str] = [
        "rclone",
        "listremotes",
    ]
    proc: subprocess.CompletedProcess = subprocess.run(
        args, capture_output=True, check=True
    )

    rclone_configs: Set[str] = {
        raw[:-1] for raw in proc.stdout.decode("utf-8").split()
    }

    return rclone_configs


RCLONE_CONFIGS: Set[str] = _get_rclone_configs()

# TODO: allow user to exclude things <2022-07-22, Hyunjae Kim>
# EXCLUDE_FROM = Path("/home/hyunjae/Sync/.rclone-exclude")
ISO8601_COMPACT: str = "%Y%m%dT%H%M%S%z"


class Backup:
    """
    Backup Class
    """

    def __init__(self, name: str, path: str, time: datetime, is_dir: bool):
        if time.tzinfo is None:
            raise AttributeError("Requires Timezone Information")

        if time.resolution > timedelta(seconds=1):
            # TODO: change message <2022-07-22, Hyunjae Kim>
            raise AttributeError("Requires more accurate time data")

        self.name: str = name
        self.path: str = path

        self.time: datetime = time
        self.is_dir = is_dir

    def __lt__(self, other) -> bool:
        return self.time < other.time

    def __gt__(self, other) -> bool:
        return self.time > other.time

    def __hash__(self) -> int:
        return hash(self.time.astimezone(timezone.utc).isoformat() + self.path)

    def __eq__(self, other) -> bool:
        return self.time == other.time and self.path == other.path

    def __str__(self) -> str:
        return self.path

    def get_isoformat(self) -> str:
        return self.time.replace(microsecond=0).isoformat()

    def remove(self, config_name: str, dst_path: str, use_trash: bool):
        if self.is_dir:
            rclone_command: str = "purge"
        else:
            rclone_command: str = "delete"

        logger.info(
            "Deleting backup captured at %s",
            self.get_isoformat(),
        )
        args: List[str] = [
            "rclone",
            "--log-systemd",
            "--log-level",
            f"{CONFIG.rclone_log_level}",
            f"--drive-use-trash={str(use_trash).lower()}",
            rclone_command,
            f"{dst_path}/{self.path}",
        ]
        subprocess.run(args, capture_output=False, check=True)

    def upload(
        self,
        config_name: str,
        src_arg: str,
        dst_arg: str,
        use_trash: bool,
        upload_type_is_dir: bool,
    ):
        logger.info(
            "Uploading backup captured at %s",
            self.get_isoformat(),
        )

        args: List[str] = [
            "rclone",
            "--links",
            "--log-systemd",
            "--log-level",
            f"{CONFIG.rclone_log_level}",
            f"--drive-use-trash={str(use_trash).lower()}",
        ]
        if upload_type_is_dir:
            args.extend(
                [f"--exclude={pattern}" for pattern in CONFIG.excludes]
            )
        args.extend(["sync", src_arg, dst_arg])
        subprocess.run(args, capture_output=False, check=True)


class Sync:
    """
    Sync Class
    """

    def __init__(self, config: SingleBackupConfig):

        if config.dst.path.split(":")[0] not in RCLONE_CONFIGS:
            raise AttributeError(f"Invalid rclone config {config.dst}")

        if config.src.type == SrcType.DIRECTORY:
            config.src.path = Path(config.src.path)
            # TODO: do this on data type <2022-07-23, Hyunjae Kim>

        if (
            config.src.type == SrcType.DIRECTORY
            and not config.src.path.is_absolute()
        ):
            raise AttributeError(
                f"Input path is not absolute: {config.src.path}"
            )

        if (
            config.src.type == SrcType.DIRECTORY
            and not config.src.path.exists()
        ):
            raise AttributeError(
                f"Input path does not exists: {config.src.path}"
            )

        self.config = config
        # self.base_target = f"{self.config.dst.path}/{self.config.name}"
        self._backups: Optional[List[Backup]] = None
        # TODO: more data checking <2022-07-20, Hyunjae Kim>

        # Backup that has been created by this Sync
        self.new_backup: Optional[Backup] = None

    def _server_side_copy(self, new_backup: Backup):
        if not new_backup.is_dir:
            return
        # 정렬 되어 있어야함.
        backups = self.get_backups()
        if not backups:
            return

        for backup in backups[::-1]:
            if not backup.is_dir:
                continue
            latest_backup: Backup = backup

            logger.info(
                "Copying the backup captured at %s from server-side",
                self.config.name,
                latest_backup.get_isoformat(),
            )

            args: List[str] = [
                "rclone",
                "--log-systemd",
                "--log-level",
                f"{CONFIG.rclone_log_level}",
            ]
            args.extend(
                [f"--exclude={pattern}" for pattern in CONFIG.excludes]
            )
            args.extend(
                [
                    "copy",
                    f"{self.config.dst.path}/{latest_backup.name}",
                    f"{self.config.dst.path}/{new_backup.name}",
                ]
            )
            subprocess.run(args, capture_output=False, check=True)
            break

    def undo(self):
        """
        Remove backup that has been uploaded
        """
        # 중간에 취소하면 올라간 것을 삭제할 필요가 있음.
        # TODO: rclone 은 중간 취소되면 올라간거 삭제하나? <2022-07-23, Hyunjae Kim>
        if self.new_backup is None:
            return

        logger.info(
            "Finding backup captured now from rclone to undo",
        )
        if not self.new_backup in self.get_backups(force=True):
            logger.info(
                "Backup of %s has not been uploaded",
                self.config.name,
            )
            return

        self.new_backup.remove(self.config.name, self.config.dst.path, False)
        self.new_backup = None
        return

    def _backup_archive(self, backup_time: datetime, backup_time_str: str):
        """
        Backup using archive
        """

        with Snapshot(
            self.config.src.path,
            self.config.src.type,
            f"temp_{backup_time_str}",
        ) as snaped_path, Archive(
            snaped_path,
            self.config.dst.archive.type,
            f"{self.config.name}_{backup_time_str}",
        ) as archive:

            new_backup = Backup(
                time=backup_time,
                name=f"{archive.name}",
                path=f"{archive.name}",
                is_dir=False,
            )
            src_arg: str = str(archive)
            dst_arg: str = f"{self.config.dst.path}"
            self.new_backup = new_backup
            self.new_backup.upload(
                self.config.name,
                src_arg,
                dst_arg,
                self.config.dst.rclone_config.use_trash,
                False,
            )

            if self._backups is not None:
                self._backups.append(new_backup)

    def _backup_dir(self, backup_time: datetime, backup_time_str: str):
        """
        Backup in directory format
        """

        with Snapshot(
            self.config.src.path,
            self.config.src.type,
            f"temp_{backup_time_str}",
        ) as snaped_path:

            src_arg: str = str(snaped_path)
            new_backup = Backup(
                time=backup_time,
                name=f"{self.config.name}_{backup_time_str}",
                path=f"{self.config.name}_{backup_time_str}",
                is_dir=not self.config.dst.archive.enable,
            )
            dst_arg: str = f"{self.config.dst.path}/{new_backup.path}"

            self.new_backup = new_backup
            if (
                self.config.dst.rclone_config.server_side_copy
                and self.config.dst.type == DstType.RCLONE
                and not self.config.dst.archive.enable
            ):
                self._server_side_copy(new_backup)

            self.new_backup.upload(
                self.config.name,
                src_arg,
                dst_arg,
                self.config.dst.rclone_config.use_trash,
                True,
            )
            if self._backups is not None:
                self._backups.append(new_backup)

    def backup(self):
        logger.info("Starting backup of %s", self.config.name)
        # TODO: does not backup if no changes <2022-07-20, Hyunjae Kim>

        backup_time: datetime = (
            datetime.now(timezone.utc).replace(microsecond=0).astimezone()
        )
        backup_time_str: str = backup_time.strftime(ISO8601_COMPACT)

        if self.config.dst.type != DstType.RCLONE:
            raise NotImplementedError(
                f"{self.config.dst.type} does not supported"
            )

        if self.config.dst.archive.enable:
            self._backup_archive(backup_time, backup_time_str)
        else:
            self._backup_dir(backup_time, backup_time_str)

        logger.info("Ending backup of %s", self.config.name)

    def get_backups(self, force: bool = False) -> List[Backup]:
        """
        Return List of previous backups
        """

        if self._backups is not None and not force:
            return self._backups

        logger.info(
            "Querying previous backups from %s",
            self.config.dst.path,
        )
        args: List[str] = ["rclone", "lsjson", self.config.dst.path]
        try:
            proc: subprocess.CompletedProcess = subprocess.run(
                args, capture_output=True, check=True
            )
        except subprocess.CalledProcessError as err:
            # if directory does not exists it causes error.
            logger.warning(
                "%s: Error querying previous backup by following error: %s",
                self.config.name,
                err.stderr,
            )
            return []

        backups: List[Dict[str, Any]] = json.loads(proc.stdout.decode("UTF-8"))
        # logger_debug.debug("Get backups done: %s", backups)

        ret: List[Backup] = []
        for backup in backups:
            if not backup["Name"].startswith(f"{self.config.name}_"):
                continue

            # TODO: onedrive 말고도 mimetype 주는지 확인 <2022-07-23, Hyunjae Kim>
            is_dir: bool = backup["MimeType"] == "inode/directory"
            if is_dir:
                time_str: str = backup["Name"][len(self.config.name) + 1 :]
            else:
                time_str: str = backup["Name"][
                    len(self.config.name) + 1 :
                ].split(".")[0]

            try:
                backup_time = datetime.strptime(
                    time_str,
                    ISO8601_COMPACT,
                )
            except ValueError:
                # The files that does not follow ISO8601_COMPACT_FORMAT
                continue
            ret.append(
                Backup(
                    time=backup_time,
                    name=backup["Name"],
                    path=backup["Path"],
                    is_dir=is_dir,
                )
            )

        self._backups = sorted(ret)

        return self._backups

    def clean(self):
        """
        Clean old backup
        """

        logger.info("Starting cleanup of %s", self.config.name)
        cur_time: datetime = datetime.now(timezone.utc)
        backups: List[Backup] = self.get_backups()

        if not backups:
            return

        # 해당 timeline 에서 가장 최신 값 보존
        # limit_hourly: specific_hour: newest backup in this hour
        grouping: Dict[str, Dict[datetime, Backup]] = collections.defaultdict(
            dict
        )

        keep_alive: Set[Backup] = set()
        for backup in backups:
            if cur_time - backup.time < timedelta(
                seconds=self.config.dst.timeline.min_age
            ):
                keep_alive.add(backup)
                continue

            hour = backup.time.replace(minute=0, second=0, microsecond=0)
            day = hour.replace(hour=0)
            week = day - timedelta(days=day.weekday())
            month = day.replace(day=1)
            year = month.replace(month=1)

            for limit_name, time in [
                ("limit_hourly", hour),
                ("limit_daily", day),
                ("limit_weekly", week),
                ("limit_monthly", month),
                ("limit_yearly", year),
            ]:
                if grouping[limit_name].get(time) is None:
                    grouping[limit_name][time] = backup
                elif backup < grouping[limit_name][time]:
                    grouping[limit_name][time] = backup

        for limit_name, local_group in grouping.items():
            for _, backup in itertools.islice(
                sorted(local_group.items(), reverse=True),
                getattr(self.config.dst.timeline, limit_name),
            ):
                keep_alive.add(backup)

        for backup in set(backups) - keep_alive:
            backup.remove(
                self.config.name,
                self.config.dst.path,
                self.config.dst.rclone_config.use_trash,
            )

        logger.info("Ending cleanup of %s", self.config.name)
