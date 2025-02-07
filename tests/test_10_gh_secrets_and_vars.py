import asyncio
import os

import click
import pytest
from click.testing import CliRunner

from gh_secrets_and_vars_async import cli, perform_update


# from src.gh_secrets_and_vars import cli


@pytest.fixture(scope="module")
def env_file():
    """Fixture for the environment file."""
    # get path to current file
    current_file = __file__
    # get the directory path
    current_dir = os.path.dirname(current_file)
    # get the parent directory
    resources_dir = os.path.join(current_dir, "resources")
    # get the file path
    filename = os.path.join(resources_dir, "test.env")
    return filename


class TestGitHubSecretsAndVars:
    @pytest.mark.xfail(reason="secrets not working in CI or something...")
    @pytest.mark.skip_ci
    def test_perform_update(self, env_file):
        """
        Test the function that updates secrets and environment variables.
        :return:
        """
        results = asyncio.run(perform_update(env_file, True, True))
        assert results is not None

    @pytest.mark.xfail(reason="can't auth in CI")
    @pytest.mark.skip_ci
    def test_cli_invoke(self, env_file):
        """
        Test the CLI for creating and updating secrets and environment variables.
        :return:
        """
        runner = CliRunner()
        result = runner.invoke(cli, ["-d", env_file])
        assert result.exit_code == 0
