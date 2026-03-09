from __future__ import annotations

import time
from pathlib import Path

from ima_bridge.config import get_settings
from ima_bridge.driver_protocol import DriverModelCatalog, DriverModelOption
from ima_bridge.schemas import AskResponse, HealthResponse, KnowledgeBaseIdentity
from ima_bridge.worker_pool import WorkerPoolManager


def _configure_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IMA_MANAGED_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("IMA_WEB_PROFILE_ROOT", str(tmp_path / "web-profiles"))
    monkeypatch.setenv("IMA_ARTIFACTS_DIR", str(tmp_path / "artifacts"))


def _make_health(instance: str, *, ok: bool, error_code: str | None = None) -> HealthResponse:
    return HealthResponse(
        ok=ok,
        instance=instance,
        source_driver="web",
        base_url="https://ima.qq.com/",
        profile_dir=f"profile/{instance}",
        headless=True,
        managed_profile_dir=f"managed/{instance}",
        error_code=error_code,
        error_message=None if error_code is None else error_code.lower(),
    )


def _make_ask(instance: str, question: str, *, ok: bool, error_code: str | None = None) -> AskResponse:
    kb = KnowledgeBaseIdentity(name="爱分享", owner="购物小助手", title="【爱分享】的财经资讯")
    return AskResponse(
        ok=ok,
        question=question,
        knowledge_base=kb,
        mode="对话模式",
        model="DS V3.2 T",
        source_driver="web",
        answer_text="answer" if ok else "",
        error_code=error_code,
        error_message=None if error_code is None else error_code.lower(),
    )


class FakeService:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.health_response = _make_health(settings.instance, ok=True)
        self.model_catalog = DriverModelCatalog(
            current_model="DeepSeek V3.2 Think",
            options=[
                DriverModelOption(value="DeepSeek V3.2 Think", label="DeepSeek V3.2 Think", selected=True),
                DriverModelOption(value="DeepSeek V3.2", label="DeepSeek V3.2", selected=False),
            ],
        )
        self.model_catalog_calls = 0

    def health(self) -> HealthResponse:
        return self.health_response

    def get_model_catalog(self) -> DriverModelCatalog:
        self.model_catalog_calls += 1
        return self.model_catalog


def test_worker_pool_acquire_release_and_busy(tmp_path, monkeypatch):
    _configure_env(tmp_path, monkeypatch)
    services = {}

    def service_factory(settings):
        service = FakeService(settings)
        services[settings.instance] = service
        return service

    template_settings = get_settings(instance="template", driver_mode="web")
    manager = WorkerPoolManager(template_settings=template_settings, worker_count=2, service_factory=service_factory)
    manager.refresh_all()

    first = manager.try_acquire()
    second = manager.try_acquire()
    third = manager.try_acquire()

    assert first is not None
    assert second is not None
    assert third is None

    manager.release(first, response=_make_ask(first.settings.instance, "q1", ok=True))
    manager.release(second, exc=RuntimeError("boom"))
    summary = manager.summarize()

    assert summary.workers_ready == 1
    assert summary.workers_error == 1
    assert summary.capacity_available is True


def test_worker_pool_health_payload_reports_warming_before_refresh(tmp_path, monkeypatch):
    _configure_env(tmp_path, monkeypatch)
    template_settings = get_settings(instance="template", driver_mode="web")
    manager = WorkerPoolManager(
        template_settings=template_settings,
        worker_count=2,
        service_factory=lambda settings: FakeService(settings),
    )

    payload = manager.health_payload()

    assert payload["ok"] is False
    assert payload["status"] == "warming"
    assert payload["warming_up"] is True
    assert payload["error_code"] == "WARMING_UP"
    assert payload["pool"]["workers_warming"] == 2


