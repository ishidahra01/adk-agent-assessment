# Agent Spec: customer-support-agent

## Overview
A customer support agent for a shipping company built using the ADK 2.0 Graph Workflow API (`google.adk.workflow.Workflow`).
The workflow classifies incoming user queries to determine whether they pertain to shipping services (rates, package tracking, delivery status/options, returns).
- If the query is related to shipping, the workflow routes execution to a dedicated Shipping FAQ agent that provides accurate, helpful, and courteous support based on company policies.
- If the query is unrelated to shipping, the workflow routes to a decline node that politely informs the user that this assistant only handles shipping-related inquiries.

## Language
`python` (ADK 2.0 / `google-adk >= 2.0.0`)

## Architecture & Workflow Graph
- **START**: Built-in entry point receiving the user's message.
- **Node: `query_classifier`** (`LlmAgent`):
  - Uses `gemini-3.8-flash` with structured output schema `QueryClassification(is_shipping_related: bool, reasoning: str)`.
  - Determines if the inquiry relates to shipping (rates, tracking, delivery, returns).
  - Emits routing signal (`"shipping"` or `"unrelated"`).
- **Node: `shipping_faq_agent`** (`LlmAgent`):
  - Domain expert customer support representative specializing in shipping rates, tracking, delivery timelines, and return policies.
  - Generates clear, helpful, customer-facing answers.
- **Node: `decline_node`** (`FunctionNode`):
  - Generates a courteous decline message stating that the assistant is specifically dedicated to shipping assistance (rates, tracking, delivery, and returns) and asks how it can help with a shipping request.
- **Edges**:
  - `('START', query_classifier)`
  - `(query_classifier, shipping_faq_agent, "shipping")`
  - `(query_classifier, decline_node, "unrelated")`

## Example Use Cases
1. **Shipping Tracking**:
   - Input: "Can you help me check where package 1Z9999999999 is?"
   - Route: `shipping`
   - Output: Courteous explanation of tracking process and assistance steps.
2. **Shipping Rates**:
   - Input: "How much does it cost to send a 2kg parcel from New York to London?"
   - Route: `shipping`
   - Output: Overview of shipping tiers (express vs standard) and pricing calculation factors.
3. **Returns**:
   - Input: "What is your policy for returning damaged goods?"
   - Route: `shipping`
   - Output: Detailed steps on return merchandise authorization, packaging, and label generation.
4. **Unrelated Query**:
   - Input: "Can you write a poem about the French revolution?"
   - Route: `unrelated`
   - Output: Polite decline: "I am a customer support assistant for shipping services. I can only assist with questions regarding shipping rates, tracking, delivery, and returns. How can I help you with a shipping request today?"

## Tools Required
None (pure knowledge-based FAQ with structured graph routing as requested).

## Constraints & Safety Rules
- Must politely refuse all non-shipping queries.
- Do not provide inaccurate legal or financial guarantees; refer users to official claims forms for disputes or high-value insurance claims.
- Maintain a professional, helpful, and concise customer support tone.
- Skip deployment files (prototype only, no Terraform / CI/CD).

## Success Criteria
- Accurately classifies shipping queries vs unrelated queries (>= 95% accuracy on test prompts).
- Correctly routes along graph edges to either the FAQ agent or decline node.
- Provides friendly, accurate answers for shipping inquiries.
- Gracefully and politely declines off-topic prompts.

## Reference Samples
None required (workflow uses core ADK 2.0 `Workflow` graph API without external backing infrastructure).
