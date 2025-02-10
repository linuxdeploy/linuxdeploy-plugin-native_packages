import glob
import os
import shutil
from pathlib import Path
from typing import List

import gnupg

from .abstractpackager import AbstractPackager, AbstractMetaInfo
from .templating import jinja_env
from .logging import get_logger
from .util import run_command

logger = get_logger("rpm")


def is_any_parent_dir_a_symlink(root_dir: Path, relative_file_path: Path):
    full_path = root_dir / relative_file_path

    # directories that are not symlinks have been handled already
    if full_path.is_dir():
        assert full_path.is_symlink()
        return False

    parts = relative_file_path.parts

    # make sure to skip the last part
    # also, no need to continuously check the root dir (i.e., :0)
    for i in range(1, len(parts)):
        part_path = root_dir / Path(*parts[:i])

        assert part_path.is_dir()

        if part_path.is_symlink():
            return True

    return False


class RpmMetaInfo(AbstractMetaInfo):
    @staticmethod
    def packager_prefix():
        return "RPM"


class Scriptlet:
    @staticmethod
    def _extract_shebang(data: str):
        first_line = data.splitlines()[0]

        if first_line[:2] != "#!":
            return None

        return first_line[2:]

    def __init__(self, type: str, source_file: str):
        self.type = type

        with open(source_file) as f:
            self.content = f.read()

        self.shebang = Scriptlet._extract_shebang(self.content)


class RpmPackager(AbstractPackager):
    """
    This class is inspired by CPack's DEB generator code.
    """

    @staticmethod
    def make_meta_info():
        return RpmMetaInfo()

    def generate_spec_file(self):
        files_and_directories = list(
            map(Path, glob.glob(str(self.context.install_root_dir / "**"), recursive=True, include_hidden=True))
        )

        # we should not need to handle duplicates ourselves if the algorithm below works correctly
        # therefore, using a list is sufficient
        files = []

        for fd in files_and_directories:
            # we need absolute paths below
            fd = fd.absolute()

            if fd.is_dir() and not fd.is_symlink():
                continue

            # we need the relative path for two purposes
            # first, we need to include it later in the files list to include that list in the .spec file
            # second, we need to check all the components (parent directories) up until the install root dir whether
            # either of them is a symlink
            relative_path = fd.relative_to(self.context.install_root_dir)

            # if any of the parent directories is a symlink, we must not include this entry in the list
            # it's totally sufficient to include the symlink itself
            # otherwise, RPM is (rightfully) going to complain that it cannot extract the file
            if is_any_parent_dir_a_symlink(self.context.install_root_dir, relative_path):
                continue

            path_to_include = "/" / relative_path

            assert path_to_include not in files

            files.append(path_to_include)

        assert self.meta_info["package_name"]

        version = self.meta_info["version"]
        assert version

        # try to automagically fix the version number if needed to make it work with rpm
        fixed_version = version.replace("-", "_")

        if fixed_version != version:
            logger.warning(f"version number {version} incompatible, changed to: {fixed_version}")

        scriptlets: List[Scriptlet] = []

        for scriptlet_type in ["pretrans", "pre", "post", "preun", "postun", "posttrans"]:
            scriptlet_path = os.environ.get(f"LDNP_RPM_SCRIPTLET_{scriptlet_type}")

            if scriptlet_path:
                logger.info(f"Found scriptlet of type {scriptlet_type} at {scriptlet_path}")
                scriptlets.append(Scriptlet(scriptlet_type, scriptlet_path))

        # sorting is technically not needed but makes reading and debugging easier
        # note: fixed_version is packager-specific, so we pass it separately
        rendered = jinja_env.get_template("rpm/spec").render(
            files=list(sorted(files)),
            meta_info=self.meta_info,
            fixed_version=fixed_version,
            scriptlets=scriptlets,
        )

        with open(self.context.work_dir / "package.spec", "w") as f:
            f.write(rendered)

    def generate_rpm(self, out_path: str, build_arch: str):
        run_command(
            [
                "rpmbuild",
                # make sure rpm can find files from the current directory
                # this is the elaborate alternative to newer rpmbuild's --build-in-place
                "--define",
                f"_builddir {self.context.work_dir}",
                # make sure we don't pollute the current user's $HOME
                "--define",
                f"_topdir {self.context.work_dir / 'rpmbuild'}",
                # make rpmbuild put the generated file into an expected location
                "--define",
                f"_rpmdir {self.context.out_dir}",
                # better use a custom variable to make things explicit
                "--define",
                f"_install_root {self.context.install_root_dir}",
                # make the package coinstallable
                "--define",
                "_build_id_links none",
                "-bb",
                # specify target explicitly to work around some bug in newer rpmbuild versions
                # "error: No compatible architectures found for build"
                "--target",
                build_arch,
                "package.spec",
            ],
            cwd=self.context.work_dir,
        )

        built_rpms = list(glob.glob(str(self.context.out_dir / "**/*.rpm"), recursive=True))

        if not built_rpms:
            raise ValueError("no built RPM found")

        if len(built_rpms) > 2:
            raise ValueError("more than one RPM built")

        shutil.move(built_rpms[0], out_path)

    def create_package(self, out_path: str | os.PathLike):
        logger.info(f"Creating RPM package called {out_path}")

        extension = ".rpm"

        # remove extension temporarily so we can insert the build architecture (if needed)
        out_path = str(out_path).removesuffix(extension)

        build_arch = self.meta_info.get("build_arch")

        if build_arch:
            out_path += f"_{build_arch}"

        # (re-)add extension which either was lacking all the time or has been removed earlier
        out_path += extension

        self.copy_appdir_contents()
        self.copy_data_to_usr()
        self.write_ldnp_conf()
        self.generate_spec_file()
        self.generate_rpm(out_path, build_arch)

        return out_path

    def sign_package(self, path: str | os.PathLike, gpg_key: str = None):
        # signing is really essential for RPM-based distributions
        # in comparison to Debian, binary package signatures are widely supported and required by distributions
        # if a package is not signed, users will run into annoying warnings very quickly

        # unfortunately, rpmsign requires is to specify a GPG identity
        # if none is provided by the user explicitly, we need to specify the top of the private keyring ourselves
        if gpg_key is None:
            gpg = gnupg.GPG()
            keys = gpg.list_keys(secret=True)
            gpg_key = keys[0]["keyid"]

        run_command(["rpmsign", "--resign", path, "-D", f"_gpg_name {gpg_key}"])
