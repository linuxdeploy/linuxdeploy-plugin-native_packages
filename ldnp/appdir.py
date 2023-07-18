import glob
import os
import shlex
from pathlib import Path
from typing import Iterable

from xdg.DesktopEntry import DesktopEntry


class AppDir:
    """
    A simple object-oriented wrapper around an AppDir on the filesystem.
    This class contains some utilities to extract information from the AppDir.
    """

    DESKTOP_FILES_RELATIVE_LOCATION = "usr/share/applications"

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)

    def find_desktop_files(self) -> Iterable[Path]:
        rv = glob.glob(
            str(self.path / self.__class__.DESKTOP_FILES_RELATIVE_LOCATION / "*.desktop")
        )
        return map(Path, rv)

    def root_desktop_file(self) -> DesktopEntry:
        desktop_files = glob.glob(str(self.path / "*.desktop"))

        # we don't expect more than a single desktop file at once
        assert len(desktop_files) == 1

        return DesktopEntry(desktop_files[0])

    def guess_package_name(self) -> str:
        root_desktop_file = self.root_desktop_file()
        exec_name = root_desktop_file.getExec()
        assert exec_name
        return shlex.split(exec_name)[0]

    def guess_version(self) -> str | None:
        """
        Guess version based on version data in desktop file (if available).
        :returns: None if no version is found, version string otherwise
        """
        root_desktop_file = self.root_desktop_file()
        version = root_desktop_file.get("X-AppImage-Version")
        return version

    def guess_package_maintainer(self) -> str:
        raise NotImplementedError

    def guess_package_version(self):
        # AppDirs which appimagetool already ran on usually provide a version marker which we can recycle
        root_desktop_file = self.root_desktop_file()
        x_appimage_version = root_desktop_file.get("X-AppImage-Version")

        if x_appimage_version:
            return x_appimage_version

        raise ValueError("Could not find version in AppDir")
