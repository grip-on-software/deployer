"""
Module for bootstrapping the deployer Web service.

Copyright 2017-2020 ICTU
Copyright 2017-2022 Leiden University
Copyright 2017-2024 Leon Helwerda

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from argparse import ArgumentParser
from typing import Any, Dict
import cherrypy
from server.bootstrap import Bootstrap
from .application import Deployer

class Bootstrap_Deployer(Bootstrap):
    """
    Bootstrapper for the deployment interface.
    """

    @property
    def application_id(self) -> str:
        return 'deployer'

    @property
    def description(self) -> str:
        return 'Run deployment WSGI server'

    def add_args(self, parser: ArgumentParser) -> None:
        parser.add_argument('--deploy-path', dest='deploy_path',
                            default='.', help='Path to deploy data')

    def mount(self, conf: Dict[str, Dict[str, Any]]) -> None:
        cherrypy.tree.mount(Deployer(self.args, self.config), '/deploy', conf)
