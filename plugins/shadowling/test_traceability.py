import unittest

import traceability


class TraceabilityTest(unittest.TestCase):
    def test_data_structure_contract_holds(self):
        # schema <-> models <-> skill record placeholders <-> tutor PROMPT_SQL.
        # check() runs against a throwaway DB, so no SHADOWLING_HOME setUp needed.
        violations = traceability.check()
        self.assertEqual(
            violations, [], "\n".join(["traceability drift:"] + violations)
        )

    def test_check_catches_drift(self):
        # the check must be able to FAIL — temporarily break one model's
        # insert_cols and confirm a violation is reported, then restore.
        import models

        verbs = models.REGISTRY["verbs"]
        original = verbs.insert_cols
        verbs.insert_cols = original + ["ghost_column"]
        try:
            violations = traceability.check()
            self.assertTrue(
                any("ghost_column" in v for v in violations),
                "check() failed to catch an injected bad insert_col",
            )
        finally:
            verbs.insert_cols = original

    def test_check_flags_new_recorder_without_skill_line(self):
        # robustness to growth: a newly registered recorder that no skill
        # documents must be flagged, not silently ignored.
        import models

        models.RECORDERS["__ghost_cat__"] = lambda a, b: "ok"
        try:
            violations = traceability.check()
            self.assertTrue(
                any("__ghost_cat__" in v for v in violations),
                "check() failed to flag a recorder with no skill record line",
            )
        finally:
            del models.RECORDERS["__ghost_cat__"]


if __name__ == "__main__":
    unittest.main()
