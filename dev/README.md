# Dev Docs Directory

This directory contains structured documentation for development tasks.

## Structure

```
dev/
├── active/     # Work-in-progress tasks
├── archive/    # Completed tasks
└── templates/  # Templates for new tasks
```

## Usage

1. For a new task, create a directory: `dev/active/task-name/`
2. Copy templates from `templates/`
3. Fill in the plan, context, and tasks files
4. Update frequently during development
5. Move to `archive/` when complete

## Templates

- `feature-plan.template.md` - New features
- `bugfix-plan.template.md` - Bug fixes
- `refactor-plan.template.md` - Refactoring
- `context.template.md` - Session context
- `tasks.template.md` - Task checklists

## Commands

- `/dev-docs [description]` - Create new task documentation
- `/dev-docs-update` - Update before context reset

See templates for detailed structures.
