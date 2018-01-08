"""
Entry point for the deployer Web service.
"""

import argparse
import logging
import os
import cherrypy
from deployment import Deployer
from gatherer.authentication import Authentication
from gatherer.config import Configuration
from gatherer.log import Log_Setup

def parse_args(config):
    """
    Parse command line arguments.
    """

    # Default authentication scheme
    auth = config.get('deploy', 'auth')
    if not Configuration.has_value(auth):
        auth = 'ldap'

    parser = argparse.ArgumentParser(description='Run deployment WSGI server')
    Log_Setup.add_argument(parser, default='INFO')
    parser.add_argument('--debug', action='store_true', default=False,
                        help='Display logging in terminal and traces on web')
    parser.add_argument('--log-path', dest='log_path', default='.',
                        help='Path to store logs at in production')
    parser.add_argument('--deploy-path', dest='deploy_path',
                        default='.', help='Path to deploy data')
    parser.add_argument('--auth', choices=Authentication.get_types(),
                        default=auth, help='Authentication scheme')
    parser.add_argument('--port', type=int, default=8080,
                        help='Port for the server to listen on')
    parser.add_argument('--daemonize', action='store_true', default=False,
                        help='Run the server as a daemon')
    parser.add_argument('--pidfile', help='Store process ID in file')

    server = parser.add_mutually_exclusive_group()
    server.add_argument('--fastcgi', action='store_true', default=False,
                        help='Start a FastCGI server instead of HTTP')
    server.add_argument('--scgi', action='store_true', default=False,
                        help='Start a SCGI server instead of HTTP')
    server.add_argument('--cgi', action='store_true', default=False,
                        help='Start a CGI server instead of the HTTP')
    return parser.parse_args()

def setup_log(debug=False, log_level='INFO', log_path='.'):
    """
    Setup logging.
    """

    stream_handler = {
        'level': log_level,
        'class':'logging.StreamHandler',
        'formatter': 'standard',
        'stream': 'ext://sys.stdout'
    }
    file_handler = {
        'level': log_level,
        'class': 'logging.handlers.RotatingFileHandler',
        'formatter': 'void',
        'maxBytes': 10485760,
        'backupCount': 20,
        'encoding': 'utf8'
    }

    config = {
        'version': 1,
        'formatters': {
            'void': {
                'format': ''
            },
            'standard': {
                'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            },
        },
        'handlers': {
            'default': stream_handler.copy(),
            'cherrypy_console': stream_handler.copy(),
            'cherrypy_access': dict(filename=os.path.join(log_path, 'access.log'),
                                    **file_handler),
            'cherrypy_error': dict(filename=os.path.join(log_path, 'error.log'),
                                   **file_handler),
            'python': dict(filename=os.path.join(log_path, 'python.log'),
                           **file_handler)
        },
        'loggers': {
            '': {
                'handlers': ['default' if debug else 'python'],
                'level': log_level
            },
            'cherrypy.access': {
                'handlers': ['cherrypy_console' if debug else 'cherrypy_access'],
                'level': log_level,
                'propagate': False
            },
            'cherrypy.error': {
                'handlers': ['cherrypy_console' if debug else 'cherrypy_error'],
                'level': log_level,
                'propagate': False
            },
        }
    }
    logging.config.dictConfig(config)

def bootstrap():
    """
    Start the WSGI server.
    """

    # Setup arguments and deployment-specific configuration
    config = Configuration.get_settings()
    args = parse_args(config)
    setup_log(debug=args.debug, log_level=args.log, log_path=args.log_path)
    conf = {
        'global': {
            'request.show_tracebacks': args.debug
        },
        '/': {
            'tools.sessions.on': True
        }
    }
    cherrypy.config.update({'server.socket_port': args.port})

    # Start the application and server daemon.
    cherrypy.tree.mount(Deployer(args, config), '/deploy', conf)
    cherrypy.daemon.start(daemonize=args.daemonize, pidfile=args.pidfile,
                          fastcgi=args.fastcgi, scgi=args.scgi, cgi=args.cgi)

if __name__ == '__main__':
    bootstrap()
