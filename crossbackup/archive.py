"""
Provides Archive class
"""

import logging
import tempfile
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from .config import CONFIG
from .data_type import ArchiveType

logger = logging.getLogger("default")
logger_debug = logging.getLogger("debug")


class _Archive:
    def __init__(self, input_path: Path, name: str):
        """
        :param input_path: Path
        :param name: name without extension
        """
        if not input_path.is_dir():
            raise RuntimeError(f"{input_path} is not directory")
        if not input_path.is_absolute():
            raise RuntimeError(f"{input_path} is not absolute path")

        self.input_path: Path = input_path
        self.name: str = name
        self.archive_path: Optional[Path] = None
        self.tmpdir: Optional[Path] = None

    def _get_working_path(self) -> Path:
        input_size: int = sum(
            f.stat().st_size
            for f in self.input_path.glob("**/*")
            if f.is_file()
        )

        for path in CONFIG.archive_working_paths:
            free_space: int = shutil.disk_usage(path).free
            if free_space > input_size:
                logger.info("Using %s as working directory for archives", path)
                return path

        msg: str = "Could not find a workspace with enough free space"
        logger.error(msg)
        raise RuntimeError(msg)

    def create_archive(self) -> Path:
        """
        Return archive location
        """
        raise NotImplementedError

    def clean_archive(self):
        """
        Clean archive
        """

        try:
            if self.archive_path is not None and self.archive_path.exists():
                logger.info("Deleting archive %s", self.archive_path)
                self.archive_path.unlink()
            if self.tmpdir is not None and self.tmpdir.exists():
                logger.info("Deleting temporary directory %s", self.tmpdir)
                shutil.rmtree(self.tmpdir)
        except Exception as err:
            logger.critical(
                "ERROR: Could not delete %s or %s",
                self.archive_path,
                self.tmpdir,
            )
            raise err

        self.archive_path = None

    def __enter__(self) -> Path:
        try:
            path: Path = self.create_archive()
        except Exception as err:
            msg: str = "An error occurred while creating archives"
            logger.error("%s: %s", msg, err)
            self.clean_archive()
            raise err

        return path

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.clean_archive()


class _Tar(_Archive):
    def create_archive(self) -> Path:
        """
        Return archive location

        should set self.tmpdir and self.archive_path
        """
        if self.archive_path is not None and self.archive_path.exists():
            return self.archive_path

        # NOTE: this is absolute path <2022-07-23, Hyunjae Kim>
        working_path: Path = self._get_working_path()
        self.tmpdir = Path(tempfile.mkdtemp(dir=working_path))
        self.archive_path = self.tmpdir.joinpath(
            f"{self.name}{CONFIG.tar_extension}"
        )

        if self.archive_path.exists():
            # NOTE: This will never likely to happen
            raise FileExistsError(
                f"Following archive already exists: {self.archive_path}"
            )

        logger.info("Archiving %s to %s", self.input_path, self.archive_path)

        args: List[str] = ["tar"]
        args.extend(CONFIG.tar_args)
        args.extend(["-cf", str(self.archive_path)])
        files = [
            str(x.relative_to(self.input_path))
            for x in self.input_path.iterdir()
        ]
        args.extend(sorted(files))

        try:
            subprocess.run(
                args,
                capture_output=True,
                cwd=self.input_path,
                check=True,
            )
        except subprocess.CalledProcessError as err:
            logger.error(err)
            raise err

        return self.archive_path


class _Sevenz(_Archive):
    def create_archive(self) -> Path:
        """
        Return archive location

        should set self.tmpdir and self.archive_path
        """

        if self.archive_path is not None and self.archive_path.exists():
            return self.archive_path

        if CONFIG.sevenz_path is None:
            raise RuntimeError("Could not find 7z in $PATH")

        # NOTE: this is absolute path <2022-07-23, Hyunjae Kim>
        working_path: Path = self._get_working_path()
        self.tmpdir = Path(tempfile.mkdtemp(dir=working_path))
        self.archive_path = self.tmpdir.joinpath(f"{self.name}.7z")

        if self.archive_path.exists():
            # NOTE: This will never likely to happen
            raise FileExistsError(
                f"Following archive already exists: {self.archive_path}"
            )

        logger.info("Archiving %s to %s", self.input_path, self.archive_path)

        args: List[str] = [str(CONFIG.sevenz_path)]
        args.extend(CONFIG.sevenz_args)
        args.extend(["a", str(self.archive_path)])
        files = [
            str(x.relative_to(self.input_path))
            for x in self.input_path.iterdir()
        ]
        args.extend(sorted(files))

        try:
            subprocess.run(
                args,
                capture_output=True,
                cwd=self.input_path,
                check=True,
            )
        except subprocess.CalledProcessError as err:
            logger.error(err)
            raise err

        return self.archive_path


class _Rar(_Archive):
    def create_archive(self) -> Path:
        """
        Return archive location

        should set self.tmpdir and self.archive_path
        """
        if self.archive_path is not None and self.archive_path.exists():
            return self.archive_path

        if CONFIG.rar_path is None:
            raise RuntimeError("Could not find rar in $PATH")

        # NOTE: this is absolute path <2022-07-23, Hyunjae Kim>
        working_path: Path = self._get_working_path()
        self.tmpdir = Path(tempfile.mkdtemp(dir=working_path))
        self.archive_path = self.tmpdir.joinpath(f"{self.name}.rar")

        if self.archive_path.exists():
            # NOTE: This will never likely to happen
            raise FileExistsError(
                f"Following archive already exists: {self.archive_path}"
            )

        logger.info("Archiving %s to %s", self.input_path, self.archive_path)
        args: List[str] = [str(CONFIG.rar_path)]
        args.extend(CONFIG.rar_args)

        if "a" in args:
            CONFIG.rar_args.remove("a")

        args.extend(["a", str(self.archive_path)])
        files = [
            str(x.relative_to(self.input_path))
            for x in self.input_path.iterdir()
        ]
        args.extend(sorted(files))

        try:
            subprocess.run(
                args,
                capture_output=True,
                cwd=self.input_path,
                check=True,
            )
            subprocess.run(
                [str(CONFIG.rar_path), "-idc", "t", str(self.archive_path)],
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as err:
            logger.error(err)
            raise err

        return self.archive_path


class Archive:
    """
    Provides Unifying interface of accessing archive of target
    """

    def __init__(self, input_path: Path, archive_type: ArchiveType, name: str):

        if archive_type == ArchiveType.RAR:
            self.archive_handler = _Rar(input_path, name)
        elif archive_type == ArchiveType.TAR:
            self.archive_handler = _Tar(input_path, name)
        elif archive_type == ArchiveType.SEVENZ:
            self.archive_handler = _Sevenz(input_path, name)
        else:
            raise NotImplementedError(f"{archive_type} is not implemented")

    def __enter__(self) -> Path:
        return self.archive_handler.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.archive_handler.__exit__(exc_type, exc_val, exc_tb)
