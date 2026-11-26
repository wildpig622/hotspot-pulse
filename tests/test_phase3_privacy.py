import unittest
from scripts.phase3_public_evidence import redact


class PublicEvidencePrivacyTests(unittest.TestCase):
    def test_synthetic_contacts_are_removed_but_event_dates_are_preserved(self):
        synthetic_phone='1'+'3'+'0'*9
        text='西安会议：2026年12月19日。联系 contact@example.org '+synthetic_phone
        clean,counts=redact(text)
        self.assertNotIn(synthetic_phone,clean);self.assertNotIn('contact@example.org',clean)
        self.assertIn('2026年12月19日',clean);self.assertEqual(counts,{'email':1,'phone':1})

    def test_entity_encoded_and_tag_split_contacts_are_also_removed(self):
        text='<b>contact</b>&#64;<i>example.org</i>'
        clean,counts=redact(text)
        self.assertEqual(counts['email'],1);self.assertNotIn('contact',clean.lower().replace('contact_email_removed',''))
        self.assertIn('<b>',clean);self.assertIn('<i>',clean)
