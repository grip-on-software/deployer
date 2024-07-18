# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) 
and we adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2024-07-16

### Added

- Unit tests for `application`, `bootstrap`, `deployment` and `task` modules 
  added.

### Changed

- Dependency for `mock` package dropped in favor of standard `unittest.mock`.

### Fixed

- The `deploy` endpoint now correctly checks for missing `name` parameter.
- The `edit` endpoint now looks up deployments using the `old_name` parameter 
  if it is given instead of `name`, such that the form is properly reloaded 
  with the unchanged state if the user is logged out when attempting to submit.

## [0.0.3] - 2024-06-27

### Added

- Initial release of version as used during the GROS research project. 
  Previously, versions were rolling releases based on Git commits.

### Fixed

- Missing dependencies added.

### Removed

- Support for Python 2.7 dropped.

[Unreleased]: 
https://github.com/grip-on-software/deployer/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/grip-on-software/deployer/compare/v0.0.3...v1.0.0
[0.0.3]: https://github.com/grip-on-software/deployer/releases/tag/v0.0.3
