import logging
import os
import secrets
import shutil
import string
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .common import get_random_str
from .data_type import SrcType

logger = logging.getLogger("default")


_LETTERS = set(string.ascii_letters) | set(string.digits) | set("_")


class _Dir:
    def __init__(self, path_raw: Any):
        if isinstance(path_raw, Path):
            path: Path = path_raw
        else:
            path: Path = Path(path_raw)

        if not path.is_absolute():
            raise RuntimeError(f"{path} is not absolute")

        self.path: Path = path

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, exc_type, exc_val, exc_tb):
        return


class _Btrfs:
    # TODO: Btrfs class has not been tested <2022-07-23, Hyunjae Kim>
    def __init__(self, path_raw: Any, snapname: str = get_random_str(14)):
        if isinstance(path_raw, Path):
            path: Path = path_raw
        else:
            path: Path = Path(path_raw)

        if not path.is_absolute():
            raise RuntimeError("Requires absolute path")

        self.snapname: str = "".join(
            filter(lambda char: char in _LETTERS, snapname)
        )
        self.path: Path = path
        self.snap_path: Optional[Path] = None

    def create_snapshot(self) -> Path:
        if self.snap_path is not None:
            return self.snap_path

        snap_path: Path = self.path.joinpath(f"{self.snapname}")
        while snap_path.exists():
            snap_path = self.path.joinpath(
                f"{self.snapname}_{get_random_str(10)}"
            )

        args: List[str] = [
            "btrfs",
            "subvolume",
            "snapshot",
            str(self.path),
            str(snap_path),
        ]

        try:
            subprocess.run(args, check=True, capture_output=True)
        except subprocess.CalledProcessError as err:
            logger.error(
                "ERROR making snapshot (Check Permission): %s: %s",
                snap_path,
                err.stderr,
            )
            raise err

        self.snap_path = snap_path
        return self.snap_path

    def clear_snapshot(self):
        if self.snap_path is None:
            return

        args: List[str] = ["btrfs", "subvolume", "delete", str(self.snap_path)]

        try:
            subprocess.run(args, check=True, capture_output=True)
        except subprocess.CalledProcessError as err:
            logger.critical(
                "ERROR deleting BTRFS snapshot: %s: %s",
                self.snap_path,
                err.stderr,
            )
            raise err
        return

    def __enter__(self) -> Path:
        try:
            path = self.create_snapshot()
        except Exception as err:
            msg: str = "An error occurred while creating BTRFS snapshot"
            logger.error(msg)
            self.clear_snapshot()
            raise err

        return path

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.clear_snapshot()


