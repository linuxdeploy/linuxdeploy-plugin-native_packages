# linuxdeploy-plugin-native_packages

This output plugin for [linuxdeploy](https://github.com/linuxdeploy/linuxdeploy/) lets users package [AppDirs](https://docs.appimage.org/reference/appdir.html) into `.deb` and `.rpm`, i.e., distribution-native packages.


## Parameters

As a linuxdeploy plugin, this software provides the parameters mandated by the [linuxdeploy plugin system](https://github.com/linuxdeploy/linuxdeploy/wiki/Plugin-system), i.e., `--plugin-type`, `--plugin-api-version` and `--appdir`.

The plugin supports the new, standardized output plugin environment variables:

- `LINUXDEPLOY_OUTPUT_APP_NAME`: Application name. Used in the resulting output filename and in the package metadata if not customized.
- `LINUXDEPLOY_OUTPUT_VERSION`: Application version, used in the filename and the package metadata.

Additionally, the following environment variables are supported:

- `LDNP_DESCRIPTION`: Optional package description for the package's metadata.
- `LDNP_SHORT_DESCRIPTION`: Optional short package description for the package's metadata.
- `LDNP_PACKAGE_NAME`: The package name to be configured in the metadata. If this is not set, the app name is used.
- `LDNP_FILENAME_PREFIX`: By default, the package name is used. If this is insufficient, a custom value can be specified.
