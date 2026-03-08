from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Literal

from ima_bridge.config import Settings, get_settings
from ima_bridge.schemas import AskResponse, HealthResponse
from ima_bridge.service import IMAAskService

WorkerStatus = Literal["ready", "busy", "login_required", "error"]


@dataclass
class WorkerSlot:
    worker_id: str
    settings: Settings
    service: IMAAskService
    status: WorkerStatus = "error"
    last_error_code: str | None = None
    last_error_message: str | None = None


@dataclass(frozen=True)
class PoolHealthSummary:
    workers_total: int
    workers_ready: int
    workers_busy: int
    workers_login_required: int
    workers_error: int
    capacity_available: bool

    def model_dump(self) -> dict:
        return {
            "workers_total": self.workers_total,
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
        service_factory: Callable[[Settings], IMAAskService] | None = None,
    ) -> None:
        self.template_settings = template_settings
        self.worker_count = max(1, worker_count)
        self._service_factory = service_factory or (lambda settings: IMAAskService(settings=settings))
        self._lock = Lock()
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

    def refresh_worker(self, worker: WorkerSlot) -> WorkerStatus:
        health = worker.service.health()
        worker.status = self._status_from_health(health)
        worker.last_error_code = health.error_code
        worker.last_error_message = health.error_message
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
        ready = sum(worker.status == "ready" for worker in self._workers)
        busy = sum(worker.status == "busy" for worker in self._workers)
        login_required = sum(worker.status == "login_required" for worker in self._workers)
        error = sum(worker.status == "error" for worker in self._workers)
        return PoolHealthSummary(
            workers_total=len(self._workers),
            workers_ready=ready,
            workers_busy=busy,
            workers_login_required=login_required,
            workers_error=error,
            capacity_available=ready > 0,
        )

    def health_payload(self) -> dict:
        summary = self.summarize()
        error_code: str | None = None
        error_message: str | None = None
        if not summary.capacity_available:
            if summary.workers_busy > 0:
                error_code = "BUSY"
                error_message = "No idle worker available"
            elif summary.workers_login_required > 0:
                error_code = "LOGIN_REQUIRED"
                error_message = "All workers require login"
            else:
                error_code = "CAPTURE_FAILED"
                error_message = "No healthy worker available"

        return {
            "ok": summary.capacity_available,
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

    def iter_login_services(self) -> list[WorkerSlot]:
        return list(self._workers)

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
