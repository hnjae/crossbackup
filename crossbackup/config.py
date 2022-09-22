"""
Provides Config objects
"""
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml
from pydantic import BaseModel, validator

_DO_NOT_COMPRESS: Set[str] = {
    # images
    ".jpg",
    ".jpeg",
    ".png",
    ".avif",
    ".heif",
    ".heic",
    ".webp",
    ".jxr",
    ".j2k",
    # videos
    ".mp4",
    ".mov",
    ".webm",
    ".mkv",
    ".wmv",
    ".avi",
    ".rm",
    # archives
    # ".zip",
    ".rar",
    ".7z",
    ".zipx",
    ".zst",
    ".lha",
    ".zstd",
    ".bz2",
    ".lzma",
    ".lzh",
    ".ace",
    ".alz",
    ".egg",
    ".arc",
    ".arj",
    ".ar",
    ".cab",
    ".cb7",
    ".cbr",
    ".cbz",
    ".taz",
    ".gz",
    ".tgz",
    ".bzip2",
    ".tbz",
    ".tbz2",
    ".xz",
    ".txz",
    # audio files
    ".m4a",
    ".mka",
    ".opus",
    ".ogg",
    ".mp3",
    ".aac",
    ".flac",
    ".ape",
    ".tak",
    ".tta",
    ".wma",
}


# Get Path of various Executable
_RAR_EXE: Optional[Path] = None
_tmp: Optional[str] = shutil.which("rar")
if _tmp is not None:
    _RAR_EXE = Path(_tmp)

_SEVENZ_EXE: Optional[Path] = None
_tmp = shutil.which("7zz")
if _tmp is not None:
    _SEVENZ_EXE = Path(_tmp)
else:
    _tmp = shutil.which("7z")
    if _tmp is not None:
        _SEVENZ_EXE = Path(_tmp)

_ARCHIVE_WORKING_PATHS: List[Path] = [Path("/tmp")]
_xdg_cache_home: Optional[Path] = None
if "XDG_CACHE_HOME" in os.environ:
    _xdg_cache_home = Path(os.environ["XDG_CACHE_HOME"])
elif "HOME" in os.environ:
    _xdg_cache_home = Path(os.environ["HOME"]).joinpath(".cache")
if _xdg_cache_home is not None:
    _ARCHIVE_WORKING_PATHS.append(_xdg_cache_home)


class _ProgramConfig(BaseModel):
    """
    System config class
    """

    # dry_run: bool = False
    log_level: str = "INFO"
    # rclone_log_level: str = "WARNING"
    rclone_log_level: str = "INFO"
    excludes: List[str] = [
        "__pycache__/**",
        ".Trash-1000/**",
        ".thumbnails/**",
        ".git/**",
        ".ropeproject/**",
        ".svn",
        ".DS_Store",
        ".directory",
        "Thumbs.db",
        "fish_variables",
        ".zsh_history",
        "*.zcompdump",
        "*.lock",
    ]

    tar_args: List[str] = [
        "--format=gnu",
        "-I",
        "zstd -19 --threads=0",
        "--preserve-permissions",
        "--xattrs",
    ]
    tar_extension: str = ".tar.zst"

    rar_path: Optional[Path] = _RAR_EXE
    rar_args: List[str] = [
        "-s",  # Solid Archives
        "-rr1",  # Add data recovery record
        "-htb",  # Use BLAKE2sp
        "-m5",  # Best compression method
        "-ma5",  # Use RAR 5.0
        "-idc",  # disables copyright string
        "".join(["-ms", ";".join(_DO_NOT_COMPRESS)]),
        "-r",  # recursive
    ]
    sevenz_path: Optional[Path] = _SEVENZ_EXE
    # -sccUTF-8 -scsUTF-8
    sevenz_args: List[str] = [
        "-bd",  # disable percentage indicator
        "-scrcSHA256",
        "-m0=lzma2",
        "-mx7",
        "-mfb=64",  # number of fast bytes for LZMA
        "-md=32m",  # dictionary size
        "-snl",  # store symbolic links as links (not default)
        "-ssp",  # do not change Last Access Time of source files while archiving
        "-ms=on",  # enable solid archive
        "-t7z",
        # "-mcu=on",   # use UTF-8 for no Ascii : Not working (2022-07-24)
        # "-mhc=off",  # disable header compression: Not working (2022-07-24)
    ]
    # "-y" : assume yes on all queries

    # TODO: check this is absolute <2022-07-23, Hyunjae Kim>
    archive_working_paths: List[Path] = _ARCHIVE_WORKING_PATHS

    # TODO: add validator <2022-07-23, Hyunjae Kim>
    @validator("log_level", "rclone_log_level")
    def validate_log_level(cls, v):
        avail_type = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        assert v in avail_type, f"log level must be in {avail_type}"
        return v


def _get_config_settings_from_source() -> Dict[str, Any]:
    """
    Loads variable from YAML files in config directory
    """

    xdg_config_home: Path
    if "XDG_CONFIG_HOME" in os.environ:
        xdg_config_home = Path(os.environ["XDG_CONFIG_HOME"])
    elif "HOME" in os.environ:
        xdg_config_home = Path(os.environ["HOME"]).joinpath(".config")
    else:
        raise Exception('"HOME" environment variable is not set')

    config: Dict[str, Any] = {}
    for config_dir in [Path("/etc"), xdg_config_home]:
        for config_filename in ["config.yaml", "config.yml"]:

            config_file = config_dir.joinpath("crossbackup", config_filename)
            if not config_file.is_file():
                continue

            config.update(yaml.safe_load(config_file.read_text()))

    return config


_config_dict: Dict[str, Any] = _ProgramConfig().dict()
_config_dict.update(_get_config_settings_from_source())
CONFIG: _ProgramConfig = _ProgramConfig.parse_obj(_config_dict)

def update_program_config(local_config: Dict[str, Any]):
    _config_dict.update(local_config)
    global CONFIG
    CONFIG = _ProgramConfig.parse_obj(_config_dict)
