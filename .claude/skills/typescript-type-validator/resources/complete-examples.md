# Complete Examples

Real-world implementation examples.

---

## API Validation Example

**Context:** Phase 4.1.2 of jobs project - API validation errors

**Problem:**
- Passing `{ repositoryPath: 123 }` caused HTTP 500 error
- Manual validation missed type checking
- Inconsistent error messages

### Solution

**1. Create Zod schema:**
```typescript
// api/types/scan-requests.ts
export const StartScanRequestSchema = z.object({
  repositoryPath: z.string()
    .min(1, 'repositoryPath must not be empty'),
  options: z.object({
    forceRefresh: z.boolean().optional(),
    cacheEnabled: z.boolean().optional()
  }).optional()
}).strict();

export type StartScanRequest = z.infer<typeof StartScanRequestSchema>;
```

**2. Create validation middleware:**
```typescript
// api/middleware/validation.ts
export function validateRequest(schema: ZodSchema) {
  return (req: Request, res: Response, next: NextFunction) => {
    try {
      req.body = schema.parse(req.body);
      next();
    } catch (error) {
      if (error instanceof ZodError) {
        return res.status(400).json({
          error: 'Bad Request',
          message: 'Request validation failed',
          errors: error.errors.map(err => ({
            field: err.path.join('.'),
            message: err.message,
            code: err.code
          }))
        });
      }
      next(error);
    }
  };
}
```

**3. Update route:**
```typescript
router.post(
  '/start',
  validateRequest(StartScanRequestSchema),
  async (req: Request<{}, {}, StartScanRequest>, res: Response) => {
    const { repositoryPath, options } = req.body; // Type-safe!
  }
);
```

**Result:**
- 13/13 validation tests passing
- Clear error messages
- Type safety guaranteed
- No manual validation needed

---

## Form Validation Example

```typescript
// Form submission schema
export const ContactFormSchema = z.object({
  name: z.string()
    .min(1, 'Name is required')
    .max(100, 'Name too long'),
  email: z.string()
    .email('Invalid email address'),
  message: z.string()
    .min(10, 'Message must be at least 10 characters')
    .max(1000, 'Message too long'),
  subscribe: z.boolean().optional().default(false)
}).strict();

export type ContactForm = z.infer<typeof ContactFormSchema>;
```

---

## Config Validation Example

```typescript
// Environment/config validation
export const ConfigSchema = z.object({
  port: z.number().int().positive().default(3000),
  database: z.object({
    host: z.string().min(1),
    port: z.number().int().positive(),
    name: z.string().min(1),
    ssl: z.boolean().default(false)
  }),
  redis: z.object({
    url: z.string().url()
  }).optional(),
  logLevel: z.enum(['debug', 'info', 'warn', 'error']).default('info')
});

export type Config = z.infer<typeof ConfigSchema>;

// Usage
const config = ConfigSchema.parse(process.env);
```

---

## Query Params Validation

```typescript
// GET request query validation
export const PaginationSchema = z.object({
  page: z.coerce.number().int().positive().default(1),
  limit: z.coerce.number().int().min(1).max(100).default(20),
  sort: z.enum(['asc', 'desc']).default('desc'),
  search: z.string().optional()
});

export type Pagination = z.infer<typeof PaginationSchema>;

// Middleware for query params
export function validateQuery(schema: ZodSchema) {
  return (req: Request, res: Response, next: NextFunction) => {
    try {
      req.query = schema.parse(req.query);
      next();
    } catch (error) {
      if (error instanceof ZodError) {
        return res.status(400).json({
          error: 'Bad Request',
          message: 'Query validation failed',
          errors: error.errors
        });
      }
      next(error);
    }
  };
}
```
