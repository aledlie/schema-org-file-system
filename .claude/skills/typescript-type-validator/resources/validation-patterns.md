# Zod Validation Patterns

Common validation patterns for Zod schemas.

---

## String Validation

```typescript
z.string()
  .min(1, 'must not be empty')
  .max(255, 'too long')
  .email('must be valid email')
  .url('must be valid URL')
  .regex(/^[a-z]+$/, 'lowercase letters only')
  .trim() // Remove whitespace
  .toLowerCase() // Normalize to lowercase
```

---

## Number Validation

```typescript
z.number()
  .int('must be integer')
  .positive('must be positive')
  .min(0, 'must be >= 0')
  .max(100, 'must be <= 100')
  .finite('must be finite')
```

---

## Array Validation

```typescript
z.array(z.string())
  .min(1, 'must have at least one item')
  .max(10, 'too many items')
  .nonempty('cannot be empty array')
```

---

## Enum Validation

```typescript
z.enum(['option1', 'option2', 'option3'])

// For status codes:
z.enum(['queued', 'running', 'completed', 'failed'])
```

---

## Object Validation

```typescript
z.object({
  field1: z.string(),
  field2: z.number()
})
.strict() // Reject extra fields
.partial() // Make all fields optional
.required() // Make all fields required
.pick({ field1: true }) // Only include field1
.omit({ field2: true }) // Exclude field2
```

---

## Union Types

```typescript
z.union([z.string(), z.number()]) // string OR number

z.discriminatedUnion('type', [
  z.object({ type: z.literal('a'), value: z.string() }),
  z.object({ type: z.literal('b'), value: z.number() })
])
```

---

## Custom Validation

```typescript
z.string()
  .refine(
    (path) => fs.existsSync(path),
    { message: 'path must exist' }
  )
  .refine(
    (path) => !path.includes('..'),
    { message: 'path traversal not allowed' }
  )
```

---

## Optional vs Nullable

```typescript
// Optional: field may not exist
z.string().optional() // { } is valid

// Nullable: field exists but may be null
z.string().nullable() // { field: null } is valid

// Both: field may not exist OR may be null
z.string().optional().nullable()
```

---

## Error Response Pattern

```typescript
export function createValidationError(
  field: string,
  message: string,
  code: string = 'VALIDATION_ERROR'
): ValidationErrorResponse {
  return {
    error: 'Bad Request',
    message: `Validation failed: ${message}`,
    timestamp: new Date().toISOString(),
    status: 400,
    errors: [{
      field,
      message,
      code
    }]
  };
}
```

### Example Error Response

```json
{
  "error": "Bad Request",
  "message": "Request validation failed",
  "timestamp": "2025-11-18T12:00:00.000Z",
  "errors": [
    {
      "field": "repositoryPath",
      "message": "Expected string, received number",
      "code": "invalid_type"
    },
    {
      "field": "options.maxDepth",
      "message": "Number must be greater than 0",
      "code": "too_small"
    }
  ]
}
```
