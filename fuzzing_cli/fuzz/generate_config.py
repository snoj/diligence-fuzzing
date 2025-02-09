from os.path import commonpath, relpath
from pathlib import Path
from typing import List

import click
import inquirer
from click import BadParameter, UsageError, style
from ruamel.yaml import YAML

from fuzzing_cli.fuzz.config import update_config
from fuzzing_cli.fuzz.config.template import generate_yaml
from fuzzing_cli.fuzz.ide import IDERepository
from fuzzing_cli.util import sol_files_by_directory

yaml = YAML()
yaml.indent(offset=2)

CPU_MIN = 1
CPU_MAX = 4

QM = f"[{style('?', fg='yellow')}]"


def __prompt_ide() -> str:
    repo = IDERepository.get_instance()
    IDEs_list = [i.capitalize() for i in repo.list_ide().keys()]
    answers = inquirer.prompt(
        [inquirer.List("ide", message="Please select IDE", choices=IDEs_list)]
    )
    if not answers or not answers.get("ide"):
        raise UsageError("You must select IDE")
    return answers["ide"].lower()


def determine_ide(confirm=False) -> str:
    repo = IDERepository.get_instance()
    _IDEClass = repo.detect_ide()
    if not _IDEClass:
        ide_name = __prompt_ide()
    elif not confirm and not click.confirm(
        f"{QM} You seem to be using {_IDEClass.get_name().capitalize()}, is that correct?",
        default=True,
    ):
        ide_name = __prompt_ide()
    else:
        ide_name = _IDEClass.get_name()

    return ide_name


def __select_targets(targets: List[str]) -> List[str]:
    files = []
    files_in_dirs = []
    for target in targets:
        if Path(target).is_dir():
            files_in_dirs.extend(sorted(sol_files_by_directory(target)))
        else:
            files.append(target)

    if len(files_in_dirs) > 0:
        if click.confirm(
            f"{QM} Directories contain source files. Do you want to select them individually?"
        ):
            answers = inquirer.prompt(
                [
                    inquirer.Checkbox(
                        "targets",
                        message="Please select target files (SPACE to select, RETURN to finish)",
                        choices=[
                            (relpath(t, Path.cwd().absolute()), t)
                            for t in files_in_dirs
                        ],
                    )
                ]
            )
            if not answers["targets"]:
                click.secho(
                    "⚠️  No targets are selected, please configure them manually in a config file"
                )
            targets = answers.get("targets", []) + files
    return targets


def __prompt_targets() -> List[str]:
    target = click.prompt(
        f"{QM} Specify folder(s) or smart-contract(s) (comma-separated) to fuzz"
    )
    targets = [
        t.strip()
        if Path(t.strip()).is_absolute()
        else str(Path.cwd().absolute().joinpath(t.strip()))
        for t in target.split(",")
    ]
    return targets


def determine_targets(ide: str) -> List[str]:
    repo = IDERepository.get_instance()
    _IDEArtifactsClass = repo.get_ide(ide)
    target = _IDEArtifactsClass.get_default_sources_dir()
    ts = style(target, fg="yellow")

    targets = [str(target)]

    if target.exists() and target.is_dir():
        if not click.confirm(
            f"{QM} Is {ts} correct directory to fuzz contracts from?", default=True
        ):
            targets = __prompt_targets()

    elif click.confirm(
        f"{QM} We couldn't find any contracts at {ts}. Have you configured a custom contracts sources directory?",
        default=True,
    ):
        targets = __prompt_targets()

    return __select_targets(targets)


def determine_build_dir(ide: str) -> str:
    repo = IDERepository.get_instance()
    _IDEArtifactsClass = repo.get_ide(ide)

    build_dir = Path(_IDEArtifactsClass.get_default_build_dir())
    if not build_dir.is_absolute():
        build_dir = Path.cwd().absolute().joinpath(build_dir)

    message = f"{QM} Specify build directory path"
    bds = style(build_dir, fg="yellow")

    if build_dir.exists() and build_dir.is_dir():
        if not click.confirm(
            f"{QM} Is {bds} correct build directory for the project?", default=True
        ):
            build_dir = str(click.prompt(message)).strip()
    elif click.confirm(
        f"{QM} We couldn't find build directory at {bds}. Have you configured a custom build directory?",
        default=True,
    ):
        build_dir = str(click.prompt(message)).strip()

    if not Path(build_dir).is_absolute():
        build_dir = str(Path.cwd().absolute().joinpath(build_dir))

    return str(build_dir)


