"""
Frontend for accessing deployments and (re)starting them.
"""

import argparse
import json
import logging.config
import os
import cherrypy
from requests.utils import quote

class Deployer(object):
    # pylint: disable=no-self-use
    """
    Deployer web interface.
    """

    COMMON_HTML = """<!doctype html>
<html>
    <head>
        <meta charset="utf-8">
        <title>{title} - Deployment</title>
        <link rel="stylesheet" href="css">
    </head>
    <body>
        <h1>Deployment: {title}</h1>
        <div class="content">
            {content}
        </div>
    </body>
</html>"""

    def __init__(self, args):
        self.args = args

    def _validate_page(self, page):
        try:
            getattr(self, page).exposed
        except AttributeError:
            # Invalid method or not exposed
            raise cherrypy.HTTPError(400, 'Page must be valid')

    @cherrypy.expose
    def index(self, page='list', params=''):
        """
        Login page.
        """

        self._validate_page(page)

        form = """
            <form class="login" method="post" action="login?page={page}&amp;params={params}">
                <label>
                    Username: <input type="text" name="username" autofocus>
                </label>
                <label>
                    Password: <input type="password" name="password">
                </label>
                <button type="submit">Login</button>
            </form>""".format(page=page, params=quote(params))

        return self.COMMON_HTML.format(title='Login', content=form)

    @cherrypy.expose
    def css(self):
        """
        Serve CSS.
        """

        cherrypy.response.headers['Content-Type'] = 'text/css'

        return """
body {
  font-family: -apple-system, "Segoe UI", "Roboto", "Ubuntu", "Droid Sans", "Helvetica Neue", "Helvetica", "Arial", sans-serif;
}
.content {
    margin: auto 20rem auto 20rem;
    padding: 2rem 2rem 2rem 10rem;
    border: 0.01rem solid #aaa;
    border-radius: 1rem;
    -webkit-box-shadow: 0 2px 3px rgba(10, 10, 10, 0.1), 0 0 0 1px rgba(10, 10, 10, 0.1);
    box-shadow: 0 2px 3px rgba(10, 10, 10, 0.1), 0 0 0 1px rgba(10, 10, 10, 0.1);
    text-align: left;
}
form.login {
    max-width: 60%;
    text-align: center;
}
form.login label, form.edit label {
    display: block;
}
form.login label {
    text-align: right;
}
button {
    border: none;
    font-size: 90%;
    padding: 0.5rem;
    background-color: #99ff99;
    transition: background-color 0.2s linear;
}
button:active,
button:hover {
    background-color: #00ff00;

}
button::-moz-focus-inner {
    border: 0;
}
button:active, button:focus {
    outline: 0.01rem dashed #777;
    text-decoration: none;
}
button a {
    color: #000;
    text-decoration: none;
}
.logout {
    text-align: right;
    font-size: 90%;
    color: #777;
}
.logout a {
    color: #5555ff;
}
.logout a:hover {
    color: #ff5555;
}"""

    @cherrypy.expose
    def logout(self):
        """
        Log out the user.
        """

        cherrypy.session.pop('authenticated', None)
        cherrypy.lib.sessions.expire()

        raise cherrypy.HTTPRedirect('index')

    @staticmethod
    def _validate_login(username=None, password=None, page=None):
        if page is None:
            page = cherrypy.request.path_info.strip('/')

        params = quote(cherrypy.request.query_string)
        redirect = 'index?page={}&params={}'.format(page, params)
        if cherrypy.request.method == 'POST':
            if username == 'a' and password == 'b':
                cherrypy.session['authenticated'] = 'a'
            else:
                logging.info('Credentials invalid')
                raise cherrypy.HTTPRedirect(redirect)
        elif username is not None or password is not None:
            raise cherrypy.HTTPError(400, 'POST only allowed for username and password')
        elif 'authenticated' not in cherrypy.session:
            logging.info('No credentials or session found')
            raise cherrypy.HTTPRedirect(redirect)

    @cherrypy.expose
    def login(self, username=None, password=None, page='list', params=''):
        """
        Log in the user.
        """

        self._validate_page(page)
        self._validate_login(username=username, password=password, page=page)

        if params != '':
            page += '?' + params
        raise cherrypy.HTTPRedirect(page)

    def _read(self):
        if os.path.exists(self.args.deploy_path):
            with open(self.args.deploy_path) as deploy_file:
                return json.load(deploy_file)
        else:
            return []

    def _write(self, deployments):
        with open(self.args.deploy_path, 'w') as deploy_file:
            json.dump(deployments, deploy_file)

    @staticmethod
    def _get_session_html():
        return """
            <div class="logout">
                {user} - <a href="logout">Logout</a>
            </div>""".format(user=cherrypy.session['authenticated'])

    @cherrypy.expose
    def list(self):
        """
        List deployments.
        """

        self._validate_login()

        deployments = self._read()
        content = self._get_session_html()
        if not deployments:
            content += """
            <p>No deployments found - <a href="create">create one</a>
            """
        else:
            item = """
                    <li>
                        {deployment[name]}
                        <button formaction="deploy" name="name" value="{deployment[name]}" formmethod="post">Deploy</button>
                        <button formaction="edit" name="name" value="{deployment[name]}">Edit</button>
                    </li>"""
            items = [
                item.format(deployment=deployment)
                for deployment in deployments
            ]
            content += """
            <form>
                <ul class="items">
                    {items}
                </ul>
                <p><button formaction="create">Create</button></p>
            </form>""".format(items='\n'.join(items))

        return self.COMMON_HTML.format(title='List', content=content)

    def _find_deployment(self, name, deployments=None):
        if deployments is None:
            deployments = self._read()

        deployment = None
        for deployment in deployments:
            if deployment["name"] == name:
                return deployment

        raise cherrypy.HTTPError(404, 'Deployment {} does not exist'.format(name))

    def _format_fields(self, deployment, fields):
        form = ''
        for field_name, display_name, field_type in fields:
            value = deployment.get(field_name, '')
            input_type = 'text'
            if issubclass(field_type, list):
                value = ','.join(value)
            elif issubclass(field_type, bool):
                value = '1' if value != '' else '0'
                input_type = 'checkbox'

            form += """
                <label>
                    {display_name}:
                    <input type="{input_type}" name="{field_name}" value="{value}">
                </label>""".format(display_name=display_name,
                                   input_type=input_type,
                                   field_name=field_name,
                                   value=value)

        return form

    @cherrypy.expose
    def edit(self, name, old_name=None, **kwargs):
        """
        Display single deployment configuration.
        """

        self._validate_login()
        deployments = self._read()

        if cherrypy.request.method == 'POST':
            old_deployment = self._find_deployment(old_name)
            deployments = [
                deploy for deploy in deployments if deploy["name"] != old_name
            ]
            if kwargs.pop("deploy_key"):
                deploy_key = old_deployment.get("deploy_key", '')
            else:
                deploy_key = ''
            deployment = {
                "name": name,
                "git_path": kwargs.pop("git_path", ''),
                "deploy_key": deploy_key,
                "services": kwargs.pop("services", '').split(',')
            }
            deployments.append(deployment)
            self._write(deployments)
            success = '<p>The deployment has been updated - <a href="list">back to list</p>'
        else:
            success = ''
            deployment = self._find_deployment(name)

        fields = [
            ("name", "Deployment name", str),
            ("git_path", "Git clone path", str),
            ("deploy_key", "Keep deploy key", bool),
            ("services", "Systemctl service names", list)
        ]
        form = """<input type="hidden" name="old_name" value="{name}">""".format(name=name)
        form += self._format_fields(deployment, fields)

        content = """
            {session}
            {success}
            <form class="edit" action="edit" method="post">
                {form}
                <button>Update</button>
            </form>""".format(session=self._get_session_html(), success=success,
                              form=form)
        return self.COMMON_HTML.format(title='Edit', content=content)

