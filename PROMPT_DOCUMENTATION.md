# 360 Company Data Summarization Prompt

## Overview

This document explains the prompt structure designed for summarizing company financial data using the Gemma3 27B model via OpenRouter API.

## File Structure

```
360Summarize/
├── app.py                  # Flask web application
├── PROMPT_DOCUMENTATION.md # This documentation
├── Dockerfile              # Cloud Run deployment
├── requirements.txt        # Python dependencies
├── .env                    # API credentials
├── templates/
│   └── index.html          # Web UI template (tabbed design)
├── data/
│   └── 360data.xlsx        # Company data
└── prompts/
    ├── system_prompt_000.txt   # Base system prompt
    ├── system_prompt_001.txt   # Version 001 (if saved)
    ├── user_prompt_000.txt     # Base user prompt
    └── user_prompt_001.txt     # Version 001 (if saved)
```

## Prompt Version Management

### Versioning System

Prompts are stored in the `prompts/` folder with incremental version numbers:
- **Base version**: `_000` suffix (e.g., `system_prompt_000.txt`)
- **New versions**: Incremental numbers (001, 002, 003, etc.)
- **System prompts**: Define the model's role and rules
- **User prompts**: Template for data presentation

### Version Functions

| Function | Description |
|----------|-------------|
| `get_prompt_versions(type)` | List all versions for system/user prompt |
| `get_latest_version(type)` | Get the highest version number |
| `load_prompt(type, version)` | Load a specific prompt version |
| `save_prompt(type, content)` | Save as new version (auto-increments) |

## Web UI - Tabbed Design

The web application features a modern tabbed interface:

### Tab 1: Ozetleme (Summarization)
- **Company dropdown**: Select from available companies
- **Data textarea**: Auto-populated with formatted company data
- **Version badge**: Shows current system/user prompt versions
- **Summarize button**: Generate AI summary
- **Result display**: Shows the generated summary

### Tab 2: Prompt Ayarlari (Prompt Settings)
- **Sub-tabs**: Switch between System and User prompts
- **Version selector**: Load any saved version
- **Prompt editor**: Edit prompt content
- **Save button**: Save as new version (auto-increments)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      INPUT: 360data.xlsx                     │
│   (Company data with 5 product rows per company)            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    DATA PREPROCESSING                        │
│   - Format numbers (thousand separators, no decimals)       │
│   - Map time periods (Y/M/3M → Yıllık/Aylık/3 Aylık)       │
│   - Structure rows for prompt                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     PROMPT ASSEMBLY                          │
│   ┌─────────────────┐    ┌──────────────┐                   │
│   │ SYSTEM PROMPT   │    │ USER         │                   │
│   │ (versioned)     │ +  │ PROMPT       │                   │
│   │                 │    │ (versioned)  │                   │
│   └─────────────────┘    └──────────────┘                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 GEMMA3 27B (OpenRouter)                      │
│   - Temperature: 0.3 (deterministic)                        │
│   - Max tokens: 1500                                        │
│   - Top-p: 0.9                                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    OUTPUT: Turkish Summary                   │
│   (5 sentences - one per data row)                          │
└─────────────────────────────────────────────────────────────┘
```

## System Prompt (prompts/system_prompt_000.txt)

### Structure

#### 1. Role Definition
```
Sen finansal veri özetleme asistanısın. Türkçe özet üret.
```
Concise, single-purpose role optimized for smaller models.

#### 2. Data Dictionary
| Column | Description |
|--------|-------------|
| TIME_PERIOD_CODE | Y=Yıllık M=Aylık 3M=3Aylık |
| CURR_AMNT | Bu dönem tutarı |
| PREV_AMNT | Önceki dönem tutarı |
| DIFF_RATIO | Değişim yüzdesi |
| DIFF_AMNT | Değişim tutarı |
| CURRENCY_CODE | Para birimi |

#### 3. Mandatory Rules
1. One sentence per row (5 rows = 5 sentences)
2. Preserve numbers exactly (including minus sign)
3. DIFF_RATIO → write as percentage: -%41 or %23
4. DIFF_AMNT → write as amount: -175.027 TL
5. End sentences with period
6. NO bullet points/numbers

#### 4. Example Sentence
```
DOĞRU: "Bankacılık hizmet gelirleri bu sene 250.700 TL olup geçen seneye göre -%41 oranında, -175.027 TL değişim kaydetmiştir."
```

#### 5. Conjunction Rules
- All DIFF negative → Start with "Ayrıca"
- DIFF sign changes → Start with "Öte yandan"

#### 6. Special Case
- CURR=0 and PREV>0 → Use "ürün aktif olarak kullanılmamaktadır"

## User Prompt (prompts/user_prompt_000.txt)

### Company Header
```
## ŞİRKET: {company_name}
```

### Structured Data Rows
```
Satır {n}:
  - Kategori: {CATEGORY_NAME}
  - Ürün: {PRODUCT_CODE}
  - Dönem: {Yıllık/Aylık/3 Aylık}
  - Bu Dönem: {CURR_AMNT} {CURRENCY}
  - Önceki Dönem: {PREV_AMNT} {CURRENCY}
  - Değişim Oranı: {DIFF_RATIO}%
  - Değişim Tutarı: {DIFF_AMNT} {CURRENCY}
