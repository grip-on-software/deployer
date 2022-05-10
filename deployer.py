"""
Entry point for the deployer Web service.

Copyright 2017-2020 ICTU
Copyright 2017-2022 Leiden University

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

import cherrypy
from server.bootstrap import Bootstrap
from deployment import Deployer

class Bootstrap_Deployer(Bootstrap):
    """
    Bootstrapper for the deployment interface.
    """

    @property
    def application_id(self):
        return 'deployer'

    @property
    def description(self):
        return 'Run deployment WSGI server'

    def add_args(self, parser):
        parser.add_argument('--deploy-path', dest='deploy_path',
                            default='.', help='Path to deploy data')

    def mount(self, conf):
        cherrypy.tree.mount(Deployer(self.args, self.config), '/deploy', conf)

def main():
    """
    Main entry point.
    """

    bootstrap = Bootstrap_Deployer()
    bootstrap.bootstrap()

if __name__ == '__main__':
    main()
