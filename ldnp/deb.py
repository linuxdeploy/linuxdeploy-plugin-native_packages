import glob
import os

from pathlib import Path

from .abstractpackager import AbstractPackager, AbstractMetaInfo
from .templating import jinja_env
from .util import run_command
from .logging import get_logger


logger = get_logger("deb")


class DebMetaInfo(AbstractMetaInfo):
    @staticmethod
    def packager_prefix():
        return "DEB"


class DebPackager(AbstractPackager):
    """
    This class is inspired by CPack's DEB generator code.
    """

    @staticmethod
    def make_meta_info():
        return DebMetaInfo()

    def generate_control_file(self):
        # this key is optional, however it shouldn't be a big deal to calculate the value
        installed_size = sum(
            map(
                os.path.getsize,
                glob.glob(str(self.appdir.path) + "/**", recursive=True),
            )
        )

        try:
            self.meta_info.get("version")
            self.meta_info.get("package_name")
        except KeyError:
            assert False

        # sorting is technically not needed but makes reading and debugging easier
        # note: installed_size is packager specific and must not be overwritten by the user, so we pass it separately
        rendered = jinja_env.get_template("deb/control").render(meta_info=self.meta_info, installed_size=installed_size)

        # a binary control file may not contain any empty lines in the main body, but must have a trailing one
        dual_newline = "\n" * 2
        while dual_newline in rendered:
            rendered = rendered.replace(dual_newline, "\n")
        rendered += "\n"

        debian_dir = self.context.install_root_dir / "DEBIAN"
        os.makedirs(debian_dir, exist_ok=True)

        control_path = debian_dir / "control"
        logger.info(f"Generating control file in {control_path}")

        with open(control_path, "w") as f:
            f.write(rendered)

    def generate_shlibs_file(self):
        # FIXME: shlibs
        # # TODO: make shlibs configurable
        # with open(self.context.work_dir / "shlibs", "w") as f:
        #     f.write("true")
        pass

    def generate_deb(self, out_path: str):
        logger.info(f"Generating .deb package called {out_path}")
        run_command(["dpkg-deb", "-Zxz", "-b", self.context.install_root_dir, out_path])

    def create_package(self, out_path: str | os.PathLike):
        logger.info(f"Creating Debian package called {out_path}")

        extension = ".deb"

        if not str(out_path).endswith(extension):
            out_path = Path(f"{out_path}{extension}")

        self.copy_appdir_contents()
        self.copy_data_to_usr()
        self.write_ldnp_conf()
        self.generate_control_file()
        self.generate_shlibs_file()
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
        command = ["dpkg-sig", "--sign=builder", str(path)]

        if gpg_key is not None:
            command += ["-k", gpg_key]

        run_command(command)
