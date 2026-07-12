#!/usr/bin/env node
/**
 * Prompt Finder Agent Implementation
 * Intelligent discovery and recommendation of effective prompts from prompts.chat
 *
 * Usage:
 *   node prompt-finder-implementation.ts --task "Your task description"
 *   Or invoke via Claude Code Agent system
 */

import Anthropic from "@anthropic-ai/sdk";

interface Prompt {
  id?: string;
  title: string;
  content: string;
  category?: string;
  tags?: string[];
  author?: string;
  voteCount?: number;
  viewCount?: number;
  isFeatured?: boolean;
  type?: "STRUCTURED" | "TEXT";
}

interface PromptsApiResponse {
  prompts: Prompt[];
  count: number;
  page: number;
  totalPages: number;
}

/**
 * Fetch prompts from the prompts.chat API
 */
async function fetchPromptsFromAPI(
  query: string,
  limit = 30,
): Promise<Prompt[]> {
  try {
    // Encode query for URL safety
    const encodedQuery = encodeURIComponent(query);
    const url = `https://prompts.chat/prompts.json?q=${encodedQuery}&limit=${limit}&full_content=true`;

    const response = await fetch(url, {
      headers: {
        "Accept": "application/json",
        "User-Agent": "prompt-finder-agent/1.0",
      },
    });

    if (!response.ok) {
      console.warn(`API returned ${response.status}, falling back to local examples`);
      return getLocalPromptExamples();
    }

    const data = (await response.json()) as PromptsApiResponse;
    return data.prompts || [];
  } catch (error) {
    console.warn("Failed to fetch from API:", error);
    return getLocalPromptExamples();
  }
}

/**
 * Get local example prompts (fallback for demo/offline use)
 */
function getLocalPromptExamples(): Prompt[] {
  return [
    {
      title: "Code Reviewer",
      content: `You are an expert code reviewer. Review the following code for:
1. Security vulnerabilities
2. Performance issues
3. Code quality and maintainability
4. Best practices compliance

Provide specific line numbers and actionable suggestions.`,
      category: "Coding",
      tags: ["Python", "JavaScript", "Quality"],
      voteCount: 234,
      viewCount: 5000,
      isFeatured: true,
      type: "STRUCTURED",
    },
    {
      title: "Technical Documentation Writer",
      content: `You are a technical writer specializing in clear, concise documentation.
Write documentation for:
- Purpose and use cases
- API reference with examples
- Installation and setup
- Troubleshooting guide

Use markdown formatting with clear sections.`,
      category: "Documentation",
      tags: ["Writing", "Technical"],
      voteCount: 156,
      viewCount: 3200,
      type: "STRUCTURED",
    },
    {
      title: "Data Analysis Mentor",
      content: `You are a mentor helping users understand data analysis concepts.
For each query:
1. Explain the concept simply
2. Provide a practical Python example
3. Suggest relevant libraries
4. Ask clarifying follow-up questions

Focus on learning, not just answers.`,
      category: "Analysis",
      tags: ["Python", "Data Science", "Education"],
      voteCount: 189,
      viewCount: 4100,
      type: "STRUCTURED",
    },
    {
      title: "Creative Writing Assistant",
      content: `You are a creative writing coach. Help users develop their writing by:
1. Suggesting plot improvements
2. Developing characters with depth
3. Creating engaging dialogue
4. Building atmosphere and tension

Ask clarifying questions about their vision.`,
      category: "Writing",
      tags: ["Creative", "Fiction"],
      voteCount: 267,
      viewCount: 6800,
      type: "STRUCTURED",
    },
    {
      title: "API Design Consultant",
      content: `You are an API design expert. When reviewing or designing APIs:
1. Evaluate REST principles adherence
2. Check for consistency in naming
3. Assess error handling approach
4. Review authentication strategy
5. Validate versioning strategy

Provide actionable improvements.`,
      category: "Architecture",
      tags: ["API", "Design", "Backend"],
      voteCount: 145,
      viewCount: 2900,
      type: "STRUCTURED",
    },
  ];
}

