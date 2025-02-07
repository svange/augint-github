import asyncio
import os
from pathlib import Path

import click
import github.GithubException
from dotenv import load_dotenv
from github import Github, Auth
from github.Repository import Repository
from github.GithubException import UnknownObjectException
from rich import print
from loguru import logger


@click.command()
@click.option("--verbose", "-v", is_flag=True, help="Print all the output.")
@click.option("--dry-run", "-d", is_flag=True, help="Run through the process, but make no changes to GitHub.")
@click.argument("filename", type=click.Path(exists=True, readable=True), default=".env")
def cli(verbose: bool, dry_run: bool, filename: click.Path):
    """
    Update GitHub repository secrets and environment variables from a .env file. Requires the values for `GH_REPO`, `GH_ACCOUNT`, and `GH_TOKEN` in your .env file. This script finds sensitive key/value pairs in FILENAME (by looking for substrins like KEY, TOKEN, SECRET, etc. in the key name) and updates the GitHub repository secrets with them. It then updates the GitHub repository environment variables with the remaining key/value pairs.
    """

    if dry_run:
        logger.info("Dry run mode enabled. No changes will be made to GitHub.")
    results = asyncio.run(perform_update(filename, verbose, dry_run))
    if verbose:
        print(results)
    total_secrets = len(results["SECRETS"])
    total_vars = len(results["VARIABLES"])
    print(f"Updated {total_secrets} secrets and {total_vars} variables.")


async def perform_update(filename: click.Path, verbose: bool = False, dry_run: bool = False):
    """
    Performs the update of the GitHub repository secrets and environment variables.
    :param filename: file to use for secrets, variables, and github repo
    :return:
    """
    if not filename:
        raise ValueError("No filename specified. Exiting to avoid an accident.")

    load_dotenv(str(filename), override=True)
    github_repo = os.environ.get("GH_REPO", None)
    github_account = os.environ.get("GH_ACCOUNT", None)

    file_path = Path(filename.__str__())
    # Read the .env file and convert it to a JSON object
    secrets = {}
    not_secrets = {}
    SECRETS_INDICATORS = ["secret", "key", "token", "bearer", "password", "pass", "pwd", "pword", "hash"]
    logger.debug(f"Reading file {file_path}")

    with file_path.open("r") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
                continue
            key, value = line.strip().split("=", 1)

            match key:
                case key if key.startswith("AWS_PROFILE"):
                    continue
                case key if any(indicator in key.casefold() for indicator in SECRETS_INDICATORS):
                    secrets[key] = value
                case _:
                    not_secrets[key] = value

    try:
        repo = get_github_repo(github_account, github_repo)
    except github.GithubException as e:
        logger.critical(f"Repo {github_repo} not found. Ensure GH_REPO and GH_ACCOUNT are in your env file.")
        exit(1)

    secret_update_result = await create_or_update_github_secrets(repo=repo, env_data=secrets, dry_run=dry_run)
    not_secret_update_result = await create_or_update_github_variables(repo=repo, env_data=not_secrets, dry_run=dry_run)

    results = {"SECRETS": secret_update_result, "VARIABLES": not_secret_update_result}

    return results


def get_github_repo(github_account, github_repo_name) -> Repository:
    """
    Get the GitHub repository object.
    :param github_account: Name of your GitHub account (i.e. your username), or the name of the organization.
    :param github_repo_name: Name of the repository.
    :return: a GitHub repository object
    """
    auth = Auth.Token(os.environ.get("GH_TOKEN", None))
    g = Github(auth=auth)
    try:
        repo = g.get_user(github_account).get_repo(github_repo_name)
    except UnknownObjectException as e:
        logger.critical(e)
        repo = g.get_organization(github_account).get_repo(github_repo_name)
        logger.critical("You must add GH_USER to your env file.")

    return repo


async def create_or_update_github_secrets(repo, env_data, dry_run: bool = False):
    """
    Create or update GitHub repository secrets.
    :param dry_run: run through the process, but make no changes to GitHub
    :param repo: the repository on which to operate
    :param env_data: the secrets and their values in a dictionary
    :return: list of results
    """
    secrets = await asyncio.to_thread(repo.get_secrets)
    secret_names = [secret.name for secret in secrets]
    dry_run_prefix = "[DRY RUN] " if dry_run else ""

    tasks = []
    for env_var_name, env_var_value in env_data.items():
        # Create or update secrets
        if env_var_name in secret_names:
            logger.info(f"{dry_run_prefix}Updating secret {env_var_name}...")
            tasks.append(asyncio.to_thread(repo.create_secret, env_var_name, env_var_value))
        else:
            logger.info(f"{dry_run_prefix}Creating secret {env_var_name}...")
            tasks.append(asyncio.to_thread(repo.create_secret, env_var_name, env_var_value))

    for secret_name in secret_names:
        if secret_name not in env_data.keys():
            logger.info(f"{dry_run_prefix}Deleting secret {secret_name}...")
            tasks.append(asyncio.to_thread(repo.delete_secret, secret_name))

    if dry_run:
        results = [secret for secret in secrets]
    else:
        results = await asyncio.gather(*tasks)
    return results


async def create_or_update_github_variables(repo, env_data, dry_run: bool = False):
    """
    Create or update GitHub repository environment variables.
    :param repo: the repository on which to operate
    :param dry_run: run through the process, but make no changes to GitHub
    :param env_data: the secrets and their values in a dictionary
    :return: list of results
    """
    vars = await asyncio.to_thread(repo.get_variables)
    var_names = [var.name for var in vars]
    dry_run_prefix = "[DRY RUN] " if dry_run else ""

    tasks = []
    for env_var_name, env_var_value in env_data.items():
        # Create or update secrets
        if env_var_name in var_names:
            logger.info(f"{dry_run_prefix}Updating variable {env_var_name}...")

            def delete_then_create_variable(repo, env_var_name, env_var_value):
                repo.delete_variable(env_var_name)
                return repo.create_variable(env_var_name, env_var_value)

            # tasks.append(asyncio.to_thread(repo.delete_variable, env_var_name))
            tasks.append(asyncio.to_thread(delete_then_create_variable, repo, env_var_name, env_var_value))
        else:
            logger.info(f"{dry_run_prefix}Creating variable {env_var_name}...")
            tasks.append(asyncio.to_thread(repo.create_variable, env_var_name, env_var_value))

    for var_name in var_names:
        if var_name not in env_data.keys():
            logger.info(f"{dry_run_prefix}Deleting variable {var_name}...")
            tasks.append(asyncio.to_thread(repo.delete_variable, var_name))

    if dry_run:
        results = [var for var in vars]
    else:
        results = await asyncio.gather(*tasks)

    return results


if __name__ == "__main__":
    cli()
