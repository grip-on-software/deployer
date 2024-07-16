GROS deployment interface
=========================

[![PyPI](https://img.shields.io/pypi/v/gros-deployer.svg)](https://pypi.python.org/pypi/gros-deployer)
[![Build 
status](https://github.com/grip-on-software/deployer/actions/workflows/status-tests.yml/badge.svg)](https://github.com/grip-on-software/deployer/actions/workflows/status-tests.yml)
[![Coverage 
Status](https://coveralls.io/repos/github/grip-on-software/deployer/badge.svg?branch=master)](https://coveralls.io/github/grip-on-software/deployer?branch=master)
[![Quality Gate
Status](https://sonarcloud.io/api/project_badges/measure?project=grip-on-software_deployer&metric=alert_status)](https://sonarcloud.io/project/overview?id=grip-on-software_deployer)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.12571035.svg)](https://doi.org/10.5281/zenodo.12571035)

This repository contains a Web application that provides a management interface 
for application deployments using a quality gate.

## Installation

The latest version of the GROS deployment interface and its dependencies can be 
installed using `pip install gros-deployer`.

Another option is to build the module from this repository, which allows using 
the most recent development code. Run `make setup` to install the dependencies. 
The deployment interface itself may then be installed with `make install`, 
which places the package in your current environment. We recommend using 
a virtual environment during development.

## Running

Simply start the application using `gros-deployer`. Use command-line arguments 
(displayed with `gros-deployer --help`) and/or a data-gathering `settings.cfg` 
file (specifically the sections `ldap`, `deploy` and `jenkins` influence this 
application's behavior - see the [gros-gatherer documentation on 
configuration](https://gros.liacs.nl/data-gathering/configuration.html) for 
details).

You can also configure the application as a `systemd` service such that it can 
run headless under a separate user, using a `virtualenv` setup shared with the 
[controller](https://gros.liacs.nl/data-gathering/api.html#controller-api) of 
the agent-based data gathering setup. See the `gros-deployer.service` file in 
this repository for a possible setup (using a `deployer` user and group) and 
[installation](https://gros.liacs.nl/data-gathering/installation.html#controller) 
of the controller for some pointers in this advanced setup.

For the option to restart a `systemd` service when a deployment is updated, the 
user running the application must have `sudo` rights to execute at least the 
`systemctl` binary.

## Development and testing

To run tests, first install the test dependencies with `make setup_test` which 
also installs all dependencies for the server framework. Then `make coverage` 
provides test results in the output and in XML versions compatible with, e.g., 
JUnit and SonarQube available in the `test-reports/` directory. If you do not 
need XML outputs, then run `make test` to just report on test successes and 
failures or `make cover` to also have the terminal report on hits and misses in 
statements and branches.

[GitHub Actions](https://github.com/grip-on-software/deployer/actions) 
is used to run the unit tests and report on coverage on commits and pull 
requests. This includes quality gate scans tracked by 
[SonarCloud](https://sonarcloud.io/project/overview?id=grip-on-software_deployer) 
and [Coveralls](https://coveralls.io/github/grip-on-software/deployer) for 
coverage history.

The Python module conforms to code style and typing standards which can be 
checked using Pylint with `make pylint` and mypy with `make mypy`, after 
installing the pylint and mypy dependencies using `make setup_analysis`; typing 
reports are XML formats compatible with JUnit and SonarQube placed in the 
`mypy-report/` directory. To also receive the HTML report, use `make mypy_html` 
instead.

We publish releases to [PyPI](https://pypi.org/project/gros-deployer/) using 
`make setup_release` to install dependencies and `make release` which performs 
multiple checks: unit tests, typing, lint and version number consistency. The 
release files are also published on 
[GitHub](https://github.com/grip-on-software/deployer/releases) and from there 
are archived on [Zenodo](https://zenodo.org/doi/10.5281/zenodo.12571034). 
Noteworthy changes to the module are added to the [changelog](CHANGELOG.md).

## License

GROS deployment interface is licensed under the Apache 2.0 License.
