import glob
import os
import shutil
import subprocess
from pathlib import Path

import gnupg

from .context import Context
from .packager import Packager
from .templating import jinja_env
from .logging import get_logger
from .util import run_command

logger = get_logger().getChild("deb")


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


class RpmPackager(Packager):
    """
    This class is inspired by CPack's DEB generator code.
    """

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

        # sorting is technically not needed but makes reading and debugging easier
        rendered = jinja_env.get_template("rpm/spec").render(files=list(sorted(files)))

        with open(self.context.work_dir / "package.spec", "w") as f:
            f.write(rendered)

    def generate_rpm(self, out_path: str):
        subprocess.check_call(
            [
                "rpmbuild",
                "--build-in-place",
                # make sure we don't pollute the current user's $HOME
                "--define",
                f"_topdir {self.context.work_dir / 'rpmbuild'}",
                # make rpmbuild put the generated file into an expected location
                "--define",
                f"_rpmdir {self.context.out_dir}",
                # better use a custom variable to make things explicit
                "--define",
                f"_install_root {self.context.install_root_dir}",
                "-bb",
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
        extension = ".rpm"

        if not out_path.endswith(extension):
            out_path = Path(f"{out_path}{extension}")

        self.copy_appdir_contents()
        self.copy_data_to_usr()
        self.generate_spec_file()
        self.generate_rpm(out_path)

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
            gpg_key = keys[0].keyid

        subprocess.check_call(["rpmsign", "--resign", path, "-D", f"_gpg_name {gpg_key}"])
