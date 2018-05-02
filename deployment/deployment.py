"""
Data structures for interfacing with deployment configurations.
"""

from collections import Mapping, MutableSet, OrderedDict
import json
import os.path
from gatherer.domain import Source
from gatherer.version_control.repo import RepositorySourceException
from gatherer.version_control.review import Review_System

class Deployments(MutableSet):
    """
    A set of deployments.
    """

    def __init__(self, deployments):
        # pylint: disable=super-init-not-called
        self._deployments = {}
        for config in deployments:
            self.add(config)

    @classmethod
    def read(cls, filename):
        """
        Read a deployments collection from a JSON file.
        """

        if os.path.exists(filename):
            with open(filename) as deploy_file:
                return cls(json.load(deploy_file,
                                     object_pairs_hook=OrderedDict))
        else:
            return cls([])

    def write(self, filename):
        """
        Write the deployments to a JSON file.
        """

        with open(filename, 'w') as deploy_file:
            json.dump([
                dict(deployment) for deployment in self._deployments.values()
            ], deploy_file)

    @staticmethod
    def _convert(data):
        if isinstance(data, Deployment):
            return data

        if isinstance(data, dict):
            return Deployment(**data)

        return Deployment(name=data)

    def __contains__(self, value):
        deployment = self._convert(value)
        return deployment["name"] in self._deployments

    def __iter__(self):
        return iter(self._deployments.values())

    def __len__(self):
        return len(self._deployments)

    def get(self, value):
        """
        Retrieve a Deployment object stored in this set based on the name of
        the deployment or a (partial) Deployment object or dict containing at
        least the "name" key.

        Raises a `KeyError` if the deployment is not found.
        """

        deployment = self._convert(value)
        name = deployment["name"]
        return self._deployments[name]

    def add(self, value):
        deployment = self._convert(value)
        name = deployment["name"]
        if name in self._deployments:
            # Ignore duplicate deployments
            return

        self._deployments[name] = deployment

    def discard(self, value):
        deployment = self._convert(value)
        name = deployment["name"]
        if name not in self._deployments:
            return

        del self._deployments[name]

    def __repr__(self):
        return 'Deployments({!r})'.format(list(self._deployments.values()))

class Deployment(Mapping):
    """
    A single deployment configuration.
    """

    def __init__(self, **config):
        # pylint: disable=super-init-not-called
        self._config = config

    def get_source(self):
        """
        Retrieve a Source object describing the version control system of
        this deployment's source code origin.
        """

        if "git_url" not in self._config:
            raise ValueError("Cannot retrieve Git repository: misconfiguration")

        # Describe Git source repository
        source = Source.from_type('git', name=self._config["name"],
                                  url=self._config["git_url"])
        source.credentials_path = self._config["deploy_key"]

        return source

    def _get_latest_source_version(self):
        try:
            source = self.get_source()
        except ValueError:
            return None, None

        if source.repository_class is None:
            return None, None

        repo = source.repository_class(source, self._config["git_path"])
        if not repo.exists():
            return source, None

        return source, repo.repo.head.commit.hexsha

    def get_compare_url(self):
        """
        Retrieve a URL to a human-readable comparison page for the changes since
        the latest version.
        """

        source, latest_version = self._get_latest_source_version()
        if latest_version is None:
            return None
        if not issubclass(source.repository_class, Review_System):
            return None

        return source.repository_class.get_compare_url(source, latest_version)

    def get_tree_url(self):
        """
        Retrieve a URL to a human-readable page showing the state of the
        repository at the latest version.
        """

        source, latest_version = self._get_latest_source_version()
        if latest_version is None:
            return None
        if not issubclass(source.repository_class, Review_System):
            return None

        return source.repository_class.get_tree_url(source, latest_version)

    def is_up_to_date(self):
        """
        Check whether the deployment's local checkout is up to date compared
        to the upstream version.
        """

        source, latest_version = self._get_latest_source_version()
        if latest_version is None:
            return False

        try:
            return source.repository_class.is_up_to_date(source, latest_version)
        except RepositorySourceException:
            return False

    def check_jenkins(self, jenkins):
        """
        Check build stability before deployment based on Jenkins job success.

        This raises a `ValueError` if any problem occurs. Otherwise, the latest
        build for the master branch is returned.
        """

        source = self.get_source()
        job = jenkins.get_job(self._config["jenkins_job"])
        if job.jobs:
            # Retrieve master branch job of multibranch pipeline job
            job = job.get_job('master')

        # Retrieve the latest branch build job.
        build = None
        for branch in ('master', 'origin/master'):
            build, branch_build = job.get_last_branch_build(branch)

            if build is not None:
                # Retrieve the branches that were involved in this build.
                # Branch may be duplicated in case of merge strategies.
                # We only accept master branch builds if the latest build for
                # that branch not a merge request build, since the stability of
                # the master branch code is not demonstrated by this build.
                branch_data = branch_build['revision']['branch']
                branches = set([branch['name'] for branch in branch_data])
                if len(branches) > 1:
                    raise ValueError('Latest build is caused by merge request')

                # Check whether the revision that was built is actually the
                # upstream repository's HEAD commit for this branch.
                revision = branch_build['revision']['SHA1']
                if not source.repository_class.is_up_to_date(source, revision):
                    raise ValueError('Latest build is stale compared to Git repository')

                break

        if build is None:
            raise ValueError('Master branch build could not be found')

        # Check whether the latest (branch) build is complete and successful.
        if build.building:
            raise ValueError("Build is not complete")
        if build.result != "SUCCESS":
            raise ValueError("Build result was not success, but {}".format(build.result))

        return build

    def __getitem__(self, item):
        return self._config[item]

    def __iter__(self):
        return iter(self._config)

    def __len__(self):
        return len(self._config)

    def __repr__(self):
        return 'Deployment(name={!r})'.format(self._config["name"])
