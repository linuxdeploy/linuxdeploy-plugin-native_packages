import os
import sys

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable

import click

from .abstractpackager import AbstractMetaInfo, AbstractPackager
from .logging import set_up_logging, get_logger
from .context import Context
from .appdir import AppDir
from .deb import DebPackager, DebMetaInfo
from .rpm import RpmPackager, RpmMetaInfo


def make_meta_info(build_type: str) -> AbstractMetaInfo:
    if build_type == "rpm":
        meta_info = RpmMetaInfo()

    elif build_type == "deb":
        meta_info = DebMetaInfo()

    else:
        raise KeyError(f"cannot create packager for unknown build type {build_type}")

    return meta_info


def make_packager(build_type: str, appdir: AppDir, meta_info: AbstractMetaInfo, context_path: Path) -> AbstractPackager:
    context = Context(context_path)

    if build_type == "rpm":
        packager = RpmPackager(appdir, meta_info, context)

    elif build_type == "deb":
        packager = DebPackager(appdir, meta_info, context)

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
# compatibility with linuxdeploy output plugin spec flags, plugin-specific environment variables will always take
# precedence
@click.option("--app-name", default=None, envvar="LINUXDEPLOY_OUTPUT_APP_NAME", show_envvar=True)
@click.option("--package-version", default=None, envvar="LINUXDEPLOY_OUTPUT_VERSION", show_envvar=True)
def main(
    build: Iterable[str],
    appdir: str | os.PathLike,
    sign: bool,
    gpg_key: str,
    debug: bool,
    app_name: str,
    package_version: str,
):
    set_up_logging(debug)

    logger = get_logger("main")

    appdir_instance = AppDir(appdir)

    if not package_version:
        try:
            package_version = appdir_instance.guess_package_version()
        except ValueError:
            logger.critical("Could not guess version and user did not specify one")
            sys.exit(2)

    logger.info(f"Package version: {package_version}")

    for build_type in build:
        meta_info = make_meta_info(build_type)
        meta_info["version"] = package_version

        if app_name and not meta_info.get("package_name"):
            logger.info(f"Using user-provided linuxdeploy output app name as package name: {app_name}")
            meta_info["package_name"] = app_name
        elif meta_info.get("package_name"):
            logger.info(f"Using user-provided package name: {meta_info['package_name']}")
        else:
            guessed_package_name = appdir_instance.guess_package_name()

            if not guessed_package_name:
                logger.critical("No package name provided and guessing failed")
                sys.exit(2)

            meta_info["package_name"] = guessed_package_name
            logger.info(f"Guessed package name {meta_info['package_name']}")

        if not meta_info.get("filename_prefix"):
            logger.info("Using package name as filename prefix")
            meta_info["filename_prefix"] = meta_info["package_name"]

        with TemporaryDirectory(prefix="ldnp-") as td:
            packager = make_packager(build_type, appdir_instance, meta_info, Path(td))

            description = meta_info.get("description")
            short_description = meta_info.get("short_description")

            if short_description and not description:
                logger.warning("No description provided, falling back to short description")
                description = short_description
            elif description and not short_description:
                logger.warning("No short description provided, falling back to description")
                short_description = description
            elif not description and not short_description:
                logger.warning("Neither description nor short description provided")

            if description:
                meta_info["description"] = description

            if short_description:
                meta_info["short_description"] = short_description

            # the correct filename suffix will be appended automatically if not specified
            # for now, we just build the package in the current working directory
            out_path = Path(os.getcwd()) / meta_info["package_name"]

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
