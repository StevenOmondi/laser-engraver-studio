import tempfile
import unittest
from pathlib import Path

from laserengraver.core.jobs import JobStore


class JobStoreTests(unittest.TestCase):
    def test_save_and_load_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp))

            record = store.save_job("Small square", "G90\nG0 X0 Y0\nG1 X10 Y10\n", "test")
            loaded, gcode = store.get_job(record.id)

            self.assertEqual(loaded.name, "Small square")
            self.assertIn("G1 X10 Y10", gcode)
            self.assertEqual(len(store.list_jobs()), 1)

    def test_rejects_unsafe_job_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp))

            with self.assertRaises(FileNotFoundError):
                store.get_job("../outside")

            with self.assertRaises(FileNotFoundError):
                store.delete_job("bad/id")


if __name__ == "__main__":
    unittest.main()
