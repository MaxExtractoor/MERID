"""Local-first Prime Screen launcher.

This CLI orchestrates the local MERID stack that powers the Prime Screen:
- FastAPI backend (web.main:app)
- Swarm/consensus workers
- Data/news ingestors
- Optional explainer + Flutter desktop shell

It reads defaults from config/local.toml (if present) and .env.local, then
spawns each service as a subprocess so you can run everything from one
command: `python -m tools.prime_screen_cli launch`.
"""

from __future__ import annotations

import argparse
import os
import shlex
import signal
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIRS = [BASE_DIR / "data", BASE_DIR / "logs", BASE_DIR / "db"]
CONFIG_PATH = BASE_DIR / "config" / "local.toml"
ENV_PATH = BASE_DIR / ".env.local"

ServiceCommand = List[str]


def _log(message: str) -> None:
    print(f"[prime-screen] {message}")


@dataclass
class ServiceProcess:
    name: str
    command: ServiceCommand
    cwd: Optional[Path] = None
    env: Optional[Dict[str, str]] = None
    process: Optional[subprocess.Popen] = field(default=None, init=False)

    def start(self) -> "ServiceProcess":
        cwd_display = str(self.cwd) if self.cwd else str(BASE_DIR)
        _log(f"starting {self.name}: {' '.join(self.command)} (cwd={cwd_display})")
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=self.cwd or BASE_DIR,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Failed to start {self.name}: {exc}") from exc
        return self

    def stop(self) -> None:
        if not self.process:
            return
        if self.process.poll() is None:
            _log(f"stopping {self.name} (pid={self.process.pid})")
            try:
                self.process.send_signal(signal.SIGTERM)
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
        self.process = None

    def forward_output(self) -> None:
        if not self.process or not self.process.stdout:
            return
        line = self.process.stdout.readline()
        while line:
            sys.stdout.write(f"[{self.name}] {line}")
            line = self.process.stdout.readline()

    def is_running(self) -> bool:
        return bool(self.process and self.process.poll() is None)


class Config:
    def __init__(self) -> None:
        self.raw: Dict[str, Dict[str, object]] = {}
        if CONFIG_PATH.exists():
            self.raw = tomllib.loads(CONFIG_PATH.read_text())

    def section(self, name: str) -> Dict[str, object]:
        return self.raw.get(name, {})


def load_env_file(path: Path = ENV_PATH) -> Dict[str, str]:
    if not path.exists():
        return {}
    env: Dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def ensure_directories(paths: List[Path]) -> None:
    for directory in paths:
        directory.mkdir(parents=True, exist_ok=True)
        _log(f"ensured directory: {directory}")


def _format_command(command: object) -> ServiceCommand:
    if isinstance(command, list):
        return [str(item) for item in command]
    if isinstance(command, str):
        return shlex.split(command)
    raise ValueError("command must be a list or string")


def build_web_command(config: Config) -> ServiceCommand:
    web_cfg = config.section("web")
    host = str(web_cfg.get("host", "127.0.0.1"))
    port = str(web_cfg.get("port", 8011))
    command = web_cfg.get("command")
    if command:
        return _format_command(command)
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "web.main:app",
        "--host",
        host,
        "--port",
        port,
    ]


def build_swarm_command(config: Config) -> ServiceCommand:
    swarm_cfg = config.section("swarm")
    command = swarm_cfg.get("command")
    if command:
        return _format_command(command)
    # Default placeholder that keeps process alive while printing heartbeats.
    return [
        sys.executable,
        "-u",
        "-c",
        textwrap.dedent(
            """
            import time
            from utils.logger import get_logger
            logger = get_logger('swarm.local.loop')
            logger.info('Swarm loop placeholder started; customize config/swarm.command to point to your real worker.')
            try:
                while True:
                    time.sleep(5)
                    logger.info('Swarm loop placeholder heartbeat')
            except KeyboardInterrupt:
                logger.info('Swarm loop placeholder exiting')
            """
        ).strip(),
    ]


def build_ingestor_command(config: Config) -> ServiceCommand:
    ing_cfg = config.section("ingestors")
    command = ing_cfg.get("command")
    if command:
        return _format_command(command)
    return [
        sys.executable,
        "-u",
        "-c",
        textwrap.dedent(
            """
            import time
            from utils.logger import get_logger
            logger = get_logger('ingestors.local.loop')
            logger.info('Ingestor placeholder running; override via config/local.toml [ingestors].command')
            try:
                while True:
                    time.sleep(10)
                    logger.info('Ingestor placeholder heartbeat')
            except KeyboardInterrupt:
                logger.info('Ingestor placeholder exiting')
            """
        ).strip(),
    ]


