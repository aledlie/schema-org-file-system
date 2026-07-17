#!/usr/bin/env node
/**
 * Test script to verify OTLP export to obtool-ingest
 * Uses protobuf (application/x-protobuf) to match production hook config.
 */
import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-proto';
import { trace } from '@opentelemetry/api';
import { resourceFromAttributes } from '@opentelemetry/resources';

// Claude Code's telemetry env sets OTEL_SERVICE_NAME=claude-code-hooks and
// OTEL_RESOURCE_ATTRIBUTES; the SDK's env detector would override this script's
// resource and misattribute test data. Drop them so 'claude-code-test' wins.
delete process.env.OTEL_SERVICE_NAME;
delete process.env.OTEL_RESOURCE_ATTRIBUTES;

const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT || 'https://ingest.integritystudio.ai';
const apiKey = process.env.OBTOOL_API_KEY;
const headerEnv = process.env.OTEL_EXPORTER_OTLP_HEADERS;

console.log(`Sending test trace to: ${endpoint}/v1/traces`);

// Build auth headers: prefer OBTOOL_API_KEY, fall back to OTEL_EXPORTER_OTLP_HEADERS
const headers = {};
if (apiKey) {
  headers['Authorization'] = `Bearer ${apiKey}`;
  console.log('Auth: OBTOOL_API_KEY');
} else if (headerEnv) {
  // OTEL_EXPORTER_OTLP_HEADERS format: "Key=Value"
  const eqIdx = headerEnv.indexOf('=');
  if (eqIdx > 0) {
    headers[headerEnv.slice(0, eqIdx)] = headerEnv.slice(eqIdx + 1);
  }
  console.log('Auth: OTEL_EXPORTER_OTLP_HEADERS');
} else {
  console.warn('Warning: no auth configured — expect 401');
}

const exporter = new OTLPTraceExporter({
  url: `${endpoint}/v1/traces`,
  headers,
});

const sdk = new NodeSDK({
  traceExporter: exporter,
  resource: resourceFromAttributes({
    'service.name': 'claude-code-test',
    'deployment.environment': 'development',
  }),
});

sdk.start();

const tracer = trace.getTracer('test-tracer', '1.0.0');
const span = tracer.startSpan('test-span');
span.setAttribute('test.key', 'hello-obtool');
span.setAttribute('test.timestamp', Date.now());
span.addEvent('test-event', { 'event.data': 'test data' });
span.end();

// Give time for export
await new Promise(resolve => setTimeout(resolve, 2000));
try {
  await sdk.shutdown();
} catch (err) {
  console.error(`Trace export failed: ${err.message}`);
  process.exit(1);
}

console.log('Trace sent successfully!');
