# ruff: noqa: E501
"""Prompt templates for the LLM-backed agent nodes.

Long lines are intentional: these are natural-language instructions sent
verbatim to the LLM, and artificially rewrapping them would either change
the model's interpretation or require reconstructing the prompt at runtime.
"""

OPTIMIZATION_ADVISOR_PROMPT = """You are a cloud infrastructure cost optimization advisor.

INFRASTRUCTURE COST SUMMARY:
Total Monthly Cost: ${total_monthly_cost}
Provider: {provider}
Region: {region}

RESOURCE COST BREAKDOWN:
{resource_costs_json}

DETECTED PATTERNS:
{patterns_json}

For each detected pattern and for any other cost optimization opportunities you identify in the resource data, provide a suggestion in the following JSON format:

{{
  "optimizations": [
    {{
      "title": "Short descriptive title",
      "resource_address": "terraform resource address",
      "current_config": "What is currently configured",
      "suggested_config": "What you recommend instead",
      "estimated_monthly_savings": dollar_amount,
      "risk": "low|medium|high",
      "risk_explanation": "Why this risk level",
      "implementation_notes": "Specific Terraform changes needed"
    }}
  ]
}}

RULES:
1. Only suggest optimizations where you can estimate real dollar savings.
2. Always assess risk honestly — switching instance families is medium risk, changing from on-demand to reserved is low risk, removing redundancy is high risk.
3. Be specific about Terraform attribute changes (e.g., "change instance_type from m5.4xlarge to m6g.xlarge").
4. Consider ARM/Graviton instances where applicable — they offer 20% savings but require compatibility verification.
5. Do not suggest reserved instances if the infrastructure appears to be for development/staging.
6. If total cost is already low (< $100/month), focus on best practices rather than aggressive optimization.

Respond ONLY with the JSON object."""


REPORT_GENERATION_PROMPT = """You are writing an infrastructure cost analysis report for a DevOps team.

PROJECT: {project_path}
PROVIDER: {provider} ({region})
TOTAL MONTHLY COST: ${total_monthly_cost}
RESOURCE COUNT: {resource_count}

TOP COST DRIVERS:
{top_drivers_formatted}

OPTIMIZATION SUGGESTIONS:
{optimizations_formatted}

TOTAL POTENTIAL SAVINGS: ${savings} ({savings_pct}% reduction)

Write an executive summary (200 words max) covering:
1. Overall cost assessment — is this reasonable for the infrastructure described?
2. The biggest cost driver and why it's expensive
3. The highest-impact optimization opportunity
4. Any risks or caveats the team should be aware of

Write for a DevOps engineer audience. Be specific with resource names and dollar amounts. Do not be generic.

Respond with a JSON object:
{{
  "summary": "..."
}}

Respond ONLY with the JSON object."""
