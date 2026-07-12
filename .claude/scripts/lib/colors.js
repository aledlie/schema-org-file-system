#!/usr/bin/env node
// Shared ANSI colors and log helpers for JS scripts

import path from 'path';

export const COLORS = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
};

export const CLAUDE_DIR = process.env.OTEL_CONFIG_DIR || process.env.CLAUDE_CONFIG_DIR || path.join(process.env.HOME, '.claude');
export const TELEMETRY_DIR = process.env.TELEMETRY_DIR || path.join(process.env.HOME, '.claude-history', 'telemetry');

export function log(message, color = 'reset') {
  console.log(`${COLORS[color]}${message}${COLORS.reset}`);
}

export function error(message) {
  log(`✗ ERROR: ${message}`, 'red');
}

export function warn(message) {
  log(`⚠ WARNING: ${message}`, 'yellow');
}

export function success(message) {
  log(`✓ ${message}`, 'green');
}
