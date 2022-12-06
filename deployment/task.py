"""
Background deployment tasks.

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

from configparser import RawConfigParser
import logging
import os
from pathlib import Path
import shlex
import subprocess
import threading
from typing import Dict, List, Optional, Union
import bigboat
from cherrypy.process.wspbus import Bus
import yaml
from gatherer.git import Git_Repository
from gatherer.jenkins import Jenkins, Build
from .deployment import Deployment

class Thread_Interrupt(Exception):
    """
    Exception indicating that the thread is stopped from an external source.
    """

class Deploy_Task(threading.Thread):
    """
    Background task to update a deployment.
    """

    # Compose files for BigBoat
    BIGBOAT_FILES = [
        ('docker-compose.yml', 'dockerCompose'),
        ('bigboat-compose.yml', 'bigboatCompose')
    ]

    def __init__(self, deployment: Deployment, config: RawConfigParser,
                 bus: Optional[Bus] = None):
        super().__init__()
        self._deployment = deployment
        self._name = deployment["name"]
        self._config = config
        self._bus = bus
        self._stop = False

    def run(self) -> None:
        try:
            self._deploy()
        except (KeyboardInterrupt, SystemExit, Thread_Interrupt):
            pass
        except (RuntimeError, ValueError) as error:
            self._publish('error', str(error))

    def stop(self) -> None:
        """
        Indicate that the thread should stop.
        """

        self._stop = True

    def _publish(self, state: str, message: str) -> None:
        if self._stop:
            raise Thread_Interrupt("Thread is stopped")

        logging.info('Deploy %s: %s: %s', self._name, state, message)
        if self._bus is not None:
            self._bus.publish('deploy', self._name, state, message)

    def _add_artifacts(self, repo_path: Path, last_build: Build) -> None:
        if 'artifacts' not in last_build.data or not last_build.data['artifacts']:
            raise RuntimeError('Jenkins build has no artifacts')

        self._publish('progress', 'Collecting artifacts')
        session = last_build.instance.session
        for artifact in last_build.data['artifacts']:
            path = artifact['relativePath']
            self._publish('progress', f'Collecting artifact {path}')

            # Ensure directories within the relative artifact path exist
            repo_artifact = repo_path / path
            dirname = repo_artifact.parent
            if not dirname.exists():
                dirname.mkdir(parents=True)

            # Download the artifact to the repository path
            url = f'{last_build.base_url}/artifact/{path}'
            request = session.get(url)
            with repo_artifact.open('wb') as repo_file:
                repo_file.write(request.content)

    def _add_secret_files(self, deploy_path: Path) -> None:
        self._publish('progress', 'Writing secret files')
        secret_files = self._deployment.get("secret_files", {})
        for secret_name, secret_file in list(secret_files.items()):
            if secret_name != '':
                secret_path = deploy_path / secret_name
                try:
                    with secret_path.open('w', encoding='utf-8') as secret:
                        secret.write(secret_file)
                except IOError as error:
                    raise RuntimeError(f"Could not write secret file: {error}") from error

    def _update_bigboat(self, repository: Git_Repository) -> None:
        if self._deployment.get("bigboat_key", '') == '':
            raise ValueError("BigBoat API key required to update BigBoat")

        path = Path(self._deployment.get("bigboat_compose", ''))
        files: Dict[str, bytes] = {}
        paths: List[Union[str, os.PathLike]] = []
        for filename, api_filename in self.BIGBOAT_FILES:
            full_filename = path / filename
            files[api_filename] = repository.get_contents(str(full_filename))
            paths.append(full_filename)

        if not repository.repo.head.commit.diff(repository.prev_head,
                                                paths=paths):
            self._publish('progress',
                          'BigBoat compose files were unchanged, skipping.')
            return

        self._publish('progress', 'Updating BigBoat compose files')
        compose = yaml.safe_load(files['bigboatCompose'])
        client = bigboat.Client_v2(self._deployment["bigboat_url"],
                                   self._deployment["bigboat_key"])

        name = compose['name']
        version = compose['version']
        application = client.get_app(name, version)
        if application is None:
            logging.warning('Application %s version %s not on %s, creating.',
                            name, version, self._deployment['bigboat_url'])
            if client.update_app(name, version) is None:
                raise RuntimeError('Cannot register application')

        for api_filename, contents in files.items():
            if not client.update_compose(name, version, api_filename, contents):
                raise RuntimeError('Cannot update compose file')

        self._publish('progress', 'Updating BigBoat instances')
        client.update_instance(name, name, version)

    def _deploy(self) -> None:
        # Check Jenkins job success
        if self._deployment.get("jenkins_job", '') != '':
            jenkins = Jenkins.from_config(self._config)
            self._publish('progress', 'Checking Jenkins build state')
            last_build = self._deployment.check_jenkins(jenkins)
        else:
            last_build = None

        # Update Git repository using deploy key
        self._publish('progress', 'Updating Git repository')
        source = self._deployment.get_source()
        git_path = Path(self._deployment["git_path"])
        git_branch = self._deployment.get("git_branch", "master")
        repository = Git_Repository.from_source(source, git_path,
                                                checkout=True, shared=True,
                                                force=True, pull=True,
                                                branch=git_branch)

        logging.info('Updated repository %s', repository.repo_name)

        if last_build is not None and self._deployment.get("artifacts", False):
            self._add_artifacts(git_path, last_build)

        self._add_secret_files(git_path)

        # Run script
        script = self._deployment.get("script", '')
        if script != '':
            try:
                self._publish('progress', f'Runnning script {script}')
                environment = os.environ.copy()
                environment['DEPLOYMENT_NAME'] = self._name
                subprocess.check_output(shlex.split(script),
                                        stderr=subprocess.STDOUT,
                                        cwd=git_path,
                                        env=environment)
            except subprocess.CalledProcessError as error:
                output = error.output.decode('utf-8')
                raise RuntimeError(f'Could not run script {script}: {output}') from error

        # Restart services
        for service in self._deployment["services"]:
            if service != '':
                self._publish('progress', f'Restarting service {service}')
                try:
                    subprocess.check_call([
                        'sudo', 'systemctl', 'restart', service
                    ])
                except subprocess.CalledProcessError as error:
                    raise RuntimeError(f'Could not restart service {service}') from error

        # Update BigBoat dashboard applications
        if self._deployment.get("bigboat_url", '') != '':
            self._update_bigboat(repository)

        self._publish('success', 'Finished deployment')
