import test from 'node:test';
import assert from 'node:assert/strict';
import { isPendingRetry } from '../src/lib/retry.js';
import { makeId } from '../src/lib/storage.js';

const pending = {
  id: 'chat-1',
  messages: [
    { id: 'u1', role: 'user', text: 'What is the application fee?' }
  ]
};

test('only newest unanswered user question can be retried', () => {
  assert.equal(isPendingRetry(pending, 'What is the application fee?', 'u1'), true);
});

test('retry refuses to append after an assistant answered', () => {
  const replied = {
    ...pending,
    messages: [...pending.messages, { id: 'a1', role: 'assistant', text: 'Unknown' }]
  };
  assert.equal(isPendingRetry(replied, 'What is the application fee?', 'u1'), false);
});

test('retry refuses an earlier question or mismatched text', () => {
  const two = { messages: [...pending.messages, {
    id: 'u2', role: 'user', text: 'New query'
  }] };
  assert.equal(isPendingRetry(two, 'What is the application fee?', 'u1'), false);
  assert.equal(isPendingRetry(two, 'Changed text', 'u2'), false);
});

test('retry requires a stable request ID', () => {
  assert.equal(isPendingRetry(pending, 'What is the application fee?', null), false);
});

test('generated session and request IDs meet FastAPI validation', () => {
  for (let n = 0; n < 40; n += 1) {
    assert.match(makeId(), /^[A-Za-z0-9_-]{1,128}$/);
  }
});

test('new IDs are distinct for separate user requests', () => {
  assert.notEqual(makeId(), makeId());
});
