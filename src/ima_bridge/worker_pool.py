from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock, Thread
from typing import Callable, Literal

from ima_bridge.config import Settings, get_settings
from ima_bridge.driver_protocol import DriverModelCatalog, DriverModelOption
from ima_bridge.profile_sync import sync_profile_state
from ima_bridge.schemas import AskResponse, HealthResponse
from ima_bridge.web_worker_service import WebWorkerService

WorkerStatus = Literal["warming", "ready", "busy", "login_required", "error"]


@dataclass
class WorkerSlot:
    worker_id: str
    settings: Settings
    service: object
    status: WorkerStatus = "warming"
    last_error_code: str | None = None
    last_error_message: str | None = None


@dataclass(frozen=True)
class PoolHealthSummary:
    workers_total: int
    workers_warming: int
    workers_ready: int
    workers_busy: int
    workers_login_required: int
    workers_error: int
    capacity_available: bool

    def model_dump(self) -> dict:
        return {
            "workers_total": self.workers_total,
            "workers_warming": self.workers_warming,
            "workers_ready": self.workers_ready,
            "workers_busy": self.workers_busy,
            "workers_login_required": self.workers_login_required,
            "workers_error": self.workers_error,
            "capacity_available": self.capacity_available,
        }


class WorkerPoolManager:
    def __init__(
        self,
        template_settings: Settings,
        worker_count: int,
        service_factory: Callable[[Settings], object] | None = None,
    ) -> None:
        self.template_settings = template_settings
        self.worker_count = max(1, worker_count)
        self._service_factory = service_factory or (lambda settings: WebWorkerService(settings=settings))
        self._lock = Lock()
        self._cached_model_catalog = self._fallback_model_catalog()
        self._refresh_in_progress = False
        self._last_profile_seed_report: dict | None = None
        self._workers = [self._build_worker_slot(index=index) for index in range(1, self.worker_count + 1)]

    @property
    def workers(self) -> list[WorkerSlot]:
        return self._workers

    def _build_worker_slot(self, index: int) -> WorkerSlot:
        worker_id = f"worker-{index:02d}"
        settings = get_settings(
            instance=worker_id,
            driver_mode="web",
            web_headless=self.template_settings.web_headless,
        )
        return WorkerSlot(
            worker_id=worker_id,
            settings=settings,
            service=self._service_factory(settings),
        )

    def refresh_all(self) -> None:
        refreshable_workers = [worker for worker in self._workers if worker.status != "busy"]
        if len(refreshable_workers) <= 1:
            for worker in refreshable_workers:
                self.refresh_worker(worker)
            return

        with ThreadPoolExecutor(max_workers=len(refreshable_workers), thread_name_prefix="ima-health") as executor:
            futures = [executor.submit(self.refresh_worker, worker) for worker in refreshable_workers]
            for future in futures:
                future.result()

    def refresh_in_background(self, *, eager_worker_count: int = 1) -> bool:
        refreshable_workers = [worker for worker in self._workers if worker.status != "busy"]
        if not refreshable_workers:
            return False

        with self._lock:
            if self._refresh_in_progress:
                return False
            self._refresh_in_progress = True
            for worker in refreshable_workers:
                if worker.status != "ready":
                    worker.status = "warming"
                    worker.last_error_code = None
                    worker.last_error_message = None

        def runner() -> None:
            try:
                self._refresh_startup_workers(refreshable_workers, eager_worker_count=eager_worker_count)
            finally:
                with self._lock:
                    self._refresh_in_progress = False

        Thread(target=runner, name="ima-worker-warmup", daemon=True).start()
        return True

    def refresh_worker(self, worker: WorkerSlot) -> WorkerStatus:
        health = worker.service.health()
        next_status = self._status_from_health(health)
        cached_catalog = self._load_model_catalog(worker) if next_status == "ready" else None

        worker.status = next_status
        worker.last_error_code = health.error_code
        worker.last_error_message = health.error_message
        if cached_catalog is not None:
            with self._lock:
                self._cached_model_catalog = cached_catalog
        return worker.status

    def try_acquire(self) -> WorkerSlot | None:
        with self._lock:
            for worker in self._workers:
                if worker.status == "ready":
                    worker.status = "busy"
                    return worker
        return None

    def release(self, worker: WorkerSlot, response: AskResponse | None = None, exc: Exception | None = None) -> WorkerStatus:
        with self._lock:
            if response is not None:
                worker.status = self._status_from_response(response)
                worker.last_error_code = response.error_code
                worker.last_error_message = response.error_message
            elif exc is not None:
                worker.status = "error"
                worker.last_error_code = "CAPTURE_FAILED"
                worker.last_error_message = str(exc)
            else:
                worker.status = "ready"
                worker.last_error_code = None
                worker.last_error_message = None
            return worker.status

    def summarize(self) -> PoolHealthSummary:
        warming = sum(worker.status == "warming" for worker in self._workers)
        ready = sum(worker.status == "ready" for worker in self._workers)
        busy = sum(worker.status == "busy" for worker in self._workers)
        login_required = sum(worker.status == "login_required" for worker in self._workers)
        error = sum(worker.status == "error" for worker in self._workers)
        return PoolHealthSummary(
            workers_total=len(self._workers),
            workers_warming=warming,
            workers_ready=ready,
            workers_busy=busy,
            workers_login_required=login_required,
            workers_error=error,
            capacity_available=ready > 0,
        )

    def health_payload(self) -> dict:
        summary = self.summarize()
        refresh_in_progress = self._refresh_in_progress
        error_code: str | None = None
        error_message: str | None = None
        warming_up = bool(summary.workers_warming or refresh_in_progress)
        status = "ready" if summary.capacity_available else "error"
        if not summary.capacity_available:
            if warming_up:
                status = "warming"
                error_code = "WARMING_UP"
                error_message = "Workers are still initializing"
            elif summary.workers_busy > 0:
                status = "busy"
                error_code = "BUSY"
                error_message = "No idle worker available"
            elif summary.workers_login_required > 0:
                status = "login_required"
                error_code = "LOGIN_REQUIRED"
                error_message = "All workers require login"
            else:
                status = "error"
                error_code = "CAPTURE_FAILED"
                error_message = "No healthy worker available"
        elif summary.workers_busy >= summary.workers_total and summary.workers_total > 0:
            status = "busy"

        return {
            "ok": summary.capacity_available,
            "status": status,
            "warming_up": warming_up,
            "refresh_in_progress": refresh_in_progress,
            "instance": "pool",
            "source_driver": "web",
            "cdp_port": None,
            "cdp_endpoint": None,
            "cdp_ready": None,
            "base_url": self.template_settings.web_base_url,
            "profile_dir": None,
            "headless": self.template_settings.web_headless,
            "app_executable": None,
            "managed_profile_dir": str(self.template_settings.managed_profile_dir.resolve()),
            "error_code": error_code,
            "error_message": error_message,
            "pool": summary.model_dump(),
        }

    def _refresh_startup_workers(self, workers: list[WorkerSlot], *, eager_worker_count: int) -> None:
        if not workers:
            return

        eager_count = max(1, min(eager_worker_count, len(workers)))
        eager_workers = workers[:eager_count]
        remaining_workers = workers[eager_count:]

        for worker in eager_workers:
            self.refresh_worker(worker)

        if not remaining_workers:
            return

        max_workers = min(len(remaining_workers), max(1, min(4, len(remaining_workers))))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ima-health") as executor:
            futures = [executor.submit(self.refresh_worker, worker) for worker in remaining_workers]
            for future in futures:
                future.result()

    def iter_login_services(self) -> list[WorkerSlot]:
        return list(self._workers)

    def close(self) -> None:
        for worker in self._workers:
            close_service = getattr(worker.service, "close", None)
            if callable(close_service):
                try:
                    close_service()
                except Exception:
                    continue

    def seed_profiles_from(self, source_settings: Settings | None = None) -> int:
        source = source_settings or self.template_settings
        seeded = 0
        attempted = 0
        seeded_workers: list[str] = []
        for worker in self._workers:
            attempted += 1
            changed = sync_profile_state(source, worker.settings)
            if changed:
                worker.status = "warming"
                worker.last_error_code = None
                worker.last_error_message = None
                seeded += 1
                seeded_workers.append(worker.worker_id)

        self._last_profile_seed_report = {
            "attempted": attempted,
            "seeded": seeded,
            "seeded_workers": seeded_workers,
        }
        return seeded

    def profile_seed_report(self) -> dict | None:
        return self._last_profile_seed_report

    def get_model_catalog(self) -> DriverModelCatalog:
        return self._cached_model_catalog

    def _load_model_catalog(self, worker: WorkerSlot) -> DriverModelCatalog | None:
        try:
            catalog = worker.service.get_model_catalog()
        except Exception:
            return None
        if catalog.options or catalog.current_model:
            return catalog
        return None

    def _fallback_model_catalog(self) -> DriverModelCatalog:
        label = self.template_settings.model_prefix.strip()
        options = [DriverModelOption(value=label, label=label, selected=True)] if label else []
        return DriverModelCatalog(current_model=label, options=options)

    @staticmethod
    def _status_from_health(health: HealthResponse) -> WorkerStatus:
        if health.ok:
            return "ready"
        if health.error_code == "LOGIN_REQUIRED":
            return "login_required"
        return "error"

    @staticmethod
    def _status_from_response(response: AskResponse) -> WorkerStatus:
        if response.ok:
            return "ready"
        if response.error_code == "LOGIN_REQUIRED":
            return "login_required"
        return "error"
