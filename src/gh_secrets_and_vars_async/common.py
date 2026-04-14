import os
import subprocess
import sys

from dotenv import load_dotenv
from github import Auth, Github
from github.GithubException import UnknownObjectException
from github.Repository import Repository
from loguru import logger


def configure_logging(verbose: bool) -> None:
    """Configure loguru: silent by default, compact format with --verbose."""
    logger.remove()
    if verbose:
        logger.add(sys.stderr, level="DEBUG", format="  {message}")


def load_env_config(filename: str = ".env") -> tuple[str, str, str]:
    """Load .env file and return (GH_REPO, GH_ACCOUNT, GH_TOKEN)."""
    load_dotenv(filename, override=True)
    gh_repo = os.environ.get("GH_REPO", "")
    gh_account = os.environ.get("GH_ACCOUNT", "")
    gh_token = os.environ.get("GH_TOKEN", "")
    return gh_repo, gh_account, gh_token


def _resolve_token() -> str:
    """Return a GitHub token from GH_TOKEN env var or ``gh auth token`` CLI."""
    token = os.environ.get("GH_TOKEN", "").strip()
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            check=True,
        )
        token = result.stdout.strip()
        if token:
            return token
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    raise RuntimeError(
        "No GitHub token found. Set GH_TOKEN in .env / environment, "
        "or authenticate with: gh auth login"
    )


def get_github_repo(github_account: str, github_repo_name: str) -> Repository:
    """Get the GitHub repository object.

    Tries user lookup first, falls back to organization.
    """
    token = _resolve_token()
    auth = Auth.Token(token)
    g = Github(auth=auth)
    try:
        repo = g.get_user(github_account).get_repo(github_repo_name)
    except UnknownObjectException as e:
        logger.critical(e)
        repo = g.get_organization(github_account).get_repo(github_repo_name)
        logger.critical("You must add GH_USER to your env file.")

    return repo


def get_github_client() -> Github:
    """Create an authenticated Github client from GH_TOKEN or ``gh auth token``."""
    token = _resolve_token()
    auth = Auth.Token(token)
    return Github(auth=auth)
