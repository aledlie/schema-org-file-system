/**
 * Notification Handler
 * Tracks tool errors, warnings, and system notifications via OTEL
 */

import { instrumentHook } from '../lib/otel-monitor.js';
import { THRESHOLDS, HOOK_TRIGGER_NOTIFICATION } from '../lib/constants.js';
import { classifyNotification } from '../lib/categorizers.js';

interface HookInput {
  session_id?: string;
  tool_name?: string;
  tool_output?: string;
  message?: string;
  level?: string;
  hook_event_name?: string;
}

export async function handleNotification(input: HookInput): Promise<void> {
  await instrumentHook('notification', async (ctx) => {
    const message = input.message || input.tool_output || '';
    const level = input.level || 'info';

    ctx.addAttributes({
      'notification.level': level,
      'notification.message_length': message.length,
      'notification.tool_name': input.tool_name || '',
      'session.id': input.session_id || '',
    });

    const severity = classifyNotification(level, message);

    ctx.addAttribute('notification.severity', severity);

    if (severity === 'error') {
      ctx.span.recordException(new Error(message.slice(0, THRESHOLDS.ERROR_MESSAGE_TRUNCATE)));
      ctx.logger.error('Notification error', {
        'notification.message': message.slice(0, THRESHOLDS.ERROR_MESSAGE_TRUNCATE),
        'notification.tool': input.tool_name || '',
      });
      ctx.recordMetric('notification.errors', 1, {
        tool: input.tool_name || 'unknown',
      });
    } else if (severity === 'warning') {
      ctx.logger.warn('Notification warning', {
        'notification.message': message.slice(0, THRESHOLDS.ERROR_MESSAGE_TRUNCATE),
      });
      ctx.recordMetric('notification.warnings', 1);
    } else {
      ctx.logger.info('Notification received', {
        'notification.level': level,
      });
    }

    ctx.recordMetric('notification.total', 1, { level });
  }, { 'hook.trigger': input.hook_event_name || HOOK_TRIGGER_NOTIFICATION, 'hook.type': 'notification' });
}
