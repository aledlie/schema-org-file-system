# Troubleshooting Zod Validation

Common issues and solutions.

---

## TypeScript file not found

**Error:**
```
Error [ERR_MODULE_NOT_FOUND]: Cannot find module '.../my-types.js'
```

**Solution:**
```bash
npx tsc api/types/my-types.ts --outDir api/types --module esnext --target esnext
```

---

## Zod not installed

**Error:**
```
Cannot find package 'zod'
```

**Solution:**
```bash
npm install zod
```

---

## Validation passes but shouldn't

**Problem:** Extra fields are accepted

**Solution:** Add `.strict()` to schema
```typescript
const Schema = z.object({
  field: z.string()
}).strict(); // Now rejects unknown fields
```

---

## Error messages not clear

**Problem:** Generic Zod errors

**Solution:** Add custom error messages
```typescript
z.string()
  .min(1, 'field must not be empty') // Clear
  .min(1) // Generic "String must contain at least 1 character(s)"
```

---

## Cannot validate nested fields

**Solution:** Use nested objects
```typescript
z.object({
  user: z.object({
    name: z.string(),
    email: z.string().email()
  })
})
```

---

## Optional vs nullable confusion

```typescript
// Optional: field may not exist
z.string().optional() // { } is valid

// Nullable: field exists but may be null
z.string().nullable() // { field: null } is valid

// Both: field may not exist OR may be null
z.string().optional().nullable()
```

---

## API returns 500 instead of 400

**Problem:** Validation errors not caught properly

**Solution:** Ensure middleware catches ZodError:
```typescript
if (error instanceof ZodError) {
  return res.status(400).json({
    error: 'Bad Request',
    message: 'Request validation failed',
    errors: error.errors.map(err => ({
      field: err.path.join('.'),
      message: err.message
    }))
  });
}
```

---

## Type inference not working

**Problem:** TypeScript doesn't infer type from schema

**Solution:** Use `z.infer`:
```typescript
const Schema = z.object({ field: z.string() });
type MyType = z.infer<typeof Schema>; // { field: string }
```
