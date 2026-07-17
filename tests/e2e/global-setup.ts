import { FullConfig } from '@playwright/test';
import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from '@opentelemetry/semantic-conventions';
import { v4 as uuidv4 } from 'uuid';
import fs from 'fs';
import path from 'path';

const TELEMETRY_DIR = 'test-results/telemetry';
const METADATA_FILE = 'test-run-metadata.json';

interface TestRunMetadata {
  runId: string;
  correlationId: string;
  startTime: string;
  playwright: {
    version: string;
    projects: string[];
  };
  otel: {
    enabled: boolean;
    endpoint: string | null;
  };
  environment: {
    nodeVersion: string;
    platform: string;
    ci: boolean;
  };
}

let sdk: NodeSDK | null = null;

async function globalSetup(config: FullConfig): Promise<void> {
  const runId = uuidv4();
  const correlationId = uuidv4();

  // Set correlation ID for all tests
  process.env.TEST_RUN_ID = runId;
  process.env.TEST_CORRELATION_ID = correlationId;

  // Ensure telemetry directory exists
  const telemetryDir = path.join(process.cwd(), TELEMETRY_DIR);
  if (!fs.existsSync(telemetryDir)) {
    fs.mkdirSync(telemetryDir, { recursive: true });
  }

  // Initialize OpenTelemetry if endpoint is configured
  const otelEndpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT;
  const otelEnabled = !!otelEndpoint;

  if (otelEnabled) {
    try {
      const exporter = new OTLPTraceExporter({
        url: `${otelEndpoint}/v1/traces`,
      });

      sdk = new NodeSDK({
        resource: resourceFromAttributes({
          [ATTR_SERVICE_NAME]: 'playwright-e2e',
          [ATTR_SERVICE_VERSION]: '1.0.0',
          'test.run_id': runId,
          'test.correlation_id': correlationId,
        }),
        traceExporter: exporter,
      });

      await sdk.start();

      if (process.env.OTEL_DEBUG) {
        console.log('[OTEL] SDK initialized successfully');
        console.log(`[OTEL] Exporting to: ${otelEndpoint}`);
      }
    } catch (error) {
      console.error('[OTEL] Failed to initialize SDK:', error);
    }
  }

  // Create test run metadata
  const metadata: TestRunMetadata = {
    runId,
    correlationId,
    startTime: new Date().toISOString(),
    playwright: {
      version: require('@playwright/test/package.json').version,
      projects: config.projects.map(p => p.name),
    },
    otel: {
      enabled: otelEnabled,
      endpoint: otelEndpoint || null,
    },
    environment: {
      nodeVersion: process.version,
      platform: process.platform,
      ci: !!process.env.CI,
    },
  };

  // Write metadata file
  const metadataPath = path.join(telemetryDir, METADATA_FILE);
  fs.writeFileSync(metadataPath, JSON.stringify(metadata, null, 2));

  console.log(`\n[E2E Setup] Test run started`);
  console.log(`  Run ID: ${runId}`);
  console.log(`  Correlation ID: ${correlationId}`);
  console.log(`  OTEL: ${otelEnabled ? 'enabled' : 'disabled'}`);
  console.log(`  Metadata: ${metadataPath}\n`);
}

export default globalSetup;

// Export SDK for teardown
export { sdk };
