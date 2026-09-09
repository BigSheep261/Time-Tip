import tempfile, unittest, zipfile
from pathlib import Path
from app.infrastructure.database import DataStore

class DatabaseTests(unittest.TestCase):
    def test_classified_sqlite_data_roundtrip_and_zip_cover(self):
        with tempfile.TemporaryDirectory() as folder:
            store = DataStore(folder)
            store.set("date_format", "both")
            store.write_json("anime", [{"id":"a1", "title":"测试", "cover":""}])
            export = Path(folder) / "backup.zip"
            store.export_data(str(export))
            self.assertTrue((Path(folder) / "timetip.sqlite3").exists())
            restored = Path(folder) / "restored"
            imported = DataStore(str(restored)); imported.import_data(str(export))
            self.assertEqual(imported.get("date_format"), "both")
            self.assertEqual(imported.read_json("anime", [])[0]["title"], "测试")
            with zipfile.ZipFile(export) as archive: self.assertIn("data.json", archive.namelist())
            store.close(); imported.close()
    def test_json_import_rejects_invalid_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "bad.json"; source.write_text("{}", encoding="utf-8")
            store = DataStore(folder)
            try:
                with self.assertRaises(ValueError): store.import_data(str(source))
            finally:
                store.close()
if __name__ == "__main__": unittest.main()
