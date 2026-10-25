#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from detroit_cognitive_memory import EpisodicMemory, faction_for
from detroit_reasoning_governor import decide


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.world = Path(self.temp.name) / 'detroit_persistent'
        self.world.mkdir()
        (self.world / 'factions.json').write_text(json.dumps({'factions': {
            'red': {'name': 'Obsidian Network', 'members': ['Morbeious', 'Alex Medina']},
            'blue': {'name': 'ThAI Guardians', 'leader': 'TGOT', 'members': ['Amber Delacroix']},
        }}))
        self.memory = EpisodicMemory(self.world)

    def test_recall_acl_and_persistence(self):
        self.assertTrue(self.memory.remember(event_id='1', category='goal', visibility='agent',
                                             audience='TGOT', summary='Open a cybersecurity school'))
        self.assertFalse(self.memory.remember(event_id='1', category='goal', visibility='agent',
                                              audience='TGOT', summary='Open a cybersecurity school'))
        self.memory.remember(event_id='2', category='campaign', visibility='faction',
                             audience='Obsidian Network', summary='The simulated phishing campaign failed')
        self.memory.remember(event_id='3', category='public', visibility='public',
                             audience='', summary='The Woodward festival started')
        self.assertEqual(faction_for(self.world, 'TGOT'), 'ThAI Guardians')
        self.assertEqual([x['summary'] for x in self.memory.recall('TGOT', 'school')],
                         ['Open a cybersecurity school'])
        self.assertEqual(self.memory.recall('TGOT', 'phishing'), [])
        self.assertEqual(len(self.memory.recall('Morbeious', 'phishing')), 1)
        self.assertEqual(len(EpisodicMemory(self.world).recall('nonmember', 'festival')), 1)
        self.assertEqual(self.memory.stats()['episodes'], 3)

    def test_diary_cursor_and_incomplete_lines(self):
        path = self.world / 'persona' / 'TGOT' / 'memory' / 'weekly_diary.jsonl'
        path.parent.mkdir(parents=True)
        row1 = json.dumps({'time': '2045-01', 'content': 'Founded a school'}) + '\n'
        row2 = json.dumps({'time': '2045-02', 'content': 'Hired a teacher'}) + '\n'
        path.write_bytes(row1.encode() + row2.encode()[:-1])
        self.assertEqual(self.memory.ingest(path, 'TGOT')['added'], 1)
        with path.open('ab') as f:
            f.write(b'\n')
        self.assertEqual(self.memory.ingest(path, 'TGOT')['added'], 1)
        self.assertEqual(self.memory.ingest(path, 'TGOT')['added'], 0)
        self.assertEqual(len(self.memory.recall('TGOT', 'teacher')), 1)
        self.assertEqual(self.memory.recall('Morbeious', 'teacher'), [])

    def test_digital_twin_knowledge_separation(self):
        path = self.world / 'digital_twin' / 'cyber_events.jsonl'
        path.parent.mkdir(parents=True)
        rows = [
            {'time': '2045-01', 'threat': 'phishing', 'target': 'DT-ENERGY',
             'result': 'blocked', 'detected': False},
            {'time': '2045-02', 'threat': 'ransomware', 'target': 'DT-WATER',
             'result': 'success', 'detected': True, 'impact': {'service_disruption': 'simulated'}},
        ]
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        first = self.memory.ingest(path)
        self.assertEqual(first['added'], 4)  # two attacker + one detected + one public
        self.assertEqual(self.memory.ingest(path)['added'], 0)
        self.assertEqual(len(self.memory.recall('Morbeious', 'phishing')), 1)
        self.assertEqual(self.memory.recall('TGOT', 'phishing'), [])
        self.assertEqual(len(self.memory.recall('TGOT', 'ransomware')), 1)
        self.assertEqual(self.memory.recall('nonmember', 'phishing'), [])
        self.assertEqual(len(self.memory.recall('nonmember', 'service')), 1)

    def test_validation_and_size_budget(self):
        with self.assertRaises(ValueError):
            self.memory.remember(event_id='1', category='bad', visibility='faction',
                                 audience='', summary='bad')
        with self.assertRaises(ValueError):
            self.memory.remember(event_id='1', category='bad', visibility='other',
                                 audience='TGOT', summary='bad')
        self.memory.remember(event_id='x', category='goal', visibility='agent',
                             audience='TGOT', summary='A' * 5000)
        self.assertLessEqual(sum(len(x['summary']) for x in self.memory.recall('TGOT', max_chars=80)), 80)


class GovernorTests(unittest.TestCase):
    def test_deep_reasoning_gates(self):
        e = {'kind': 'city_emergency', 'importance': 1, 'uncertainty': 1, 'consequence': 1}
        self.assertEqual(decide(e, deep_model_available=True, memory_pressure='green').lane, 'deep_reasoning')
        self.assertEqual(decide(e, deep_model_available=True, memory_pressure='yellow').lane, 'strategy')
        self.assertEqual(decide(e, deep_model_available=True, memory_pressure='green', queue_depth=3).lane, 'strategy')
        self.assertEqual(decide(e, deep_model_available=False, memory_pressure='green').lane, 'strategy')
        self.assertEqual(decide({'kind': 'routine', 'importance': .1}).lane, 'citizen')
        self.assertEqual(decide({'kind': 'cyber_incident', 'importance': .5}).lane, 'cyber')


if __name__ == '__main__':
    unittest.main()