class _Zfs:
    def __init__(self, dataset_raw: Any, snapname: str = get_random_str(14)):
        if isinstance(dataset_raw, str):
            dataset: str = dataset_raw
        else:
            dataset: str = str(dataset_raw)

        if "@" in dataset or dataset.startswith("/"):
            raise RuntimeError("Cannot handle snapshot or path")

        self.dataset: str = dataset
        self.snapname: str = "".join(
            filter(lambda char: char in _LETTERS, snapname)
        )
        self._system_datasets: Optional[Dict[str, Optional[Path]]] = None
        self._snapshot_fullname: Optional[str] = None
        self.snapshot_mount_path: Optional[Path] = None
        self.manual_mount_flag: bool = False

    def list_dataset(self, refresh: bool = False) -> Dict[str, Optional[Path]]:
        """
        return list of zfs snapshot and dataset with its mountpoint
        """

        if not refresh and self._system_datasets is not None:
            return self._system_datasets

        args: List[str] = [
            "zfs",
            "list",
            "-o",
            "name,mountpoint",
            "-t",
            "filesystem,snapshot",
        ]
        proc: subprocess.CompletedProcess = subprocess.run(
            args, capture_output=True, check=True
        )

        ret: Dict[str, Optional[Path]] = {}
        for line in proc.stdout.decode("UTF-8").split("\n")[1:]:
            if not line:
                continue
            items = line.split()
            # name: mountpoint
            if items[-1].startswith("/"):
                ret[items[0]] = Path(items[-1])
            else:
                ret[items[0]] = None

        self._system_datasets = ret
        return ret

    def create_snapshot(self, recursive: bool = True) -> Path:
        """
        Create and mount snapshot
        """

        if self.snapshot_mount_path is not None:
            return self.snapshot_mount_path

        snapshot_name = f"{self.dataset}@{self.snapname}"
        while snapshot_name in self.list_dataset():
            snapshot_name = (
                f"{self.dataset}@{self.snapname}_{get_random_str(6)}"
            )

        args: List[str] = ["zfs", "snapshot"]
        if recursive:
            args.append("-r")
        args.append(snapshot_name)

        logger.info("Creating ZFS snapshot %s", snapshot_name)
        try:
            subprocess.run(args, check=True)
        except subprocess.CalledProcessError as err:
            logger.error(
                "ERROR making snapshot: %s / Try zfs-allow snapshot to delegate the permission",
                snapshot_name,
            )
            raise err

        self._snapshot_fullname = snapshot_name
        if self._system_datasets is not None:
            self._system_datasets[snapshot_name] = None

        mountpoint: Optional[Path] = self.list_dataset()[self.dataset]
        if isinstance(mountpoint, Path):
            self.snapshot_mount_path = mountpoint.joinpath(
                ".zfs", "snapshot", snapshot_name.split("@")[-1]
            )
        else:
            self.snapshot_mount_path = self._mount_snapshot()

        return self.snapshot_mount_path

    def _mount_snapshot(self) -> Path:
        """
        Mount snapshot (if needed)
        """

        def get_mountdir() -> Path:
            # TODO: try other way <2022-07-23, Hyunjae Kim>
            base_path = Path("/run/media/")
            # more specific handling
            path_name: str = "".join(
                filter(lambda char: char in _LETTERS, snapshot)
            )
            new_path = base_path.joinpath(f".tmp_{path_name}")
            while new_path.exists():
                new_path = base_path.joinpath(
                    f".tmp_{path_name}_{get_random_str(6)}"
                )

            return new_path

        if self.snapshot_mount_path is not None:
            return self.snapshot_mount_path

        if os.getuid() != 0:
            msg: str = "Require root privilege to mount snapshot"
            logger.error(msg)
            raise PermissionError(msg)

        if self._snapshot_fullname is None:
            raise RuntimeError("Snapshot is not created")
        elif self._snapshot_fullname not in self.list_dataset():
            raise RuntimeError("Snapshot is not in the ZFS list")

        snapshot: str = self._snapshot_fullname

        new_path = get_mountdir()
        new_path.mkdir(parents=True)

        logger.info("ZFS mounting %s to %s", snapshot, new_path)
        args = ["mount", "-t", "zfs", "-o", "ro", snapshot, str(new_path)]

        try:
            subprocess.run(args, check=True, capture_output=True)
        except subprocess.CalledProcessError as err:
            logger.error(
                "ERROR mounting snapshot %s to %s/ from mount: %s",
                snapshot,
                new_path,
                err.stderr.decode(),
            )
            raise err
            # TODO: delete snapshot if fails <2022-07-23, Hyunjae Kim>

        self.snapshot_mount_path = new_path
        self.manual_mount_flag = True
        return new_path

    def _unmount_snapshot(self):
        """
        Unmount manually mounted snapshot
        """
        # this code has been tested

        if not self.manual_mount_flag or self.snapshot_mount_path is None:
            return

        logger.info(
            "ZFS unmounting %s from %s",
            self.snapshot_mount_path,
            self._snapshot_fullname,
        )
        args: List[str] = ["umount", str(self.snapshot_mount_path)]
        try:
            subprocess.run(args, check=True, capture_output=True)
        except subprocess.CalledProcessError as err:
            logger.critical(
                ("ERROR unmounting ZFS snapshot %s at %s",),
                self._snapshot_fullname,
                self.snapshot_mount_path,
            )
            raise err

        self.snapshot_mount_path.rmdir()
        self.snapshot_mount_path = None
        self.manual_mount_flag = False
        return

    def clear_snapshot(self):
        """
        Unmount snapshot and destroy it
        """
        if self._snapshot_fullname is None:
            return

        if self.manual_mount_flag and self.snapshot_mount_path is not None:
            self._unmount_snapshot()

        if "@" not in self._snapshot_fullname:
            raise RuntimeError("Can not destroy non-snapshot dataset")

        logger.info("Deleting ZFS snapshot %s", self._snapshot_fullname)
        args: List[str] = ["zfs", "destroy", "-R", self._snapshot_fullname]

        try:
            subprocess.run(args, check=True, capture_output=True)
        except subprocess.CalledProcessError as err:
            logger.critical(
                (
                    "ERROR Destroying ZFS snapshot: %s \n"
                    "Try zfs-allow destroy to delegate the permission"
                ),
                self._snapshot_fullname,
            )
            raise err

        self._snapshot_fullname = None

    def __enter__(self) -> Path:
        try:
            path: Path = self.create_snapshot()
        except PermissionError as err:
            msg: str = (
                "An error occurred while creating and mounting a ZFS snapshot."
            )
            logger.error(msg)
            self.clear_snapshot()
            raise err
        except Exception as err:
            msg: str = (
                "An error occurred while creating and mounting a ZFS snapshot."
            )
            logger.error("%s: %s", msg, err)
            self.clear_snapshot()
            raise err

        return path

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.clear_snapshot()


class Snapshot:
    """
    Provides Unifying interface of accessing temporary snapshot of directory
    """

    def __init__(self, path: Any, dir_type: SrcType, snapname: str):
        if dir_type == SrcType.DIRECTORY:
            self.snap_handler = _Dir(path)
        elif dir_type == SrcType.ZFS:
            self.snap_handler = _Zfs(path, snapname)
        elif dir_type == SrcType.BTRFS:
            self.snap_handler = _Btrfs(path, snapname)
        else:
            raise NotImplementedError(f"{dir_type} is not implemented")

    def __enter__(self) -> Path:
        return self.snap_handler.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.snap_handler.__exit__(exc_type, exc_val, exc_tb)
