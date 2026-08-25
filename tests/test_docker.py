from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.routing import classify_task, resolve_worker
from app.agent.workers.docker import docker_status, run_docker_job
from app.tools.docker_tools import DockerTool, docker_daemon_ok


class DockerWorkerTests(unittest.IsolatedAsyncioTestCase):
    def test_daemon_ok_on_this_machine(self) -> None:
        ok, reason = docker_daemon_ok()
        self.assertTrue(ok, reason)
        status = docker_status()
        self.assertTrue(status["available"], status)

    def test_docker_prompt_routes_to_docker_class(self) -> None:
        route = classify_task("Use docker run to execute a containerized hello-world job and show the logs.")
        self.assertEqual(route.task_class, "docker")
        self.assertIn("docker", route.preferred_tools)
        self.assertEqual(resolve_worker("docker").name, "docker")

    async def test_run_without_image_fails_cleanly(self) -> None:
        result = await DockerTool().execute(action="run")
        self.assertFalse(result.success)
        self.assertIn("image", result.error.lower())

    async def test_run_hello_world_container(self) -> None:
        result = await DockerTool().execute(action="run", image="hello-world")
        self.assertTrue(result.success, result.error or result.output)
        combined = (result.output or "") + (result.error or "")
        self.assertIn("Hello from Docker", combined)
        job = await run_docker_job("hello-world")
        self.assertTrue(job["ok"], job)


if __name__ == "__main__":
    unittest.main()
