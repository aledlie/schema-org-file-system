# Prompts.Chat Skill Usage Guide

## Quick Start

```bash
# Search for a specific prompt
/prompts-chat search "code reviewer"

# Load a role-based prompt as system context
/prompts-chat load "DevOps Engineer"

# Get prompts by category
/prompts-chat category development

# Improve an existing prompt
/prompts-chat improve "my existing prompt text here"

# Generate examples for a prompt
/prompts-chat examples "my prompt"

# List available roles
/prompts-chat roles
```

## Command Reference

### Search Commands

**Search by keyword**
```
/prompts-chat search "keyword"
```
Find all prompts matching the keyword.

**Search by role**
```
/prompts-chat role "Linux Terminal"
```
Find prompts for specific roles (Code Reviewer, Security Auditor, etc).

**Search by category**
```
/prompts-chat category "development"
```
Browse prompts in categories: development, content, business, creative, education, research.

**Search by language**
```
/prompts-chat language "es" search "contenido"
```
Find prompts in Spanish (ar, de, es, fr, it, ja, ko, zh, etc).

### Application Commands

**Load as system context**
```
/prompts-chat load "Code Reviewer"
```
Use a prompt as the system instruction for your session.

**Apply to current task**
```
/prompts-chat apply "JavaScript Expert" to my-function.js
```
Apply a prompt to analyze or work with a specific file.

**Chain prompts**
```
/prompts-chat chain ["Code Reviewer", "Security Auditor"]
```
Combine multiple prompts for multi-step analysis.

### Enhancement Commands

**Improve a prompt**
```
/prompts-chat improve "your prompt text"
```
Use AI to refine clarity, add structure, and optimize for results.

**Generate examples**
```
/prompts-chat examples "your prompt"
```
Create sample inputs/outputs to demonstrate the prompt.

**Add constraints**
```
/prompts-chat constrain "your prompt" with "max 50 words output"
```
Add specific output constraints or requirements.

### Discovery Commands

**List available roles**
```
/prompts-chat roles
```
See all 100+ role-based prompts available.

**List categories**
```
/prompts-chat categories
```
Browse prompt categories.

**Top rated prompts**
```
/prompts-chat top-rated
```
See most useful prompts (by community votes).

**Recent updates**
```
/prompts-chat recent
```
Find newly added or improved prompts.

## Common Workflows

### Code Review Workflow
```
/prompts-chat load "Code Reviewer"
# Now ask Claude to review code with expert guidance

/prompts-chat load "Security Auditor"
# Then ask Claude to check security issues
```

### Content Creation Workflow
```
/prompts-chat role "Content Writer"
/prompts-chat improve "my blog post outline"
/prompts-chat examples "refine this prompt"
```

### Development Task Workflow
```
/prompts-chat search "javascript expert"
/prompts-chat load "JavaScript Expert"
# Work on JS task with expert guidance

/prompts-chat load "DevOps Engineer"
# Then shift to deployment concerns
```

### Multi-Language Project
```
/prompts-chat language "es" search "desarrollador"
/prompts-chat language "fr" role "Code Reviewer"
```

## Integration Examples

### Using with File Analysis
```
/prompts-chat apply "Security Auditor" to src/auth.ts
```
Analyzes your auth module with security expertise.

### Using with Documentation
```
/prompts-chat load "Technical Writer"
# Now write API documentation with expert guidance
```

### Using with Testing
```
/prompts-chat load "QA Engineer"
/prompts-chat improve "test strategy for X feature"
```

## Tips & Best Practices

1. **Load roles early**: Set your system context with a role-based prompt at the start of a task
2. **Combine roles**: Chain 2-3 related roles for complex tasks (Code Reviewer → Security Auditor → Performance Engineer)
3. **Improve once**: Ask to improve a prompt once rather than tweaking it repeatedly
4. **Use examples**: Generate examples to verify the prompt works as expected
5. **Language matching**: Use language parameter when working in non-English contexts

## Available Roles (Sample)

| Role | Best For |
|------|----------|
| Code Reviewer | Reviewing code, finding issues |
| Security Auditor | Security analysis, vulnerability assessment |
| DevOps Engineer | Infrastructure, deployment, scaling |
| Linux Terminal | Command-line tasks, shell scripting |
| Data Analyst | Data analysis, visualization |
| Technical Writer | Documentation, API docs |
| Content Writer | Blog posts, articles, copy |
| English Translator | Language translation, localization |
| Software Architect | System design, architecture decisions |
| Performance Engineer | Optimization, profiling, metrics |

See `/prompts-chat roles` for the complete list.

## Troubleshooting

**Prompt not found**
- Try broader search: `search "review"` instead of `search "peer code review"`
- Check category: `/prompts-chat categories` then search within that category
- Browse all: `/prompts-chat role` to see similar available roles

**Prompt doesn't fit my context**
- Use `/prompts-chat improve` to refine it
- Use `/prompts-chat examples` to see how it works
- Try `/prompts-chat constrain` to add specific requirements

**Need multiple prompts combined**
- Use `/prompts-chat chain` to combine them
- Apply them sequentially for different angles on the same task

---

**Resource**: Learn more at [prompts.chat](https://prompts.chat) or [GitHub](https://github.com/f/prompts.chat)
