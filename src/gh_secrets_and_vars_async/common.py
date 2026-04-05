import json
import os
import sys
from importlib.resources import files

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


def get_github_repo(github_account: str, github_repo_name: str) -> Repository:
    """Get the GitHub repository object.

    Tries user lookup first, falls back to organization.
    """
    token = os.environ.get("GH_TOKEN", "")
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
    """Create an authenticated Github client from GH_TOKEN env var."""
    token = os.environ.get("GH_TOKEN", "")
    auth = Auth.Token(token)
    return Github(auth=auth)


def load_template(category: str, name: str) -> dict | str:
    """Load a template file from the templates directory.

    Args:
        category: Template category ("rulesets" or "workflows").
        name: Template name without extension.

    Returns:
        Parsed dict for JSON templates, raw string for YAML templates.
    """
    template_dir = files("gh_secrets_and_vars_async") / "templates" / category
    if category == "rulesets":
        content = (template_dir / f"{name}.json").read_text()
        result: dict = json.loads(content)
        return result
    else:
        return (template_dir / f"{name}.yaml").read_text()
