import configparser
import glob
import os
import shlex
import shutil
import stat
from collections import UserDict
from pathlib import Path
from typing import Iterable

from xdg.DesktopEntry import DesktopEntry

from .appdir import AppDir
from .context import Context
from .logging import get_logger

logger = get_logger("packager")


class AbstractMetaInfo(UserDict):
    """
    Base class for meta information from which the packaging files are generated.

    The metadata needed for either supported packager can differ to some extent, but there are also shared values
    which are implemented here.

    The meta information is typically passed to the application via environment variables which follow a specific
    pattern:

    "LDNP_" as a prefix, "META_" to identify it as meta information and an arbitrary identifier suffix.

    Optionally, before the identifier suffix, a packager designation may be passed to use the information only for a
    specific packager. Currently, DEB_ and RPM_ are supported.

    The identifier may contain any character that is valid for an environment variable. It is recommended to only use
    uppercase alphanumeric characters [A-Z0-9] and underscores _.

    For instance, a package description could be passed to the meta information system as "LDNP_META_DESCRIPTION".
    An RPM-only description would be passed as "LDNP_META_RPM_DESCRIPTION".

    If the packager cannot make any use of the information provided in the environment, the value will be ignored.

    Packager-specific implementations need to implement the packager_prefix method, returning a unique designator.
    """

    # as some meta information may be set programmatically, too, we need a "cache" for those values
    # information provided via environment variables currently always take precedence over those programmatically
    # provided values
    # all identifiers are case supposed to be case-insensitive and will be normalized to upper case (which matches
    # the environment variables)

    @staticmethod
    def packager_prefix():
        raise NotImplementedError

    def __setitem__(self, key, value):
        # we treat all keys as case-insensitive and normalize them to uppercase
        self.data[key.upper()] = value

    def __getitem__(self, identifier: str):
        """
        Implements the "subscript" operator. Checks the environment for packager-specific and globally set meta info.

        :param identifier: identifier suffix (see class description)
        :return: value for provided identifier (if available)
        :raises KeyError: if the requested value is unavailable
        """

        # identifiers are supposed to be case-insensitive within our code (we accept only upper-case env vars)
        identifier = identifier.upper()

        prefix = "LDNP_META"

        global_env_var = f"{prefix}_{identifier}"
        specific_env_var = f"{prefix}_{self.packager_prefix()}_{identifier.upper()}"

        # just needed to be able to rewrite the error message
        try:
            try:
                return os.environ[specific_env_var]

            except KeyError:
                try:
                    return os.environ[global_env_var]

                except KeyError:
                    # the KeyError here should propagate to the caller if raised
                    return self.data[identifier]

        except KeyError:
            raise KeyError(f"Could not find {identifier.upper()}")


class AbstractPackager:
    def __init__(self, appdir: AppDir, meta_info: AbstractMetaInfo, context: Context):
        self.appdir = appdir
        self.meta_info = meta_info
        self.context: Context = context

        assert self.meta_info["package_name"]
        assert self.meta_info["version"]
        assert self.meta_info["filename_prefix"]

        self.appdir_installed_path = Path(f"/opt/{self.meta_info['package_name']}.AppDir")
        self.appdir_install_path = self.context.install_root_dir / str(self.appdir_installed_path).lstrip("/")
        logger.debug(f"AppDir install path: {self.appdir_install_path}")

    @staticmethod
    def make_meta_info():
        raise NotImplementedError

    def find_desktop_files(self) -> Iterable[Path]:
        rv = glob.glob(str(self.appdir_install_path / AppDir.DESKTOP_FILES_RELATIVE_LOCATION / "*.desktop"))
        return map(Path, rv)

    @staticmethod
    def _find_file_paths_in_directory(directory: Path) -> Iterable[Path]:
        for path in map(Path, glob.glob(str(directory / "**" / "*.*"), recursive=True, include_hidden=True)):
            if not path.is_file():
                continue
            yield path

    def find_icons(self, prefix: str = None) -> Iterable[Path]:
        all_icons = self._find_file_paths_in_directory(self.appdir_install_path / AppDir.ICONS_RELATIVE_LOCATION)

        if prefix is None:
            return all_icons

        return filter(lambda p: p.parts[-1].startswith(prefix), all_icons)

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

        def deploy_file_as_is(path):
            logger.debug(f"Deploying file {path} as-is")
            relative_path = path.relative_to(self.appdir_install_path)
            dst = self.context.install_root_dir / relative_path
            os.makedirs(dst.parent, mode=0o755, exist_ok=True)
            create_relative_symlink(path, dst)

        for desktop_file in self.find_desktop_files():
            dst = desktop_files_dest_dir / desktop_file.name
            create_relative_symlink(desktop_file, dst)

            # create symlink in /usr/bin to the desktop file's binary to make it available to the user
            # TODO: make optional
            desktop_entry = DesktopEntry(dst)
            exec_entry = desktop_entry.getExec()

            # icon files can just be symlinked, there is no reason _ever_ to modify them
            # note: this assumes that the icon entry is configured correctly with a filename only!
            icons_prefix = f"{desktop_entry.getIcon()}."
            logger.debug(f"icons prefix: {icons_prefix}")
            for icon in self.find_icons(icons_prefix):
                deploy_file_as_is(icon)

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

        # MIME files just describe a type and shouldn't contain any paths, therefore we can just link them
        # TODO: deploy icons for MIME files
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

    def write_ldnp_conf(self):
        conf_path = self.appdir_install_path / "usr" / "bin" / "linuxdeploy.conf"

        config = configparser.ConfigParser()

        try:
            with open(conf_path) as f:
                config.read_file(f)
        except FileNotFoundError:
            pass

        config["ldnp"] = {
            "appdir_installed_path": str(self.appdir_installed_path),
        }

        with open(conf_path, "w") as f:
            config.write(f)

    def create_package(self, out_path: str | os.PathLike):
        # to be implemented by subclasses
        raise NotImplementedError

    def sign_package(self, path: str | os.PathLike, gpg_key: str = None):
        # to be implemented by subclasses
        raise NotImplementedError
