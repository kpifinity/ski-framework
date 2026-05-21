"""
Command-line interface for MiLM Deploy
"""

import click
import json
from typing import Optional

from .deployer import Deployer
from .utils import load_config, save_config


@click.group()
def main():
    """Deploy and configure the MiLM inference engine"""
    pass


@main.command()
@click.option("--name", "-n", required=True, help="Deployment name")
@click.option("--sector", "-s", required=True, help="Industry sector (energy, finance, manufacturing, defense)")
@click.option("--mode", "-m", default="docker", help="Deployment mode (docker, kubernetes, direct)")
@click.option("--output", "-o", default="deployment-config.yaml", help="Output config file")
def init(name: str, sector: str, mode: str, output: str):
    """Initialize a new MiLM deployment"""
    try:
        click.echo(f"Initializing MiLM deployment: {name}")

        deployer = Deployer()
        config = deployer.initialize(
            name=name,
            sector=sector,
            mode=mode,
            config_output=output,
        )

        click.echo(f"✓ Deployment initialized")
        click.echo(f"  Name: {config.name}")
        click.echo(f"  Sector: {config.sector}")
        click.echo(f"  Mode: {config.mode}")
        click.echo(f"\nConfiguration saved to: {output}")
        click.echo(f"\nNext steps:")
        click.echo(f"  1. Review configuration: cat {output}")
        click.echo(f"  2. Load Knowledge Graph: milm-deploy load-kg --config {output} --kg validated-rules.json")
        click.echo(f"  3. Start deployment: milm-deploy start --config {output}")

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--config", "-c", required=True, help="Deployment configuration file")
@click.option("--kg", "-kg", required=True, help="Knowledge Graph JSON file")
@click.option("--verify-signature", is_flag=True, help="Verify Knowledge Graph signature")
@click.option("--signing-cert", default=None, help="Path to signing certificate")
def load_kg(config: str, kg: str, verify_signature: bool, signing_cert: Optional[str]):
    """Load Knowledge Graph into deployment"""
    try:
        click.echo(f"Loading Knowledge Graph: {kg}")

        deployer = Deployer(config)
        if not deployer.config:
            deployer.config = load_config(config)

        deployer.load_knowledge_graph(
            kg_path=kg,
            verify_signature=verify_signature,
            signing_cert=signing_cert,
        )

        # Save updated config
        save_config(deployer.config, config)

        click.echo(f"✓ Knowledge Graph loaded")
        click.echo(f"  Version: {deployer.config.knowledge_graph.version}")
        click.echo(f"  Signature verified: {verify_signature}")

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--config", "-c", default="deployment-config.yaml", help="Deployment configuration file")
@click.option("--mode", "-m", default=None, help="Deployment mode (docker, kubernetes, direct)")
def start(config: str, mode: Optional[str]):
    """Start MiLM deployment"""
    try:
        click.echo("Starting MiLM deployment...")

        deployer = Deployer(config)
        if not deployer.config:
            deployer.config = load_config(config)

        if deployer.start(mode=mode):
            click.echo("✓ MiLM deployment started")
            click.echo(f"  Mode: {deployer.config.mode}")
            click.echo(f"\nAPI available at: http://localhost:8000")
            click.echo(f"Health check: curl http://localhost:8000/api/health")
        else:
            click.echo("✗ Failed to start deployment", err=True)
            raise SystemExit(1)

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--config", "-c", default="deployment-config.yaml", help="Deployment configuration file")
def stop(config: str):
    """Stop MiLM deployment"""
    try:
        click.echo("Stopping MiLM deployment...")

        deployer = Deployer(config)
        if not deployer.config:
            deployer.config = load_config(config)

        if deployer.stop():
            click.echo("✓ Deployment stopped")
        else:
            click.echo("✗ Failed to stop deployment", err=True)

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--config", "-c", default="deployment-config.yaml", help="Deployment configuration file")
@click.option("--endpoint", "-e", default="http://localhost:8000", help="API endpoint")
def verify(config: str, endpoint: str):
    """Verify deployment is working"""
    try:
        click.echo("Verifying deployment...")

        deployer = Deployer(config)
        if not deployer.config:
            deployer.config = load_config(config)

        if deployer.verify(endpoint=endpoint):
            click.echo("✓ Deployment is healthy")
            click.echo(f"  API: {endpoint}")
            click.echo(f"  Status: {deployer.get_status().status}")
        else:
            click.echo("✗ Deployment verification failed", err=True)
            raise SystemExit(1)

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--config", "-c", default="deployment-config.yaml", help="Deployment configuration file")
def status(config: str):
    """Get deployment status"""
    try:
        deployer = Deployer(config)
        if not deployer.config:
            deployer.config = load_config(config)

        status = deployer.get_status()

        click.echo(f"Deployment Status: {status.status}")
        click.echo(f"  Uptime: {status.uptime_seconds} seconds")
        click.echo(f"  Knowledge Graph: {status.knowledge_graph_version if status.knowledge_graph_loaded else 'Not loaded'}")
        click.echo(f"  API Health: {'✓ Healthy' if status.api_healthy else '✗ Unhealthy'}")
        click.echo(f"  Sidecar Connected: {'✓ Yes' if status.sidecar_connected else '✗ No'}")
        click.echo(f"  Verdicts Produced: {status.verdicts_produced}")
        click.echo(f"  Ledger Entries: {status.ledger_entries}")

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise SystemExit(1)


@main.command()
@click.option("--config", "-c", default="deployment-config.yaml", help="Deployment configuration file")
def health(config: str):
    """Run health checks"""
    try:
        deployer = Deployer(config)
        if not deployer.config:
            deployer.config = load_config(config)

        checks = deployer.health_check()

        click.echo("Health Checks:")
        for service, check in checks.items():
            icon = "✓" if check.status == "healthy" else "✗"
            click.echo(f"  {icon} {service}: {check.status} ({check.response_time_ms:.1f}ms)")

    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise SystemExit(1)


@main.command()
def examples():
    """Show usage examples"""
    examples_text = """
MiLM Deploy Examples:

1. Initialize a new deployment:
   milm-deploy init --name "energy-system" --sector energy

2. Load Knowledge Graph:
   milm-deploy load-kg --config deployment-config.yaml --kg validated-rules.json

3. Start deployment (Docker):
   milm-deploy start --config deployment-config.yaml

4. Verify deployment:
   milm-deploy verify --config deployment-config.yaml

5. Check deployment status:
   milm-deploy status --config deployment-config.yaml

6. Run health checks:
   milm-deploy health --config deployment-config.yaml

7. Complete deployment workflow:
   # Step 1: Extract rules
   kg-extractor extract --file regulation.txt --output extracted.json

   # Step 2: Validate rules
   kg-validator validate --input extracted.json --output validated.json

   # Step 3: Initialize deployment
   milm-deploy init --name "my-system" --sector energy

   # Step 4: Load validated rules
   milm-deploy load-kg --config deployment-config.yaml --kg validated.json

   # Step 5: Start MiLM
   milm-deploy start --config deployment-config.yaml

   # Step 6: Verify and test
   milm-deploy verify --config deployment-config.yaml
"""
    click.echo(examples_text)


@main.command()
def version():
    """Show version"""
    from . import __version__

    click.echo(f"milm-deploy {__version__}")


if __name__ == "__main__":
    main()
