# Using the Research Brief with Web-Research Agent

## Quick Start

### Command to Run

```
Agent(
  subagent_type='web-research-analyst',
  description='Find curated neural network intro resources for new OTEL-focused hire',
  prompt='[Copy the full command from neural-networks-research-brief.md]'
)
```

### Or Use This Shorter Version

```
Agent(
  subagent_type='web-research-analyst',
  description='Curate NN intro for OTEL observability hire with teaching background',
  prompt='''
Find highly-rated, accessible introductory content on Neural Networks for:
- Target: Mildly technical new hire with teaching background
- Context: AI-native startup focusing on OTEL measurement and LLM explainability
- Goal: Understand how NNs work, their uses, limitations, and how to observe/debug them

Prioritize resources that:
1. Explain concepts using analogies and visuals (not heavy math)
2. Include Python code examples
3. Address why NNs fail and when NOT to use them
4. Connect to monitoring, observability, and explainability
5. Explain transformers and LLMs specifically
6. Are recent (2023+) and from reputable sources

Return 8-12 resources organized by learning week (Day 1, Week 1-3, Month 2).
For each, provide: title, link, source, time, key takeaway, OTEL relevance.

Also include a reference section with key acronyms and industry terms
relevant to observability and explainability.
  '''
)
```

## Expected Output

The web-research agent will return a **curated reading list** organized like:

```
# Neural Networks 101: Curated Reading List
## For: New Hire with Teaching Background @ OTEL-Focused AI Startup

### Quick Start (Day 1 Reading)
1. [Resource Title]
   - Link: ...
   - Time: 15 min read
   - Key Takeaway: ...
   - OTEL Relevance: ...

### Core Concepts (Week 1)
2. [Resource Title]
   ...

### OTEL & Observability (Week 2)
...

### Reference Section
**Key Acronyms**: LLM, OTEL, RNN, CNN, ...
**Core Terms**: Backpropagation, Embeddings, Loss, ...
```

## Customization Tips

### Adjust for Different Hiring Contexts

**If target is Software Engineer (not teaching background):**
```
prompt='...for a mildly technical software engineer new hire
without ML experience but strong programming background...'
```

**If target is Product Manager:**
```
prompt='...for a non-technical product manager who needs to
understand ML basics, capabilities, and limitations...'
```

**If target is Sales/Marketing:**
```
prompt='...for a sales professional who needs to understand
neural network capabilities to discuss with customers...'
```

### Adjust for Different Focus Areas

**For Infrastructure Team (Compute/Cost Focus):**
```
Additional focus: quantization, inference optimization,
hardware considerations, cost of training vs inference
```

**For Safety Team (Alignment Focus):**
```
Additional focus: hallucination prevention, adversarial examples,
safety considerations, alignment with human values
```

**For Data Team (Quality Focus):**
```
Additional focus: training data quality, labeling, validation
datasets, benchmarking, evaluation metrics
```

## Integrating Results into Onboarding

Once you get the curated list, you can:

### 1. Create Weekly Reading Schedule
```
Week 1 (Days 1-5): Quick Start resources
Week 2 (Days 6-12): Core Concepts
Week 3 (Days 13-19): OTEL & Observability
Week 4 (Days 20-26): LLM & Explainability
```

### 2. Add Hands-On Exercises
For each resource, create a companion exercise:
- **Day 1**: Read intro, answer "What is a neural network?"
- **Week 1**: Code a simple network, train it on MNIST
- **Week 2**: Add monitoring to training loop, capture metrics
- **Week 3**: Visualize attention weights, explain predictions

### 3. Create Discussion Topics
- "What did you learn about when NOT to use neural networks?"
- "How would you monitor this model in production?"
- "What metrics matter most for observability?"

### 4. Connect to Company Work
- "How does this relate to our LLM explainability work?"
- "Where might we add observability here?"
- "What failure modes should we watch for?"

## Using Results for Other Hires

Once you have the curated list, it becomes a template:

### For Next Teaching-Background Hire
- Reuse the same list
- Add new resources as they emerge
- Track what was most helpful

### For Different Backgrounds
- Use the list as a baseline
- Add specialized resources for their background
- Remove resources that didn't work well

## Verification Checklist

After getting the curated list, verify it includes:

✓ **Clarity**: Each resource clearly explained (not just links)
✓ **Variety**: Mix of blogs, papers, tutorials, videos
✓ **Recency**: Mostly 2023+ content, some foundational pieces
✓ **Pedagogy**: Resources designed for teaching/learning
✓ **Observability**: Clear connection to OTEL/monitoring themes
✓ **Honesty**: Discusses limitations and failure modes
✓ **Practical**: Includes code examples and exercises
✓ **Completeness**: Covers uses, deficiencies, and considerations

## Pro Tips

### For Teaching-Background People
- Pair technical resources with pedagogy resources
- Ask: "How would you teach this to a beginner?"
- Include resources on how to explain ML concepts

### For Observability Focus
- Prioritize resources that mention monitoring, metrics, tracing
- Look for production/ops perspective, not just theory
- Find resources on model drift, reliability, failure modes

### For LLM Explainability
- Focus on transformer-specific content
- Look for attention visualization resources
- Find content on hallucination and uncertainty

## Next Steps

1. Run the web-research agent with this brief
2. Review and evaluate the curated list
3. Create a 4-week onboarding reading schedule
4. Add hands-on coding exercises aligned with each week
5. Create discussion questions connecting to company work
6. Share with other new hires and teammates
7. Collect feedback on what worked best

---

**Save the results**: Once you have the curated list, save it as:
`docs/onboarding/neural-networks-hiring-brief.md`

This becomes a reusable onboarding resource for future hires with similar backgrounds.
