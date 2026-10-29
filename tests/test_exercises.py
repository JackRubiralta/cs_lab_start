"""Exercise copier: placement, zip handling, never overwriting. Run: python3 -m unittest discover tests"""
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lab_start  # noqa: E402


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class ExerciseSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "studres")
        self.dst = os.path.join(self.tmp.name, "Documents/CS1002/Exercises")
        lab_start.STUDRES_EXERCISES, lab_start.MY_EXERCISES = self.src, self.dst
        s = self.src
        # W07 style: code beside Tests/
        write(f"{s}/W07/Tests/practical.config", "[info]\nsrcdir = W07Exercises\n")
        write(f"{s}/W07/Tests/prog-run-x.out", "expected")
        write(f"{s}/W07/W07Exercises.java", "class W07Exercises {}")
        write(f"{s}/W07/W07Exercises.html", "<html>")
        write(f"{s}/W07/css/standard.css", "css")
        # W02 style: one Tests folder per exercise + a zip with the same files
        write(f"{s}/W02/W02Exercises/W02Exercise1/Tests/practical.config", "srcdir = W02Exercise1\n")
        write(f"{s}/W02/W02Exercises/W02Exercise1/W02Exercise1.java", "loose")
        os.makedirs(f"{s}/W02", exist_ok=True)
        with zipfile.ZipFile(f"{s}/W02/W02Exercises.zip", "w") as z:
            z.writestr("W02Exercises/W02Exercise1/W02Exercise1.java", "zipped")
            z.writestr("W02Exercises/.DS_Store", "junk")
        # W01 style: starter only in a zip with a wrapper folder
        write(f"{s}/W01/Tests/practical.config", "srcdir = W01Exercises\n")
        with zipfile.ZipFile(f"{s}/W01/W01ExercisesStarter.zip", "w") as z:
            z.writestr("W01ExercisesStarter/W01Exercises/W01Exercise1.java", "starter")
        # W03 style: tests but no starter code at all
        write(f"{s}/W03/Tests/Part1/practical.config", "srcdir = W03Exercises\n")
        write(f"{s}/W03/W03Exercises.html", "<html>")
        write(f"{s}/Challenges/Challenges.txt", "not a week")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, rel):
        with open(os.path.join(self.dst, rel)) as f:
            return f.read()

    def test_layout(self):
        self.assertTrue(lab_start.sync_exercises())
        self.assertEqual(self.read("W07/W07Exercises/W07Exercises.java"), "class W07Exercises {}")
        self.assertEqual(self.read("W07/W07Exercises.html"), "<html>")
        self.assertTrue(os.path.isfile(os.path.join(self.dst, "W07/css/standard.css")))
        self.assertEqual(self.read("W02/W02Exercise1/W02Exercise1.java"), "loose")
        self.assertEqual(self.read("W01/W01Exercises/W01Exercise1.java"), "starter")
        self.assertTrue(os.path.isdir(os.path.join(self.dst, "W03/W03Exercises")))
        for junk in ("W07/Tests", "W02/W02Exercises/.DS_Store", "Challenges"):
            self.assertFalse(os.path.exists(os.path.join(self.dst, junk)), junk)

    def test_never_overwrites(self):
        lab_start.sync_exercises()
        mine = os.path.join(self.dst, "W07/W07Exercises/W07Exercises.java")
        write(mine, "my answers")
        os.remove(os.path.join(self.dst, "W07/W07Exercises.html"))
        write(f"{self.src}/W08/Tests/practical.config", "srcdir = W08Exercises\n")
        write(f"{self.src}/W08/W08Exercises.java", "new week")
        lab_start.sync_exercises()
        self.assertEqual(self.read("W07/W07Exercises/W07Exercises.java"), "my answers")
        self.assertEqual(self.read("W07/W07Exercises.html"), "<html>")   # missing file restored
        self.assertEqual(self.read("W08/W08Exercises/W08Exercises.java"), "new week")

    def test_dry_run_writes_nothing(self):
        lab_start.sync_exercises(dry_run=True)
        self.assertFalse(os.path.exists(self.dst))


if __name__ == "__main__":
    unittest.main()
