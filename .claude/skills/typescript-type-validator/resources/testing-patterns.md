# Testing Zod Validation

Patterns for unit and integration testing of Zod schemas.

---

## Unit Tests for Schemas

```javascript
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { MyRequestSchema } from '../api/types/my-requests.js';

describe('MyRequestSchema', () => {
  it('should accept valid request', () => {
    const valid = { field: 'value' };
    const result = MyRequestSchema.parse(valid);
    assert.deepStrictEqual(result, valid);
  });

  it('should reject invalid type', () => {
    const invalid = { field: 123 };
    assert.throws(() => {
      MyRequestSchema.parse(invalid);
    }, {
      name: 'ZodError',
      message: /Expected string/
    });
  });

  it('should reject empty string', () => {
    const invalid = { field: '' };
    assert.throws(() => {
      MyRequestSchema.parse(invalid);
    }, {
      name: 'ZodError',
      message: /must not be empty/
    });
  });

  it('should reject missing field', () => {
    const invalid = {};
    assert.throws(() => {
      MyRequestSchema.parse(invalid);
    }, {
      name: 'ZodError',
      message: /Required/
    });
  });
});
```

---

## Integration Tests for API

```javascript
describe('POST /api/endpoint', () => {
  it('should return 400 for invalid type', async () => {
    const response = await fetch('http://localhost:8080/api/endpoint', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ field: 123 })
    });

    assert.strictEqual(response.status, 400);
    const error = await response.json();
    assert.strictEqual(error.error, 'Bad Request');
    assert.ok(error.errors);
    assert.ok(error.errors[0].message.includes('string'));
  });
});
```

---

## Test Coverage Checklist

- [ ] Valid input accepted
- [ ] Invalid types rejected
- [ ] Empty values rejected (if required)
- [ ] Missing fields rejected (if required)
- [ ] Extra fields rejected (if strict mode)
- [ ] Boundary values tested (min/max)
- [ ] Optional fields work correctly
- [ ] Nullable fields work correctly
- [ ] Custom refinements work
- [ ] Error messages are clear
