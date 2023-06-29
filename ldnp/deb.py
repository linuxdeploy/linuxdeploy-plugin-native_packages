import glob
import os
import subprocess

from pathlib import Path

from .context import Context
from .packager import Packager
from .templating import jinja_env


class DebPackager(Packager):
    """
    This class is inspired by CPack's DEB generator code.
    """

    def __init__(self, appdir_path: str | os.PathLike, context: Context):
        super().__init__(appdir_path, context)

    def generate_control_file(self):
        # this key is optional, however it shouldn't be a big deal to calculate the value
        installed_size = sum(
            map(
                os.path.getsize,
                glob.glob(str(self.appdir.path) + "/**", recursive=True),
            )
        )

        # sorting is technically not needed but makes reading and debugging easier
        rendered = jinja_env.get_template("deb/control").render(installed_size=installed_size)

        # a binary control file may not contain any empty lines in the main body, but must have a trailing one
        dual_newline = "\n" * 2
        while dual_newline in rendered:
            rendered = rendered.replace(dual_newline, "\n")
        rendered += "\n"

        debian_dir = self.context.install_root_dir / "DEBIAN"
        os.makedirs(debian_dir, exist_ok=True)
        with open(debian_dir / "control", "w") as f:
            f.write(rendered)

    def generate_deb(self, out_name: str):
        subprocess.check_call(["dpkg-deb", "-Zxz", "-b", self.context.install_root_dir, out_name])

    def create_package(self, out_path: str | os.PathLike):
        extension = ".deb"

        if not out_path.endswith(extension):
            out_path = Path(f"{out_path}{extension}")

        self.copy_appdir_contents()
        self.copy_data_to_usr()
        self.generate_control_file()
        self.generate_deb(out_path)

        return out_path

    def sign_package(self, path: str | os.PathLike, gpg_key: str = None):
        # unfortunately, Debian doesn't really support signatures on binary archives
        # in Debian's world, what matters most is signing the source archives as well as signing the entire package
        # repositories
        # there is an optional binary archive signature tool called dpkg-sig that can be used to create and verify
        # signatures of binary .deb archives
        # we use this tool to sign the packages built by this tool if requested to do so by the user
        # it is at least better than not attaching any signatures or using detached ones
        subprocess.check_call(["dpkg-sig", "--sign=builder", path, "-k", gpg_key])
