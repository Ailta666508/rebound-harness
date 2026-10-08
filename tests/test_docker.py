"""Opt-in tests against a real Docker daemon and pre-pulled Python image.

Run: REBOUND_TEST_DOCKER=1 pytest tests/test_docker.py -q
No Docker behavior is mocked. Named containers are removed even on assertion
failure so an integration test cannot deliberately leave its workload running.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import uuid
from types import SimpleNamespace

import pytest

import rebound.tools as tools_module

pytestmark = pytest.mark.skipif(
    os.getenv("REBOUND_TEST_DOCKER") != "1",
    reason="enable real Docker integration with REBOUND_TEST_DOCKER=1",
)


def inspect_container(name: str) -> dict | None:
    result = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, timeout=10)
    if result.returncode:
        # A stopped but retained container still appears in inspect and fails cleanup checks.
        if "No such" not in result.stderr:
            raise AssertionError(f"Docker inspection failed: {result.stderr}")
        return None
    return json.loads(result.stdout)[0]


@pytest.fixture
def named_container(monkeypatch):
    assert shutil.which("docker"), "REBOUND_TEST_DOCKER=1 requires Docker on PATH"
    identity = uuid.uuid4()
    name = "rebound-" + identity.hex
    # Only control the generated name; calls still launch the real CLI and engine.
    monkeypatch.setattr(tools_module, "uuid", SimpleNamespace(uuid4=lambda: identity))
    yield name
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)


async def wait_until_running(name: str, task: asyncio.Task) -> None:
    async with asyncio.timeout(12):
        while True:
            if task.done():
                raise AssertionError(f"Container workload exited before inspection: {task.result()}")
            container = await asyncio.to_thread(inspect_container, name)
            if container and container["State"]["Running"]:
                return
            await asyncio.sleep(0.05)


async def test_container_enforces_filesystem_privilege_and_network_boundaries(named_container):
    code = r'''
import errno
import json
import os
from pathlib import Path
import socket

status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
mounts = {parts[1]: parts[3].split(",") for line in Path("/proc/mounts").read_text().splitlines() if (parts := line.split())}
path = Path("/tmp/writable-check")
path.write_text("temporary output")
root_write_denied = False
try:
    Path("/root-write-check").write_text("must fail")
except OSError as error:
    root_write_denied = error.errno in (errno.EROFS, errno.EACCES, errno.EPERM)
# UDP connect checks route availability without sending any application payload.
network_unreachable = False
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
    connection.settimeout(0.3)
    try:
        connection.connect(("198.51.100.1", 9))
    except OSError as error:
        network_unreachable = error.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EACCES, errno.EPERM)
print(json.dumps({
    "uid": os.getuid(), "gid": os.getgid(),
    "cap_effective": int(status["CapEff"].strip(), 16),
    "cap_bounding": int(status["CapBnd"].strip(), 16),
    "no_new_privs": int(status["NoNewPrivs"].strip()),
    "root_mount_read_only": "ro" in mounts["/"],
    "root_write_denied": root_write_denied,
    "tmp_writable": path.read_text() == "temporary output",
    "tmp_noexec": "noexec" in mounts["/tmp"],
    "interfaces": sorted(name for _, name in socket.if_nameindex()),
    "network_unreachable": network_unreachable,
    "docker_socket_present": Path("/var/run/docker.sock").exists(),
}))
'''
    result = await tools_module.docker_tool().execute("isolation-test", {"code": code})
    assert result["exit_code"] == 0, result["stderr"]
    observed = json.loads(result["stdout"])
    assert observed["uid"] == observed["gid"] == 65534
    assert observed["cap_effective"] == observed["cap_bounding"] == 0
    assert observed["no_new_privs"] == 1
    assert observed["root_mount_read_only"] and observed["root_write_denied"]
    assert observed["tmp_writable"] and observed["tmp_noexec"]
    assert observed["interfaces"] == ["lo"] and observed["network_unreachable"]
    assert not observed["docker_socket_present"]
    assert await asyncio.to_thread(inspect_container, named_container) is None


async def test_timeout_cancellation_removes_running_container(named_container):
    task = asyncio.create_task(tools_module.docker_tool().execute(
        "cancel-test", {"code": "import time; time.sleep(60)"},
    ))
    try:
        await wait_until_running(named_container, task)
        # Match Runtime's wait_for cancellation after the engine has started work.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(task, timeout=0.05)
        assert task.cancelled()
        assert await asyncio.to_thread(inspect_container, named_container) is None
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
async def test_output_limit_fails_and_removes_container(named_container, stream):
    # Write beyond the reader budget and remain alive, requiring explicit cleanup.
    code = (f"import sys, time; sys.{stream}.write('x' * 2000000); "
            f"sys.{stream}.flush(); time.sleep(60)")
    task = asyncio.create_task(tools_module.docker_tool().execute("output-limit-test", {"code": code}))
    try:
        with pytest.raises(RuntimeError, match="sandbox output limit exceeded"):
            await asyncio.wait_for(task, timeout=15)
        assert await asyncio.to_thread(inspect_container, named_container) is None
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
