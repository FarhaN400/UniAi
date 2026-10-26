import test from 'node:test';
import assert from 'node:assert/strict';
import { getLatestAssistantMessage, getSourcesForMessage } from '../src/lib/sources.js';

const pdf = [{ title: 'Earlier PDF', url: 'https://makautwb.ac.in/earlier.pdf' }];
const messages = [
  { id: 'u1', role: 'user', text: 'What documents?' },
  { id: 'a1', role: 'assistant', text: 'Documents listed', sources: pdf },
  { id: 'u2', role: 'user', text: 'What is the fee?' },
  { id: 'a2', role: 'assistant', text: 'No verified fee evidence', sources: [] },
];

test('latest assistant message is selected, even without citations', () => {
  assert.equal(getLatestAssistantMessage(messages)?.id, 'a2');
  assert.deepEqual(getSourcesForMessage(messages), []);
});

test('older sources never appear as the latest answer sources', () => {
  assert.notDeepEqual(getSourcesForMessage(messages), pdf);
});

test('explicitly choosing an older assistant message shows only its sources', () => {
  assert.deepEqual(getSourcesForMessage(messages, 'a1'), pdf);
});

test('selected assistant without sources shows empty list', () => {
  assert.deepEqual(getSourcesForMessage(messages, 'a2'), []);
});

test('chat lacking assistant responses has no sources', () => {
  assert.deepEqual(getSourcesForMessage([{ id: 'u3', role: 'user' }]), []);
});

test('switching chats does not carry source references', () => {
  assert.deepEqual(getSourcesForMessage([], 'a1'), []);
});

test('missing sources field does not inherit citations', () => {
  assert.deepEqual(getSourcesForMessage([...messages, {
    id: 'a3', role: 'assistant', text: 'Unavailable'
  }]), []);
});
