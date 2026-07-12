# Bug Detective Commands Reference

Common commands for each debugging phase.

---

## Discovery Phase

```bash
# Find all bugfix plans
ls ~/dev/active/bugfix-*/plan.md

# Search for error patterns in logs
grep -r "Error:" --include="*.log" .

# Run test suite and capture output
npm test 2>&1 | tee test-results.log

# Check recent fix commits
git log --all --grep="fix:" --since="1 week ago"

# Find all TODO/FIXME comments
grep -r "TODO\|FIXME" --include="*.ts" --include="*.js" .

# List recent Sentry errors (if configured)
sentry-cli issues list --project=myproject
```

---

## Analysis Phase

```bash
# Count error occurrences
grep -c "specific error pattern" error.log

# Find when error-prone code was introduced
git log -p --all -S "error-prone code"

# Compare environments
diff production.env staging.env

# Find all files with a specific pattern
grep -rl "pattern" --include="*.ts" .

# Check git blame for specific lines
git blame -L 50,60 path/to/file.ts

# View file at specific commit
git show abc123:path/to/file.ts
```

---

## Testing Phase

```bash
# Run specific tests by pattern
npm test -- --grep "pattern"

# Run tests in watch mode
npm test -- --watch

# Generate coverage report
npm test -- --coverage

# Run single test file
npm test -- path/to/test.spec.ts

# Run tests with verbose output
npm test -- --verbose

# Run tests matching multiple patterns
npm test -- --grep "pattern1|pattern2"
```

---

## Git Operations

```bash
# Create fix branch
git checkout -b fix/issue-name

# View recent changes to a file
git log -p --follow -n 5 -- path/to/file.ts

# Find commits that changed specific function
git log -p -S "functionName" -- "*.ts"

# Compare branches
git diff main..feature-branch

# Interactive rebase for cleanup
git rebase -i HEAD~3

# Commit with descriptive message
git commit -m "fix(component): description

- Detail 1
- Detail 2

Fixes #123"
```

---

## Environment Debugging

```bash
# Check environment variables
printenv | grep -i "key"

# Check Node.js version
node --version

# Check npm packages
npm list --depth=0

# Check for outdated packages
npm outdated

# Verify PATH
echo $PATH | tr ':' '\n'

# Check process environment in Node
node -e "console.log(process.env)"
```

---

## Log Analysis

```bash
# Tail logs in real-time
tail -f application.log

# Search logs with context
grep -B 5 -A 5 "error" application.log

# Count unique errors
grep "Error:" app.log | sort | uniq -c | sort -rn

# Filter logs by timestamp
awk '/2025-11-22 14:/ {print}' app.log

# Extract specific fields from JSON logs
cat app.log | jq '.level, .message'
```
