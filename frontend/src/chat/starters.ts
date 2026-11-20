/** Starter prompts shown on an empty chat, aimed at beginners (Chainlit-style starter cards). */
export type StarterIcon = "price" | "trend" | "learn" | "language" | "compare" | "scenario";

export const STARTER_PROMPTS: { label: string; prompt: string; icon: StarterIcon }[] = [
  { label: "Latest price", prompt: "What is Apple's latest stock price?", icon: "price" },
  {
    label: "Recent trend",
    prompt: "How did NVIDIA's share price move over the last month?",
    icon: "trend",
  },
  {
    label: "Learn a term",
    prompt: "What does trading volume mean? Show me Microsoft's latest volume as an example.",
    icon: "learn",
  },
  { label: "Roman Urdu", prompt: "Amazon ka share price aaj kitna hai?", icon: "language" },
];
