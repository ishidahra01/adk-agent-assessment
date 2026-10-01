# Logistics Customer Support Agent (ADK 2.0)

[![CI Pipeline](https://github.com/ishidahra01/adk-agent-assessment/actions/workflows/ci.yml/badge.svg)](https://github.com/ishidahra01/adk-agent-assessment/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Framework](https://img.shields.io/badge/Framework-Google%20ADK%202.0-orange)](https://google.github.io/adk-docs/)

An intelligent enterprise-grade customer support agent for shipping and logistics built with **Google Agent Development Kit (ADK 2.0)**, **Gemini 3.8 Flash**, and **Vertex AI**.

---

## 🎯 Problem and Solution

- **The Problem**: E-commerce and parcel logistics companies face immense volumes of repetitive customer inquiries regarding package tracking, shipping rate estimates, delivery rescheduling, and return requests. Human support agents spend over 60% of their time performing repetitive manual lookups across fragmented systems, causing high wait times and operational costs.
- **The Solution**: An automated, context-aware **Logistics Customer Support Agent** that combines deterministic graph orchestration, real-time tool calling, session context memory, and safety guardrails. The agent handles end-to-end inquiry resolution in both English and Japanese while politely declining off-topic queries and maintaining strict enterprise safety boundaries.

---

## 🏛️ Architecture & Orchestration

```mermaid
flowchart TD
    User([Customer / Client]) --> Ingress["API & Interface Layer<br/>(FastAPI / SSE / A2A Protocol / Vertex AI Reasoning Engine)"]
    Ingress --> Workflow["ADK 2.0 Graph Workflow<br/>(customer_support_agent)"]
    
    subgraph OrchestrationGraph ["ADK Graph Workflow Engine"]
        Workflow --> StartNode["__START__"]
        StartNode --> Classifier["FunctionNode: query_classifier<br/>(Gemini Structured Output + Heuristic Fallback)"]
        
        Classifier -->|"route: shipping"| SupportAgent["LlmAgent: shipping_faq_agent<br/>(Gemini 3.8 Flash + State + Tools)"]
        Classifier -->|"route: unrelated"| DeclineNode["FunctionNode: decline_node<br/>(Polite Scope Refusal: EN/JA)"]
    end

    subgraph ToolsAndState ["Tool & Context Layer"]
        SupportAgent --> TrackTool["Tool: track_package<br/>(Real-time status & milestones)"]
        SupportAgent --> RateTool["Tool: calculate_shipping_rate<br/>(Ground, Express, Overnight)"]
        SupportAgent --> ReturnTool["Tool: create_return_label<br/>(RMA & Prepaid label creation)"]
        SupportAgent <--> SessionMem[("Session State & Memory<br/>(InMemory / Cloud SQL / Vertex AI)")]
    end

    subgraph ObservabilityLayer ["Observability & Telemetry"]
        SupportAgent -.-> Callbacks["Callbacks & Guardrails<br/>(Prompt Injection Filter, Audit Logs)"]
        Callbacks -.-> CloudTrace["Google Cloud Trace (OTel)"]
        Callbacks -.-> CloudLogging["Cloud Logging (Structured JSON)"]
        Callbacks -.-> BigQuery["BigQuery Agent Analytics"]
    end

    SupportAgent --> Response([Resolved Customer Answer])
    DeclineNode --> Response
```

---

## 🌟 Key Capabilities & Technical Highlights

This repository implements a production-grade enterprise agent architecture:

| Capability | Technical Highlights |
| :--- | :--- |
| **Tool & Interface Design** | • **Pydantic Schemas**: Explicit output models (`TrackingResult`, `ShippingRateResult`, `ReturnLabelResult`) with OpenAPI-compliant field descriptions.<br/>• **Guided Error Recovery**: Structured exception handling providing dynamic recovery instructions (`recovery_guidance`) for self-correcting tool use.<br/>• **Interfaces**: REST endpoints, Server-Sent Events (SSE), A2A protocol endpoint, and Vertex AI Reasoning Engine integration. |
| **Context & Memory** | • **Session State**: Stateful multi-turn conversation management with interaction history and user profiling.<br/>• **History Compaction & Caching**: ADK 2.0 event compaction and context caching for optimized token economics.<br/>• **Background Memory Consolidation**: Asynchronous non-blocking worker consolidating customer interaction summaries. |
| **Orchestration & Logic** | • **Deterministic Graph Workflow**: ADK 2.0 graph workflow with conditional routing nodes.<br/>• **Strategic Model Routing**: Dynamic routing across models (`gemini-2.5-flash-lite` for routing, `gemini-3.8-flash` for operations, `gemini-2.5-pro` for dispute resolution).<br/>• **Human-in-the-Loop (HITL)**: Confirmation hooks requiring supervisor validation for high-stakes damaged/lost parcel claims.<br/>• **Safety Guardrails**: Pre-model interceptor blocking prompt injection patterns. |
| **Observability & Tracing** | • **Dedicated Structured Logging**: Cloud Logging and OpenTelemetry compatible adapter (`json_fields`).<br/>• **PII Redaction**: Automatic regex-based sanitization of emails, phone numbers, payment cards, and credentials.<br/>• **Cloud Trace & Analytics**: Native trace export and BigQuery telemetry sink. |
| **Infrastructure & CI/CD** | • **CI Pipeline**: Automated testing (`pytest`), linting (`ruff`), and Docker build validation on pull requests.<br/>• **CD Pipeline**: Automated Cloud Run deployment via GitHub Actions.<br/>• **Terraform (IaC)**: Production-ready Infrastructure as Code for Cloud Run, Artifact Registry, and telemetry. |

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.11, 3.12, or 3.13
- `uv` (recommended package manager): `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Google Cloud project with Vertex AI enabled (or `GEMINI_API_KEY`)

### 2. Setup Environment
```bash
# Clone the repository
git clone https://github.com/ishidahra01/adk-agent-assessment.git
cd adk-agent-assessment

# Copy environment template
cp .env.example .env
# Edit .env with your GCP project ID or GEMINI_API_KEY
```

### 3. Install Dependencies
```bash
uv sync --extra lint --extra eval
```

### 4. Run Tests & Linter
```bash
# Run unit tests
uv run pytest tests/unit

# Run linter
uv run --extra lint ruff check app tests
```

### 5. Launch Locally
```bash
# Start FastAPI backend server
uv run uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8000
```
Open your browser to `http://localhost:8000/docs` to test endpoints via Swagger UI.

---

## 🧪 Evaluation & Quality Benchmarks

Run evaluations using the built-in evaluation datasets:
```bash
# Run response quality evaluation
uv run pytest tests/eval/response_quality.py
```

Eval datasets included:
- `customer_support_eval_set.json`: Multi-turn dialogue scenarios covering tracking, rates, returns, and off-topic declines.
- `customer_support_tools_eval_set.json`: Tool execution accuracy benchmarks.
- `eval_config.json`: LLM-as-a-judge rubrics evaluating relevance, scope adherence, policy accuracy, and courtesy.

---

## 📦 Deployment

### Cloud Run Deployment via Terraform
```bash
cd deployment/terraform/single-project
terraform init
terraform plan
terraform apply
```

### Direct Docker Container Run
```bash
docker build -t customer-support-agent:latest .
docker run -p 8080:8080 --env-file .env customer-support-agent:latest
```

---

## 📄 License
This project is licensed under the Apache 2.0 License - see the [LICENSE](LICENSE) file for details.