def parse_args():
    """
    Parse command line arguments.
    """

    parser = argparse.ArgumentParser(description='Run deployment WSGI server')
    parser.add_argument('--debug', action='store_true', default=False,
                        help='Display logging in terminal')
    parser.add_argument('--log-path', dest='log_path', default='.',
                        help='Path to store logs at in production')
    parser.add_argument('--deploy-path', dest='deploy_path',
                        default='deployment.json', help='Path to deploy data')
    return parser.parse_args()

def setup_log(debug=False, log_path='.'):
    """
    Setup logging.
    """

    stream_handler = {
        'level':'INFO',
        'class':'logging.StreamHandler',
        'formatter': 'standard',
        'stream': 'ext://sys.stdout'
    }
    file_handler = {
        'level':'INFO',
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
                'level': 'INFO'
            },
            'cherrypy.access': {
                'handlers': ['cherrypy_console' if debug else 'cherrypy_access'],
                'level': 'INFO',
                'propagate': False
            },
            'cherrypy.error': {
                'handlers': ['cherrypy_console' if debug else 'cherrypy_error'],
                'level': 'INFO',
                'propagate': False
            },
        }
    }
    logging.config.dictConfig(config)

def bootstrap():
    """
    Start the WSGI server.
    """

    args = parse_args()
    setup_log(args.debug, args.log_path)
    conf = {
        'global': {
            'request.show_tracebacks': args.debug
        },
        '/': {
            'tools.sessions.on': True
        }
    }
    cherrypy.quickstart(Deployer(args), '/deploy', conf)

if __name__ == '__main__':
    bootstrap()
