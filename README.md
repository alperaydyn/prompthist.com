# PromptHist

**PromptHist** is a deterministic prompt evaluation and benchmarking platform for Large Language Models (LLMs).  
It enables systematic comparison of prompt versions across models using reproducible test cases, model-based judging, and statistical analysis.

PromptHist is designed for **prompt engineering as an engineering discipline**, not trial-and-error.

---

## Core Capabilities

### 1. Prompt Versioning
- Create and manage multiple versions of:
  - system prompts
  - user prompts
- Track prompt evolution during development
- Test changes incrementally or in full benchmark runs

---

### 2. Deterministic Prompt Evaluation
- Run prompts against fixed test cases
- Control randomness (temperature, seeds where supported)
- Ensure repeatable and comparable results across runs

---

### 3. Test Case Management
- Upload and manage structured test cases
- Execute prompts across:
  - selected inputs
  - selected prompt versions
  - selected LLM models

---

### 4. Multi-Model Testing
- Compare prompt performance across different LLMs
- Run the same prompt version against multiple models
- Analyze prompt–model interaction effects

---

### 5. Model-Based Judging
- Select a **judging model**
- Define custom **evaluation criteria**, such as:
  - correctness
  - relevance
  - completeness
  - tone
  - safety
  - formatting adherence
- Judge each output at test time
- Assign numeric scores per criterion

---

### 6. Full Benchmark Runs
- Execute full test suites across:
  - multiple prompt versions
  - multiple models
- Automatically aggregate results
- Compute statistics per criterion:
  - mean
  - variance
  - distribution

---

### 7. Comparative Analysis
- Compare benchmark runs against each other
- Identify:
  - which prompt version performs better
  - which model performs better
  - under which criteria
- Track regressions and improvements over time

---

### 8. Differential Case Analysis
- Automatically identify **most differentiating test cases**
- Highlight where outputs diverge the most
- Support root-cause analysis:
  - which prompt changes matter
  - which sections of a prompt are most impactful

---

### 9. Reporting
- Generate comparison reports
- Export results for offline analysis
- Use reports for:
  - prompt reviews
  - model selection
  - governance and audit trails

---

## Typical Workflow

1. Upload or define test cases
2. Write system and user prompts
3. Save multiple prompt versions
4. Select one or more LLMs
5. Define judging criteria and judging model
6. Run exploratory tests
7. Execute a full benchmark run
8. Compare results across versions and models
9. Analyze differentiating cases
10. Export and review reports

---

## Why PromptHist?

PromptHist is built for teams that need:

- **Repeatability** instead of ad-hoc testing
- **Evidence-based prompt decisions**
- **Model-agnostic evaluation**
- **Governance-ready benchmarking**
- **Engineering-grade prompt development workflows**

This is especially relevant for:
- enterprise AI teams
- data & advanced analytics units
- LLM platform teams
- regulated environments

---

## Scope & Philosophy

PromptHist treats prompts as:
- versioned artifacts
- testable units
- benchmarkable assets

Evaluation is:
- deterministic where possible
- explicit
- explainable
- comparable over time

---

## Status

> 🚧 Active development

APIs, features, and UX are evolving.

---

## License

TBD

---

## Contributing

Contribution guidelines will be added as the project stabilizes.

---

## Disclaimer

PromptHist evaluates LLM outputs using models as judges.  
Scores reflect **defined criteria and judge behavior**, not objective truth.