def test_worker_pool_status_transitions(tmp_path, monkeypatch):
    _configure_env(tmp_path, monkeypatch)

    template_settings = get_settings(instance="template", driver_mode="web")
    manager = WorkerPoolManager(
        template_settings=template_settings,
        worker_count=1,
        service_factory=lambda settings: FakeService(settings),
    )
    manager.refresh_all()

    worker = manager.try_acquire()
    assert worker is not None
    assert worker.status == "busy"

    manager.release(worker, response=_make_ask(worker.settings.instance, "q", ok=False, error_code="LOGIN_REQUIRED"))

    assert worker.status == "login_required"
    summary = manager.summarize()
    assert summary.workers_login_required == 1
    assert summary.capacity_available is False


def test_worker_pool_health_payload_prefers_login_required(tmp_path, monkeypatch):
    _configure_env(tmp_path, monkeypatch)
    services = {}

    def service_factory(settings):
        service = FakeService(settings)
        services[settings.instance] = service
        return service

    template_settings = get_settings(instance="template", driver_mode="web")
    manager = WorkerPoolManager(template_settings=template_settings, worker_count=2, service_factory=service_factory)

    services_map = manager.workers
    services[services_map[0].settings.instance].health_response = _make_health(
        services_map[0].settings.instance,
        ok=False,
        error_code="LOGIN_REQUIRED",
    )
    services[services_map[1].settings.instance].health_response = _make_health(
        services_map[1].settings.instance,
        ok=False,
        error_code="CAPTURE_FAILED",
    )

    manager.refresh_all()
    payload = manager.health_payload()

    assert payload["ok"] is False
    assert payload["error_code"] == "LOGIN_REQUIRED"
    assert payload["pool"]["workers_login_required"] == 1
    assert payload["pool"]["workers_error"] == 1


def test_worker_pool_seeds_profiles_from_template(tmp_path, monkeypatch):
    _configure_env(tmp_path, monkeypatch)
    template_settings = get_settings(instance="default", driver_mode="web")
    source_file = template_settings.web_profile_dir / "Default" / "Preferences"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text('{"auth": true}', encoding="utf-8")
    template_settings.target_url_state_path.write_text("https://ima.qq.com/wiki/123", encoding="utf-8")

    manager = WorkerPoolManager(
        template_settings=template_settings,
        worker_count=2,
        service_factory=lambda settings: FakeService(settings),
    )

    seeded = manager.seed_profiles_from(template_settings)

    assert seeded == 2
    for worker in manager.workers:
        copied = worker.settings.web_profile_dir / "Default" / "Preferences"
        assert copied.exists()
        assert copied.read_text(encoding="utf-8") == '{"auth": true}'
        assert worker.settings.target_url_state_path.read_text(encoding="utf-8") == "https://ima.qq.com/wiki/123"


def test_worker_pool_caches_model_catalog_during_refresh(tmp_path, monkeypatch):
    _configure_env(tmp_path, monkeypatch)
    services = {}

    def service_factory(settings):
        service = FakeService(settings)
        services[settings.instance] = service
        return service

    template_settings = get_settings(instance="template", driver_mode="web")
    manager = WorkerPoolManager(template_settings=template_settings, worker_count=1, service_factory=service_factory)

    manager.refresh_all()

    worker = manager.workers[0]
    cached = manager.get_model_catalog()

    assert worker.status == "ready"
    assert cached.current_model == "DeepSeek V3.2 Think"
    assert len(cached.options) == 2
    assert services[worker.settings.instance].model_catalog_calls == 1

    worker_after = manager.try_acquire()
    assert worker_after is worker


def test_worker_pool_refresh_in_background_warms_workers(tmp_path, monkeypatch):
    _configure_env(tmp_path, monkeypatch)
    template_settings = get_settings(instance="template", driver_mode="web")
    manager = WorkerPoolManager(
        template_settings=template_settings,
        worker_count=2,
        service_factory=lambda settings: FakeService(settings),
    )

    assert manager.refresh_in_background() is True

    for _ in range(100):
        payload = manager.health_payload()
        if payload["ok"] and not payload["refresh_in_progress"]:
            break
        time.sleep(0.01)
    else:
        raise AssertionError("background warmup did not finish")

    assert payload["status"] == "ready"
    assert payload["pool"]["workers_ready"] == 2
