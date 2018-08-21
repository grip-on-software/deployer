"""
Entry point for the deployer Web service.
"""

import cherrypy
from deployment import Deployer
from server.bootstrap import Bootstrap

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
