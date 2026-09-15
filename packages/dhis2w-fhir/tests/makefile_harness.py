"""Run a scaffolded Makefile against a stand-in docker, so its recipes are exercised and not read."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pydantic import BaseModel


class StubbedDocker(BaseModel):
    """A logging stand-in `docker` first on PATH, and the file recording every call made to it."""

    environment: dict[str, str]
    call_log: Path

    def subcommands(self) -> list[str]:
        """Every docker subcommand invoked since the stub was installed, in order."""
        if not self.call_log.is_file():
            return []
        return self.call_log.read_text(encoding="utf-8").split()


def stub_docker(directory: Path, docker_info: str, *, sushi_exit_status: int = 0) -> StubbedDocker:
    """Install a `docker` in `directory` that answers `docker info` from `docker_info` and counts calls.

    A scaffolded Makefile asks the daemon how much memory it has, and a test of that question needs
    a daemon that answers on demand and records how often it was asked - which no real docker does.

    `sushi_exit_status` is what the stub exits with for the run whose arguments name `sushi`, and
    that run alone: a compile that stops on an error is what the `sushi` recipe's own clean-up is
    about, and the package-cache run ahead of it has to keep succeeding for the recipe to be reached.
    """
    binaries = directory / "stub-bin"
    binaries.mkdir(parents=True, exist_ok=True)
    answer = binaries / "docker-info.txt"
    answer.write_text(docker_info, encoding="utf-8")
    call_log = binaries / "docker.log"
    script = binaries / "docker"
    script.write_text(
        f'#!/bin/sh\necho "$1" >> "{call_log}"\n'
        f'if [ "$1" = "info" ]; then cat "{answer}"; fi\n'
        f'for argument in "$@"; do\n'
        f'  if [ "$argument" = "sushi" ]; then exit {sushi_exit_status}; fi\n'
        f"done\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    environment = dict(os.environ)
    environment["PATH"] = f"{binaries}{os.pathsep}{environment['PATH']}"
    # An outer `make test` hands its own flags and jobserver down through the environment, and a
    # run under test must answer for the Makefile under test alone.
    for inherited in ("MAKEFLAGS", "MFLAGS", "JAVA_HEAP"):
        environment.pop(inherited, None)
    return StubbedDocker(environment=environment, call_log=call_log)


def run_make(directory: Path, stub: StubbedDocker, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run make in `directory` with the stubbed docker first on PATH."""
    return subprocess.run(
        ["make", *arguments],
        cwd=directory,
        env=stub.environment,
        capture_output=True,
        text=True,
        check=False,
    )