def determine_rpc_url() -> str:
    rpc_url = click.prompt(
        f"{QM} Specify RPC URL to get seed state from (e.g. local Ganache instance)",
        default="http://localhost:8545",
    )
    return rpc_url


def determine_cpu_cores() -> int:
    def value_proc(value, *args, **kwargs) -> int:
        try:
            val = int(value)
            if CPU_MIN <= val <= CPU_MAX:
                return val
            raise BadParameter("CPU cores should be >= 1 and <= 4")
        except ValueError:
            raise BadParameter("{} is not a valid integer".format(value))

    cpu_cores = click.prompt(
        f"{QM} Specify CPU cores (1-4) to be used for fuzzing",
        default=1,
        value_proc=value_proc,
    )
    return cpu_cores


def determine_campaign_name() -> str:
    name = Path.cwd().name.lower().replace("-", "_")
    name = click.prompt(
        f"{QM} Now set fuzzing campaign name prefix", default=name, show_default=True
    )
    return name


def determine_sources_dir(targets: List[str]) -> str:
    if len(targets) == 1:
        if Path(targets[0]).is_dir():
            # looks like contracts directory
            return targets[0]
        # return parent folder of the contract file
        return str(Path(targets[0]).parent)
    # return common parent of target files
    return commonpath(targets)


def recreate_config(config_file: str):
    ide = determine_ide()
    targets = determine_targets(ide)
    build_dir = determine_build_dir(ide)
    rpc_url = determine_rpc_url()
    number_of_cores = determine_cpu_cores()
    campaign_name_prefix = determine_campaign_name()

    config_path = Path().cwd().joinpath(config_file)

    sources_directory = determine_sources_dir(targets)

    click.echo(
        f"⚡️ Alright! Generating config at {style(config_path, fg='yellow', italic=True)}"
    )

    with config_path.open("w") as f:
        f.write(
            generate_yaml(
                {
                    "ide": ide,
                    "build_directory": build_dir,
                    "sources_directory": sources_directory,
                    "targets": targets,
                    "rpc_url": rpc_url,
                    "number_of_cores": number_of_cores,
                    "campaign_name_prefix": campaign_name_prefix,
                    "no-assert": True,
                    "quick_check": False,
                }
            )
        )
        f.flush()

    click.echo("Done 🎉")


def sync_config(config_file: Path):
    ide = determine_ide(confirm=True)
    targets = determine_targets(ide)

    click.echo(
        f"⚡️ Alright! Syncing config at {style(str(config_file), fg='yellow', italic=True)}"
    )
    update_config(config_file, {"fuzz": {"targets": targets}})
    click.echo("Done 🎉")


@click.command("generate-config")
@click.option("--sync", help="Option to update targets", is_flag=True, default=False)
@click.argument("config-file", type=click.Path(), default=".fuzz.yml", nargs=1)
@click.pass_obj
def fuzz_generate_config(ctx, config_file, sync: bool) -> None:
    """Generate config file for fuzzing

    CONFIG_FILE config file name (default is .fuzz.yml)
    """
    cfs = style(config_file, fg="yellow")
    if sync:
        config_file = Path.cwd().joinpath(config_file)
        if not config_file.exists() or not config_file.is_file():
            command = style(
                f"fuzz generate-config {config_file}", italic=True, fg="green"
            )
            raise click.UsageError(
                f"⚠️  Config file {cfs} does not exist. "
                f"Please create one either manually or using {command} command"
            )
        return sync_config(config_file)
    if Path(config_file).exists():
        command = style(
            f"fuzz generate-config {config_file} --sync", italic=True, fg="green"
        )
        raise click.UsageError(
            f"⚠️  Config file {cfs} already exists. "
            f"Please specify another file or run {command} to update one."
        )
    recreate_config(config_file)
