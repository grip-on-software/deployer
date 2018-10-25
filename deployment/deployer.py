"""
Frontend for accessing deployments and (re)starting them.
"""

try:
    from future import standard_library
    standard_library.install_aliases()
except ImportError:
    raise

from collections import OrderedDict
from hashlib import md5
try:
    from itertools import zip_longest
except ImportError:
    raise
import logging
import logging.config
import os
import sys
import cherrypy
try:
    from mock import MagicMock
    sys.modules['abraxas'] = MagicMock()
    from sshdeploy.key import Key
except ImportError:
    raise
from server.application import Authenticated_Application
from server.template import Template
from .deployment import Deployments
from .task import Deploy_Task

class Deployer(Authenticated_Application):
    # pylint: disable=no-self-use
    """
    Deployer web interface.
    """

    # Fields in the deployment and their human-readable variant.
    FIELDS = [
        ("name", "Deployment name", {"type": "str"}),
        ("git_path", "Git clone path", {"type": "str"}),
        ("git_url", "Git repository URL", {"type": "str"}),
        ("git_branch", "Git branch to check out", {
            "type": "str",
            "default": "master"
        }),
        ("jenkins_job", "Jenkins job", {"type": "str"}),
        ("jenkins_git", "Check build staleness against Git repository", {
            "type": "bool",
            "default": True
        }),
        ("jenkins_states", "Build results to consider successful", {
            "type": "list",
            "default": ["SUCCESS"]
        }),
        ("artifacts", "Add job artifacts to deployment", {"type": "bool"}),
        ("deploy_key", "Keep deploy key", {"type": "bool"}),
        ("script", "Install command", {"type": "str"}),
        ("services", "Systemctl service names", {"type": "list"}),
        ("bigboat_url", "URL to BigBoat instance", {"type": "str"}),
        ("bigboat_key", "API key of BigBoat instance", {"type": "str"}),
        ("bigboat_compose", "Repository path to compose files", {"type": "str"}),
        ("secret_files", "Secret files to add to deployment", {"type": "file"})
    ]

    # Common HTML template
    COMMON_HTML = """<!doctype html>
<html>
    <head>
        <meta charset="utf-8">
        <title>{title!h} - Deployment</title>
        <link rel="stylesheet" href="css">
    </head>
    <body>
        <h1>Deployment: {title!h}</h1>
        <div class="content">
            {content}
        </div>
    </body>
</html>"""

    def __init__(self, args, config):
        super(Deployer, self).__init__(args, config)

        self.args = args
        self.config = config
        self.deploy_filename = os.path.join(self.args.deploy_path,
                                            'deployment.json')
        self._deployments = None

        self._template = Template()

        self._deploy_progress = {}
        cherrypy.engine.subscribe('stop', self._stop_threads)
        cherrypy.engine.subscribe('graceful', self._stop_threads)
        cherrypy.engine.subscribe('deploy', self._set_deploy_progress)

    def _format_html(self, title='', content=''):
        return self._template.format(self.COMMON_HTML, title=title,
                                     content=content)

    @cherrypy.expose
    def index(self, page='list', params=''):
        """
        Login page.
        """

        self.validate_page(page)

        form = self._template.format("""
            <form class="login" method="post" action="login?page={page!u}&amp;params={params!u}">
                <label>
                    Username: <input type="text" name="username" autofocus>
                </label>
                <label>
                    Password: <input type="password" name="password">
                </label>
                <button type="submit">Login</button>
            </form>""", page=page, params=params)

        return self._format_html(title='Login', content=form)

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
form.edit label.file + label {
    font-size: 90%;
    padding-left: 1rem;
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
    word-break: break-all;
    white-space: pre-line;
}
.success, .error, .starting, .progress {
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
.starting {
    border: 0.01rem solid #666666;
    background-color: #eeeeee;
}
.progress {
    border: 0.01rem solid #5555ff;
    background-color: #ccccff;
}
"""

        cherrypy.response.headers['Content-Type'] = 'text/css'
        cherrypy.response.headers['ETag'] = md5(content.encode('ISO-8859-1')).hexdigest()

        cherrypy.lib.cptools.validate_etags()

        return content

    @property
    def deployments(self):
        """
        Retrieve the current deployments.
        """

        if self._deployments is None:
            self._deployments = Deployments.read(self.deploy_filename,
                                                 self.FIELDS)

        return self._deployments

    def _get_session_html(self):
        return self._template.format("""
            <div class="logout">
                {user!h} - <a href="logout">Logout</a>
            </div>""", user=cherrypy.session['authenticated'])

    @cherrypy.expose
    def list(self):
        """
        List deployments.
        """

        self.validate_login()

        content = self._get_session_html()
        if not self.deployments:
            content += """
            <p>No deployments found - <a href="create">create one</a>
            """
        else:
            item = """
                    <li>
                        {deployment[name]!h}
                        <button formaction="deploy" name="name" value="{deployment[name]!h}" formmethod="post">Deploy</button>
                        <button formaction="edit" name="name" value="{deployment[name]!h}">Edit</button>
                        {status}
                    </li>"""
            items = []
            for deployment in sorted(self.deployments,
                                     key=lambda deployment: deployment["name"]):
                if deployment.is_up_to_date():
                    status = 'Up to date'
                    url = deployment.get_tree_url()
                else:
                    status = 'Outdated'
                    url = deployment.get_compare_url()

                if url is not None:
                    status = self._template.format('<a href="{url!h}">{status}</a>',
                                                   url=url, status=status)

                items.append(self._template.format(item,
                                                   deployment=deployment,
                                                   status=status))

            content += """
            <form>
                <ul class="items">
                    {items}
                </ul>
                <p><button formaction="create">Create</button></p>
            </form>""".format(items='\n'.join(items))

        return self._format_html(title='List', content=content)

    def _find_deployment(self, name):
        try:
            return self.deployments.get(name)
        except KeyError:
            raise cherrypy.HTTPError(404, 'Deployment {} does not exist'.format(name))

    def _format_fields(self, deployment, **excluded):
        form = ''
        for field_name, display_name, field_config in self.FIELDS:
            if field_name in excluded:
                continue

            field = {
                "display_name": display_name,
                "field_name": field_name,
                "input_type": 'text',
                "value": deployment.get(field_name,
                                        field_config.get('default', '')),
                "props": ''
            }
            field_type = field_config.get("type")
            if field_type == "file":
                form += self._template.format("""
                <label class="file">
                    {display_name!h}:
                    <input type="file" name="{field_name!h}" multiple>
                </label>""", display_name=display_name, field_name=field_name)
                field["display_name"] = 'Names'
                field["field_name"] += '_names'
                if field["value"] != '':
                    field["value"] = ' '.join(field["value"].keys())
            elif field_type == "list":
                field["value"] = ','.join(field["value"])
            elif field_type == "bool":
                if field["value"] != '':
                    field["props"] += ' checked'

                field.update({
                    "value": '1',
                    "input_type": 'checkbox'
                })

            form += self._template.format("""
                <label>
                    {display_name!h}:
                    <input type="{input_type!h}" name="{field_name!h}" value="{value!h}"{props}>
                </label>""", **field)

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
        if os.path.exists(key_file):
            logging.info('Removing old key file %s', key_file)
            os.remove(key_file)
        key = Key(key_file, data, update, {}, False)
        key.generate()
        return key.keyname

    @staticmethod
    def _upload_file(uploaded_file):
        block_size = 8192
        has_data = True
        data = ''
        while has_data:
            chunk = uploaded_file.read(block_size)
            data += chunk
            if not chunk:
                has_data = False

        return data

    @staticmethod
    def _extract_filename(path):
        # Compatible filename parsing as per
        # https://html.spec.whatwg.org/multipage/input.html#fakepath-srsly
        if path[:12] == 'C:\\fakepath\\':
            # Modern browser
            return path[12:]

        index = path.rfind('/')
        if index >= 0:
            # Unix-based path
            return path[index+1:]

        index = path.rfind('\\')
        if index >= 0:
            # Windows-based path
            return path[index+1:]

        # Just the file name
        return path

    def _upload_files(self, current, new_files):
        if not isinstance(new_files, list):
            new_files = [new_files]

        for name, new_file in zip_longest(list(current.keys()), new_files):
            if new_file is None or new_file.file is None:
                break
            if name is None:
                name = self._extract_filename(new_file.filename)

            logging.info('Reading uploaded file for name %s', name)
            data = self._upload_file(new_file.file)
            current[name] = data

    def _create_deployment(self, name, kwargs, deploy_key=None,
                           secret_files=None):
        if name in self.deployments:
            raise ValueError("Deployment '{}' already exists".format(name))

        if deploy_key is None:
            deploy_key = self._generate_deploy_key(name)
        if secret_files is not None:
            self._upload_files(secret_files, kwargs.pop("secret_files", []))

        services = kwargs.pop("services", '')
        states = kwargs.pop("jenkins_states", '')
        deployment = {
            "name": name,
            "git_path": kwargs.pop("git_path", ''),
            "git_url": kwargs.pop("git_url", ''),
            "git_branch": kwargs.pop("git_branch", "master"),
            "deploy_key": deploy_key,
            "jenkins_job": kwargs.pop("jenkins_job", ''),
            "jenkins_git": kwargs.pop("jenkins_git", ''),
            "jenkins_states": states.split(',') if states != '' else [],
            "artifacts": kwargs.pop("artifacts", ''),
            "script": kwargs.pop("script", ''),
            "services": services.split(',') if services != '' else [],
            "bigboat_url": kwargs.pop("bigboat_url", ''),
            "bigboat_key": kwargs.pop("bigboat_key", ''),
            "bigboat_compose": kwargs.pop("bigboat_compose", ''),
            "secret_files": secret_files
        }
        self.deployments.add(deployment)
        self.deployments.write(self.deploy_filename)
        with open('{}.pub'.format(deploy_key), 'r') as public_key_file:
            public_key = public_key_file.read()

        return deployment, public_key

    @cherrypy.expose
    def create(self, name='', **kwargs):
        """
        Create a new deployment using a form or handle the form submission.
        """

        self.validate_login()

        if cherrypy.request.method == 'POST':
            public_key = self._create_deployment(name, kwargs,
                                                 secret_files={})[1]

            success = self._template.format("""<div class="success">
                The deployment has been created. The new deploy key's public
                part is shown below. Register this key in the GitLab repository.
                You can <a href="edit?name={name!u}">edit the deployment</a>,
                <a href="list">go to the list</a> or create a new deployment.
            </div>
            <pre>{deploy_key!h}</pre>""", name=name, deploy_key=public_key)
        else:
            success = ''

        content = """
            {session}
            {success}
            <form class="edit" action="create" method="post" enctype="multipart/form-data">
                {form}
                <button>Update</button>
            </form>""".format(session=self._get_session_html(), success=success,
                              form=self._format_fields({}, deploy_key=False))

        return self._format_html(title='Create', content=content)

    def _check_old_secrets(self, secret_names, old_deployment):
        old_path = old_deployment.get("git_path", "")
        old_secrets = old_deployment.get("secret_files", {})
        old_names = list(old_secrets.keys())
        if old_names != secret_names:
            # Remove old files from repository which might never be overwritten
            for secret_file in old_secrets:
                secret_path = os.path.join(old_path, secret_file)
                if os.path.isfile(secret_path):
                    os.remove(secret_path)

        new_secrets = OrderedDict()
        for new_name, old_name in zip_longest(secret_names, old_names):
            if new_name == '':
                continue

            if old_name is None:
                new_secrets[new_name] = ''
            elif new_name is not None:
                new_secrets[new_name] = old_secrets[old_name]

        return new_secrets

    @cherrypy.expose
    def edit(self, name=None, old_name=None, **kwargs):
        """
        Display an existing deployment configuration in an editable form, or
        handle the form submission to update the deployment.
        """

        self.validate_login()
        if name is None:
            # Paramter 'name' required
            raise cherrypy.HTTPRedirect('list')

        if cherrypy.request.method == 'POST':
            old_deployment = self._find_deployment(old_name)
            self.deployments.remove(old_deployment)
            if kwargs.pop("deploy_key"):
                # Keep the deploy key according to checkbox state
                deploy_key = old_deployment.get("deploy_key", '')
                state = 'original'
            else:
                # Generate a new deploy key
                deploy_key = None
                state = 'new'
                if os.path.exists(old_deployment.get("deploy_key", '')):
                    os.remove(old_deployment.get("deploy_key", ''))

            secret_names = kwargs.pop("secret_files_names", '').split(' ')
            secret_files = self._check_old_secrets(secret_names, old_deployment)

            deployment, public_key = \
                self._create_deployment(name, kwargs, deploy_key=deploy_key,
                                        secret_files=secret_files)

            success = self._template.format("""<div class="success">
                The deployment has been updated. The {state!h} deploy key's public
                part is shown below. Ensure that this key exists in the GitLab
                repository. You can edit the deployment configuration again or
                <a href="list">go to the list</a>.
            </div>
            <pre>{deploy_key!h}</pre>""", state=state, deploy_key=public_key)
        else:
            success = ''
            deployment = self._find_deployment(name)

        form = self._template.format("""
            <input type="hidden" name="old_name" value="{name!h}">""", name=name)
        form += self._format_fields(deployment)

        content = """
            {session}
            {success}
            <form class="edit" action="edit" method="post" enctype="multipart/form-data">
                {form}
                <button>Update</button>
            </form>""".format(session=self._get_session_html(), success=success,
                              form=form)

        return self._format_html(title='Edit', content=content)

    def _stop_threads(self, *args, **kwargs):
        # pylint: disable=unused-argument
        for progress in list(self._deploy_progress.values()):
            thread = progress['thread']
            if thread is not None:
                thread.stop()
                if thread.is_alive():
                    thread.join()

        self._deploy_progress = {}

    def _set_deploy_progress(self, name, state, message):
        self._deploy_progress[name] = {
            'state': state,
            'message': message,
            'thread': self._deploy_progress[name]['thread']
        }
        if state in ('success', 'error'):
            self._deploy_progress[name]['thread'] = None

    @cherrypy.expose
    def deploy(self, name):
        """
        Update the deployment based on the configuration.
        """

        self.validate_login()
        deployment = self._find_deployment(name)

        if cherrypy.request.method != 'POST':
            if name in self._deploy_progress:
                # Do something
                content = self._template.format("""
                    <div class="{state!h}">
                        The deployment of {name!h} is in the "{state}" state.
                        The latest message is: <code>{message!h}</code>.
                        You can <a href="deploy?name={name!u}">view progress</a>.
                        You can <a href="list">return to the list</a>.
                    </div>""", name=name, **self._deploy_progress[name])

                return self._format_html(title='Deploy', content=content)

            raise cherrypy.HTTPRedirect('list')

        progress = self._deploy_progress.get(name, {'thread': None})
        if progress['thread'] is not None:
            content = self._template.format("""
                <div class="error">
                    Another deployment of {name!h} is already underway.
                    You can <a href="deploy?name={name!u}">view progress</a>.
                </div>""", name=name)

            return self._format_html(title='Deploy', content=content)

        thread = Deploy_Task(deployment, self.config, bus=cherrypy.engine)
        self._deploy_progress[name] = {
            'state': 'starting',
            'message': 'Thread is starting',
            'thread': thread
        }
        thread.start()

        content = self._template.format("""
            <div class="success">
                The deployment of {name} has started.
                You can <a href="deploy?name={name}">view progress</a>.
                You can <a href="list">return to the list</a>.
            </div>""", name=name)

        return self._format_html(title='Deploy', content=content)
