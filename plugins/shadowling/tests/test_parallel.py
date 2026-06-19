import io
import unittest
from contextlib import redirect_stderr

import parallel


class FanOutTest(unittest.TestCase):
    def test_collects_ok_results_by_name(self):
        jobs = {"a": lambda: 1, "b": lambda: 2}
        ok, failed = parallel.fan_out(jobs, max_workers=2)
        self.assertEqual(ok, {"a": 1, "b": 2})
        self.assertEqual(failed, {})

    def test_failing_thunk_lands_in_failed_not_raised(self):
        def boom():
            raise ValueError("nope")

        ok, failed = parallel.fan_out({"a": lambda: 1, "b": boom}, max_workers=2)
        self.assertEqual(ok, {"a": 1})
        self.assertIn("b", failed)
        self.assertIsInstance(failed["b"], ValueError)

    def test_logs_name_and_status_to_stderr(self):
        def boom():
            raise ValueError("nope")

        buf = io.StringIO()
        with redirect_stderr(buf):
            parallel.fan_out({"good": lambda: 1, "bad": boom}, max_workers=2)
        err = buf.getvalue()
        self.assertIn("good", err)
        self.assertIn("bad", err)
        self.assertIn("OK", err)
        self.assertIn("ERROR", err)


class WithRetryTest(unittest.TestCase):
    def test_returns_first_success_without_retry(self):
        calls = []
        out = parallel.with_retry(lambda: calls.append(1) or "ok", sleep=lambda _: None)
        self.assertEqual(out, "ok")
        self.assertEqual(len(calls), 1)

    def test_retries_then_succeeds(self):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise TimeoutError("transient")
            return "done"

        out = parallel.with_retry(
            flaky, attempts=3, retry_on=TimeoutError, sleep=lambda _: None
        )
        self.assertEqual(out, "done")
        self.assertEqual(len(calls), 3)

    def test_gives_up_after_attempts_and_reraises(self):
        calls = []

        def always():
            calls.append(1)
            raise TimeoutError("transient")

        with self.assertRaises(TimeoutError):
            parallel.with_retry(
                always, attempts=3, retry_on=TimeoutError, sleep=lambda _: None
            )
        self.assertEqual(len(calls), 3)

    def test_does_not_retry_unlisted_exception(self):
        calls = []

        def boom():
            calls.append(1)
            raise ValueError("not retryable")

        with self.assertRaises(ValueError):
            parallel.with_retry(
                boom, attempts=3, retry_on=TimeoutError, sleep=lambda _: None
            )
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
