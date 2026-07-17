#!/usr/bin/env node
/**
 * Test script to verify OTLP metric export to obtool-ingest.
 * Sends a single counter metric via protobuf, then shuts down.
 */
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-proto';
import { resourceFromAttributes } from '@opentelemetry/resources';

// Claude Code's telemetry env sets OTEL_SERVICE_NAME=claude-code-hooks and
// OTEL_RESOURCE_ATTRIBUTES; the SDK's env detector would override this script's
// resource and misattribute test data. Drop them so 'claude-code-test' wins.
delete process.env.OTEL_SERVICE_NAME;
delete process.env.OTEL_RESOURCE_ATTRIBUTES;

const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT || 'https://ingest.integritystudio.ai';
const apiKey = process.env.OBTOOL_API_KEY;
const headerEnv = process.env.OTEL_EXPORTER_OTLP_HEADERS;

console.log(`Sending test metric to: ${endpoint}/v1/metrics`);

const headers = {};
if (apiKey) {
  headers['Authorization'] = `Bearer ${apiKey}`;
  console.log('Auth: OBTOOL_API_KEY');
} else if (headerEnv) {
  const eqIdx = headerEnv.indexOf('=');
  if (eqIdx > 0) {
    headers[headerEnv.slice(0, eqIdx)] = headerEnv.slice(eqIdx + 1);
  }
  console.log('Auth: OTEL_EXPORTER_OTLP_HEADERS');
} else {
  console.warn('Warning: no auth configured — expect 401');
}

const exporter = new OTLPMetricExporter({
  url: `${endpoint}/v1/metrics`,
  headers,
});

const reader = new PeriodicExportingMetricReader({
  exporter,
  exportIntervalMillis: 1000,
});

const meterProvider = new MeterProvider({
  resource: resourceFromAttributes({
    'service.name': 'claude-code-test',
    'deployment.environment': 'development',
  }),
  readers: [reader],
});

const meter = meterProvider.getMeter('test-meter', '1.0.0');
const counter = meter.createCounter('test.metric.counter', {
  description: 'E2E test counter for metric export verification',
});

counter.add(1, { 'test.key': 'hello-metrics', 'test.timestamp': Date.now().toString() });

// Wait for periodic export to fire then shut down
await new Promise(resolve => setTimeout(resolve, 2000));
await meterProvider.shutdown();

console.log('Metric sent successfully!');
