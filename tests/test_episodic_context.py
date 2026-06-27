import unittest

from episodic_context import DIGEST_RUN_CONTEXT, reset_digest_run_context, select_retrieval_correction_type


class SelectRetrievalCorrectionTypeTests(unittest.TestCase):
    def setUp(self):
        reset_digest_run_context()

    def tearDown(self):
        reset_digest_run_context()

    def test_priority_override_selected_for_vip_signal(self):
        DIGEST_RUN_CONTEXT["by_action"]["key_highlights"] = "VIP attendee needsaction before meeting"
        self.assertEqual(select_retrieval_correction_type(), "priority_override")

    def test_missed_item_selected_for_missing_signal(self):
        DIGEST_RUN_CONTEXT["by_action"]["emails"] = "We missed this sender in the digest"
        self.assertEqual(select_retrieval_correction_type(), "missed_item")

    def test_irrelevant_item_selected_for_noise_signal(self):
        DIGEST_RUN_CONTEXT["by_action"]["emails"] = "This is too much noise and irrelevant"
        self.assertEqual(select_retrieval_correction_type(), "irrelevant_item")

    def test_empty_scope_when_no_signals(self):
        DIGEST_RUN_CONTEXT["by_action"]["calendar"] = "Upcoming events listed"
        self.assertEqual(select_retrieval_correction_type(), "")


if __name__ == "__main__":
    unittest.main()
