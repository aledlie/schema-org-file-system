/**
 * Changelog Version Bump → README Sync
 *
 * Fires when a NEW version directory is created under docs/changelog/.
 * Detection:
 *   - Write: first file created in docs/changelog/<version>/ (new dir)
 *   - Bash: mkdir targeting docs/changelog/<version>
 *
 * Updates the README.md [Changelog] link to point at the latest version
 * directory by semver sort.
 *
 * Called from PostToolUse hook on Write and Bash routes.
 */

import { instrumentHook } from '../lib/otel-monitor.js';
import { readdir, readFile, writeFile, access } from 'fs/promises';
import { join, isAbsolute } from 'path';

interface HookInput {
  session_id?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  cwd?: string;
}

/** Safely extract a string field from tool_input. */
function getStringField(input: HookInput, key: string): string | undefined {
  const ti = input.tool_input;
  if (ti && typeof ti === 'object' && key in ti) return String(ti[key]);
  return undefined;
}

const CHANGELOG_DIR_SEGMENT = 'docs/changelog/';
const CHANGELOG_DIR_PARTS = ['docs', 'changelog'] as const;
const CHANGELOG_PATH_PATTERN = /docs\/changelog\/([^/]+)\//;
const CHANGELOG_LINK_PATTERN = /\[Changelog\]\(docs\/changelog\/[^/]+\/CHANGELOG\.md\)/;
// Handles: mkdir -p docs/changelog/1.2, mkdir --verbose -p "path/docs/changelog/1.2", cd /repo && mkdir -p docs/changelog/1.2
const MKDIR_CHANGELOG_PATTERN = /\bmkdir\s+(?:(?:--?\w+)\s+)*["']?([^\s"']*docs\/changelog\/([^/"'\s]+))["']?/;
const VERSION_SEGMENT_PATTERN = /^[a-zA-Z0-9._-]+$/;

/** Track versions already processed in this process lifetime to avoid duplicate firings. */
const processedVersions = new Set<string>();

/** Check if a path exists (async). */
async function pathExists(p: string): Promise<boolean> {
  try { await access(p); return true; } catch { return false; }
}

/** Parse a segment to a finite number, defaulting non-numeric to 0. */
function toSegment(s: string): number {
  const n = Number(s);
  return Number.isFinite(n) ? n : 0;
}

/** Compare two dotted-number version strings (e.g. "1.2" vs "1.10"). */
function compareSemver(a: string, b: string): number {
  const pa = a.split('.').map(toSegment);
  const pb = b.split('.').map(toSegment);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

/** Find the highest version directory under docs/changelog/. */
async function findLatestVersion(changelogDir: string): Promise<string | undefined> {
  try {
    const entries = await readdir(changelogDir, { withFileTypes: true });
    const versions = entries
      .filter(d => d.isDirectory() && VERSION_SEGMENT_PATTERN.test(d.name))
      .map(d => d.name)
      .sort(compareSemver);

    return versions[versions.length - 1];
  } catch {
    return undefined;
  }
}

/** Extract version and project root from a Write tool file path. */
async function parseWritePath(input: HookInput): Promise<{ version: string; projectRoot: string } | undefined> {
  if (input.tool_name !== 'Write') return;

  const filePath = getStringField(input, 'file_path');
  if (!filePath) return;

  const match = filePath.match(CHANGELOG_PATH_PATTERN);
  if (!match || !VERSION_SEGMENT_PATTERN.test(match[1])) return;

  const idx = filePath.indexOf(CHANGELOG_DIR_SEGMENT);
  if (idx < 0) return;

  const projectRoot = filePath.substring(0, idx).replace(/\/$/, '') || '.';
  const versionDir = join(projectRoot, ...CHANGELOG_DIR_PARTS, match[1]);

  // Only fire for new directories — skip if dir already had files before this Write
  // A new dir created by Write will contain exactly one entry (the file just written)
  if (await pathExists(versionDir)) {
    const entries = await readdir(versionDir);
    if (entries.length > 1) return;
  }

  return { version: match[1], projectRoot };
}

/** Extract version and project root from a Bash mkdir command. */
function parseMkdirCommand(input: HookInput): { version: string; projectRoot: string } | undefined {
  if (input.tool_name !== 'Bash') return;

  const command = getStringField(input, 'command');
  if (!command) return;

  // Group 1 = full path, group 2 = version segment
  const match = command.match(MKDIR_CHANGELOG_PATTERN);
  if (!match || !VERSION_SEGMENT_PATTERN.test(match[2])) return;

  const fullPath = match[1];
  const idx = fullPath.indexOf(CHANGELOG_DIR_SEGMENT);
  if (idx < 0) return;

  const fromPath = fullPath.substring(0, idx).replace(/\/$/, '');
  const cwdFallback = input.cwd && isAbsolute(input.cwd) ? input.cwd : undefined;
  const projectRoot = fromPath || cwdFallback || '.';

  return { version: match[2], projectRoot };
}

/** Sync README.md changelog link to the latest version directory. */
async function syncReadmeLink(
  version: string,
  projectRoot: string,
  sessionId: string,
  trigger: string,
): Promise<void> {
  await instrumentHook('changelog-version-bump', async (ctx) => {
    ctx.addAttributes({
      'changelog.version': version,
      'changelog.trigger': trigger,
      'session.id': sessionId,
    });

    const changelogDir = join(projectRoot, ...CHANGELOG_DIR_PARTS);
    if (!await pathExists(changelogDir)) return;

    const latestVersion = await findLatestVersion(changelogDir);
    if (!latestVersion) return;

    const readmePath = join(projectRoot, 'README.md');
    if (!await pathExists(readmePath)) return;

    const readme = await readFile(readmePath, 'utf-8');
    const changelogLinkMatch = readme.match(CHANGELOG_LINK_PATTERN);

    if (!changelogLinkMatch) {
      ctx.addAttribute('changelog.readme_link_found', false);
      return;
    }

    const newLink = `[Changelog](docs/changelog/${latestVersion}/CHANGELOG.md)`;
    if (changelogLinkMatch[0] === newLink) {
      ctx.addAttribute('changelog.readme_already_current', true);
      return;
    }

    const updatedReadme = readme.replace(CHANGELOG_LINK_PATTERN, newLink);
    await writeFile(readmePath, updatedReadme, 'utf-8');

    ctx.addAttributes({
      'changelog.readme_link_found': true,
      'changelog.readme_updated': true,
      'changelog.latest_version': latestVersion,
      'changelog.previous_link': changelogLinkMatch[0],
    });

    ctx.recordMetric('changelog.readme_syncs', 1);

    console.error(`\n[changelog-version-bump] README.md changelog link updated → v${latestVersion}\n`);
  }, { 'hook.trigger': 'PostToolUse', 'hook.type': 'changelog-version-bump' });
}

export async function handleChangelogVersionBump(input: HookInput): Promise<void> {
  const parsed = await parseWritePath(input) || parseMkdirCommand(input);
  if (!parsed) return;

  const key = `${parsed.projectRoot}:${parsed.version}`;
  if (processedVersions.has(key)) return;
  processedVersions.add(key);

  const trigger = input.tool_name === 'Bash' ? 'mkdir' : 'write';
  await syncReadmeLink(parsed.version, parsed.projectRoot, input.session_id || '', trigger);
}
