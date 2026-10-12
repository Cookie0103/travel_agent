"""R12：真实HTTP/API kill→重启→SSE补发/快照；没有付费模型。"""

import asyncio
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import URL

from backend.persistence.catalog import import_catalog
from backend.persistence.database import Database
from backend.services.common import transaction
from data.import_catalog import load_snapshot

pytestmark = pytest.mark.integration


@contextmanager
def api_process(
    url: URL, *, interrupt: bool = False
) -> Iterator[tuple[str, subprocess.Popen[str]]]:
    with subprocess.Popen(
        [sys.executable, "-m", "tests.integration.api_process"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
    ) as process:
        assert process.stdin and process.stdout
        process.stdin.write(
            json.dumps({"dsn": url.render_as_string(hide_password=False), "interrupt": interrupt})
            + "\n"
        )
        process.stdin.flush()
        with ThreadPoolExecutor(max_workers=1) as reader:
            try:
                endpoint = reader.submit(process.stdout.readline).result(timeout=10).strip()
                assert endpoint.startswith("http://127.0.0.1:")
                yield endpoint, process
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)


def test_api_process_crash_preserves_committed_conditions_and_unblocks_session(
    postgres_url: URL,
) -> None:
    async def import_data() -> None:
        database = Database(postgres_url)
        try:
            async with transaction(database) as db:
                await import_catalog(db, load_snapshot())
        finally:
            await database.close()

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(import_data())
    with api_process(postgres_url, interrupt=True) as (endpoint, process):
        with httpx.Client(base_url=endpoint, timeout=5, trust_env=False) as client:
            user = client.post("/demo/login", json={"display_name": "API恢复实验"}).json()
            headers = {"Authorization": "Bearer " + user["token"]}
            sid = client.post("/sessions", headers=headers).json()["session_id"]
            assert (
                client.patch(
                    f"/sessions/{sid}/request",
                    headers=headers,
                    json={"expected_revision": 0, "set": {"city": "京都", "rooms": 1}},
                ).status_code
                == 200
            )
            message = {"client_message_id": str(uuid4()), "text": "房间改成2", "mode": "offline"}
            submitted = client.post(f"/sessions/{sid}/messages", headers=headers, json=message)
            assert submitted.status_code == 202
            run_id = submitted.json()["run_id"]
            assert process.stdout
            with ThreadPoolExecutor(max_workers=1) as reader:
                try:
                    assert (
                        reader.submit(process.stdout.readline).result(timeout=10).strip()
                        == "business_committed"
                    )
                finally:
                    process.kill()
    with api_process(postgres_url) as (endpoint, _):
        with httpx.Client(base_url=endpoint, timeout=5, trust_env=False) as client:
            saved = client.get(f"/sessions/{sid}/request", headers=headers).json()
            assert saved["revision"] == 2 and saved["rooms"] == 2
            recovered = client.get(f"/runs/{run_id}", headers=headers).json()
            assert recovered["status"] == "partial" and recovered["error_code"] == "unavailable"
            replay = client.get(f"/runs/{run_id}/events", headers=headers)
            assert '"kind":"partial"' in replay.text
            # 游标重连只读，终态快照不变；重复原消息返回原执行。
            assert not client.get(
                f"/runs/{run_id}/events",
                headers=headers,
                params={"after": recovered["last_sequence"]},
            ).text.strip()
            assert (
                client.post(f"/sessions/{sid}/messages", headers=headers, json=message).json()
                == recovered
            )
            assert client.get(f"/runs/{run_id}", headers=headers).json() == recovered
            new = client.post(
                f"/sessions/{sid}/messages",
                headers=headers,
                json={"client_message_id": str(uuid4()), "text": "比较酒店", "mode": "offline"},
            )
            assert new.status_code == 202 and new.json()["run_id"] != run_id
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                current = client.get("/runs/" + new.json()["run_id"], headers=headers).json()
                if current["status"] not in {"running", "cancelling"}:
                    break
                time.sleep(0.01)
            assert current["status"] == "completed"
