import tempfile
import unittest
from pathlib import Path
from europe_history import PostingHistory


class HistoryTests(unittest.TestCase):
    def test_restart_and_uncertain_post(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'history.sqlite';a=PostingHistory(path)
            a.reserve(1,'FR');a.close();b=PostingHistory(path)
            self.assertEqual(b.successful(),[])
            with self.assertRaises(ValueError):b.reserve(2,'RO')
            b.confirm(1,'status-1');b.close();c=PostingHistory(path)
            self.assertEqual(c.successful()[0]['status_id'],'status-1')
            with self.assertRaises(ValueError):c.reserve(1,'FR')
            with self.assertRaises(ValueError):c.reserve(3,'FR')
            c.reserve(2,'RO');c.release_confirmed_failure(2)
            self.assertEqual(len(c.successful()),1)
            c.reserve(2,'RO');c.confirm(2,'status-2');c.close()

    def test_two_connections_cannot_reserve(self):
        with tempfile.TemporaryDirectory() as d:
            a=PostingHistory(Path(d)/'history.sqlite');b=PostingHistory(Path(d)/'history.sqlite')
            a.reserve(1,'FR')
            with self.assertRaises(ValueError):b.reserve(2,'RO')
            a.close();b.close()


if __name__=='__main__':unittest.main()
