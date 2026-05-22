"""Command-line interface for ski-model-deploy."""

from __future__ import annotations

import json
from typing import Optional

import click

from .deployer import Deployer, UnsignedKGError
from .utils import load_config, save_config


@click.group()
def main() -> None:
    """Deploy and configure the SKI Model inference engine."""


@main.command()
@click.option("--name", "-n", required=True, help="Deployment name")
@click.option("--sector", "-s", required=True, help="Industry sector (energy, finance, manufacturing, defense)")
@click.option("--mode", "-m", default="docker", help="Deployment mode (docker, kubernetes, direct)")
@click.option("--output", "-o", default="deployment-config.yaml", help="Output config file")
def init(name: str, sector: str, mode: str, output: str) -> None:
    """Initialise a new SKI Model deployment configuration."""
    deployer = Deployer()
    config = deployer.initialize(name=name, sector=sector, mode=mode, config_output=output)
    click.echo("✓ Deployment initialised")
    click.echo(f"  Name:   {config.name}")
    click.echo(f"  Sector: {config.sector}")
    click.echo(f"  Mode:   {config.mode}")
    click.echo(f"\nConfiguration saved to: {output}")
    click.echo("\nNext steps:")
    click.echo(f"  1. Review:           cat {output}")
    click.echo(f"  2. Load signed KG:   ski-model-deploy load-kg --config {output} --kg signed-kg.json")
    click.echo(f"  3. Start the stack:  ski-model-deploy start --config {output}")


@main.command(name="load-kg")
@click.option("--config", "-c", required=True, help="Deployment configuration file")
@click.option("--kg", "-k", required=True, help="Knowledge Graph JSON file (MUST be signed)")
def load_kg(config: str, kg: str) -> None:
    """Verify a signed Knowledge Graph and register it with a deployment.

    Signature verification is MANDATORY. There is no override flag here.
    To load an unsigned KG you would have to disable signature checking
    on the server itself (KG_REQUIRE_SIGNATURE=false), which makes the
    deployment non-conformant.
    """
    try:
        deployer = Deployer(config)
        if not deployer.config:
            deployer.config = load_config(config)
        deployer.load_knowledge_graph(kg_path=kg)
        save_config(deployer.config, config)
        click.echo("✓ Knowledge Graph signature verified and registered.")
        click.echo(f"  Version: {deployer.config.knowledge_graph.version}")
        click.echo(f"  Path:    {deployer.config.knowledge_graph.path}")
    except UnsignedKGError as exc:
        click.echo(f"✗ Refused to load: {exc}", err=True)
        raise SystemExit(1)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--config", "-c", required=True, help="Deployment configuration file")
def start(config: str) -> None:
    """Start a deployed SKI Model stack."""
    deployer = Deployer(config)
    if not deployer.config:
        deployer.config = load_config(config)
    if deployer.start():
        click.echo("✓ Deployment started.")
    else:
        click.echo("✗ Start failed.", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--config", "-c", required=True, help="Deployment configuration file")
def stop(config: str) -> None:
    deployer = Deployer(config)
    if not deployer.config:
        deployer.config = load_config(config)
    if deployer.stop():
        click.echo("✓ Deployment stopped.")
    else:
        click.echo("✗ Stop failed.", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--config", "-c", required=True, help="Deployment configuration file")
def status(config: str) -> None:
    deployer = Deployer(config)
    if not deployer.config:
        deployer.config = load_config(config)
    s = deployer.get_status()
    click.echo(json.dumps(s.model_dump(), indent=2, default=str))


if __name__ == "__main__":  # pragma: no cover
    main()
