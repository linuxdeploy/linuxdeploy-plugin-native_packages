import os
import sys

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable

import click

from .logging import set_up_logging, get_logger
from .context import Context
from .appdir import AppDir
from .deb import DebPackager
from .rpm import RpmPackager


def make_packager(
    build_type: str, appdir: AppDir, package_name: str, app_name: str, filename_prefix: str, context_path: Path
):
    context = Context(context_path)

    if build_type == "rpm":
        packager = RpmPackager(appdir, package_name, app_name, filename_prefix, context)

    elif build_type == "deb":
        packager = DebPackager(appdir, package_name, app_name, filename_prefix, context)

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
@click.option("--app-name", default=None, envvar="LINUXDEPLOY_OUTPUT_APP_NAME", show_envvar=True)
@click.option("--package-version", default=None, envvar="LINUXDEPLOY_OUTPUT_VERSION", show_envvar=True)
@click.option("--package-name", default=None, envvar="LDNP_PACKAGE_NAME", show_envvar=True)
@click.option("--description", default=None, envvar="LDNP_DESCRIPTION", show_envvar=True)
@click.option("--short-description", default=None, envvar="LDNP_SHORT_DESCRIPTION", show_envvar=True)
@click.option("--filename-prefix", default=None, envvar="LDNP_FILENAME_PREFIX", show_envvar=True)
def main(
    build: Iterable[str],
    appdir: str | os.PathLike,
    sign: bool,
    gpg_key: str,
    debug: bool,
    app_name: str,
    package_version: str,
    package_name: str,
    description: str,
    short_description: str,
    filename_prefix: str,
):
    set_up_logging(debug)

    logger = get_logger("main")

    appdir_instance = AppDir(appdir, "demo.AppDir")

    for build_type in build:
        with TemporaryDirectory(prefix="ldnp-") as td:
            if not package_name:
                package_name = appdir_instance.guess_package_name()

                if not package_name:
                    logger.critical("No package name provided and guessing failed")
                    sys.exit(2)

                logger.info(f"Using default package name {package_name}")

            if not app_name:
                app_name = package_name
                logger.info("Falling back to package name as the app's name")

            if not filename_prefix:
                logger.info("Using package name as filename prefix")
                filename_prefix = package_name

            packager = make_packager(build_type, appdir_instance, package_name, app_name, filename_prefix, Path(td))

            if not package_version:
                package_version = appdir_instance.guess_package_version()

            if not package_version:
                logger.warning("Could not guess package version")
            else:
                packager.set_version(package_version)

            if short_description and not description:
                logger.warning("No description provided, falling back to short description")
                description = short_description
            elif description and not short_description:
                logger.warning("No short description provided, falling back to description")
                short_description = description
            elif not description and not short_description:
                logger.warning("Neither description nor short description provided")

            if description:
                packager.set_description(description)

            if short_description:
                packager.set_short_description(short_description)

            # the correct filename suffix will be appended automatically if not specified
            # for now, we just build the package in the current working directory
            out_path = Path(os.getcwd()) / package_name

            if package_version:
                out_path = Path(f"{out_path}_{package_version}")

            logger.debug(f"Building package in {out_path}")

            out_name = packager.create_package(out_path)

            assert Path(out_name).is_file()

            logger.info(f"Build package {out_path}")

            if sign:
                logger.info(f"Signing package {out_path}")
                packager.sign_package(out_name, gpg_key)

    logger.info("Done!")


main(auto_envvar_prefix=ENV_VAR_PREFIX)
