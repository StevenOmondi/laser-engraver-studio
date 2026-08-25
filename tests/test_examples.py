import unittest

from laserengraver.core.examples import list_demo_jobs
from laserengraver.core.gcode import gcode_stats


class DemoExampleTests(unittest.TestCase):
    def test_demo_keys_are_unique(self):
        keys = [demo.key for demo in list_demo_jobs()]

        self.assertEqual(len(keys), len(set(keys)))

    def test_air_assist_cut_demos_use_air_commands_and_laser_power(self):
        air_demos = [demo for demo in list_demo_jobs() if demo.key.startswith("air_assist")]

        self.assertGreaterEqual(len(air_demos), 6)
        for demo in air_demos:
            with self.subTest(demo=demo.key):
                self.assertIn("M8", demo.gcode)
                self.assertIn("M9", demo.gcode)
                self.assertGreater(gcode_stats(demo.gcode).laser_lines, 0)


if __name__ == "__main__":
    unittest.main()
