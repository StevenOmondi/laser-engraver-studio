import unittest

import app as laser_app
from app import app, store


class AppTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.created_jobs: list[str] = []
        self.original_connection = dict(laser_app.settings.get("connection", {}))

    def tearDown(self):
        for job_id in self.created_jobs:
            store.delete_job(job_id)
        laser_app.controller.active_pins = ()
        laser_app.settings["connection"] = self.original_connection

    def test_core_pages_render(self):
        for path in ["/", "/designer", "/jobs", "/console", "/settings"]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_demo_job_preview_and_disarmed_run_block(self):
        self.client.post("/api/connect", json={"mode": "simulator", "baud": 115200})
        response = self.client.post("/api/examples/alignment_frame/create")
        self.assertEqual(response.status_code, 200)
        job_id = response.get_json()["job"]["id"]
        self.created_jobs.append(job_id)

        preview = self.client.get(f"/api/jobs/{job_id}/preview.svg")
        self.assertEqual(preview.status_code, 200)
        self.assertIn(b"<svg", preview.data)

        blocked = self.client.post(f"/api/jobs/{job_id}/run")
        self.assertEqual(blocked.status_code, 403)

    def test_limits_endpoint_applies_safe_settings(self):
        self.client.post("/api/connect", json={"mode": "simulator", "baud": 115200})

        response = self.client.post(
            "/api/limits/apply",
            json={"homing": True, "hard_limits": True, "soft_limits": False},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("$22=1", [item["command"] for item in payload["responses"]])

    def test_connect_remembers_auto_connect_choice(self):
        response = self.client.post(
            "/api/connect",
            json={"mode": "simulator", "baud": 115200, "auto_connect": False},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(laser_app.settings["connection"]["mode"], "simulator")
        self.assertEqual(laser_app.settings["connection"]["baud"], 115200)
        self.assertFalse(laser_app.settings["connection"]["auto_connect"])

    def test_run_blocks_when_limit_switch_is_active(self):
        self.client.post("/api/connect", json={"mode": "simulator", "baud": 115200})
        laser_app.controller.active_pins = ("Y",)
        response = self.client.post("/api/examples/air_assist_pass_ladder/create")
        self.assertEqual(response.status_code, 200)
        job_id = response.get_json()["job"]["id"]
        self.created_jobs.append(job_id)
        checklist = {
            "eye_protection": True,
            "ventilation": True,
            "fire_watch": True,
            "material": True,
            "enclosure": True,
        }
        self.client.post("/api/arm", json={"checklist": checklist, "minutes": 1})

        blocked = self.client.post(f"/api/jobs/{job_id}/run")

        self.assertEqual(blocked.status_code, 400)
        self.assertIn("Active limit switch", blocked.get_json()["message"])

    def test_frame_blocks_when_limit_switch_is_active(self):
        self.client.post("/api/connect", json={"mode": "simulator", "baud": 115200})
        laser_app.controller.active_pins = ("X",)
        response = self.client.post("/api/examples/alignment_frame/create")
        self.assertEqual(response.status_code, 200)
        job_id = response.get_json()["job"]["id"]
        self.created_jobs.append(job_id)

        blocked = self.client.post(f"/api/jobs/{job_id}/frame")

        self.assertEqual(blocked.status_code, 400)
        self.assertIn("Active limit switch", blocked.get_json()["message"])

    def test_laser_power_command_blocks_when_limit_switch_is_active(self):
        self.client.post("/api/connect", json={"mode": "simulator", "baud": 115200})
        laser_app.controller.active_pins = ("Z",)
        checklist = {
            "eye_protection": True,
            "ventilation": True,
            "fire_watch": True,
            "material": True,
            "enclosure": True,
        }
        self.client.post("/api/arm", json={"checklist": checklist, "minutes": 1})

        blocked = self.client.post("/api/command", json={"command": "M4 S10"})

        self.assertEqual(blocked.status_code, 400)
        self.assertIn("Active limit switch", blocked.get_json()["message"])


if __name__ == "__main__":
    unittest.main()
