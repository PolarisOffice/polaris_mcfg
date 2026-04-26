"""CLI entry point. Subcommands are added by each milestone module."""
from __future__ import annotations

import click

from . import __version__


@click.group(help="Polaris MCFG — Metric-Compatible Font Generator")
@click.version_option(__version__, "-V", "--version")
def main() -> None:
    pass


# Subcommands registered lazily as milestones land.
try:
    from .extractor import extract_cmd
    main.add_command(extract_cmd, name="extract")
except ImportError:
    pass

try:
    from .comparator import compare_cmd
    main.add_command(compare_cmd, name="compare")
except ImportError:
    pass

try:
    from .generator import generate_cmd
    main.add_command(generate_cmd, name="generate")
except ImportError:
    pass

try:
    from .validator import validate_cmd
    main.add_command(validate_cmd, name="validate")
except ImportError:
    pass


if __name__ == "__main__":
    main()
