GROS deployment interface
=========================

This repository contains a Web application that provides a management interface 
for application deployments using a quality gate.

## Installation

Run `pip install -r requirements.txt` to install the dependencies. Add `--user` 
if you do not have access to the system libraries, or make use of `virtualenv`.
You may need to add additional parameters, such as `--extra-index-url` for 
a private repository.

## Running

Simply start the application using `python deployer.py`. Use command-line 
arguments (displayed with `python deployer.py --help`) and/or a data-gathering 
`settings.cfg` file (see the gros-gatherer documentation for details).

You can also configure the application as a systemd service such that it can 
run headless under a separate user, using a virtualenv setup. See 
`gros-deployer.service` for details.
