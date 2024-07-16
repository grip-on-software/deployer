"""
Tests for background deployment tasks.

Copyright 2017-2020 ICTU
Copyright 2017-2022 Leiden University
Copyright 2017-2024 Leon Helwerda

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

import unittest
from unittest.mock import MagicMock, patch, DEFAULT
from cherrypy.process.wspbus import Bus
import requests_mock
from gatherer.jenkins import Jenkins
from deployment.deployment import Deployment
from deployment.task import Deploy_Task, Thread_Interrupt

class DeployTaskTest(unittest.TestCase):
    """
    Tests for background task to update a deployment.
    """

    def setUp(self) -> None:
        repo_patcher = patch('gatherer.git.repo.Git_Repository.from_source')
        self.repository = repo_patcher.start()
        attrs = {'get_contents.return_value': b'name: app\nversion: latest'}
        self.repository.return_value.configure_mock(**attrs)
        self.addCleanup(repo_patcher.stop)

        bigboat_patcher = patch('bigboat.Client_v2')
        self.bigboat = bigboat_patcher.start()
        self.addCleanup(bigboat_patcher.stop)

        path_patcher = patch('deployment.task.Path', autospec=True)
        self.path = path_patcher.start()
        self.addCleanup(path_patcher.stop)

        subprocess_patcher = patch.multiple('subprocess', check_output=DEFAULT,
                                            check_call=DEFAULT)
        self.subprocess = subprocess_patcher.start()
        self.addCleanup(subprocess_patcher.stop)

        deployment = Deployment(name='test',
                                git_url='https://gitlab.test/foo/bar',
                                git_path='test/sample/test-repo',
                                jenkins_job='test-job',
                                jenkins_git=False,
                                deploy_key='test/sample/deploy/test-key',
                                artifacts=True,
                                secret_files={
                                    '': '',
                                    'env': 'host=db.test'
                                },
                                script='./test-script.sh 123',
                                services=["test-service"],
                                bigboat_url='http://bigboat.test/',
                                bigboat_key='abcdef',
                                bigboat_compose='test-compose')

        # Set up Jenkins API adapter with crumb issuer and job route
        adapter = requests_mock.Adapter()
        adapter.register_uri('GET', '/crumbIssuer/api/json', status_code=404)
        adapter.register_uri('GET', '/job/test-job/api/json', json={})
        adapter.register_uri('GET', '/job/test-job/lastBuild/api/json', json={
            'number': 2,
            'building': False,
            'result': 'SUCCESS',
            'artifacts': [
                {'relativePath': 'data.txt'}
            ],
            'actions': [
                {
                    'buildsByBranchName': {
                        'origin/master': {
                            'buildNumber': 2,
                            'revision': {
                                'SHA1': 'abcd1234',
                                'branch': [{'name': 'master'}]
                            }
                        }
                    }
                }
            ]
        })
        adapter.register_uri('GET', '/job/test-job/lastBuild/artifact/data.txt',
                             content=b'12345')
        jenkins_host = 'http+mock://jenkins.test/'
        self.jenkins = Jenkins(jenkins_host)
        self.jenkins.mount(adapter, prefix=jenkins_host)

        self.bus = MagicMock(spec_set=Bus)
        self.task = Deploy_Task(deployment, self.jenkins, self.bus)

    def test_run(self) -> None:
        """
        Test running the thread.
        """

        self.task.run()

        self.path.assert_any_call('test/sample/test-repo')

        self.repository.assert_called_once()

        # Artifacts
        self.path.return_value.__truediv__.assert_any_call('data.txt')
        path = self.path.return_value.__truediv__.return_value
        path.parent.exists.assert_called_once_with()
        path.open.assert_any_call('wb')
        open_file = path.open.return_value.__enter__.return_value
        open_file.write.assert_any_call(b'12345')

        # Secret files
        self.path.return_value.__truediv__.assert_any_call('env')
        path.open.assert_called_with('w', encoding='utf-8')
        open_file.write.assert_called_with('host=db.test')

        # Scripts and services
        self.subprocess['check_output'].assert_called_once()
        self.subprocess['check_call'].assert_called_once_with([
            'sudo', 'systemctl', 'restart', 'test-service'
        ])

        # BigBoat compose
        self.path.assert_called_with('test-compose')
        self.path.return_value.__truediv__.assert_any_call('docker-compose.yml')
        self.path.return_value.__truediv__.assert_any_call('bigboat-compose.yml')
        self.bigboat.assert_called_once_with('http://bigboat.test/', 'abcdef')
        client = self.bigboat.return_value
        client.get_app.assert_called_once_with('app', 'latest')
        client.update_compose.assert_any_call('app', 'latest', 'dockerCompose',
                                              b'name: app\nversion: latest')
        client.update_compose.assert_any_call('app', 'latest', 'bigboatCompose',
                                              b'name: app\nversion: latest')
        client.update_instance.assert_called_once_with('app', 'app', 'latest')

        self.bus.publish.assert_called_with('deploy', 'test', 'success',
                                            'Finished deployment')

    def test_stop(self) -> None:
        """
        Test indicating that the thread should stop.
        """

        # Call stop at some point, but here before starting.
        self.task.stop()

        # On the other thread, we at some point stop.
        # Here, before something is ever published to the bus.
        self.task.run()
        self.bus.publish.assert_not_called()

        # Even without a bus, the task is stopped properly.
        with patch('deployment.task.Thread_Interrupt',
                   return_value=Thread_Interrupt()) as error:
            task = Deploy_Task(Deployment(name='test'), self.jenkins, bus=None)
            task.stop()
            task.run()
            error.assert_called_once_with('Thread is stopped')
