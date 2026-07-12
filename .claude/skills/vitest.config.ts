import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    // Scope scanning to this directory so '**/*.test.ts' cannot escape into
    // vendored plugins, submodules, or worktrees when run from the repo root.
    root: import.meta.dirname,
    include: ['**/*.test.ts'],
    testTimeout: 10000,
  },
});
