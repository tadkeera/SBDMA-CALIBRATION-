"""Infrastructure wiring: the manifests must name things that exist.

Why this file exists
--------------------
``docker-compose.yml`` and ``infra/k8s/worker-deployment.yaml`` both launched the
worker as ``celery -A app.workers.celery_app``. There is no ``app.workers`` package —
the module is ``app.worker.celery_app`` — so the container exited at import time.
Nothing caught it: the unit tests never read the manifests, and the worker had been
verified by hand from a shell where the command was typed, not copied from the file.
A stack that cannot start its worker is not a smaller stack, it is a stack with no
scheduled notices and no reports.

These tests read the deployment files as data and check the claims they make:
the Celery target imports, exactly one beat exists, the broker version is the one the
worker was verified against, and no bind mount points at a path the repository does
not contain.
"""

from __future__ import annotations

import importlib
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
VERCEL = ROOT / "vercel.json"
K8S = ROOT / "infra" / "k8s"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _k8s_docs() -> list[dict]:
    docs: list[dict] = []
    for path in sorted(K8S.glob("*.yaml")):
        docs.extend(d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d)
    return docs


def _celery_targets(command: list[str] | str) -> list[str]:
    if isinstance(command, str):
        command = command.split()
    targets = []
    for index, token in enumerate(command):
        if token in {"-A", "--app"} and index + 1 < len(command):
            targets.append(command[index + 1])
    return targets


def _containers() -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    for name, service in _compose()["services"].items():
        if "command" in service:
            found.append((f"compose:{name}", service))
    for doc in _k8s_docs():
        if doc.get("kind") != "Deployment":
            continue
        for container in doc["spec"]["template"]["spec"]["containers"]:
            found.append((f"k8s:{doc['metadata']['name']}/{container['name']}", container))
    return found


def test_every_celery_app_target_imports() -> None:
    """The guard for the ``app.workers`` bug: resolve the real object, not the string."""
    checked = 0
    for where, container in _containers():
        command = container.get("command") or container.get("args") or []
        for target in _celery_targets(command):
            checked += 1
            module_path, _, attribute = target.partition(":")
            module = importlib.import_module(module_path)  # ModuleNotFoundError if wrong
            symbol = attribute or "celery_app"
            app = getattr(module, symbol, None)
            assert app is not None, f"{where}: {module_path} has no {symbol}"
            assert hasattr(app, "control"), f"{where}: {target} is not a Celery app"
    assert checked >= 3, "expected the worker and the beat in both compose and k8s"


def test_celery_targets_are_named_explicitly() -> None:
    """``-A app.worker.celery_app`` happens to resolve today because Celery sniffs the
    module; naming the object removes the dependency on that inference."""
    for where, container in _containers():
        command = container.get("command") or []
        for target in _celery_targets(command):
            assert ":" in target, f"{where}: name the Celery object in {target!r}"


def test_the_broker_is_the_verified_major_version() -> None:
    image = _compose()["services"]["redis"]["image"]
    major = int(re.search(r"redis:(\d+)", image).group(1))
    assert major >= 8, f"worker was verified on Redis 8, compose asks for {image}"


def test_the_worker_and_beat_exist_and_beat_is_alone() -> None:
    services = _compose()["services"]
    assert "worker" in services and "beat" in services

    beats = [d for d in _k8s_docs() if d.get("kind") == "Deployment" and "beat" in d["metadata"]["name"]]
    assert len(beats) == 1
    assert beats[0]["spec"]["replicas"] == 1
    assert beats[0]["spec"]["strategy"]["type"] == "Recreate"
    # the schedule file must not live in the container's writable layer
    beat_command = " ".join(beats[0]["spec"]["template"]["spec"]["containers"][0]["command"])
    assert "--schedule=" in beat_command


def test_scheduled_work_needs_a_healthy_broker_to_start() -> None:
    services = _compose()["services"]
    for name in ("api", "worker", "beat"):
        depends = services[name].get("depends_on", {})
        assert "redis" in depends, f"{name} must wait for the broker"
        assert depends["redis"]["condition"] == "service_healthy"
    for name in ("api", "worker"):
        assert services[name]["healthcheck"], f"{name} declares no healthcheck"


#: Mounts the operator supplies, deliberately absent from source control: TLS material
#: must never be committed, and an empty directory in the repository would suggest it
#: ships a certificate.
OPERATOR_PROVIDED = {"infra/nginx/certs"}


def test_no_bind_mount_points_at_a_missing_path() -> None:
    """A compose bind mount of a path that is not in the repository creates an empty
    directory on the host, which then reads as configuration that does nothing."""
    missing = []
    for name, service in _compose()["services"].items():
        for volume in service.get("volumes", []):
            if isinstance(volume, str) and volume.startswith("."):
                host = volume.split(":")[0].removeprefix("./")
                if host in OPERATOR_PROVIDED:
                    continue
                if not (ROOT / host).exists():
                    missing.append(f"{name}: {host}")
    assert not missing, f"bind mounts to paths that do not exist: {missing}"


def test_images_and_version_agree() -> None:
    for doc in _k8s_docs():
        if doc.get("kind") != "Deployment":
            continue
        image = doc["spec"]["template"]["spec"]["containers"][0]["image"]
        assert image.endswith(f":{VERSION}"), f"{doc['metadata']['name']} runs {image}, repo is {VERSION}"


@pytest.mark.parametrize("path", ["backend/Dockerfile", "Dockerfile", "infra/nginx/nginx.conf"])
def test_deployment_inputs_are_tracked(path: str) -> None:
    assert (ROOT / path).exists()


# --------------------------------------------------------------- vercel.json
def _vercel() -> dict:
    """``vercel.json`` must be JSON. The file committed before this release was a
    text note *describing* a vercel.json, so the deployment failed to parse it."""
    import json

    return json.loads(VERCEL.read_text(encoding="utf-8"))


def test_vercel_services_point_at_real_directories_and_entrypoints() -> None:
    services = _vercel()["services"]
    assert {"web", "api"} <= set(services)
    for name, service in services.items():
        assert (ROOT / service["root"]).is_dir(), f"{name}: root does not exist"
        if entrypoint := service.get("entrypoint"):
            target = (ROOT / service["root"] / entrypoint).resolve()
            assert target.is_file(), f"{name}: entrypoint {entrypoint} does not exist"
            assert "app = " in target.read_text(encoding="utf-8")


def test_vercel_routes_the_api_before_the_catch_all() -> None:
    rewrites = _vercel()["rewrites"]
    assert rewrites[0]["source"].startswith("/api/")
    assert rewrites[0]["destination"] == {"service": "api"}
    # the catch-all must come last, or it swallows /api
    assert rewrites[-1]["source"] == "/(.*)"


def test_vercel_cron_paths_exist_as_routes() -> None:
    """A cron entry pointing at a route that does not exist fails silently in
    production: Vercel calls the path, gets a 404, and nothing is reported."""
    from app.main import app

    routes = {route.path for route in app.routes}
    for cron in _vercel()["crons"]:
        assert cron["path"] in routes, f"cron {cron['path']} is not a route"
        assert len(cron["schedule"].split()) == 5, "expected a five-field cron expression"


def test_serverless_schedule_has_no_silent_duplicate_trigger() -> None:
    """On Vercel the crons are the schedule; beat must not also be assumed to run.
    /health reports the broker, and the cron routes refuse to run without a secret."""
    from app.core.config import get_settings

    settings = get_settings()
    if settings.scheduler == "vercel-cron":
        assert settings.cron_secret, "SCHEDULER=vercel-cron without CRON_SECRET is inert"
