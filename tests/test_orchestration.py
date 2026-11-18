"""Capacidades de prueba locales, sin dispositivos ni servicios simulados en producción."""

import asyncio

import pytest
from pydantic import BaseModel, ConfigDict, Field

from nexo.interactions import InteractionInput, InteractionService
from nexo.orchestration import (Busy, Capability, CapabilityRegistry, CapabilityResult,
    ExecutionContext, IntentRouter, Orchestrator, ResourceLocks)
from test_interactions import send, assert_error
from test_security import database, initialized, client
from test_terminals import admin, linked


async def handler(payload, context):
    return CapabilityResult(message=context.terminal_id + ":" + payload.text)


def capability(**kwargs):
    values = dict(identifier="test.operation", name="Operación de prueba",
        permissions=frozenset({"terminal.chat"}), resources=frozenset({"test:shared"}),
        input_model=InteractionInput, handler=handler)
    return Capability(**(values | kwargs))


def orchestrator(*capabilities, rules=None):
    registry = CapabilityRegistry(capabilities or [capability()])
    return Orchestrator(registry, IntentRouter(registry, rules or [("prueba", "test.operation")]))


async def execute(service, terminal="one", text="prueba", permissions=frozenset({"terminal.chat"})):
    return await service.execute(text, permissions, ExecutionContext(terminal))


def test_registry_and_selection():
    registry = CapabilityRegistry([capability()])
    assert registry.get("test.operation").input_model.model_json_schema()["properties"]["text"]
    assert registry.get("absent") is None
    with pytest.raises(ValueError):
        registry.register(capability())
    result = asyncio.run(execute(orchestrator()))
    assert result.message == "one:prueba" and result.http_status == 200


@pytest.mark.parametrize("changes", [
    {"identifier": "bad id"}, {"name": " "}, {"resources": frozenset({"Test:shared"})},
    {"resources": frozenset({"terminal:one"})}, {"timeout": 0}, {"timeout": float("nan")},
    {"handler": lambda p, c: None}, {"permissions": {"terminal.chat"}},
])
def test_invalid_registry_contract(changes):
    with pytest.raises(ValueError):
        CapabilityRegistry([capability(**changes)])


def test_unknown_ambiguous_and_exact_routes():
    first, second = capability(), capability(identifier="test.second")
    service = orchestrator(first, second, rules=[("prueba", first.identifier), ("PRUEBA!", second.identifier)])
    for text in ("prueba", "enciende", "prueba y ejecuta shell"):
        assert asyncio.run(execute(service, text=text)).response_type == "unavailable"
    with pytest.raises(ValueError):
        IntentRouter(service.registry, [("hola", "missing")])


@pytest.mark.parametrize("mode", ["permission", "confirmation", "validation"])
def test_rejected_before_execution(mode):
    class Restricted(BaseModel):
        model_config = ConfigDict(extra="forbid")
        text: str = Field(max_length=2)
    calls = []
    async def forbidden(payload, context):
        calls.append(1)
        return CapabilityResult(message="incorrecto")
    cap = capability(handler=forbidden,
        confirmation_required=mode == "confirmation",
        input_model=Restricted if mode == "validation" else InteractionInput)
    service = orchestrator(cap)
    result = asyncio.run(execute(service, permissions=frozenset() if mode == "permission" else cap.permissions))
    assert result.code == {"permission": "forbidden", "confirmation": "confirmation_required", "validation": "invalid_input"}[mode]
    assert not calls and not service.locks._held


def test_atomic_multiple_resources_no_partial_retention():
    locks = ResourceLocks()
    with locks.acquire(["test:b"]):
        with pytest.raises(Busy):
            with locks.acquire(["test:a", "test:b"]):
                pytest.fail("No debe adquirir")
        with locks.acquire(["test:a"]):
            assert locks._held == {"test:a", "test:b"}
    assert not locks._held


def test_atomic_acquisition_from_competing_threads():
    import queue
    import threading
    from concurrent.futures import ThreadPoolExecutor

    locks = ResourceLocks()
    start, release, results = threading.Barrier(3), threading.Event(), queue.Queue()
    def compete(keys):
        start.wait(timeout=3)
        try:
            with locks.acquire(keys):
                results.put("acquired")
                assert release.wait(5)
        except Busy:
            results.put("busy")
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(compete, keys) for keys in
                 (["test:a", "test:b"], ["test:b", "test:a"])]
        try:
            start.wait(timeout=3)
            assert sorted([results.get(timeout=3), results.get(timeout=3)]) == ["acquired", "busy"]
            assert locks._held == {"test:a", "test:b"}
        finally:
            release.set()
        for task in tasks:
            task.result(timeout=3)
    assert not locks._held
    with pytest.raises(ValueError):
        with locks.acquire(["test:a", " test:b"]):
            pass
    assert not locks._held


def test_conflict_parallelism_no_retry_and_success_release():
    async def scenario():
        entered, release, independent = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = []
        async def blocked(payload, context):
            calls.append(context.terminal_id)
            entered.set()
            await release.wait()
            return CapabilityResult(message=context.terminal_id)
        async def other(payload, context):
            independent.set()
            return CapabilityResult(message="independiente")
        one = capability(handler=blocked, resources=frozenset({"test:a", "test:b"}))
        two = capability(identifier="test.other", handler=other, resources=frozenset({"test:c"}))
        service = orchestrator(one, two, rules=[("prueba", one.identifier), ("otra", two.identifier)])
        task = asyncio.create_task(execute(service))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            conflict = await asyncio.wait_for(execute(service, terminal="two"), 2)
            assert conflict.code == "resource_busy" and conflict.http_status == 409
            assert "ocupado" in conflict.message and calls == ["one"]
            # Incluso con otro recurso, el mismo terminal no puede ejecutar dos tareas.
            assert (await execute(service, text="otra")).code == "resource_busy"
            assert (await execute(service, terminal="two", text="otra")).message == "independiente"
            assert independent.is_set() and not task.done()
            assert service.locks._held == {"test:a", "test:b", "terminal:one"}
        finally:
            release.set()
            await task
        assert calls == ["one"] and not service.locks._held
        assert (await execute(service, terminal="two")).message == "two"
        assert calls == ["one", "two"] and not service.locks._held
    asyncio.run(scenario())


