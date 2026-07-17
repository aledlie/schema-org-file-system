#!/usr/bin/env node
/**
 * Test script to verify OTLP log export to obtool-ingest.
 * Sends a single log record via protobuf, then shuts down.
 */
import { LoggerProvider, SimpleLogRecordProcessor } from '@opentelemetry/sdk-logs';
import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-proto';
import { SeverityNumber } from '@opentelemetry/api-logs';
import { resourceFromAttributes } from '@opentelemetry/resources';

// Claude Code's telemetry env sets OTEL_SERVICE_NAME=claude-code-hooks and
// OTEL_RESOURCE_ATTRIBUTES; the SDK's env detector would override this script's
// resource and misattribute test data. Drop them so 'claude-code-test' wins.
delete process.env.OTEL_SERVICE_NAME;
delete process.env.OTEL_RESOURCE_ATTRIBUTES;

const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT || 'https://ingest.integritystudio.ai';
const apiKey = process.env.OBTOOL_API_KEY;
const headerEnv = process.env.OTEL_EXPORTER_OTLP_HEADERS;

console.log(`Sending test log to: ${endpoint}/v1/logs`);

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

const exporter = new OTLPLogExporter({
  url: `${endpoint}/v1/logs`,
  headers,
});

const loggerProvider = new LoggerProvider({
  resource: resourceFromAttributes({
    'service.name': 'claude-code-test',
    'deployment.environment': 'development',
  }),
  processors: [new SimpleLogRecordProcessor({ exporter })],
});

const logger = loggerProvider.getLogger('test-logger', '1.0.0');
logger.emit({
  severityNumber: SeverityNumber.INFO,
  severityText: 'INFO',
  body: 'E2E test log record for log export verification',
  attributes: { 'test.key': 'hello-logs', 'test.timestamp': Date.now().toString() },
});

// Give time for export
await new Promise(resolve => setTimeout(resolve, 2000));
await loggerProvider.shutdown();

console.log('Log sent successfully!');
