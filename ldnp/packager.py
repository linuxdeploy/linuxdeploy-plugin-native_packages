import glob
import os
import shlex
import shutil
from pathlib import Path
from typing import Iterable

from xdg.DesktopEntry import DesktopEntry

from .context import Context


class AppDir:
    """
    A simple object-oriented wrapper around an AppDir on the filesystem.
    This class contains some utilities to extract information from the AppDir.
    """

    DESKTOP_FILES_RELATIVE_LOCATION = "usr/share/applications"

    def __init__(self, path: str | os.PathLike, install_name: str):
        self.path = Path(path)
        self.install_name = install_name
        self.relative_install_path = Path("opt") / install_name

    def find_desktop_files(self) -> Iterable[Path]:
        rv = glob.glob(
            str(self.path / "opt" / self.install_name / self.__class__.DESKTOP_FILES_RELATIVE_LOCATION / "*.desktop")
        )
        return map(Path, rv)

    def root_desktop_file(self) -> DesktopEntry:
        desktop_files = glob.glob(str(self.path / "*.desktop"))

        # we don't expect more than a single desktop file at once
        assert len(desktop_files) == 1

        return DesktopEntry(desktop_files[0])

    def guess_package_name(self) -> str:
        return NotImplemented

    def guess_package_maintainer(self) -> str:
        return NotImplemented


class Packager:
    def __init__(self, appdir_path: str | os.PathLike, context: Context):
        self.appdir = AppDir(appdir_path, "package.AppDir")
        self.context: Context = context

        self.appdir_install_path = self.context.install_root_dir / self.appdir.install_name

    def find_desktop_files(self) -> Iterable[Path]:
        rv = glob.glob(
            str(
                self.context.install_root_dir
                / "opt"
                / self.appdir.install_name
                / AppDir.DESKTOP_FILES_RELATIVE_LOCATION
                / "*.desktop"
            )
        )
        return map(Path, rv)

    def copy_data_to_usr(self):
        def create_relative_symlink(src: Path, dst: Path):
            # to calculate the amount of parent directories we need to move up, we can't use relative_to directly
            # we need to calculate the "inverse" result, then count the number of components and insert as many ..
            distance_from_dst_to_root = dst.parent.relative_to(self.context.install_root_dir)
            relative_prefix = "/".join([".." for _ in distance_from_dst_to_root.parts])
            src = relative_prefix / src.relative_to(self.context.install_root_dir)
            dst.unlink(missing_ok=True)
            os.symlink(src, dst)

        # by default, we install all the desktop files found in AppDir/usr/share/ to the system-wide /usr/share we
        # then look for these apps' Exec= keys and install symlinks to the real binaries within the AppDir to /usr/bin
        desktop_files_dest_dir = self.context.install_root_dir / AppDir.DESKTOP_FILES_RELATIVE_LOCATION
        os.makedirs(desktop_files_dest_dir, exist_ok=True)

        bin_dest_dir = self.context.install_root_dir / "usr/bin"
        os.makedirs(bin_dest_dir, exist_ok=True)

        for desktop_file in self.find_desktop_files():
            dst = desktop_files_dest_dir / desktop_file.name
            create_relative_symlink(desktop_file, dst)

            # create symlink in /usr/bin to the desktop file's binary to make it available to the user
            # TODO: make optional
            desktop_entry = DesktopEntry(dst)
            exec_entry = desktop_entry.getExec()

            if not exec_entry:
                raise ValueError("Exec= entry not set")

            exec_binary = shlex.split(exec_entry)[0]

            usr_bin_path = self.appdir_install_path / "usr/bin" / exec_binary

            # we expect a working Exec= entry with a matching binary
            if not usr_bin_path.exists():
                raise ValueError("binary Exec= entry points to does not exist in AppDir/usr/bin/")

            create_relative_symlink(usr_bin_path, bin_dest_dir / exec_binary)

    def copy_appdir_contents(self):
        if os.path.exists(self.appdir_install_path):
            shutil.rmtree(self.appdir_install_path)

        shutil.copytree(
            self.context.install_root_dir,
            self.appdir_install_path,
            symlinks=True,
            ignore_dangling_symlinks=True,
            dirs_exist_ok=True,
        )

    def create_package(self, out_path: str | os.PathLike):
        # to be implemented by subclasses
        return NotImplemented

    def sign_package(self, path: str | os.PathLike, gpg_key: str = None):
        # to be implemented by subclasses
        return NotImplemented