/**
 * Use Claude to analyze task and recommend best prompts
 */
async function findEffectivePrompts(
  taskDescription: string,
  availablePrompts: Prompt[],
): Promise<string> {
  const client = new Anthropic();

  // Prepare prompt database as context
  const promptsContext = availablePrompts
    .map(
      (p, idx) =>
        `\n## Prompt ${idx + 1}: ${p.title}\n` +
        `Category: ${p.category || "Uncategorized"}\n` +
        `Tags: ${(p.tags || []).join(", ") || "None"}\n` +
        `Engagement: ${p.voteCount || 0} votes, ${p.viewCount || 0} views\n` +
        `Type: ${p.type || "TEXT"}\n` +
        `${p.isFeatured ? "⭐ Featured\n" : ""}` +
        `Content:\n${p.content}`,
    )
    .join("\n---");

  const systemPrompt = `You are an expert at matching user tasks with the most effective prompts from a curated library.

Your role is to:
1. Understand the user's task and constraints
2. Analyze available prompts for relevance and effectiveness
3. Recommend the top 2-3 most suitable prompts
4. Explain why each prompt is effective for their task
5. Suggest any customizations or adaptations

Consider:
- Task complexity and structure
- Prompt categories and tags alignment
- Community engagement metrics (votes, views)
- Whether the prompt is structured (template) or free-form
- Availability of examples or demonstrations

Format your recommendations clearly with prompt names, relevance scores, and customization suggestions.`;

  const userPrompt = `User Task: "${taskDescription}"

Available Prompts Library:
${promptsContext}

Based on the user's task description, analyze the available prompts and recommend the most effective ones.
Consider the task type, required structure, and domain expertise needed.
For each recommendation, explain why it's effective and how the user could customize it for their specific needs.`;

  const response = await client.messages.create({
    model: "claude-opus-4-6",
    max_tokens: 2048,
    thinking: {
      type: "adaptive",
    },
    messages: [
      {
        role: "user",
        content: userPrompt,
      },
    ],
    system: systemPrompt,
  });

  // Extract text response
  const textContent = response.content.find((block) => block.type === "text");
  if (textContent && textContent.type === "text") {
    return textContent.text;
  }

  return "Unable to generate recommendations";
}

/**
 * Main agent function
 */
async function main() {
  // Get task from command line or stdin
  const taskArg = process.argv.slice(2).join(" ");
  const task =
    taskArg ||
    (await new Promise<string>((resolve) => {
      console.log("Prompt Finder Agent");
      console.log("==================");
      console.log("\nDescribe your task (what do you need a prompt for?):");

      let input = "";
      process.stdin.setEncoding("utf8");
      process.stdin.on("readable", () => {
        let chunk;
        while ((chunk = process.stdin.read()) !== null) {
          input += chunk;
        }
      });

      process.stdin.on("end", () => {
        resolve(input.trim());
      });
    }));

  if (!task) {
    console.error("No task provided");
    process.exit(1);
  }

  console.log(`\n🔍 Searching for effective prompts for: "${task}"\n`);

  // Fetch available prompts
  console.log("📚 Loading prompt library...");
  const prompts = await fetchPromptsFromAPI(task);
  console.log(`Found ${prompts.length} candidate prompts\n`);

  // Get Claude's recommendations
  console.log("🤖 Analyzing and recommending prompts...\n");
  const recommendations = await findEffectivePrompts(task, prompts);

  console.log("📋 RECOMMENDATIONS:\n");
  console.log(recommendations);

  console.log("\n💡 Tips:");
  console.log(
    "- Copy the recommended prompt and customize it for your specific needs",
  );
  console.log(
    "- Visit https://prompts.chat to explore more prompts and community variations",
  );
  console.log(
    "- Share your customizations with the community to help others",
  );
}

main().catch(console.error);