def build_explainer_command(config: Config) -> ServiceCommand:
    exp_cfg = config.section("explainer")
    command = exp_cfg.get("command")
    if command:
        return _format_command(command)
    return [
        sys.executable,
        "-u",
        "-c",
        textwrap.dedent(
            """
            import time
            from utils.logger import get_logger
            logger = get_logger('explainer.local.loop')
            logger.info('Explainer placeholder active; override [explainer].command for real LLM service')
            try:
                while True:
                    time.sleep(15)
                    logger.info('Explainer placeholder heartbeat')
            except KeyboardInterrupt:
                logger.info('Explainer placeholder exiting')
            """
        ).strip(),
    ]


def build_flutter_command(config: Config) -> ServiceCommand:
    flutter_cfg = config.section("flutter")
    command = flutter_cfg.get("command")
    if command:
        return _format_command(command)
    desktop_target = flutter_cfg.get("device", "windows")
    project_dir = flutter_cfg.get("project_dir", str(BASE_DIR / "flutter"))
    return [
        "flutter",
        "run",
        "-d",
        str(desktop_target),
        "--target",
        "lib/main.dart",
    ], Path(project_dir)


def start_service(name: str, command: ServiceCommand, env: Dict[str, str], cwd: Optional[Path] = None) -> ServiceProcess:
    proc = ServiceProcess(name=name, command=command, cwd=cwd, env=env.copy())
    return proc.start()


def _monitor(processes: List[ServiceProcess]) -> None:
    try:
        while processes:
            for proc in list(processes):
                if not proc.is_running():
                    _log(f"{proc.name} exited with code {proc.process.poll() if proc.process else 'unknown'}")
                    processes.remove(proc)
                    continue
                proc.forward_output()
            time.sleep(0.2)
    except KeyboardInterrupt:
        _log("received interrupt, shutting down services...")
    finally:
        for proc in processes:
            proc.stop()


def command_launch(args: argparse.Namespace) -> None:
    config = Config()
    env = os.environ.copy()
    env.update(load_env_file())
    ensure_directories(DEFAULT_DATA_DIRS)

    processes: List[ServiceProcess] = []

    web_proc = start_service("web", build_web_command(config), env)
    processes.append(web_proc)

    if not args.skip_swarm:
        swarm_proc = start_service("swarm", build_swarm_command(config), env)
        processes.append(swarm_proc)

    if not args.skip_ingestors:
        ingestor_proc = start_service("ingestors", build_ingestor_command(config), env)
        processes.append(ingestor_proc)

    if args.explainer:
        explainer_proc = start_service("explainer", build_explainer_command(config), env)
        processes.append(explainer_proc)

    if args.flutter:
        flutter_command, flutter_cwd = build_flutter_command(config)
        flutter_proc = start_service("flutter", flutter_command, env, cwd=flutter_cwd)
        processes.append(flutter_proc)

    _monitor(processes)


def command_start_web(_: argparse.Namespace) -> None:
    config = Config()
    env = os.environ.copy()
    env.update(load_env_file())
    ensure_directories(DEFAULT_DATA_DIRS)
    proc = start_service("web", build_web_command(config), env)
    _monitor([proc])


def command_start_swarm(_: argparse.Namespace) -> None:
    config = Config()
    env = os.environ.copy()
    env.update(load_env_file())
    ensure_directories(DEFAULT_DATA_DIRS)
    proc = start_service("swarm", build_swarm_command(config), env)
    _monitor([proc])


def command_start_ingestors(_: argparse.Namespace) -> None:
    config = Config()
    env = os.environ.copy()
    env.update(load_env_file())
    ensure_directories(DEFAULT_DATA_DIRS)
    proc = start_service("ingestors", build_ingestor_command(config), env)
    _monitor([proc])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prime Screen local launcher")
    subparsers = parser.add_subparsers(dest="command", required=True)

    launch_parser = subparsers.add_parser("launch", help="Start web + swarm + ingestors (and optional extras)")
    launch_parser.add_argument("--skip-swarm", action="store_true", help="Do not start swarm workers")
    launch_parser.add_argument("--skip-ingestors", action="store_true", help="Do not start data/news ingestors")
    launch_parser.add_argument("--explainer", action="store_true", help="Start explainer service stub")
    launch_parser.add_argument("--flutter", action="store_true", help="Launch Flutter desktop client")
    launch_parser.set_defaults(func=command_launch)

    web_parser = subparsers.add_parser("start-web", help="Start only the FastAPI backend")
    web_parser.set_defaults(func=command_start_web)

    swarm_parser = subparsers.add_parser("start-swarm", help="Start only the swarm workers")
    swarm_parser.set_defaults(func=command_start_swarm)

    ingestors_parser = subparsers.add_parser("start-ingestors", help="Start only the ingest pipelines")
    ingestors_parser.set_defaults(func=command_start_ingestors)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
