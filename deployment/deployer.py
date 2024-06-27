"""
Frontend for accessing deployments and (re)starting them.

Copyright 2017-2020 ICTU
Copyright 2017-2022 Leiden University
Copyright 2017-2023 Leon Helwerda

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

from argparse import Namespace
from collections import OrderedDict
from configparser import RawConfigParser
from hashlib import md5
from itertools import zip_longest
import logging
import logging.config
from pathlib import Path
import sys
from typing import Any, BinaryIO, Dict, List, Optional, Union, Sequence, Tuple
import cherrypy
import cherrypy.lib.cptools
from cherrypy._cpreqbody import Part
try:
    from unittest.mock import MagicMock
    sys.modules['abraxas'] = MagicMock()
    from sshdeploy.key import Key
except ImportError:
    sys.modules.pop('abraxas', None)
    raise
from gatherer.jenkins import Jenkins
from server.application import Authenticated_Application
from server.template import Template
from .deployment import Deployments, Deployment, Fields
from .task import Deploy_Task

Parameter = Union[str, Part, List[Part]]

class Deployer(Authenticated_Application):
    """
    Deployer web interface.
    """

    # Fields in the deployment and their human-readable variant.
    FIELDS: Fields = [
        ("name", "Deployment name", {"type": "str"}),
        ("git_path", "Git clone path", {"type": "str"}),
        ("git_url", "Git repository URL", {"type": "str"}),
        ("git_branch", "Git branch to check out", {
            "type": "branch",
            "default": "master"
        }),
        ("jenkins_job", "Jenkins job", {"type": "job"}),
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

    def __init__(self, args: Namespace, config: RawConfigParser):
        super().__init__(args, config)

        self.args = args
        self.config = config
        self.deploy_filename = Path(self.args.deploy_path) / 'deployment.json'
        self._deployments: Optional[Deployments] = None

        self._template = Template()

        self._deploy_progress: \
            Dict[str, Dict[str, Union[str, Optional[Deploy_Task]]]] = {}
        cherrypy.engine.subscribe('stop', self._stop_threads)
        cherrypy.engine.subscribe('graceful', self._stop_threads)
        cherrypy.engine.subscribe('deploy', self._set_deploy_progress)

    def _format_html(self, title: str = '', content: str = '') -> str:
        return self._template.format(self.COMMON_HTML, title=title,
                                     content=content)

    @cherrypy.expose
    def index(self, page: str = 'list', params: str = '') -> str:
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
    def css(self) -> str:
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
form.edit label.file + label, form.edit label.options + label {
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
    def deployments(self) -> Deployments:
        """
        Retrieve the current deployments.
        """

        if self._deployments is None:
            self._deployments = Deployments.read(self.deploy_filename,
                                                 self.FIELDS)

        return self._deployments

    def _get_session_html(self) -> str:
        return self._template.format("""
            <div class="logout">
                {user!h} - <a href="logout">Logout</a>
            </div>""", user=cherrypy.session['authenticated'])

    @cherrypy.expose
    def list(self) -> str:
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
            deployments: List[Deployment] = \
                sorted(self.deployments,
                       key=lambda deployment: str(deployment["name"]))
            for deployment in deployments:
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

            content += f"""
            <form>
                <ul class="items">
                    {"".join(items)}
                </ul>
                <p><button formaction="create">Create</button></p>
            </form>"""

        return self._format_html(title='List', content=content)

    def _find_deployment(self, name: str) -> Deployment:
        try:
            return self.deployments.get(name)
        except KeyError as error:
            raise cherrypy.HTTPError(404, f'Deployment {name} does not exist') from error

    def _format_fields(self, deployment: Deployment, **included: bool) -> str:
        form = ''
        for field_name, display_name, field_config in self.FIELDS:
            if not included.get(field_name, True):
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
            elif field_type == "job":
                jenkins = Jenkins.from_config(self.config)
                jobs = [job.name for job in jenkins.jobs]
                form += self._format_options_field(field, jobs,
                                                   display_name='Other job')
            elif field_type == "branch":
                branches = deployment.get_branches()
                form += self._format_options_field(field, branches,
                                                   display_name='Other branch')

            form += self._template.format("""
                <label>
                    {display_name!h}:
                    <input type="{input_type!h}" name="{field_name!h}" value="{value!h}"{props}>
                </label>""", **field)

        return form

    def _format_options_field(self, field: Dict[str, str],
                              choices: Sequence[str],
                              display_name: str = 'Other') -> str:
        options = [
            self._template.format("""
                <option value="{choice!h}"{selected}>
                    {choice!h}
                </option>""",
                                  choice=choice,
                                  selected=' selected=""'
                                  if choice == field["value"] else '')
            for choice in choices
        ]
        field['options'] = '\n'.join(options)
        if field["value"] not in choices:
            field['other_selected'] = ' selected=""'
        else:
            field['other_selected'] = ''

        form_options = self._template.format("""
        <label class="options">
            {display_name!h}:
            <select name="{field_name!h}">
                {options}
                <option value=""{other_selected}>Other&hellip;</option>
            </select>
        </label>""", **field)
        field["display_name"] = display_name
        field["field_name"] += '_other'

        return form_options

    def _generate_deploy_key(self, name: str) -> str:
        data: Dict[str, Union[str, bool, Dict[str, Union[str, List[str]]]]] = {
            'purpose': f'deploy key for {name}',
            'keygen-options': '',
            'abraxas-account': False,
            'servers': {},
            'clients': {}
        }
        update: List[str] = []
        key_file = Path(self.args.deploy_path) / f'key-{name}'
        if key_file.exists():
            logging.info('Removing old key file %s', key_file)
            key_file.unlink()
        key = Key(str(key_file), data, update, set(), False)
        key.generate()
        return key.keyname

    @staticmethod
    def _upload_file(uploaded_file: BinaryIO) -> bytes:
        block_size = 8192
        has_data = True
        data = b''
        while has_data:
            chunk = uploaded_file.read(block_size)
            data += chunk
            if not chunk:
                has_data = False

        return data

    @staticmethod
    def _extract_filename(path: str) -> str:
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

    def _upload_files(self, current: Dict[str, str],
                      new_files: Union[Part, List[Part]]) -> None:
        if not isinstance(new_files, list):
            new_files = [new_files]

        for name, new_file in zip_longest(list(current.keys()), new_files,
                                          fillvalue=None):
            if new_file is None or new_file.file is None or \
                new_file.filename is None:
                break
            if name is None:
                name = self._extract_filename(new_file.filename)

            logging.info('Reading uploaded file for name %s', name)
            data = self._upload_file(new_file.file)
            current[name] = data.decode('utf-8')

    def _create_deployment(self, name: str,
                           kwargs: Dict[str, Parameter],
                           deploy_key: Optional[str] = None,
                           secret_files: Optional[Dict[str, str]] = None) -> \
            Tuple[Deployment, str]:
        if name in self.deployments:
            raise ValueError(f"Deployment '{name}' already exists")

        if deploy_key is None:
            deploy_key = self._generate_deploy_key(name)
        if secret_files is not None:
            new_files = kwargs.pop("secret_files", [])
            if isinstance(new_files, (Part, list)):
                self._upload_files(secret_files, new_files)

        services = str(kwargs.pop("services", ''))
        states = str(kwargs.pop("jenkins_states", ''))
        branch = kwargs.pop("git_branch", '')
        if branch == '':
            branch = kwargs.pop("git_branch_other", "master")
        job = kwargs.pop("jenkins_job", '')
        if job == '':
            job = kwargs.pop("jenkins_job_other", '')

        deployment = {
            "name": name,
            "git_path": kwargs.pop("git_path", ''),
            "git_url": kwargs.pop("git_url", ''),
            "git_branch": branch,
            "deploy_key": deploy_key,
            "jenkins_job": job,
            "jenkins_git": kwargs.pop("jenkins_git", ''),
            "jenkins_states": states.split(',') if states != '' else
                states.split(None),
            "artifacts": kwargs.pop("artifacts", ''),
            "script": kwargs.pop("script", ''),
            "services": services.split(',') if services != '' else
                services.split(None),
            "bigboat_url": kwargs.pop("bigboat_url", ''),
            "bigboat_key": kwargs.pop("bigboat_key", ''),
            "bigboat_compose": kwargs.pop("bigboat_compose", ''),
            "secret_files": secret_files
        }
        self.deployments.add(deployment)
        self.deployments.write(self.deploy_filename)
        with open(f'{deploy_key}.pub', 'r', encoding='utf-8') as public_key_file:
            public_key = public_key_file.read()

        return self.deployments.get(deployment), public_key

    @cherrypy.expose
    def create(self, name: str = '', **kwargs: Parameter) -> str:
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

        content = f"""
            {self._get_session_html()}
            {success}
            <form class="edit" action="create" method="post" enctype="multipart/form-data">
                {self._format_fields(Deployment(), deploy_key=False)}
                <button>Update</button>
            </form>"""

        return self._format_html(title='Create', content=content)

    def _check_old_secrets(self, secret_names: List[str],
                           old_deployment: Deployment) -> Dict[str, str]:
        old_path = Path(old_deployment.get("git_path", ""))
        old_secrets: Dict[str, str] = old_deployment.get("secret_files", {})
        old_names = list(old_secrets.keys())
        if old_names != secret_names:
            # Remove old files from repository which might never be overwritten
            for secret_file in old_secrets:
                secret_path = old_path / secret_file
                if secret_path.is_file():
                    secret_path.unlink()

        new_secrets = OrderedDict()
        for new_name, old_name in zip_longest(secret_names, old_names,
                                              fillvalue=None):
            if new_name == '' or new_name is None:
                continue

            if old_name is None:
                new_secrets[new_name] = ''
            else:
                new_secrets[new_name] = old_secrets[old_name]

        return new_secrets

    @cherrypy.expose
    def edit(self, name: Optional[str] = None, old_name: Optional[str] = None,
             **kwargs: Parameter) -> str:
        """
        Display an existing deployment configuration in an editable form, or
        handle the form submission to update the deployment.
        """

        self.validate_login()
        if name is None:
            # Parameter 'name' required
            raise cherrypy.HTTPRedirect('list')

        if cherrypy.request.method == 'POST':
            if old_name is None:
                raise cherrypy.HTTPError(400, "Parameter 'old_name' required")

            old_deployment = self._find_deployment(old_name)
            self.deployments.remove(old_deployment)
            if kwargs.pop("deploy_key"):
                # Keep the deploy key according to checkbox state
                deploy_key = str(old_deployment.get("deploy_key", ''))
                state = 'original'
            else:
                # Generate a new deploy key
                deploy_key = None
                state = 'new'
                old_key = Path(old_deployment.get("deploy_key", ''))
                if old_key.exists():
                    old_key.unlink()

            secret_names = str(kwargs.pop("secret_files_names", '')).split(' ')
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
            if old_name is not None:
                name = old_name
            deployment = self._find_deployment(name)

        form = self._template.format("""
            <input type="hidden" name="old_name" value="{name!h}">""", name=name)
        form += self._format_fields(deployment)

        content = f"""
            {self._get_session_html()}
            {success}
            <form class="edit" action="edit" method="post" enctype="multipart/form-data">
                {form}
                <button>Update</button>
            </form>"""

        return self._format_html(title='Edit', content=content)

    def _stop_threads(self, *args: Any, **kwargs: Any) -> None:
        # pylint: disable=unused-argument
        for progress in list(self._deploy_progress.values()):
            thread = progress['thread']
            if isinstance(thread, Deploy_Task):
                thread.stop()
                if thread.is_alive():
                    thread.join()

        self._deploy_progress = {}

    def _set_deploy_progress(self, name: str, state: str, message: str) -> None:
        self._deploy_progress[name] = {
            'state': state,
            'message': message,
            'thread': self._deploy_progress[name]['thread']
        }
        if state in ('success', 'error'):
            self._deploy_progress[name]['thread'] = None

    @cherrypy.expose
    def deploy(self, name: str = '') -> str:
        """
        Update the deployment based on the configuration.
        """

        self.validate_login()
        if name == '':
            # Parameter 'name' required
            raise cherrypy.HTTPRedirect('list')

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
