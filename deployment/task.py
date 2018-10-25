"""
Background deployment tasks.
"""

import logging
import os.path
import shlex
import subprocess
import threading
import bigboat
import yaml
from gatherer.git import Git_Repository
from gatherer.jenkins import Jenkins

class Thread_Interrupt(Exception):
    """
    Exception indicating that the thread is stopped from an external source.
    """

class Deploy_Task(threading.Thread):
    """
    Background task to update a deployment.
    """

    # Compose files for BigBoat
    FILES = [
        ('docker-compose.yml', 'dockerCompose'),
        ('bigboat-compose.yml', 'bigboatCompose')
    ]

    def __init__(self, deployment, config, bus=None):
        super(Deploy_Task, self).__init__()
        self._deployment = deployment
        self._name = deployment["name"]
        self._config = config
        self._bus = bus
        self._stop = False

    def run(self):
        try:
            self._deploy()
        except (KeyboardInterrupt, SystemExit, Thread_Interrupt):
            pass
        except (RuntimeError, ValueError) as error:
            self._publish('error', str(error))

    def stop(self):
        """
        Indicate that the thread should stop.
        """

        self._stop = True

    def _publish(self, state, message):
        if self._stop:
            raise Thread_Interrupt("Thread is stopped")

        logging.info('Deploy %s: %s: %s', self._name, state, message)
        if self._bus is not None:
            self._bus.publish('deploy', self._name, state, message)

    def _add_artifacts(self, repo_path, last_build):
        if 'artifacts' not in last_build.data or not last_build.data['artifacts']:
            raise RuntimeError('Jenkins build has no artifacts')

        self._publish('progress', 'Collecting artifacts')
        session = last_build.instance.session
        for artifact in last_build.data['artifacts']:
            path = artifact['relativePath']
            self._publish('progress', 'Collecting artifact {}'.format(path))

            dirname = os.path.join(repo_path, os.path.dirname(path))
            if not os.path.exists(dirname):
                os.makedirs(dirname)

            url = '{}/artifact/{}'.format(last_build.base_url, path)
            request = session.get(url)
            with open(os.path.join(repo_path, path), 'wb') as repo_file:
                repo_file.write(request.content)

    def _add_secret_files(self, deploy_path):
        self._publish('progress', 'Writing secret files')
        secret_files = self._deployment.get("secret_files", {})
        for secret_name, secret_file in list(secret_files.items()):
            if secret_name != '':
                secret_path = os.path.join(deploy_path, secret_name)
                try:
                    with open(secret_path, 'w') as secret:
                        secret.write(secret_file)
                except IOError as error:
                    raise RuntimeError("Could not write secret file: {}".format(str(error)))

    def _update_bigboat(self, repository):
        if self._deployment.get("bigboat_key", '') == '':
            raise ValueError("BigBoat API key required to update BigBoat")

        path = self._deployment.get("bigboat_compose", '')
        files = {}
        paths = []
        for filename, api_filename in self.FILES:
            full_filename = '{}/{}'.format(path, filename).lstrip('./')
            files[api_filename] = repository.get_contents(full_filename)
            paths.append(full_filename)

        if not repository.head.diff(repository.prev_head, paths=paths):
            self._publish('progress',
                          'BigBoat compose files were unchanged, skipping.')
            return

        self._publish('progress', 'Updating BigBoat compose files')
        compose = yaml.load(files['bigboatCompose'])
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

    def _deploy(self):
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
        git_path = self._deployment["git_path"]
        git_branch = self._deployment.get("git_branch", "master")
        repository = Git_Repository.from_source(source, git_path,
                                                checkout=True, shared=True,
                                                branch=git_branch)

        logging.info('Updated repository %s', repository.repo_name)

        if last_build is not None and self._deployment.get("artifacts", False):
            self._add_artifacts(git_path, last_build)

        self._add_secret_files(git_path)

        # Run script
        script = self._deployment.get("script", '')
        if script != '':
            try:
                self._publish('progress', 'Runnning script {}'.format(script))
                environment = os.environ.copy()
                environment['DEPLOYMENT_NAME'] = self._name
                subprocess.check_output(shlex.split(script),
                                        stderr=subprocess.STDOUT,
                                        cwd=git_path,
                                        env=environment)
            except subprocess.CalledProcessError as error:
                output = error.output.decode('utf-8')
                raise RuntimeError('Could not run script {}: {}'.format(script,
                                                                        output))

        # Restart services
        for service in self._deployment["services"]:
            if service != '':
                self._publish('progress',
                              'Restarting service {}'.format(service))
                try:
                    subprocess.check_call([
                        'sudo', 'systemctl', 'restart', service
                    ])
                except subprocess.CalledProcessError:
                    raise RuntimeError('Could not restart service {}'.format(service))

        # Update BigBoat dashboard applications
        if self._deployment.get("bigboat_url", '') != '':
            self._update_bigboat(repository)

        self._publish('success', 'Finished deployment')
