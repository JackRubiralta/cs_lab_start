"""VS Code setup (settings, trusted folders) and the ~/Documents/x launcher.
Run: python3 -m unittest discover tests"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lab_start  # noqa: E402


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "Code/User/settings.json")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        with open(self.path) as f:
            return json.load(f)

    def test_fresh_profile_gets_auto_save_and_no_onboarding(self):
        changed = lab_start.apply_vscode_settings(self.path)
        s = self.read()
        self.assertEqual(s["files.autoSave"], "afterDelay")
        self.assertIs(s["workbench.welcomePage.experimentalOnboarding"], False)
        self.assertEqual(sorted(changed), sorted(lab_start.VSCODE_SETTINGS))
        self.assertEqual(lab_start.apply_vscode_settings(self.path), [])   # second run: nothing to do

    def test_keeps_your_own_choices(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            json.dump({"files.autoSave": "onFocusChange", "editor.fontSize": 16}, f)
        lab_start.apply_vscode_settings(self.path)
        s = self.read()
        self.assertEqual(s["files.autoSave"], "onFocusChange")
        self.assertEqual(s["editor.fontSize"], 16)

    def test_leaves_unparseable_file_alone(self):
        os.makedirs(os.path.dirname(self.path))
        text = '{\n  // my comment\n  "editor.fontSize": 16,\n}\n'
        with open(self.path, "w") as f:
            f.write(text)
        self.assertIsNone(lab_start.apply_vscode_settings(self.path))
        with open(self.path) as f:
            self.assertEqual(f.read(), text)

    def test_user_dir_per_build(self):
        self.assertTrue(lab_start.vscode_user_dir(["/usr/bin/code"]).endswith("/Code/User"))
        self.assertTrue(lab_start.vscode_user_dir(["/usr/bin/codium"]).endswith("/VSCodium/User"))
        self.assertIn("com.visualstudio.code",
                      lab_start.vscode_user_dir(["flatpak", "run", "com.visualstudio.code"]))


class Trust(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "User/globalStorage/state.vscdb")

    def tearDown(self):
        self.tmp.cleanup()

    def model(self):
        con = sqlite3.connect(self.db)
        try:
            (value,) = con.execute("SELECT value FROM ItemTable WHERE key = ?",
                                   (lab_start.TRUST_KEY,)).fetchone()
        finally:
            con.close()
        return json.loads(value)

    def test_trusts_documents_in_vscode_format(self):
        added = lab_start.trust_folders(self.db, ["/home/u/Documents/", "/cs/home/u"])
        self.assertEqual(added, ["/home/u/Documents", "/cs/home/u"])
        info = self.model()["uriTrustInfo"]
        self.assertEqual(info[0], {"uri": {"$mid": 1, "fsPath": "/home/u/Documents",
                                           "external": "file:///home/u/Documents",
                                           "path": "/home/u/Documents", "scheme": "file"},
                                   "trusted": True})
        self.assertEqual(lab_start.trust_folders(self.db, ["/home/u/Documents"]), [])   # no duplicates

    def test_keeps_existing_trust_and_other_keys(self):
        os.makedirs(os.path.dirname(self.db))
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
        old = {"uriTrustInfo": [{"uri": {"$mid": 1, "path": "/srv/x", "scheme": "file"}, "trusted": True}]}
        con.execute("INSERT INTO ItemTable VALUES (?, ?)", (lab_start.TRUST_KEY, json.dumps(old)))
        con.execute("INSERT INTO ItemTable VALUES ('theme', 'dark')")
        con.commit()
        con.close()
        lab_start.trust_folders(self.db, ["/home/u/Documents"])
        paths = [e["uri"]["path"] for e in self.model()["uriTrustInfo"]]
        self.assertEqual(paths, ["/srv/x", "/home/u/Documents"])
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT value FROM ItemTable WHERE key='theme'").fetchone()[0], "dark")
        con.close()


class Launcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.x = os.path.join(self.tmp.name, "x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_makes_runnable_x_once(self):
        self.assertTrue(lab_start.make_launcher(self.x))
        self.assertTrue(os.access(self.x, os.X_OK))
        with open(self.x) as f:
            body = f.read()
        self.assertIn(os.path.join(lab_start.HERE, "start"), body)
        self.assertFalse(lab_start.make_launcher(self.x))   # already there
        r = subprocess.run(["sh", "-n", self.x])
        self.assertEqual(r.returncode, 0)

    def test_never_replaces_someone_elses_x(self):
        with open(self.x, "w") as f:
            f.write("my own notes\n")
        self.assertIsNone(lab_start.make_launcher(self.x))
        with open(self.x) as f:
            self.assertEqual(f.read(), "my own notes\n")


if __name__ == "__main__":
    unittest.main()