def test_exception_and_invalid_result_release_without_logs(caplog):
    caplog.set_level("DEBUG")
    async def failing(payload, context):
        raise RuntimeError("secret-token-content")
    async def invalid(payload, context):
        return {"message": "secret-token-content", "response_type": "arbitrary"}
    for fn in (failing, invalid):
        service = orchestrator(capability(handler=fn))
        result = asyncio.run(execute(service))
        assert result.code == "processing_error" and not service.locks._held
        assert "secret-token-content" not in str(result) + caplog.text


def test_cancellation_releases_resources_and_terminal_context():
    async def scenario():
        entered = asyncio.Event()
        async def blocked(payload, context):
            entered.set()
            await asyncio.Event().wait()
        store = InteractionService(900)
        store.orchestrator = orchestrator(capability(handler=blocked))
        task = asyncio.create_task(store.interact("one", "prueba", frozenset({"terminal.chat"})))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not store.orchestrator.locks._held
        assert not store._contexts["one"].busy and not store._contexts["one"].messages
        store.orchestrator.registry._capabilities["test.operation"] = capability()
        assert (await store.interact("one", "prueba", frozenset({"terminal.chat"}))).http_status == 200
    asyncio.run(scenario())


def test_timeout_no_retry_and_release():
    calls = []
    async def blocked(payload, context):
        calls.append(1)
        await asyncio.Event().wait()
    service = orchestrator(capability(handler=blocked, timeout=0.01))
    result = asyncio.run(execute(service))
    assert result.code == "execution_timeout" and result.http_status == 504
    assert calls == [1] and not service.locks._held


def test_restart_has_no_replay_or_locks():
    first, second = orchestrator(), orchestrator()
    with first.locks.acquire(["test:shared"]):
        assert not second.locks._held
    assert not first.locks._held


def test_http_resource_conflict_permission_and_no_admin_api(admin):
    terminal, headers = linked(admin, ["terminal.chat"])
    store = admin.app.state.interactions
    store.orchestrator = orchestrator()
    with store.orchestrator.locks.acquire(["test:shared"]):
        response = send(admin, headers, "prueba")
        assert_error(response, 409, "resource_busy")
        assert response.json()["terminal_id"] == terminal["terminal"]["id"]
        assert "ocupado" in response.json()["message"]
    assert send(admin, headers, "prueba").status_code == 200
    cap = capability(permissions=frozenset({"terminal.status"}))
    store.orchestrator = orchestrator(cap)
    assert_error(send(admin, headers, "prueba"), 403, "forbidden")
    assert not store.orchestrator.locks._held
    for path in ("/api/v1/terminal/capabilities", "/api/v1/terminal/locks"):
        assert admin.post(path, headers=headers, json={}).status_code == 404


def test_http_timeout_structured(admin):
    async def blocked(payload, context):
        await asyncio.Event().wait()
    _, headers = linked(admin, ["terminal.chat"])
    store = admin.app.state.interactions
    store.orchestrator = orchestrator(capability(handler=blocked, timeout=0.01))
    assert_error(send(admin, headers, "prueba"), 504, "execution_timeout")
    assert not store.orchestrator.locks._held
    assert not next(iter(store._contexts.values())).busy


def test_real_http_concurrent_resources(admin):
    """Uvicorn y sockets TCP reales; solo loopback y puerto efímero."""
    import socket
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import httpx
    import uvicorn

    _, first = linked(admin, ["terminal.chat"])
    _, second = linked(admin, ["terminal.chat"])
    ready, entered = threading.Event(), threading.Event()
    state = {}
    calls = []

    async def blocked(payload, context):
        state["release"] = asyncio.Event()
        state["loop"] = asyncio.get_running_loop()
        calls.append(context.terminal_id)
        entered.set()
        await state["release"].wait()
        return CapabilityResult(message="Operación de prueba terminada")

    cap = capability(handler=blocked, resources=frozenset({"test:a", "test:b"}))
    other = capability(identifier="test.independent", resources=frozenset({"test:c"}))
    service = orchestrator(cap, other, rules=[("prueba", cap.identifier), ("otra", other.identifier)])
    admin.app.state.interactions.orchestrator = service

    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets)
            ready.set()

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = Server(uvicorn.Config(admin.app, lifespan="off", access_log=False, log_level="critical"))
        thread = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[sock])), daemon=True)
        thread.start()
        try:
            assert ready.wait(5)
            url = "http://127.0.0.1:" + str(sock.getsockname()[1])
            with httpx.Client(base_url=url, timeout=5, trust_env=False) as client:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(send, client, first, "prueba")
                    try:
                        assert entered.wait(5)
                        assert_error(send(client, second, "prueba"), 409, "resource_busy")
                        assert_error(send(client, first, "otra"), 409, "terminal_busy")
                        assert send(client, second, "otra").status_code == 200
                        assert not pending.done() and len(calls) == 1
                    finally:
                        if entered.is_set():
                            state["loop"].call_soon_threadsafe(state["release"].set)
                    assert pending.result(timeout=5).status_code == 200
                assert not service.locks._held and len(calls) == 1
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive()
