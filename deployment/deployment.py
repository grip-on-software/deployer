"""
Data structures for interfacing with deployment configurations.

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

from collections import OrderedDict
from collections.abc import Mapping, MutableSet
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple, \
    Union, TYPE_CHECKING
from gatherer.domain import Source
from gatherer.git.repo import Git_Repository
from gatherer.jenkins import Jenkins, Build
from gatherer.version_control.repo import RepositorySourceException
from gatherer.version_control.review import Review_System

ConfigItem = Any
Config = Dict[str, ConfigItem]
DeploymentLike = Union[Config, 'Deployment', str]
Fields = List[Tuple[str, str, Dict[str, Any]]]
if TYPE_CHECKING:
    PathLike = Union[str, os.PathLike[str]]
else:
    PathLike = Union[str, os.PathLike]

class Deployments(MutableSet):
    """
    A set of deployments.
    """

    def __init__(self, deployments: Iterable[DeploymentLike]):
        # pylint: disable=super-init-not-called
        self._deployments: Dict[str, Deployment] = {}
        for config in deployments:
            self.add(config)

    @classmethod
    def read(cls, filename: PathLike, fields: Fields) -> 'Deployments':
        """
        Read a deployments collection from a JSON file.
        """

        path = Path(filename)
        if not path.exists():
            return cls([])

        with path.open('r', encoding='utf-8') as deploy_file:
            configs: List[Config] = json.load(deploy_file,
                                              object_pairs_hook=OrderedDict)
            for config in configs:
                for field_name, _, field_config in fields:
                    if field_name not in config:
                        config[field_name] = field_config.get("default", '')

            return cls(configs)

    def write(self, filename: PathLike) -> None:
        """
        Write the deployments to a JSON file.
        """

        with Path(filename).open('w', encoding='utf-8') as deploy_file:
            json.dump([
                dict(deployment) for deployment in self._deployments.values()
            ], deploy_file)

    @staticmethod
    def _convert(data: object) -> 'Deployment':
        if isinstance(data, Deployment):
            return data

        if isinstance(data, dict):
            return Deployment(**data)

        if isinstance(data, str):
            return Deployment(name=data)

        raise TypeError(f'Cannot convert deployment data of type {type(data)}')

    def __contains__(self, value: object) -> bool:
        try:
            deployment = self._convert(value)
        except TypeError:
            return False
        name = str(deployment["name"])
        return name in self._deployments

    def __iter__(self) -> Iterator['Deployment']:
        return iter(self._deployments.values())

    def __len__(self) -> int:
        return len(self._deployments)

    def get(self, value: DeploymentLike) -> 'Deployment':
        """
        Retrieve a Deployment object stored in this set based on the name of
        the deployment or a (partial) Deployment object or dict containing at
        least the "name" key.

        Raises a `KeyError` if the deployment is not found.
        """

        deployment = self._convert(value)
        name = str(deployment["name"])
        return self._deployments[name]

    def add(self, value: DeploymentLike) -> None:
        deployment = self._convert(value)
        name = str(deployment["name"])
        if name in self._deployments:
            # Ignore duplicate deployments
            return

        self._deployments[name] = deployment

    def discard(self, value: DeploymentLike) -> None:
        deployment = self._convert(value)
        name = str(deployment["name"])
        if name not in self._deployments:
            return

        del self._deployments[name]

    def __repr__(self) -> str:
        return f'Deployments({list(self._deployments.values())!r})'

class Deployment(Mapping):
    """
    A single deployment configuration.
    """

    def __init__(self, **config: ConfigItem):
        # pylint: disable=super-init-not-called
        self._config = config

    def get_source(self) -> Source:
        """
        Retrieve a Source object describing the version control system of
        this deployment's source code origin.
        """

        if "git_url" not in self._config:
            raise ValueError("Cannot retrieve Git repository: misconfiguration")

        # Describe Git source repository
        source = Source.from_type('git', name=str(self._config["name"]),
                                  url=str(self._config["git_url"]))
        source.credentials_path = str(self._config["deploy_key"])

        return source

    def _get_latest_source_version(self) -> \
            Tuple[Optional[Source], Optional[str]]:
        try:
            source = self.get_source()
        except ValueError:
            return None, None

        if source.repository_class is None:
            return None, None

        repo = source.repository_class(source, str(self._config["git_path"]))
        if not isinstance(repo, Git_Repository) or repo.is_empty():
            return source, None

        return source, repo.repo.head.commit.hexsha

    def get_compare_url(self) -> Optional[str]:
        """
        Retrieve a URL to a human-readable comparison page for the changes since
        the latest version.
        """

        source, latest_version = self._get_latest_source_version()
        if source is None or source.repository_class is None or \
            latest_version is None:
            return None
        if not issubclass(source.repository_class, Review_System):
            return None

        return source.repository_class.get_compare_url(source, latest_version)

    def get_tree_url(self) -> Optional[str]:
        """
        Retrieve a URL to a human-readable page showing the state of the
        repository at the latest version.
        """

        source, latest_version = self._get_latest_source_version()
        if source is None or source.repository_class is None or \
            latest_version is None:
            return None
        if not issubclass(source.repository_class, Review_System):
            return None

        return source.repository_class.get_tree_url(source, latest_version)

    def is_up_to_date(self) -> bool:
        """
        Check whether the deployment's local checkout is up to date compared
        to the upstream version.
        """

        source, latest_version = self._get_latest_source_version()
        if source is None or source.repository_class is None or \
            latest_version is None:
            return False

        branch = str(self._config.get("git_branch", "master"))
        try:
            return source.repository_class.is_up_to_date(source, latest_version,
                                                         branch=branch)
        except RepositorySourceException:
            return False

    def get_branches(self) -> List[str]:
        """
        Retrieve a list of branch names that the upstream version has.
        """

        try:
            source = self.get_source()
        except ValueError:
            return []

        if source.repository_class is None:
            return []

        try:
            return source.repository_class.get_branches(source)
        except RepositorySourceException:
            return []

    def check_jenkins(self, jenkins: Jenkins) -> Build:
        """
        Check build stability before deployment based on Jenkins job success.

        This raises a `ValueError` if any problem occurs. Otherwise, the latest
        build for the master branch is returned.
        """

        source = self.get_source()
        job = jenkins.get_job(str(self._config["jenkins_job"]))
        branch_name = str(self._config.get("git_branch", "master"))
        if job.jobs:
            # Retrieve branch job of multibranch pipeline job
            job = job.get_job(branch_name)

        # Retrieve the latest branch build job.
        build = None
        for branch in (branch_name, f'origin/{branch_name}'):
            build, branch_build = job.get_last_branch_build(branch)

            if build is not None and branch_build is not None and \
                source.repository_class is not None:
                # Retrieve the branches that were involved in this build.
                # Branch may be duplicated in case of merge strategies.
                # We only accept master branch builds if the latest build for
                # that branch not a merge request build, since the stability of
                # the master branch code is not demonstrated by this build.
                branch_data = branch_build['revision']['branch']
                branches = set(branch['name'] for branch in branch_data)
                if len(branches) > 1:
                    raise ValueError('Latest build is caused by merge request')

                if not self._config.get("jenkins_git", True):
                    break

                # Check whether the revision that was built is actually the
                # upstream repository's HEAD commit for this branch.
                revision = str(branch_build['revision']['SHA1'])
                if source.repository_class.is_up_to_date(source, revision,
                                                         branch=branch_name):
                    break

                raise ValueError('Latest build is stale compared to Git repository')

        return self._check_build(build)

    def _check_build(self, build: Optional[Build]) -> Build:
        if build is None:
            raise ValueError('Branch build could not be found')

        # Check whether the latest (branch) build is complete and successful.
        if build.building:
            raise ValueError("Build is not complete")

        states: List[str] = self._config.get("jenkins_states", ["SUCCESS"])
        result = build.result
        if result not in states:
            raise ValueError(f"Build result was not {' or '.join(states)}, but {result}")

        return build

    def __getitem__(self, item: str) -> ConfigItem:
        return self._config[item]

    def __iter__(self) -> Iterator[str]:
        return iter(self._config)

    def __len__(self) -> int:
        return len(self._config)

    def __repr__(self) -> str:
        return 'Deployment(name={self._config["name"]!r})'
