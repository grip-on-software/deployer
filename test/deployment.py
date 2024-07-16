"""
Tests for data structures that interface with deployment configurations.

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

import json
from pathlib import Path
from typing import Dict, List, Type, Union
import unittest
from unittest.mock import MagicMock, patch
import requests_mock
from gatherer.git.repo import Git_Repository
from gatherer.jenkins import Jenkins
from gatherer.version_control.repo import RepositorySourceException
from deployment.deployment import Config, Deployments, Deployment, Fields

class DeploymentsTest(unittest.TestCase):
    """
    Tests for sets of deployments.
    """

    fields: Fields = [
        ("jenkins_job", "Jenkins job", {"type": "job"}),
        ("extra_stuff", "Ignored", {"default": "bla"})
    ]

    def setUp(self) -> None:
        self.filename = Path('test/sample/deploy/deployment.json')
        self.deployments = Deployments.read(self.filename, self.fields)

    def test_read(self) -> None:
        """
        Test reading a deployments collection from a JSON file.
        """

        self.assertEqual(len(self.deployments), 1)
        with self.filename.open('r', encoding='utf-8') as deploy_file:
            deploys: List[Config] = json.load(deploy_file)
            for deploy in deploys:
                self.assertIn(deploy['name'], self.deployments)
                deployment = self.deployments.get(deploy)
                self.assertEqual(deployment['jenkins_job'],
                                 deploy.get('jenkins_job', ''))
                self.assertEqual(deployment['extra_stuff'], 'bla')

        deployments = Deployments.read('test/sample/missing_file.json',
                                       self.fields)
        self.assertEqual(len(deployments), 0)

    def test_write(self) -> None:
        """
        Test writing the deployments to a JSON file.
        """

        with patch('deployment.deployment.Path', autospec=True) as path:
            with patch('deployment.deployment.json.dump',
                       autospec=True) as json_dump:
                self.deployments.write(self.filename)
                path.assert_called_once_with(self.filename)
                opener = path.return_value.open
                opener.assert_called_once_with('w', encoding='utf-8')
                opener.return_value.__enter__.assert_called_once_with()
                file = opener.return_value.__enter__.return_value
                json_dump.assert_called_once()
                self.assertEqual(json_dump.call_args.args[1], file)

    def test_contains(self) -> None:
        """
        Test the membership operation.
        """

        self.assertIn('monetdb-import', self.deployments)
        self.assertIn({'name': 'monetdb-import'}, self.deployments)
        deployment = self.deployments.get('monetdb-import')
        self.assertIn(deployment, self.deployments)
        self.assertNotIn('other', self.deployments)
        self.assertNotIn(False, self.deployments)

    def test_iter(self) -> None:
        """
        Test the iterator operation.
        """

        count = 0
        for deployment in iter(self.deployments):
            count += 1
            self.assertEqual(deployment['name'], 'monetdb-import')
        self.assertEqual(count, 1)

    def test_len(self) -> None:
        """
        Test the length operation.
        """

        self.assertEqual(len(self.deployments), 1)

    def test_get(self) -> None:
        """
        Test retrieving a deployment.
        """

        self.assertEqual(self.deployments.get('monetdb-import')['name'],
                         'monetdb-import')
        with self.assertRaises(KeyError):
            self.deployments.get('missing')

    def test_add(self) -> None:
        """
        Test adding a deployment to the set.
        """

        self.deployments.add('other')
        deployment = self.deployments.get('other')
        self.assertEqual(deployment['name'], 'other')

        # Duplicate deployments are ignored.
        self.deployments.add({
            'name': 'other',
            'foo': 'ignored'
        })
        self.assertEqual(self.deployments.get('other'), deployment)
        self.assertNotIn('foo', deployment)

    def test_discard(self) -> None:
        """
        Test removing a deployment.
        """

        self.deployments.discard('monetdb-import')
        self.assertNotIn('monetdb-import', self.deployments)

        # Missing deployments can be safely discarded.
        self.deployments.discard('other')
        self.assertNotIn('other', self.deployments)

    def test_repr(self) -> None:
        """
        Test retrieving a string representation of the deployments.
        """

        self.assertEqual(repr(Deployments([])), 'Deployments([])')
        self.assertEqual(repr(self.deployments),
                         "Deployments([Deployment(name='monetdb-import')])")

class DeploymentTest(unittest.TestCase):
    """
    Tests for single deployment configuration.
    """

    def setUp(self) -> None:
        self.deployment = Deployment(name='test',
                                     git_url='https://gitlab.test/foo/bar',
                                     git_path='test/sample/test-repo',
                                     jenkins_job='test-job',
                                     deploy_key='test/sample/deploy/test-key')

        repo_patcher = patch('gatherer.git.repo.Git_Repository')
        self.repo = repo_patcher.start()
        repo_attrs = {'is_empty.return_value': False}
        self.repo.return_value.mock_add_spec(Git_Repository)
        self.repo.return_value.configure_mock(**repo_attrs)
        self.addCleanup(repo_patcher.stop)

    def test_get_source(self) -> None:
        """
        Test retrieving a Source object describing the version control system
        of the deployment.
        """

        source = self.deployment.get_source()
        self.assertEqual(source.type, 'git')
        self.assertEqual(source.name, 'test')
        self.assertEqual(source.plain_url, 'https://gitlab.test/foo/bar')
        self.assertEqual(source.credentials_path,
                         Path('test/sample/deploy/test-key'))

        with self.assertRaises(ValueError):
            Deployment(name='sparse').get_source()

    def test_get_compare_url(self) -> None:
        """
        Test retrieving a URL to a human-readable comparison page.
        """

        source = MagicMock(repository_class=self.repo)
        with patch.object(self.deployment, 'get_source', return_value=source):
            with patch('deployment.deployment.issubclass', return_value=True):
                url = 'https://gitlab.test/foo/bar/compare/abc123...master'
                attrs = {'get_compare_url.return_value': url}
                self.repo.configure_mock(**attrs)

                self.assertEqual(self.deployment.get_compare_url(), url)
                self.repo.get_compare_url.assert_called_once()

            # If the source repository class is not a review system, then we
            # cannot provide a human-readable URL.
            with patch('deployment.deployment.issubclass', return_value=False):
                self.assertIsNone(self.deployment.get_compare_url())

        # If there is no repository class for the source, then there is no URL.
        with patch.object(self.deployment, 'get_source',
                          return_value=MagicMock(repository_class=None)):
            self.assertIsNone(self.deployment.get_compare_url())

        # A deployment with no Git data has no URL.
        self.assertIsNone(Deployment(name='sparse').get_compare_url())

    def test_get_tree_url(self) -> None:
        """
        Test retrieving a URL to a human-readable repository state page.
        """

        source = MagicMock(repository_class=self.repo)
        with patch.object(self.deployment, 'get_source', return_value=source):
            with patch('deployment.deployment.issubclass', return_value=True):
                tree_url = 'https://gitlab.test/foo/bar/tree/master'
                attrs = {'get_tree_url.return_value': tree_url}
                self.repo.configure_mock(**attrs)

                self.assertEqual(self.deployment.get_tree_url(), tree_url)
                self.repo.get_tree_url.assert_called_once()

            # If the source repository class is not a review system, then we
            # cannot provide a human-readable URL.
            with patch('deployment.deployment.issubclass', return_value=False):
                self.assertIsNone(self.deployment.get_tree_url())

        # If there is no repository class for the source, then there is no URL.
        with patch.object(self.deployment, 'get_source',
                          return_value=MagicMock(repository_class=None)):
            self.assertIsNone(self.deployment.get_tree_url())

        # A deployment with no Git data has no URL.
        self.assertIsNone(Deployment(name='sparse').get_tree_url())

    def test_is_up_to_date(self) -> None:
        """
        Test checking whether the deployment's local checkout is up to date.
        """

        source = MagicMock(repository_class=self.repo)
        with patch.object(self.deployment, 'get_source', return_value=source):
            attrs: Dict[str, Union[bool, Type[Exception]]] = {
                'is_up_to_date.return_value': True
            }
            self.repo.configure_mock(**attrs)

            self.assertTrue(self.deployment.is_up_to_date())
            self.repo.is_up_to_date.assert_called_once()

            attrs = {'is_up_to_date.side_effect': RepositorySourceException}
            self.repo.configure_mock(**attrs)
            self.assertFalse(self.deployment.is_up_to_date())

        # If there is no repository class, then we assume not up to date.
        with patch.object(self.deployment, 'get_source',
                          return_value=MagicMock(repository_class=None)):
            self.assertFalse(self.deployment.is_up_to_date())

        # A deployment with no Git data is not up to date.
        self.assertFalse(Deployment(name='sparse').is_up_to_date())

    def test_get_branches(self) -> None:
        """
        Test retrieving branches that the upstream has.
        """

        source = MagicMock(repository_class=self.repo)
        with patch.object(self.deployment, 'get_source', return_value=source):
            attrs: Dict[str, Union[List[str], Type[Exception]]] = {
                'get_branches.return_value': ['master', 'my-feature', 'test']
            }
            self.repo.configure_mock(**attrs)

            self.assertEqual(self.deployment.get_branches(),
                             ['master', 'my-feature', 'test'])
            self.repo.get_branches.assert_called_once()

            attrs = {'get_branches.side_effect': RepositorySourceException}
            self.repo.configure_mock(**attrs)
            self.assertEqual(self.deployment.get_branches(), [])

        # If there is no repository class, then there are no branches.
        with patch.object(self.deployment, 'get_source',
                          return_value=MagicMock(repository_class=None)):
            self.assertEqual(self.deployment.get_branches(), [])

        # A deployment with no Git data has no branches.
        self.assertEqual(Deployment(name='sparse').get_branches(), [])

    def test_check_jenkins(self) -> None:
        """
        Test checking build stability based on Jenkins job success.
        """

        # Set up Jenkins API adapter with crumb issuer and job route
        adapter = requests_mock.Adapter()
        adapter.register_uri('GET', '/crumbIssuer/api/json', status_code=404)
        adapter.register_uri('GET', '/job/test-job/api/json', json={
            'jobs': [{'name': 'master'}]
        })
        adapter.register_uri('GET', '/job/test-job/job/master/api/json', json={
            'lastBuild': 2,
            'builds': [
                {'number': 1},
                {'number': 2}
            ]
        })
        branch_data = [{'name': 'master'}]
        build_data = {
            'number': 2,
            'building': False,
            'result': 'SUCCESS',
            'actions': [
                {
                    'buildsByBranchName': {
                        'origin/master': {
                            'buildNumber': 2,
                            'revision': {
                                'SHA1': 'abcd1234',
                                'branch': branch_data
                            }
                        }
                    }
                }
            ]
        }
        adapter.register_uri('GET',
                             '/job/test-job/job/master/lastBuild/api/json',
                             json=build_data)
        branch_build_url = '/job/test-job/job/master/1/api/json'
        adapter.register_uri('GET', branch_build_url, json=build_data)
        jenkins_host = 'http+mock://jenkins.test/'
        jenkins = Jenkins(jenkins_host)
        jenkins.mount(adapter, prefix=jenkins_host)

        source = MagicMock(repository_class=self.repo)
        with patch.object(Deployment, 'get_source', return_value=source):
            attrs: Dict[str, bool] = {'is_up_to_date.return_value': True}
            self.repo.configure_mock(**attrs)

            build = self.deployment.check_jenkins(jenkins)
            self.assertEqual(build.number, 2)
            self.repo.is_up_to_date.assert_called_once_with(source, 'abcd1234',
                                                            branch='master')

            stateless = Deployment(name='sparse',
                                   jenkins_job='test-job',
                                   jenkins_states='oops')
            with self.assertRaisesRegex(TypeError,
                                        ".*jenkins_states is not a list.*"):
                stateless.check_jenkins(jenkins)

            attrs = {'is_up_to_date.return_value': False}
            self.repo.configure_mock(**attrs)
            with self.assertRaisesRegex(ValueError, 'Latest build is stale'):
                self.deployment.check_jenkins(jenkins)

            self.repo.is_up_to_date.reset_mock()

            deployment = Deployment(jenkins_git=False,
                                    **{
                                        key: self.deployment[key]
                                        for key in self.deployment
                                    })
            build = deployment.check_jenkins(jenkins)
            self.assertEqual(build.number, 2)
            self.repo.is_up_to_date.assert_not_called()

            # A non-sucessful result in the build data is seen as problematic.
            build_data['result'] = 'UNSTABLE'
            adapter.register_uri('GET', branch_build_url, json=build_data)
            with self.assertRaisesRegex(ValueError,
                                        'Build .*not SUCCESS.* but UNSTABLE'):
                deployment.check_jenkins(jenkins)

            # A building state in the build data is seen as incomplete build.
            build_data['building'] = True
            adapter.register_uri('GET', branch_build_url, json=build_data)
            with self.assertRaisesRegex(ValueError, 'Build is not complete'):
                deployment.check_jenkins(jenkins)

            # An added branch to the build data is seen as a merge request.
            branch_data.append({'name': 'my-feature-branch'})
            adapter.register_uri('GET', branch_build_url, json=build_data)
            with self.assertRaisesRegex(ValueError,
                                        'Latest build is caused by .* request'):
                deployment.check_jenkins(jenkins)

            # Test missing data on a non-multibranch pipeline job.
            adapter.register_uri('GET', '/job/test-job/api/json', json={})
            build_url = '/job/test-job/lastBuild/api/json'
            adapter.register_uri('GET', build_url, json={'actions': []})
            with self.assertRaisesRegex(ValueError,
                                        'Branch build could not be found'):
                deployment.check_jenkins(jenkins)

    def test_getitem(self) -> None:
        """
        Test retrieving a configuration item by key through subscription.
        """

        self.assertEqual(self.deployment['name'], 'test')
        self.assertEqual(self.deployment['jenkins_job'], 'test-job')
        with self.assertRaises(KeyError):
            self.assertIsNotNone(self.deployment['missing'])

    def test_iter(self) -> None:
        """
        Test the iterator operation.
        """

        keys = []
        for key in iter(self.deployment):
            keys.append(key)
        self.assertEqual(set(keys), {
            'name', 'git_url', 'git_path', 'jenkins_job', 'deploy_key'
        })
        self.assertEqual(len(keys), 5)

    def test_len(self) -> None:
        """
        Test the length operation.
        """

        self.assertEqual(len(self.deployment), 5)

    def test_repr(self) -> None:
        """
        Test retrieving a string representation of the deployment.
        """

        self.assertEqual(repr(self.deployment), "Deployment(name='test')")
