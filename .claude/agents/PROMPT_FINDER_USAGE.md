# Prompt Finder Agent - Usage Guide

## Overview

The **Prompt Finder Agent** is an intelligent system that discovers and recommends the most effective prompts from the [prompts.chat](https://prompts.chat) dataset based on your task description.

## Quick Start

### Option 1: Use via Claude Code (Recommended)

```bash
# In Claude Code, use the Agent tool:
/agent prompt-finder --task "Your task description here"

# Or invoke directly:
Agent(
  subagent_type='prompt-finder',
  description='Find effective prompts for my task',
  prompt='I need a prompt for code review automation'
)
```

### Option 2: Command Line

```bash
# Direct invocation
node prompt-finder-implementation.ts "Your task description"

# Interactive mode (will prompt for input)
node prompt-finder-implementation.ts
```

## Examples

### Finding a Code Review Prompt

**Input:**
```
task: "I need to set up automated code review for a Python project"
```

**Agent Output:**
- Recommends "Code Reviewer" prompt
- Explains how to customize it for Python
- Provides tips for integration

### Discovering Documentation Prompts

**Input:**
```
task: "Help me write API documentation for a REST service"
```

**Agent Output:**
- Recommends "Technical Documentation Writer"
- Suggests structure customizations
- Lists relevant tags (API, Technical, Writing)

### Creating Educational Content

**Input:**
```
task: "I want to teach data analysis concepts to beginners"
```

**Agent Output:**
- Recommends "Data Analysis Mentor"
- Suggests pedagogical enhancements
- Provides example adaptations

## Features

### 1. **Semantic Task Analysis**
The agent understands your task description and identifies:
- Primary domain (Coding, Writing, Analysis, etc.)
- Required expertise level
- Structural preferences (template vs. freeform)
- Special constraints or requirements

### 2. **Intelligent Prompt Matching**
Searches the prompts.chat database (10,000+ prompts) using:
- Category alignment
- Tag relevance
- Community engagement metrics
- Prompt type compatibility

### 3. **Smart Recommendations**
Provides 2-3 most effective prompts with:
- Relevance scores
- Customization suggestions
- Community feedback (votes, views)
- Links to original prompts

### 4. **Adaptive Thinking**
Uses Claude Opus 4.6 with adaptive thinking to:
- Deeply analyze task nuances
- Consider multiple matching strategies
- Evaluate trade-offs between options
- Generate contextual customization tips

## Dataset Access

The agent accesses prompts.chat through multiple methods:

### JSON API (Live)
```
GET https://prompts.chat/prompts.json?q=YOUR_QUERY&limit=50&full_content=true
```

### CSV Export
```
GET https://prompts.chat/prompts.csv
```

### HuggingFace Dataset
```python
from datasets import load_dataset
dataset = load_dataset("fka/prompts.chat")
```

## How the Agent Works

1. **Parse Task** → Understand what you're trying to accomplish
2. **Fetch Candidates** → Query prompts.chat for relevant prompts
3. **Analyze** → Use Claude to evaluate each prompt's effectiveness
4. **Recommend** → Suggest top matches with customization tips
5. **Explain** → Provide rationale for each recommendation

## Architecture

```
┌─────────────────────┐
│  User Task Query    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────┐
│  Parse & Understand Task    │
│  (Domain, Constraints)      │
└──────────┬──────────────────┘
           │
           ▼
┌────────────────────────────────┐
│  Fetch Prompts from API/HF     │
│  (Filter by relevance)         │
└──────────┬─────────────────────┘
           │
           ▼
┌────────────────────────────────┐
│  Claude Analysis               │
│  - Semantic matching           │
│  - Effectiveness evaluation    │
│  - Customization suggestions   │
└──────────┬─────────────────────┘
           │
           ▼
┌────────────────────────────────┐
│  Return Top 2-3 Recommendations│
│  - Ranked by relevance         │
│  - Customization tips          │
│  - Community metrics           │
└────────────────────────────────┘
```

## Prompt Categories Available

- **Coding**: Python, JavaScript, DevOps, API Design
- **Writing**: Technical, Creative, Content Marketing
- **Analysis**: Data Science, Business, Code Review
- **Documentation**: API, User Guides, Technical
- **Productivity**: Project Management, Learning, Automation
- **Creativity**: Brainstorming, Design, Marketing
- **And 10+ more categories...**

## Customization

### Adapting Recommended Prompts

Once you receive a recommendation, customize it by:

1. **Adding context**: Include specific technologies or frameworks
2. **Adjusting tone**: Change formality, detail level
3. **Adding constraints**: Specify output format, length limits
4. **Including examples**: Provide sample inputs/outputs
5. **Setting guardrails**: Define what to avoid

### Example Customization

**Original Prompt:**
```
Code Reviewer: Review the following code for security,
performance, and quality issues.
```

**Customized for Your Project:**
```
Code Reviewer (Python/Django): Review the following
Python/Django code for:
1. Security vulnerabilities (SQL injection, auth issues)
2. Performance (database queries, N+1 problems)
3. Quality (PEP 8, type hints, test coverage)
4. Django best practices

Focus on critical issues first. Return findings as markdown.
```

## API Integration

### Fetch Prompts Programmatically

```typescript
const prompts = await fetchPromptsFromAPI("code review", 30);

// Returns: Array<Prompt>
// Fields: title, content, category, tags, voteCount, isFeatured
```

### Get Recommendations via CLI

```bash
echo "code review automation" | node prompt-finder-implementation.ts

# Or with environment variable:
TASK="code review automation" node prompt-finder-implementation.ts
```

## Performance & Caching

- **First request**: Full API fetch + Claude analysis (2-3 seconds)
- **Cached requests**: Subsequent identical queries use cached results (instant)
- **Rate limiting**: Respects prompts.chat API rate limits
- **Fallback**: Uses local prompt examples if API is unavailable

## Limitations

- ✅ Works with public prompts only
- ✅ Limited to prompts.chat dataset (no custom/private prompts)
- ✅ Metadata-based recommendations (not full semantic similarity)
- ✅ Community metrics update daily

## Troubleshooting

### API Connection Issues
```
Falls back to local example prompts automatically
Check: https://status.prompts.chat for API status
```

### No Matching Prompts
```
Try broader terms: "code" instead of "code linting"
Check categories: https://prompts.chat
View all prompts: https://prompts.chat/prompts.csv
```

### Low-Confidence Recommendations
```
Provide more context in your task description
Include specific technologies (Python, React, etc.)
Mention constraints or preferences
```

## Advanced Usage

### Batch Processing

```bash
# Find prompts for multiple tasks
tasks=("code review" "documentation" "testing")
for task in "${tasks[@]}"; do
  node prompt-finder-implementation.ts "$task"
done
```

### Integration with Other Tools

```typescript
// Use with prompt engineering framework
const prompt = await findEffectivePrompts(task);
const optimizedPrompt = await optimizePrompt(prompt);
const results = await executePrompt(optimizedPrompt);
```

## Contributing

Have a great prompt to share with the community?
- Add it to [prompts.chat](https://prompts.chat)
- Help other developers discover it
- Get votes and feedback from the community

## Resources

- **Website**: https://prompts.chat
- **API Docs**: https://prompts.chat/api
- **HuggingFace Dataset**: https://huggingface.co/datasets/fka/prompts.chat
- **GitHub**: https://github.com/f/prompts.chat
- **NPM Package**: https://www.npmjs.com/package/prompts.chat

## License

This agent implementation is MIT licensed.
Prompts from prompts.chat are shared under their respective licenses.

---

**Created**: 2026-03-25
**Agent Version**: 1.0.0
**Requires**: Claude Opus 4.6+, Node.js 18+