```

### Thinking Block (Chain-of-Thought)
```xml
<thinking>
Her satırı sırayla analiz et:
1. Kategori ve ürün ne?
2. Dönem ne (Y/M/3M)?
...
</thinking>
```

## Number Formatting

Numbers are formatted with:
- **Thousand separators**: Using dots (e.g., 1.234.567)
- **No decimals**: Rounded to nearest integer
- **Currency suffix**: TL, USD, or PP

### Examples
| Raw Value | Formatted |
|-----------|-----------|
| 1273874.35 | 1.273.874 TL |
| -175027.16 | -175.027 TL |
| 250700.78 | 250.701 TL |
| -41.11 | -41% |

## Optimization for Gemma3 27B

| Optimization | Rationale |
|--------------|-----------|
| **Versioned prompts** | A/B testing and rollback capability |
| **External files** | Easy editing without code changes |
| **Structured rules** | Smaller models follow explicit numbered rules better |
| **Data dictionary** | Reduces ambiguity in column interpretation |
| **Thinking block** | Encourages step-by-step processing |
| **Low temperature (0.3)** | More deterministic outputs for financial data |
| **Turkish prompts** | Native language improves Turkish output quality |
| **Integer formatting** | Cleaner output, easier to read |

### Token Efficiency
- System prompt: ~400 tokens
- User prompt per company: ~400 tokens
- Expected output: ~200-300 tokens

## Usage

### Web Application (Flask)
```bash
python app.py
# Open http://localhost:5001
```

### Cloud Deployment
```bash
gcloud run deploy summarize-360 --source . --region europe-west1
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Main page with tabbed UI |
| `/get_company_data/<id>` | GET | Get formatted data for company |
| `/get_prompt/<type>/<version>` | GET | Get specific prompt version |
| `/save_prompt` | POST | Save new prompt version |
| `/get_versions` | GET | List all prompt versions |
| `/summarize` | POST | Generate AI summary |

## Modifying Prompts

### Via Web UI
1. Go to "Prompt Ayarları" tab
2. Select System or User sub-tab
3. Choose version from dropdown (or start from latest)
4. Edit the prompt content
5. Click "Kaydet" to save as new version

### Via File System
1. Create new file: `prompts/{type}_prompt_{version}.txt`
2. Version must be 3 digits (e.g., 001, 002)
3. Restart Flask app to pick up changes

## Configuration

### Environment Variables (.env)
```
OPENROUTER_API_KEY=sk-or-v1-xxxxx
PORT=5001
FLASK_DEBUG=true
```

### Model Parameters
| Parameter | Value | Reason |
|-----------|-------|--------|
| model | google/gemma-3-27b-it | Instruction-tuned variant |
| temperature | 0.3 | Low randomness for consistency |
| max_tokens | 1500 | Sufficient for 5-sentence output |
| top_p | 0.9 | Nucleus sampling threshold |

## Error Handling

The application handles:
- API timeouts (90 second limit)
- Invalid customer numbers
- Missing data fields
- API rate limits
- Invalid prompt versions

Errors are displayed in the web UI with user-friendly messages.
