import os

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable

import click

from .deb import DebPackager
from .context import Context
from .rpm import RpmPackager
from .logging import set_up_logging


def make_packager(build_type: str, appdir_path: str | os.PathLike, context_path: Path):
    context = Context(context_path)

    if build_type == "rpm":
        packager = RpmPackager(appdir_path, context)

    elif build_type == "deb":
        packager = DebPackager(appdir_path, context)

    else:
        raise KeyError(f"cannot create packager for unknown build type {build_type}")

    return packager


ENV_VAR_PREFIX = "LDNP"


@click.command()
# required to conform with linuxdeploy plugin API
# click responds to these directly, i.e., parameters required below do not need to be passed, which is quite handy
@click.version_option("output", "--plugin-type", message="%(version)s", help="Show plugin type and exit.")
@click.version_option("0", "--plugin-api-version", message="%(version)s", help="Show plugin API version and exit")
# plugin-specific options
@click.option(
    "--appdir",
    type=click.Path(file_okay=False, dir_okay=True, resolve_path=True, path_type=Path),
    required=True,
    show_envvar=True,
)
@click.option("--build", multiple=True, type=click.Choice(["deb", "rpm"]), required=True, show_envvar=True)
@click.option("--sign", is_flag=True, default=False, show_envvar=True)
@click.option("--gpg-key", default=None, show_envvar=True)
@click.option("--debug", is_flag=True, default=False, envvar="DEBUG", show_envvar=True)
def main(build: Iterable[str], appdir: str | os.PathLike, sign: bool, gpg_key: str, debug: bool):
    set_up_logging(debug)

    for build_type in build:
        with TemporaryDirectory(prefix="ldnp-") as td:
            packager = make_packager(build_type, appdir, Path(td))

            out_name = packager.create_package("out")

            assert Path(out_name).is_file()

            if sign:
                packager.sign_package(gpg_key)


main(auto_envvar_prefix=ENV_VAR_PREFIX)
