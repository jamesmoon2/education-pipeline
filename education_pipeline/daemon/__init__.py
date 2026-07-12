"""Long-lived local run daemon: job queue, worker, and loopback JSON API."""

from __future__ import annotations

import hashlib
import os
import secrets
import tempfile
import threading
from pathlib import Path

from education_pipeline import __version__
from education_pipeline.config import (
    ConfigError,
    ModelCatalog,
    ModelPlan,
    apply_overrides,
    emit_model_plan_toml,
    load_model_catalog,
    load_model_plan,
    parse_model_plan,
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


class WorkspaceConfigSource:
    """Reads the model catalog + plan fresh from disk on every call.

    Falls back to the packaged example files when the workspace has not
    supplied its own ``config/model-catalog.toml`` / ``config/model-plan.toml``.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def catalog_path(self) -> Path:
        path = self.root / "config" / "model-catalog.toml"
        if not path.exists():
            path = _PACKAGE_CONFIG / "model-catalog.example.toml"
        return path

    def plan_path(self) -> Path:
        path = self.root / "config" / "model-plan.toml"
        if not path.exists():
            path = _PACKAGE_CONFIG / "model-plan.example.toml"
        return path

    def load(self) -> tuple[ModelCatalog, ModelPlan]:
        catalog = load_model_catalog(self.catalog_path())
        plan = load_model_plan(self.plan_path(), catalog)
        return catalog, plan

    def plan_sha256(self) -> str:
        return hashlib.sha256(self.plan_path().read_bytes()).hexdigest()

    def write_plan(self, toml_text: str) -> None:
        target = self.root / "config" / "model-plan.toml"
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".toml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(toml_text)
            os.replace(tmp, target)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


class StaticConfigSource:
    """Test double: fixed in-memory catalog/plan; write_plan re-parses into itself."""

    def __init__(self, catalog: ModelCatalog, plan: ModelPlan) -> None:
        self.catalog = catalog
        self.plan = plan
        self.held_text = emit_model_plan_toml(plan)

    def load(self) -> tuple[ModelCatalog, ModelPlan]:
        return self.catalog, self.plan

    def plan_sha256(self) -> str:
        return hashlib.sha256(self.held_text.encode("utf-8")).hexdigest()

    def write_plan(self, toml_text: str) -> None:
        import tomllib

        data = tomllib.loads(toml_text)
        self.plan = parse_model_plan(data, self.catalog)
        self.held_text = toml_text


def load_workspace_config(root: str | Path) -> tuple[ModelCatalog, ModelPlan]:
    """Load the workspace model catalog + plan, falling back to packaged examples.

    Thin compatibility wrapper around :class:`WorkspaceConfigSource`.
    """

    return WorkspaceConfigSource(root).load()


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
        config = WorkspaceConfigSource(root)
        store = JobStore(root)
        runs = RunStore(root)

        def _runner_for(job):
            catalog, plan = config.load()
            overrides = runs.read_plan_overrides(job.topic_id)
            plan = apply_overrides(plan, overrides, catalog)
            return JobRunner(store, runs, catalog, plan, timeout=timeout,
                              force=bool(job.metadata.get("force")))

        worker = Worker(store, _runner_for)
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
            config=config,
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
