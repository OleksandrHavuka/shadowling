import re
import unittest

import traceability


class HeredocDiscoveryTest(unittest.TestCase):
    def test_regex_extracts_cat_and_ordered_tags(self):
        sample = (
            "python3 \"${CLAUDE_SKILL_DIR}/grammar.py\" record <<'SL_IN'\n"
            "<slug>s</slug>\n<problem>p</problem>\n<rule>r</rule>\nSL_IN\n"
        )
        m = traceability._RECORD_HEREDOC.search(sample)
        self.assertEqual(m.group(1), "grammar")  # category = entrypoint basename
        tags = re.findall(r"(?m)^<(\w+)>", m.group(3))
        self.assertEqual(tags, ["slug", "problem", "rule"])

    def test_real_skills_discovered_with_signature_tags(self):
        found = {cat: tags for cat, tags, _ in traceability._discover_record_lines()}
        self.assertEqual(
            found["grammar"], ["slug", "problem", "original", "fixed", "rule"]
        )
        # decode documents the enum as a <type> tag (recorder param is `kind`)
        self.assertIn("type", found["decode"])


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

    def test_check_reports_unparseable_prompt_sql_instead_of_crashing(self):
        # robustness: a future PROMPT_SQL whose FROM isn't a bare table name must
        # become a clean violation, never an AttributeError that crashes the gate.
        import models.tutor as tutor

        saved = dict(tutor.PROMPT_SQL)
        tutor.PROMPT_SQL["__probe__"] = "SELECT translation FROM (subquery)"
        try:
            violations = traceability.check()  # must not raise
            self.assertTrue(any("__probe__" in v for v in violations))
        finally:
            tutor.PROMPT_SQL.clear()
            tutor.PROMPT_SQL.update(saved)


if __name__ == "__main__":
    unittest.main()
