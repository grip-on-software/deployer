"""
Frontend for accessing deployments and (re)starting them.
"""

from past.builtins import basestring
from builtins import object
import argparse
from hashlib import md5
import json
import logging.config
import os
import subprocess
import sys
import bigboat
import cherrypy
import cherrypy.daemon
import yaml
from requests.utils import quote
try:
    from mock import MagicMock
    sys.modules['abraxas'] = MagicMock()
    from sshdeploy.key import Key
except ImportError:
    raise
from gatherer.authentication import LoginException, Authentication
from gatherer.config import Configuration
from gatherer.domain import Source
from gatherer.git import Git_Repository
from gatherer.jenkins import Jenkins
from gatherer.log import Log_Setup

class Deployer(object):
    # pylint: disable=no-self-use
    """
    Deployer web interface.
    """

    # Fields in the deployment and their human-readable variant.
    FIELDS = [
        ("name", "Deployment name", str),
        ("git_path", "Git clone path", str),
        ("git_url", "Git repository URL", str),
        ("jenkins_job", "Jenkins job", str),
        ("deploy_key", "Keep deploy key", bool),
        ("services", "Systemctl service names", list),
        ("bigboat_url", "URL to BigBoat instance", str),
        ("bigboat_key", "API key of BigBoat instance", str),
        ("bigboat_compose", "Repository path to compose files", str)
    ]

    # Compose files for BigBoat
    FILES = [
        ('docker-compose.yml', 'dockerCompose'),
        ('bigboat-compose.yml', 'bigboatCompose')
    ]

    # Common HTML template
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

        auth_type = Authentication.get_type(args.auth)
        self.authentication = auth_type(args)

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
}
.success, .error {
    margin: auto 10rem auto 2rem;
    padding: 1rem 1rem 1rem 1rem;
    border-radius: 1rem;
    -webkit-box-shadow: 0 2px 3px rgba(10, 10, 10, 0.1), 0 0 0 1px rgba(10, 10, 10, 0.1);
    box-shadow: 0 2px 3px rgba(10, 10, 10, 0.1), 0 0 0 1px rgba(10, 10, 10, 0.1);
}
.success {
    border: 0.01rem solid #55ff55;
    background-color: #ccffcc;
}
.error {
    border: 0.01rem solid #ff5555;
    background-color: #ffcccc;
}
"""

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
                try:
                    result = self.authentication.validate(username, password)
                    logging.info('Authenticated as %s', username)
                    if isinstance(result, basestring):
                        cherrypy.session['authenticated'] = result
                    else:
                        cherrypy.session['authenticated'] = username
                except LoginException as error:
                    logging.info(str(error))
                    raise cherrypy.HTTPRedirect(redirect)
            else:
                raise cherrypy.HTTPError(400, 'POST only allowed for username and password')

        if 'authenticated' not in cherrypy.session:
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
                        {status}
                    </li>"""
            items = []
            for deployment in deployments:
                if self._is_up_to_date(deployment):
                    status = 'Up to date'
                else:
                    status = 'Outdated'

                items.append(item.format(deployment=deployment, status=status))

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

        services = kwargs.pop("services", '')
        deployment = {
            "name": name,
            "git_path": kwargs.pop("git_path", ''),
            "git_url": kwargs.pop("git_url", ''),
            "deploy_key": deploy_key,
            "jenkins_job": kwargs.pop("jenkins_job", ''),
            "services": services.split(',') if services != '' else [],
            "bigboat_url": kwargs.pop("bigboat_url", ''),
            "bigboat_key": kwargs.pop("bigboat_key", ''),
            "bigboat_compose": kwargs.pop("bigboat_compose", ''),
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

    def _check_jenkins(self, deployment, source):
        # Check build stability before deployment based on Jenkins job success.
        jenkins = Jenkins.from_config(self.config)
        job = jenkins.get_job(deployment["jenkins_job"])
        # Retrieve the latest build job. This may be a build for another
        # branch, so we check the builds by branch name on this build.
        # The job may have no builds in which case we cannot check stability.
        build = job.last_build
        if not build.exists:
            raise RuntimeError("Jenkins job or build could not be found")

        for action in build.data['actions']:
            if 'buildsByBranchName' in action:
                # Check if there has been a build for the master branch.
                if 'origin/master' not in action['buildsByBranchName']:
                    raise RuntimeError('Master branch build could not be found')

                # Retrieve the branches that were involved in this build.
                # Branch may be duplicated in case of merge strategies.
                # We only accept master branch builds if the latest build for
                # that branch not a merge request build, since the stability of
                # the master branch code is not demonstrated by this build.
                branch_build = action['buildsByBranchName']['origin/master']
                branch_data = branch_build['revision']['branch']
                branches = set([branch['name'] for branch in branch_data])
                if len(branches) > 1:
                    raise ValueError('Latest build is caused by merge request')

                # Check whether the revision that was built is actually the
                # upstream repository's HEAD commit for this branch.
                revision = branch_build['revision']['SHA1']
                if not Git_Repository.is_up_to_date(source, revision):
                    raise ValueError('Git repository HEAD is not {}'.format(revision))

                # Retrieve the build job that actually built the master branch.
                build_number = branch_build['buildNumber']
                if build_number != build.number:
                    build = job.get_build(build_number)

                break

        # Check whether the latest (branch) build is complete and successful.
        if build.building:
            raise ValueError("Build is not complete")
        if build.result != "SUCCESS":
            raise ValueError("Build result was not success, but {}".format(build.result))

    def _update_bigboat(self, deployment, repository):
        if deployment.get("bigboat_key", '') == '':
            raise ValueError("BigBoat API key required to update BigBoat")

        path = deployment.get("bigboat_compose", '')
        files = {}
        for filename, api_filename in self.FILES:
            full_filename = '{}/{}'.format(path, filename).lstrip('./')
            files[api_filename] = repository.get_contents(full_filename)

        compose = yaml.load(files['bigboatCompose'])
        client = bigboat.Client_v2(deployment["bigboat_url"],
                                   deployment["bigboat_key"])

        name = compose['name']
        version = compose['version']
        application = client.get_app(name, version)
        if application is None:
            logging.warning('Application %s version %s not on %s, creating.',
                            name, version, deployment['bigboat_url'])
            if client.update_app(name, version) is None:
                raise RuntimeError('Cannot register application')

        for api_filename, contents in files.items():
            if not client.update_compose(name, version, api_filename, contents):
                raise RuntimeError('Cannot update compose file')

        client.update_instance(name, name, version)

    def _is_up_to_date(self, deployment):
        try:
            source = self._get_source(deployment["name"], deployment)
        except ValueError:
            return False

        repo = Git_Repository(source, deployment["git_path"])
        if not repo.exists():
            return False

        return Git_Repository.is_up_to_date(source, repo.repo.head.commit)

    def _get_source(self, name, deployment=None):
        if deployment is None:
            deployment = self._find_deployment(name)

        if "git_url" not in deployment:
            raise ValueError("Cannot retrieve Git repository: misconfiguration")

        # Describe Git source repository
        source = Source.from_type('git', name=name, url=deployment["git_url"])
        source.credentials_path = deployment["deploy_key"]

        return source

    def _deploy(self, name):
        deployment = self._find_deployment(name)
        source = self._get_source(name, deployment)

        # Check Jenkins job success
        if deployment.get("jenkins_job", '') != '':
            self._check_jenkins(deployment, source)

        # Update Git repository using deploy key
        repository = Git_Repository.from_source(source, deployment["git_path"],
                                                checkout=True)

        logging.info('Updated repository %s', repository.repo_name)

        # Restart services
        for service in deployment["services"]:
            if service != '':
                subprocess.check_call(['sudo', 'systemctl', 'restart', service])

        # Update BigBoat dashboard applications
        if deployment.get("bigboat_url", '') != '':
            self._update_bigboat(deployment, repository)

    @cherrypy.expose
    def deploy(self, name):
        """
        Update the deployment based on the configuration.
        """

        self._validate_login()

        if cherrypy.request.method != 'POST':
            raise cherrypy.HTTPRedirect('list')

        try:
            self._deploy(name)
        except (RuntimeError, ValueError) as error:
            content = """
                <div class="error">
                    The deployment of {name} could not be updated completely.
                    The following error occurred: {error}.
                    You can <a href="list">return to the list</a>.
                </div>""".format(name=name, error=str(error))
        else:
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
    Log_Setup.add_argument(parser, default='INFO')
    parser.add_argument('--debug', action='store_true', default=False,
                        help='Display logging in terminal and traces on web')
    parser.add_argument('--log-path', dest='log_path', default='.',
                        help='Path to store logs at in production')
    parser.add_argument('--deploy-path', dest='deploy_path',
                        default='.', help='Path to deploy data')
    parser.add_argument('--auth', choices=Authentication.get_types(),
                        default='ldap', help='Authentication scheme')
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

    args = parse_args()
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
    cherrypy.tree.mount(Deployer(args), '/deploy', conf)
    cherrypy.daemon.start(daemonize=args.daemonize, pidfile=args.pidfile,
                          fastcgi=args.fastcgi, scgi=args.scgi, cgi=args.cgi)

if __name__ == '__main__':
    bootstrap()
