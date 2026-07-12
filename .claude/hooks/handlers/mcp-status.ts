/**
 * MCP Server Status Handler
 *
 * Tracks MCP server initialization failures by:
 * 1. Reading configured servers from .mcp.json files
 * 2. Parsing MCP tool errors to detect unavailable servers
 * 3. Reporting failures to OpenTelemetry
 *
 * Called from PostToolUse hook when MCP tools fail.
 */

import { instrumentHook } from '../lib/otel-monitor.js';
import * as fs from 'fs';
import * as path from 'path';

interface McpServerConfig {
  command?: string;
  args?: string[];
  type?: string;
  url?: string;
  description?: string;
}

interface McpConfig {
  mcpServers?: Record<string, McpServerConfig>;
}

interface McpStatusInput {
  session_id?: string;
  tool_name?: string;
  tool_output?: string;
  is_error?: boolean;
}

// Track servers that have been reported as failed this session
const reportedFailures = new Set<string>();

/**
 * Parse MCP tool error to extract server failure info
 */
function parseMcpError(output: string): { server: string; available: string[] } | null {
  // Match: Server "X" not found. Available servers: a, b, c
  const match = output.match(/Server "([^"]+)" not found\. Available servers: (.+)/);
  if (match) {
    return {
      server: match[1],
      available: match[2].split(', ').map((s) => s.trim()),
    };
  }
  return null;
}

/**
 * Get configured MCP servers from all .mcp.json files
 */
function getConfiguredServers(): Map<string, McpServerConfig> {
  const servers = new Map<string, McpServerConfig>();
  const home = process.env.HOME || '';

  // Global .mcp.json
  const globalPath = path.join(home, '.claude', '.mcp.json');
  loadMcpConfig(globalPath, servers);

  // Project .mcp.json (if in a project directory)
  const cwd = process.cwd();
  const projectPath = path.join(cwd, '.mcp.json');
  loadMcpConfig(projectPath, servers);

  return servers;
}

function loadMcpConfig(filePath: string, servers: Map<string, McpServerConfig>): void {
  try {
    if (fs.existsSync(filePath)) {
      const content = fs.readFileSync(filePath, 'utf-8');
      const config: McpConfig = JSON.parse(content);
      if (config.mcpServers) {
        for (const [name, serverConfig] of Object.entries(config.mcpServers)) {
          servers.set(name, serverConfig);
        }
      }
    }
  } catch {
    // Ignore parse errors
  }
}

/**
 * Handle MCP tool error and track server failures
 */
export async function handleMcpStatus(input: McpStatusInput): Promise<void> {
  if (!input.is_error || !input.tool_output) {
    return;
  }

  const errorInfo = parseMcpError(input.tool_output);
  if (!errorInfo) {
    return;
  }

  // Skip if already reported this session
  if (reportedFailures.has(errorInfo.server)) {
    return;
  }
  reportedFailures.add(errorInfo.server);

  await instrumentHook('mcp-server-failure', async (ctx) => {
    ctx.addAttribute('hook.type', 'mcp-init');

    // Get configured servers to provide context
    const configuredServers = getConfiguredServers();
    const serverConfig = configuredServers.get(errorInfo.server);

    ctx.addAttributes({
      'mcp.server.name': errorInfo.server,
      'mcp.server.status': 'failed',
      'mcp.server.configured': configuredServers.has(errorInfo.server),
      'mcp.servers.available': errorInfo.available.join(','),
      'mcp.servers.available_count': errorInfo.available.length,
      'mcp.servers.configured_count': configuredServers.size,
    });

    if (serverConfig) {
      if (serverConfig.command) {
        ctx.addAttribute('mcp.server.command', serverConfig.command);
      }
      if (serverConfig.type) {
        ctx.addAttribute('mcp.server.type', serverConfig.type);
      }
      if (serverConfig.description) {
        ctx.addAttribute('mcp.server.description', serverConfig.description);
      }
    }

    // Record metric for alerting
    ctx.recordMetric('mcp.server.failures', 1, {
      'mcp.server.name': errorInfo.server,
    });

    ctx.logger.warn('MCP server not available', {
      'mcp.server': errorInfo.server,
      'mcp.available': errorInfo.available.join(', '),
    });

    if (input.session_id) {
      ctx.addAttribute('session.id', input.session_id);
    }
  });
}

/**
 * Check MCP server status at session start.
 * Compares configured servers against a known list of available servers.
 * @deprecated Not called from any handler — kept for test coverage.
 * Tests must call resetFailureTracking() between invocations to prevent
 * state bleed from reportedFailures.
 */
export async function checkMcpServersAtStart(
  sessionId: string,
  availableServers: string[]
): Promise<void> {
  const configuredServers = getConfiguredServers();
  const availableSet = new Set(availableServers);

  const failures: string[] = [];
  const successes: string[] = [];

  for (const [name] of configuredServers) {
    if (availableSet.has(name)) {
      successes.push(name);
    } else {
      failures.push(name);
    }
  }

  if (failures.length === 0 && successes.length === 0) {
    return; // No configured servers
  }

  await instrumentHook('mcp-server-status', async (ctx) => {
    ctx.addAttribute('hook.type', 'mcp-init');
    ctx.addAttribute('session.id', sessionId);

    ctx.addAttributes({
      'mcp.servers.configured_count': configuredServers.size,
      'mcp.servers.available_count': availableServers.length,
      'mcp.servers.success_count': successes.length,
      'mcp.servers.failure_count': failures.length,
    });

    if (successes.length > 0) {
      ctx.addAttribute('mcp.servers.connected', successes.join(','));
    }

    if (failures.length > 0) {
      ctx.addAttribute('mcp.servers.failed', failures.join(','));

      // Record individual failure metrics
      for (const server of failures) {
        ctx.recordMetric('mcp.server.init_failure', 1, {
          'mcp.server.name': server,
        });
        reportedFailures.add(server);
      }

      ctx.logger.error('MCP servers failed to initialize', {
        failed: failures.join(', '),
        available: availableServers.join(', '),
      });
    } else {
      ctx.logger.info('All MCP servers initialized', {
        count: successes.length,
        servers: successes.join(', '),
      });
    }

    // Overall health metric
    const healthPercent = configuredServers.size > 0
      ? (successes.length / configuredServers.size) * 100
      : 100;
    ctx.recordMetric('mcp.servers.health_percent', healthPercent);
  });
}

/**
 * Reset failure tracking (call at session end)
 */
export function resetFailureTracking(): void {
  reportedFailures.clear();
}
