import { test as base, Page, Request, Response } from '@playwright/test';
import { trace, context as otelContext, SpanStatusCode, Span } from '@opentelemetry/api';

export interface OtelTracingOptions {
  tracer: ReturnType<typeof trace.getTracer>;
  testSpan: Span | null;
}

export interface OtelTracingFixtures {
  otelTracing: OtelTracingOptions;
  tracedPage: Page;
}

const TRACER_NAME = 'playwright-e2e';

/**
 * Fixture that provides OpenTelemetry tracing for E2E tests.
 * Creates spans for:
 * - Each test execution
 * - Network requests
 * - Page navigations
 */
export const otelTracingTest = base.extend<OtelTracingFixtures>({
  otelTracing: async ({}, use, testInfo) => {
    const tracer = trace.getTracer(TRACER_NAME);

    // Create a span for the test
    const testSpan = tracer.startSpan(`test: ${testInfo.title}`, {
      attributes: {
        'test.name': testInfo.title,
        'test.file': testInfo.file,
        'test.line': testInfo.line,
        'test.column': testInfo.column,
        'test.project': testInfo.project.name,
        'test.retry': testInfo.retry,
      },
    });

    try {
      await use({
        tracer,
        testSpan,
      });

      // Mark span as successful if test passed
      if (testInfo.status === 'passed') {
        testSpan.setStatus({ code: SpanStatusCode.OK });
      } else if (testInfo.status === 'failed') {
        testSpan.setStatus({
          code: SpanStatusCode.ERROR,
          message: testInfo.error?.message || 'Test failed'
        });
        if (testInfo.error) {
          testSpan.recordException({
            name: 'TestError',
            message: testInfo.error.message,
            stack: testInfo.error.stack,
          });
        }
      }
    } finally {
      testSpan.end();
    }
  },

  tracedPage: async ({ page, otelTracing }, use) => {
    const { tracer, testSpan } = otelTracing;
    const requestSpans = new Map<string, Span>();

    // Track request start
    page.on('request', (request: Request) => {
      const span = tracer.startSpan(`HTTP ${request.method()} ${new URL(request.url()).pathname}`, {
        attributes: {
          'http.method': request.method(),
          'http.url': request.url(),
          'http.target': new URL(request.url()).pathname,
          'http.host': new URL(request.url()).host,
          'http.scheme': new URL(request.url()).protocol.replace(':', ''),
          'resource.type': request.resourceType(),
        },
      });
      requestSpans.set(request.url() + request.method(), span);
    });

    // Track request end
    page.on('response', (response: Response) => {
      const request = response.request();
      const key = request.url() + request.method();
      const span = requestSpans.get(key);

      if (span) {
        span.setAttributes({
          'http.status_code': response.status(),
          'http.status_text': response.statusText(),
        });

        if (response.status() >= 400) {
          span.setStatus({
            code: SpanStatusCode.ERROR,
            message: `HTTP ${response.status()} ${response.statusText()}`
          });
        } else {
          span.setStatus({ code: SpanStatusCode.OK });
        }

        span.end();
        requestSpans.delete(key);
      }
    });

    // Track request failures
    page.on('requestfailed', (request: Request) => {
      const key = request.url() + request.method();
      const span = requestSpans.get(key);

      if (span) {
        span.setStatus({
          code: SpanStatusCode.ERROR,
          message: request.failure()?.errorText || 'Request failed'
        });
        span.end();
        requestSpans.delete(key);
      }
    });

    await use(page);

    // End any remaining spans
    for (const span of requestSpans.values()) {
      span.end();
    }
  },
});

/**
 * Create a child span for a specific operation within a test
 */
export function createTestSpan(
  name: string,
  attributes: Record<string, string | number | boolean> = {}
): Span {
  const tracer = trace.getTracer(TRACER_NAME);
  return tracer.startSpan(name, { attributes });
}

/**
 * Run a function within a traced span
 */
export async function withSpan<T>(
  name: string,
  fn: () => Promise<T>,
  attributes: Record<string, string | number | boolean> = {}
): Promise<T> {
  const tracer = trace.getTracer(TRACER_NAME);
  const span = tracer.startSpan(name, { attributes });

  try {
    const result = await fn();
    span.setStatus({ code: SpanStatusCode.OK });
    return result;
  } catch (error) {
    span.setStatus({
      code: SpanStatusCode.ERROR,
      message: error instanceof Error ? error.message : String(error)
    });
    if (error instanceof Error) {
      span.recordException(error);
    }
    throw error;
  } finally {
    span.end();
  }
}

/**
 * Add an event to the current span
 */
export function addSpanEvent(
  span: Span,
  name: string,
  attributes: Record<string, string | number | boolean> = {}
): void {
  span.addEvent(name, attributes);
}

/**
 * Setup page tracing without fixtures
 */
export function setupPageTracing(page: Page): void {
  const tracer = trace.getTracer(TRACER_NAME);
  const requestSpans = new Map<string, Span>();

  page.on('request', (request: Request) => {
    const span = tracer.startSpan(`HTTP ${request.method()} ${new URL(request.url()).pathname}`, {
      attributes: {
        'http.method': request.method(),
        'http.url': request.url(),
        'resource.type': request.resourceType(),
      },
    });
    requestSpans.set(request.url() + request.method(), span);
  });

  page.on('response', (response: Response) => {
    const request = response.request();
    const key = request.url() + request.method();
    const span = requestSpans.get(key);

    if (span) {
      span.setAttributes({
        'http.status_code': response.status(),
      });
      span.setStatus({
        code: response.status() >= 400 ? SpanStatusCode.ERROR : SpanStatusCode.OK
      });
      span.end();
      requestSpans.delete(key);
    }
  });

  page.on('requestfailed', (request: Request) => {
    const key = request.url() + request.method();
    const span = requestSpans.get(key);
    if (span) {
      span.setStatus({ code: SpanStatusCode.ERROR });
      span.end();
      requestSpans.delete(key);
    }
  });
}
