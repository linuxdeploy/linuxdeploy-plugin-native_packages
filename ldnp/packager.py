import glob
import os
import shlex
import shutil
import stat
from pathlib import Path
from typing import Iterable

from xdg.DesktopEntry import DesktopEntry

from .appdir import AppDir
from .context import Context
from .logging import get_logger

logger = get_logger("packager")


class Packager:
    def __init__(self, appdir: AppDir, package_name: str, version: str, filename_prefix: str, context: Context):
        self.appdir = appdir
        self.context: Context = context

        # we require these values, so the CLI needs to either demand them from the user or set sane default values
        # TODO: validate these input values
        self.package_name = package_name
        self.version = version
        self.filename_prefix = filename_prefix

        self.appdir_installed_path = Path(f"/opt/{self.package_name}.AppDir")
        self.appdir_install_path = self.context.install_root_dir / str(self.appdir_installed_path).lstrip("/")
        logger.debug(f"AppDir install path: {self.appdir_install_path}")

        # optional values that _can_ but do not have to be set
        # for these values, we internally provide default values in the templates
        self.description = None
        self.short_description = None

    def set_description(self, description: str):
        self.description = description

    def set_short_description(self, short_description: str):
        self.description = short_description

    def find_desktop_files(self) -> Iterable[Path]:
        rv = glob.glob(str(self.appdir_install_path / AppDir.DESKTOP_FILES_RELATIVE_LOCATION / "*.desktop"))
        return map(Path, rv)

    @staticmethod
    def _find_file_paths_in_directory(directory: Path) -> Iterable[Path]:
        for path in map(Path, glob.glob(str(directory / "**" / "*.*"), recursive=True, include_hidden=True)):
            if not path.is_file():
                continue
            yield path

    def find_icons(self) -> Iterable[Path]:
        return self._find_file_paths_in_directory(self.appdir_install_path / AppDir.ICONS_RELATIVE_LOCATION)

    def find_mime_files(self) -> Iterable[Path]:
        return self._find_file_paths_in_directory(self.appdir_install_path / AppDir.MIME_FILES_RELATIVE_LOCATION)

    def find_cloudproviders_files(self) -> Iterable[Path]:
        return self._find_file_paths_in_directory(
            self.appdir_install_path / AppDir.CLOUDPROVIDERS_FILES_RELATIVE_LOCATION
        )

    def copy_data_to_usr(self):
        def create_relative_symlink(src: Path, dst: Path):
            # to calculate the amount of parent directories we need to move up, we can't use relative_to directly
            # we need to calculate the "inverse" result, then count the number of components and insert as many ..
            distance_from_dst_to_root = dst.parent.relative_to(self.context.install_root_dir)
            relative_prefix = "/".join([".." for _ in distance_from_dst_to_root.parts])
            src = relative_prefix / src.relative_to(self.context.install_root_dir)
            logger.debug(f"Creating relative symlink to {src} at {dst}")
            dst.unlink(missing_ok=True)
            os.symlink(src, dst)

        def create_binary_script(script_path: str | os.PathLike, target_binary: str | os.PathLike):
            logger.debug(f"Creating script for target binary {target_binary} in {script_path}")

            with open(script_path, "w") as f:
                f.write(
                    "\n".join(
                        [
                            "#! /bin/sh",
                            "",
                            "set -e",
                            "",
                            f'script_dir="{shlex.quote(str(self.appdir_installed_path))}/apprun-hooks"',
                            f'if [ -d "$script_dir" ]; then',
                            '    for script in "$script_dir"/*; do',
                            '        . "$script"',
                            "    done",
                            "fi",
                            "",
                            f'exec {shlex.quote(str(target_binary))} "$@"',
                            "",
                        ]
                    )
                )

            st = os.stat(script_path)
            os.chmod(script_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

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
                raise ValueError("binary Exec= entry points to non-existing binary in AppDir/usr/bin/")

            create_binary_script(
                self.context.install_root_dir / "usr/bin" / exec_binary,
                self.appdir_installed_path / "usr/bin" / exec_binary,
            )

        def deploy_file_as_is(path):
            logger.debug(f"deploying file {path} as-is")
            relative_path = path.relative_to(self.appdir_install_path)
            dst = self.context.install_root_dir / relative_path
            os.makedirs(dst.parent, mode=0o755, exist_ok=True)
            create_relative_symlink(path, dst)

        # icon files can just be symlinked, there is no reason _ever_ to modify them
        for icon in self.find_icons():
            deploy_file_as_is(icon)

        # MIME files just describe a type and shouldn't contain any paths, therefore we can just link them
        for mime_file in self.find_mime_files():
            deploy_file_as_is(mime_file)

        # same goes for libcloudproviders configuration data, which just describe some D-Bus endpoints
        for cloudproviders_file in self.find_cloudproviders_files():
            deploy_file_as_is(cloudproviders_file)

    def copy_appdir_contents(self):
        if os.path.exists(self.appdir_install_path):
            shutil.rmtree(self.appdir_install_path)

        shutil.copytree(
            self.appdir.path,
            self.appdir_install_path,
            symlinks=True,
            ignore_dangling_symlinks=True,
            dirs_exist_ok=True,
        )

    def create_package(self, out_path: str | os.PathLike):
        # to be implemented by subclasses
        raise NotImplementedError

    def sign_package(self, path: str | os.PathLike, gpg_key: str = None):
        # to be implemented by subclasses
        raise NotImplementedError
