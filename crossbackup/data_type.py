import enum
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml
from pydantic import (
    BaseModel,
    BaseSettings,
    create_model,
    root_validator,
    validator,
)

# def kebab_to_camel(string: str) -> str:
#     return string.replace("-", "_")


class SrcType(enum.Enum):
    """
    Source type being supported.
    """

    DIRECTORY = "directory"
    ZFS = "zfs"
    BTRFS = "btrfs"
    # TODO: allow "dir" <2022-07-23, Hyunjae Kim>
    # TODO: ignore caps <2022-07-24, Hyunjae Kim>


class DstType(enum.Enum):
    """
    Destination type being supported.
    """

    DIRECTORY = "directory"
    RCLONE = "rclone"
    ZFS = "zfs"
    BTRFS = "btrfs"


class ArchiveType(enum.Enum):
    """
    Archive type being supported.
    """
    RAR = "rar"
    SEVENZ = "7z"
    TAR = "tar"


class _SrcConfig(BaseModel):
    path: Any
    type: SrcType


class _Timeline(BaseModel):
    min_age: int = 1800
    limit_hourly: int = 10
    limit_daily: int = 10
    limit_weekly: int = 0
    limit_monthly: int = 10
    limit_yearly: int = 10

    @root_validator
    def is_positive(cls, values):
        # NOTE: 정의되지 않은 변수에 한해서는 실행되지 않음.
        for key, val in values.items():
            if val >= 0:
                continue
            raise ValueError(
                f"timeline's {key} value should be positive number"
            )
        return values


class _RcloneConfig(BaseModel):
    server_side_copy: bool = False
    use_trash: bool = False


class _Archive(BaseModel):
    enable: bool = False
    type: ArchiveType = ArchiveType("rar")


class _DstConfig(BaseModel):
    path: str
    type: DstType
    archive: _Archive = _Archive()
    rclone_config: _RcloneConfig = _RcloneConfig()
    timeline: _Timeline = _Timeline()

    # 어떠한경우 라도 path 는 / 로 끝나서는 안될듯.
    # TODO: validate path with type <2022-07-23, Hyunjae Kim>
    # @validator("type")
    # def validate_type(cls, v):
    #     avail_type = ["directory", "dir", "file", "zfs", "btrfs"]
    #     assert v in avail_type, f"{v} must be in {avail_type}"
    #     return v



class SingleBackupConfig(BaseModel):
    """
    Backup Config Class
    """

    name: str
    src: _SrcConfig
    dst: _DstConfig
