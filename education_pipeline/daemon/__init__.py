"""Long-lived local run daemon: job queue, worker, and loopback JSON API."""

from __future__ import annotations

import os
import secrets
import threading
from pathlib import Path

from education_pipeline import __version__
from education_pipeline.config import (
    ConfigError,
    ModelCatalog,
    ModelPlan,
    load_model_catalog,
    load_model_plan,
)
from education_pipeline.daemon import lifecycle
from education_pipeline.daemon.jobs import (
    DEFAULT_TIMEOUT_SECONDS,
    JobRunner,
    JobStore,
    Worker,
)
from education_pipeline.daemon.server import DaemonContext, build_server
from education_pipeline.daemon.static import default_web_dist
from education_pipeline.runs import RunStore
from education_pipeline.workspace import ProfileStore, TopicStore

_PACKAGE_CONFIG = Path(__file__).resolve().parents[2] / "config"


def load_workspace_config(root: str | Path) -> tuple[ModelCatalog, ModelPlan]:
    """Load the workspace model catalog + plan, falling back to packaged examples."""

    root = Path(root)
    catalog_path = root / "config" / "model-catalog.toml"
    plan_path = root / "config" / "model-plan.toml"
    if not catalog_path.exists():
        catalog_path = _PACKAGE_CONFIG / "model-catalog.example.toml"
    if not plan_path.exists():
        plan_path = _PACKAGE_CONFIG / "model-plan.example.toml"
    catalog = load_model_catalog(catalog_path)
    plan = load_model_plan(plan_path, catalog)
    return catalog, plan


def serve(
    root: str | Path,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ready: threading.Event | None = None,
) -> None:
    """Run the daemon until shutdown, owning the workspace discovery file."""

    root = Path(root)
    if not lifecycle.claim_discovery(root):
        raise ConfigError(f"a daemon already owns this workspace: {lifecycle.discovery_path(root)}")

    try:
        catalog, plan = load_workspace_config(root)
        store = JobStore(root)
        runs = RunStore(root)
        worker = Worker(store, lambda job: JobRunner(store, runs, catalog, plan, timeout=timeout,
                                                     force=bool(job.metadata.get("force"))))
        worker.reconcile()
        worker.start()

        token = secrets.token_urlsafe(32)
        shutdown = threading.Event()
        context = DaemonContext(
            root=root,
            store=store,
            worker=worker,
            runs=runs,
            token=token,
            version=__version__,
            catalog=catalog,
            plan=plan,
            topics=TopicStore(root),
            profiles=ProfileStore(root),
            on_shutdown=shutdown.set,
            web_dist=default_web_dist(),
        )
        server = build_server(context)
        lifecycle.write_discovery(root, pid=os.getpid(), port=server.server_port, token=token,
                                  version=__version__)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        if ready is not None:
            ready.set()
        try:
            shutdown.wait()
        finally:
            server.shutdown()
            worker.stop()
            lifecycle.remove_discovery(root)
    except BaseException:
        # Release the claim placeholder on any startup failure so the
        # workspace isn't left permanently locked by a daemon that never
        # served. On the graceful-shutdown path above, the discovery file
        # has already been removed, so this is a no-op there.
        lifecycle.remove_discovery(root)
        raise
