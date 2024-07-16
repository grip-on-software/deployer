"""
Tests for bootstrapping the deployer Web service.

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

from argparse import ArgumentParser
from configparser import RawConfigParser
import unittest
from unittest.mock import patch
from gatherer.config import Configuration
from deployment.bootstrap import Bootstrap_Deployer

class BootstrapDeployerTest(unittest.TestCase):
    """
    Tests for bootstrapper for the deployment interface.
    """

    def setUp(self) -> None:
        config = RawConfigParser()
        config['jenkins'] = {}
        config['jenkins']['host'] = 'http://jenkins.test'
        config['jenkins']['username'] = '-'
        config['jenkins']['password'] = '-'
        config['jenkins']['verify'] = '0'
        config['jenkins']['scrape'] = 'scrape-projects'
        config_patcher = patch.object(Configuration, 'get_settings',
                                      return_value=config)
        config_patcher.start()
        self.addCleanup(config_patcher.stop)

        argv_patcher = patch('sys.argv', new=['deployer.py'])
        argv_patcher.start()
        self.addCleanup(argv_patcher.stop)

        self.bootstrap = Bootstrap_Deployer()

    def test_properties(self) -> None:
        """
        Test properties of the bootstrapper.
        """

        self.assertEqual(self.bootstrap.application_id, 'deployer')
        self.assertIn('deployment', self.bootstrap.description)

    def test_add_args(self) -> None:
        """
        Test registering additional arguments.
        """

        parser = ArgumentParser()
        self.bootstrap.add_args(parser)
        args = parser.parse_args(['--deploy-path', 'deploy'])
        self.assertEqual(args.deploy_path, 'deploy')
