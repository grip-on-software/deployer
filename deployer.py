"""
Frontend for accessing deployments and (re)starting them.
"""

import argparse
from hashlib import md5
import json
import logging.config
import os
import subprocess
import sys
import cherrypy
import ldap
from requests.utils import quote
try:
    from mock import MagicMock
    sys.modules['abraxas'] = MagicMock()
    from sshdeploy.key import Key
except ImportError:
    raise
from gatherer.config import Configuration
from gatherer.domain import Source
from gatherer.git import Git_Repository

class Deployer(object):
    # pylint: disable=no-self-use
    """
    Deployer web interface.
    """

    FIELDS = [
        ("name", "Deployment name", str),
        ("git_path", "Git clone path", str),
        ("git_url", "Git repository URL", str),
        ("deploy_key", "Keep deploy key", bool),
        ("services", "Systemctl service names", list)
    ]

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
        self.config = Configuration.get_settings()
        self.deploy_filename = os.path.join(self.args.deploy_path,
                                            'deployment.json')
        self.group = self._retrieve_ldap_group()

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

        content = """
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
}
pre {
    overflow-x: auto;
}"""

        cherrypy.response.headers['Content-Type'] = 'text/css'
        cherrypy.response.headers['ETag'] = md5(content).hexdigest()

        cherrypy.lib.cptools.validate_etags()

        return content

    @cherrypy.expose
    def logout(self):
        """
        Log out the user.
        """

        cherrypy.session.pop('authenticated', None)
        cherrypy.lib.sessions.expire()

        raise cherrypy.HTTPRedirect('index')

    def _retrieve_ldap_group(self):
        logging.info('Retrieving LDAP group list using manager DN...')
        group_attr = self.config.get('ldap', 'group_attr')
        result = self._query_ldap(self.config.get('ldap', 'manager_dn'),
                                  self.config.get('ldap', 'manager_password'),
                                  search=self.config.get('ldap', 'group_dn'),
                                  search_attrs=[str(group_attr)])[0][1]
        return result[group_attr]

    def _query_ldap(self, username, password, search=None, search_attrs=None):
        client = ldap.initialize(self.config.get('ldap', 'server'))
        # Synchronous bind
        client.set_option(ldap.OPT_REFERRALS, 0)

        try:
            client.simple_bind_s(username, password)
            if search is not None:
                return client.search_s(self.config.get('ldap', 'root_dn'),
                                       ldap.SCOPE_SUBTREE, search,
                                       search_attrs)

            return True
        except ldap.INVALID_CREDENTIALS:
            return False
        finally:
            client.unbind()

        return True

    def _validate_ldap(self, username, password):
        # Pre-check: user in group?
        if username not in self.group:
            logging.info('User %s not in group', username)
            return False

        # Next check: get DN from uid
        search = self.config.get('ldap', 'search_filter').format(username)
        display_name_field = str(self.config.get('ldap', 'display_name'))
        result = self._query_ldap(self.config.get('ldap', 'manager_dn'),
                                  self.config.get('ldap', 'manager_password'),
                                  search=search,
                                  search_attrs=[display_name_field])[0]

        # Retrieve DN and display name
        login_name = result[0]
        display_name = result[1][display_name_field][0]

        # Final check: log in
        if self._query_ldap(login_name, password):
            logging.info('Authenticated as {}'.format(username))
            cherrypy.session['authenticated'] = display_name
            return True

        logging.info('Credentials invalid')
        return False

    def _validate_login(self, username=None, password=None, page=None,
                        params=None):
        if page is None:
            page = cherrypy.request.path_info.strip('/')

        if params is None:
            params = quote(cherrypy.request.query_string)

        redirect = 'index?page={}'.format(page)
        if params != '' and page != '':
            redirect += '&params={}'.format(params)

        if username is not None or password is not None:
            if cherrypy.request.method == 'POST':
                if not self._validate_ldap(username, password):
                    raise cherrypy.HTTPRedirect(redirect)
            else:
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
        self._validate_login(username=username, password=password, page=page,
                             params=params)

        if params != '':
            page += '?' + params
        raise cherrypy.HTTPRedirect(page)

    def _read(self):
        if os.path.exists(self.deploy_filename):
            with open(self.deploy_filename) as deploy_file:
                return json.load(deploy_file)
        else:
            return []

    def _write(self, deployments):
        with open(self.deploy_filename, 'w') as deploy_file:
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

    def _format_fields(self, deployment, **excluded):
        form = ''
        for field_name, display_name, field_type in self.FIELDS:
            if field_name in excluded:
                continue

            value = deployment.get(field_name, '')
            input_type = 'text'
            props = ''
            if issubclass(field_type, list):
                value = ','.join(value)
            elif issubclass(field_type, bool):
                if value != '':
                    props += ' checked'

                value = '1'
                input_type = 'checkbox'

            form += """
                <label>
                    {display_name}:
                    <input type="{input_type}" name="{field_name}" value="{value}"{props}>
                </label>""".format(display_name=display_name,
                                   input_type=input_type,
                                   field_name=field_name,
                                   value=value, props=props)

        return form

    def _generate_deploy_key(self, name):
        data = {
            'purpose': 'deploy key for {}'.format(name),
            'keygen-options': '',
            'abraxas-account': False,
            'servers': {},
            'clients': {}
        }
        update = []
        key_file = os.path.join(self.args.deploy_path, 'key-{}'.format(name))
        key = Key(key_file, data, update, {}, False)
        key.generate()
        return key.keyname

    def _create_deployment(self, name, kwargs, deploy_key=None,
                           deployments=None):
        if deployments is None:
            deployments = self._read()

        if any(deployment["name"] == name for deployment in deployments):
            raise ValueError("Deployment '{}' already exists".format(name))

        if deploy_key is None:
            deploy_key = self._generate_deploy_key(name)

        deployment = {
            "name": name,
            "git_path": kwargs.pop("git_path", ''),
            "git_url": kwargs.pop("git_url", ''),
            "deploy_key": deploy_key,
            "services": kwargs.pop("services", '').split(',')
        }
        deployments.append(deployment)
        self._write(deployments)
        with open('{}.pub'.format(deploy_key), 'r') as public_key_file:
            public_key = public_key_file.read()

        return deployment, public_key

    @cherrypy.expose
    def create(self, name='', **kwargs):
        """
        Create a new deployment using a form or handle the form submission.
        """

        self._validate_login()

        if cherrypy.request.method == 'POST':
            public_key = self._create_deployment(name, kwargs)[1]

            success = """<div class="success">
                The deployment has been created. The new deploy key's public
                part is shown below. Register this key in the GitLab repository.
                You can <a href="edit?name={name}">edit the deployment</a>,
                <a href="list">go to the list</a> or create a new deployment.
            </div>
            <pre>{deploy_key}</pre>""".format(name=name, deploy_key=public_key)
        else:
            success = ''

        content = """
            {session}
            {success}
            <form class="edit" action="create" method="post">
                {form}
                <button>Update</button>
            </form>""".format(session=self._get_session_html(), success=success,
                              form=self._format_fields({}, deploy_key=False))
        return self.COMMON_HTML.format(title='Create', content=content)

    @cherrypy.expose
    def edit(self, name=None, old_name=None, **kwargs):
        """
        Display an existing deployment configuration in an editable form, or
        handle the form submission to update the deployment.
        """

        self._validate_login()
        if name is None:
            raise cherrypy.HTTPError(404, "Missing parameter 'name'")

        deployments = self._read()

        if cherrypy.request.method == 'POST':
            old_deployment = self._find_deployment(old_name,
                                                   deployments=deployments)
            deployments.remove(old_deployment)
            if kwargs.pop("deploy_key"):
                deploy_key = old_deployment.get("deploy_key", '')
                state = 'original'
            else:
                deploy_key = None
                state = 'new'
                if os.path.exists(old_deployment.get("deploy_key", '')):
                    os.remove(old_deployment.get("deploy_key", ''))

            deployment, public_key = \
                self._create_deployment(name, kwargs, deploy_key=deploy_key,
                                        deployments=deployments)

            success = """<div class="success">
                The deployment has been updated. The {state} deploy key's public
                part is shown below. Ensure that this key exists in the GitLab
                repository. You can edit the deployment configuration again or
                <a href="list">go to the list</a>.
            </div>
            <pre>{deploy_key}</pre>""".format(state=state,
                                              deploy_key=public_key)
        else:
            success = ''
            deployment = self._find_deployment(name)

        form = """<input type="hidden" name="old_name" value="{name}">""".format(name=name)
        form += self._format_fields(deployment)

        content = """
            {session}
            {success}
            <form class="edit" action="edit" method="post">
                {form}
                <button>Update</button>
            </form>""".format(session=self._get_session_html(), success=success,
                              form=form)
        return self.COMMON_HTML.format(title='Edit', content=content)

    @cherrypy.expose
    def deploy(self, name):
        """
        Update the deployment based on the configuration.
        """

        self._validate_login()

        if cherrypy.request.method != 'POST':
            raise cherrypy.HTTPRedirect('list')

        deployment = self._find_deployment(name)

        if "git_url" not in deployment:
            raise ValueError("Cannot retrieve Git repository: misconfiguration")

        # Update Git repository using deploy key
        source = Source.from_type('git', name=name, url=deployment["git_url"])
        source.credentials_path = deployment["deploy_key"]
        repository = Git_Repository.from_source(source, deployment["git_path"],
                                                checkout=True)

        logging.info('Updated repository %s', repository.repo_name)

        # Restart services
        for service in deployment["services"]:
            subprocess.check_call(['sudo', 'systemctl', 'restart', service])

        content = """
            <div class="success">
                The deployment of {name} has been updated.
                You can <a href="list">return to the list</a>.
            </div>""".format(name=name)

        return self.COMMON_HTML.format(title='Deploy', content=content)

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
                        default='.', help='Path to deploy data')
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
