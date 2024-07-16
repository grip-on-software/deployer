"""
Tests for deployment frontend.

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

from argparse import Namespace
from configparser import RawConfigParser
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import MagicMock, patch
import cherrypy
from cherrypy.process.wspbus import Bus
from cherrypy.test import helper
import requests_mock
from deployment import Deployer
from deployment.deployment import Deployment
from deployment.task import Deploy_Task

class DeployerTest(helper.CPWebCase):
    """
    Tests for status dashboard.
    """

    deployments_write: MagicMock
    deploy_filename = Path('test/sample/deploy/deployment.json')
    server: Deployer

    @classmethod
    def setup_server(cls) -> None:
        """"
        Set up the application server.
        """

        args = Namespace()
        args.auth = 'open'
        args.debug = True
        args.deploy_path = 'test/sample/deploy'

        jenkins_host = 'http+mock://jenkins.test/'
        config = RawConfigParser()
        config['jenkins'] = {}
        config['jenkins']['host'] = jenkins_host
        config['jenkins']['username'] = '-'
        config['jenkins']['password'] = '-'
        config['jenkins']['verify'] = '0'
        config['jenkins']['scrape'] = 'scrape-projects'

        write_patcher = patch('deployment.deployment.Deployments.write')
        cls.deployments_write = write_patcher.start()
        cls.addClassCleanup(write_patcher.stop)

        cls.server = Deployer(args, config)

        # Set up Jenkins API adapter with crumb issuer and main route
        adapter = requests_mock.Adapter()
        adapter.register_uri('GET', '/crumbIssuer/api/json', status_code=404)
        adapter.register_uri('GET', '/api/json', json={
            'jobs': [
                {'name': 'build-monetdb-import'},
                {'name': 'build-test'}
            ]
        })
        cls.server.jenkins.mount(adapter, prefix=jenkins_host)

        cherrypy.tree.mount(cls.server, '/deploy', {
            '/': {
                'tools.sessions.on': True,
                'tools.sessions.httponly': True,
            }
        })

    def setUp(self) -> None:
        self.server.reset_deployments()
        self.deployments_write.reset_mock()

    def test_index(self) -> None:
        """
        Test the index page.
        """

        self.getPage("/deploy/index")
        self.assertStatus('200 OK')
        self.assertInBody('action="login?page=list&amp;params=')

        self.getPage("/deploy/index?page=edit&params=name=deployer%26old_name=deploy")
        self.assertStatus('200 OK')
        self.assertInBody('action="login?page=edit&amp;params=name%3Ddeployer%26old_name%3Ddeploy')

    def test_css(self) -> None:
        """
        Test serving CSS.
        """

        self.getPage("/deploy/css")
        self.assertStatus('200 OK')
        content_type = self.assertHeader('Content-Type')
        self.assertIn('text/css', content_type)
        etag = self.assertHeader('ETag')

        self.getPage("/deploy/css", headers=[('If-None-Match', etag)])
        self.assertStatus('304 Not Modified')

        self.getPage("/deploy/css", headers=[('If-None-Match', 'other')])
        self.assertStatus('200 OK')

    def test_list(self) -> None:
        """
        Test the list page.
        """

        self.getPage("/deploy/list")
        self.assertIn('/deploy/index?page=list', self.assertHeader('Location'))

        self.getPage("/deploy/login", method="POST",
                     body='username=foo&password=bar')
        header = self.assertHeader('Set-Cookie')
        cookie = SimpleCookie()
        cookie.load(header)

        session_id = cookie["session_id"].value
        self.getPage("/deploy/list",
                     headers=[('Cookie', f'session_id={session_id}')])
        self.assertStatus('200 OK')
        self.assertInBody('<ul class="items">')
        self.assertInBody('monetdb-import')

    def test_create(self) -> None:
        """
        Test the create page.
        """

        self.getPage("/deploy/create")
        self.assertIn('/deploy/index?page=create', self.assertHeader('Location'))

        self.getPage("/deploy/login", method="POST",
                     body='username=foo&password=bar')
        header = self.assertHeader('Set-Cookie')
        cookie = SimpleCookie()
        cookie.load(header)

        session_id = cookie["session_id"].value
        self.getPage("/deploy/create",
                     headers=[('Cookie', f'session_id={session_id}')])
        self.assertStatus('200 OK')
        self.assertInBody('<option value="build-monetdb-import">')
        self.assertInBody('</form>')

        # POSTing the creating of a deployment.
        self.getPage("/deploy/create", method="POST",
                     body="name=test",
                     headers=[('Cookie', f'session_id={session_id}')])
        self.assertStatus('200 OK')
        self.assertInBody('<a href="edit?name=test">edit the deployment</a>')
        self.assertInBody('<pre>')
        # Additional form is to create another new deployment
        self.assertInBody('<input type="text" name="name" value="">')
        self.assertInBody('</form>')

        self.deployments_write.assert_called_once_with(self.deploy_filename)

        # Creating a deployment that already exists leads to an error.
        self.getPage("/deploy/create", method="POST",
                     body="name=monetdb-import",
                     headers=[('Cookie', f'session_id={session_id}')])
        self.assertStatus('500 Internal Server Error')
        self.assertInBody("Deployment 'monetdb-import' already exists")

    def test_edit(self) -> None:
        """
        Test the edit page.
        """

        self.getPage("/deploy/edit?name=monetdb-import")
        self.assertIn('/deploy/index?page=edit&params=name%3Dmonetdb-import',
                      self.assertHeader('Location'))

        self.getPage("/deploy/login", method="POST",
                     body='username=foo&password=bar')
        header = self.assertHeader('Set-Cookie')
        cookie = SimpleCookie()
        cookie.load(header)

        session_id = cookie["session_id"].value
        self.getPage("/deploy/edit?name=monetdb-import",
                     headers=[('Cookie', f'session_id={session_id}')])
        self.assertStatus('200 OK')
        self.assertInBody('<input type="hidden" name="old_name" value="monetdb-import">')
        self.assertInBody('<input type="text" name="name" value="monetdb-import">')
        self.assertInBody('<option value="build-monetdb-import" selected="">')
        self.assertInBody('</form>')

        # Editing a deployment without a name leads to a redirect to the list.
        self.getPage("/deploy/edit",
                     headers=[('Cookie', f'session_id={session_id}')])
        self.assertIn('/deploy/list', self.assertHeader('Location'))

        # Editing an unknown deployment leads to a 404 error.
        self.getPage("/deploy/edit?name=missing",
                     headers=[('Cookie', f'session_id={session_id}')])
        self.assertStatus('404 Not Found')

        # Editing a deployment with a rename when an old name is given should
        # use the old name to find the deployment.
        self.getPage("/deploy/edit?name=missing&old_name=monetdb-import",
                     headers=[('Cookie', f'session_id={session_id}')])
        self.assertStatus('200 OK')
        self.assertInBody('<input type="hidden" name="old_name" value="monetdb-import">')
        self.assertInBody('</form>')

        # POSTing a deployment edit requires both name and old name.
        self.getPage("/deploy/edit",
                     method="POST",
                     body="name=monetdb-import",
                     headers=[('Cookie', f'session_id={session_id}')])
        self.assertStatus('400 Bad Request')
        self.assertInBody("Parameter 'old_name' required")

        # POSTing a deployment edit with parameters in body.
        self.getPage("/deploy/edit",
                     method="POST",
                     body='&'.join(["name=monetdb-import",
                                    "old_name=monetdb-import",
                                    "jenkins_job=build-monetdb-import",
                                    "bigboat_key=123456",
                                    "git_branch=main",
                                    "deploy_key=1"]),
                     headers=[('Cookie', f'session_id={session_id}')])
        self.assertStatus('200 OK')
        self.assertInBody('original deploy key')
        self.assertInBody('<pre>')
        self.assertInBody('<input type="hidden" name="old_name" value="monetdb-import">')
        self.assertInBody('<input type="text" name="name" value="monetdb-import">')
        self.assertInBody('<input type="text" name="bigboat_key" value="123456">')
        self.assertInBody('<option value="build-monetdb-import" selected="">')
        self.assertInBody('</form>')

        self.deployments_write.assert_called_once_with(self.deploy_filename)
        self.deployments_write.reset_mock()

        # Renaming a deployment (some parameters in query string).
        self.getPage("/deploy/edit?name=test&old_name=monetdb-import",
                     method="POST",
                     body="jenkins_job=build-test",
                     headers=[('Cookie', f'session_id={session_id}')])
        self.assertStatus('200 OK')
        self.assertInBody('new deploy key')
        self.assertInBody('<pre>')
        self.assertInBody('<input type="hidden" name="old_name" value="test">')
        self.assertInBody('<input type="text" name="name" value="test">')
        self.assertInBody('<option value="build-monetdb-import">')
        self.assertInBody('<option value="build-test" selected="">')
        self.assertInBody('</form>')
        self.deployments_write.assert_called_once_with(self.deploy_filename)

    def test_deploy(self) -> None:
        """
        Test the deploy page.
        """

        self.getPage("/deploy/deploy?name=monetdb-import")
        self.assertIn('/deploy/index?page=deploy&params=name%3Dmonetdb-import',
                      self.assertHeader('Location'))

        self.getPage("/deploy/login", method="POST",
                     body='username=foo&password=bar')
        header = self.assertHeader('Set-Cookie')
        cookie = SimpleCookie()
        cookie.load(header)

        # A deployment that has not started redirects to the list.
        session_id = cookie["session_id"].value
        self.getPage("/deploy/deploy?name=monetdb-import",
                     headers=[('Cookie', f'session_id={session_id}')])
        self.assertIn('/deploy/list',
                      self.assertHeader('Location'))

        # Deployment without a name leads to a redirect to the list.
        self.getPage("/deploy/deploy", method="POST",
                     headers=[('Cookie', f'session_id={session_id}')])
        self.assertIn('/deploy/list', self.assertHeader('Location'))

        with patch('deployment.application.Deploy_Task',
                   autospec=True) as thread:
            thread.configure_mock(return_value=MagicMock(spec=Deploy_Task))
            self.getPage("/deploy/deploy?name=monetdb-import", method="POST",
                         headers=[('Cookie', f'session_id={session_id}')])
            self.assertStatus('200 OK')
            self.assertInBody('The deployment of monetdb-import has started.')
            self.assertInBody('<a href="deploy?name=monetdb-import">view progress</a>')

            thread.assert_called_once()
            deployment: Deployment = thread.call_args.args[0]
            self.assertEqual(deployment['name'], 'monetdb-import')
            bus: Bus = thread.call_args.kwargs['bus']
            thread.return_value.start.assert_called_once_with()

            self.getPage("/deploy/deploy?name=monetdb-import", method="POST",
                         headers=[('Cookie', f'session_id={session_id}')])
            self.assertStatus('200 OK')
            self.assertInBody('Another deployment of monetdb-import is already underway.')
            self.assertInBody('<a href="deploy?name=monetdb-import">view progress</a>')

            self.getPage("/deploy/deploy?name=monetdb-import",
                         headers=[('Cookie', f'session_id={session_id}')])
            self.assertStatus('200 OK')
            self.assertInBody('The deployment of monetdb-import is in the "starting" state.')
            self.assertInBody('<code>Thread is starting</code>')
            self.assertInBody('<a href="deploy?name=monetdb-import">view progress</a>')

            bus.publish('deploy', 'monetdb-import', 'progress', 'Test state')

            self.getPage("/deploy/deploy?name=monetdb-import",
                         headers=[('Cookie', f'session_id={session_id}')])
            self.assertStatus('200 OK')
            self.assertInBody('The deployment of monetdb-import is in the "progress" state.')
            self.assertInBody('<code>Test state</code>')
            self.assertInBody('<a href="deploy?name=monetdb-import">view progress</a>')

            bus.publish('deploy', 'monetdb-import', 'success', 'Finished')

            self.getPage("/deploy/deploy?name=monetdb-import",
                         headers=[('Cookie', f'session_id={session_id}')])
            self.assertStatus('200 OK')
            self.assertInBody('The deployment of monetdb-import is in the "success" state.')
            self.assertInBody('<code>Finished</code>')
