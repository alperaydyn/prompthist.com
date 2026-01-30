"""
360 Company Data Summarization Prompt for Gemma3 27B
Optimized for smaller models with structured reasoning
"""

import os
import json
import requests
import pandas as pd
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_PATH, "data")

# =============================================================================
# SYSTEM PROMPT (loaded from external file)
# =============================================================================

def load_system_prompt():
    """Load system prompt from external file"""
    prompt_path = os.path.join(BASE_PATH, "system_prompt.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()

SYSTEM_PROMPT = load_system_prompt()

# =============================================================================
# USER PROMPT TEMPLATE
# =============================================================================

USER_PROMPT_TEMPLATE = """## ŞİRKET: {company_name}

## VERİLER:
{data_rows}

## TALİMAT:
Yukarıdaki 5 satır veriyi analiz et. Her satır için 1 cümle olmak üzere toplam 5 cümlelik tek paragraf yaz.

<thinking>
Her satırı sırayla analiz et:
1. Kategori ve ürün ne?
2. Dönem ne (Y/M/3M)?
3. CURR_AMNT ve PREV_AMNT değerleri?
4. DIFF_RATIO ve DIFF_AMNT değerleri?
5. Önceki satırın DIFF işareti ne? Bağlaç seçimi?
</thinking>

Özet:"""

# =============================================================================
# DATA FORMATTING FUNCTIONS
# =============================================================================

def format_number(value, currency="TL"):
    """Format number with thousand separators, no decimals"""
    if pd.isna(value) or value == 0:
        return "0"

    # Round to integer and format with thousand separators (using dot)
    formatted = f"{int(round(value)):,}".replace(",", ".")
    return f"{formatted} {currency}"

def format_row_for_prompt(row, idx):
    """Format a single data row for the prompt"""
    period_map = {"Y": "Yıllık", "M": "Aylık", "3M": "3 Aylık"}
    period = period_map.get(row['TIME_PERIOD_CODE'], row['TIME_PERIOD_CODE'])

    diff_ratio_str = f"{int(round(row['DIFF_RATIO']))}%" if pd.notna(row['DIFF_RATIO']) and row['DIFF_RATIO'] != 0 else "N/A"

    # Handle DIFF_AMNT which might be string or float
    diff_amnt = row['DIFF_AMNT']
    if isinstance(diff_amnt, str):
        diff_amnt_str = diff_amnt
    elif pd.notna(diff_amnt) and diff_amnt != 0:
        diff_amnt_str = format_number(float(diff_amnt), row['CURRENCY_CODE'])
    else:
        diff_amnt_str = "N/A"

    return f"""Satır {idx}:
  - Kategori: {row['CATEGORY_NAME']}
  - Ürün: {row['PRODUCT_CODE']}
  - Dönem: {period}
  - Bu Dönem: {format_number(row['CURR_AMNT'], row['CURRENCY_CODE'])}
  - Önceki Dönem: {format_number(row['PREV_AMNT'], row['CURRENCY_CODE'])}
  - Değişim Oranı: {diff_ratio_str}
  - Değişim Tutarı: {diff_amnt_str}"""

def prepare_company_prompt(df, customer_num):
    """Prepare the full prompt for a company"""
    company_data = df[df['CUSTOMER_NUM'] == customer_num].sort_values('NEW_SIRA_NO')
    company_name = company_data['CUSTOMER_NAME'].iloc[0]

    data_rows = []
    for idx, (_, row) in enumerate(company_data.iterrows(), 1):
        data_rows.append(format_row_for_prompt(row, idx))

    return USER_PROMPT_TEMPLATE.format(
        company_name=company_name,
        data_rows="\n\n".join(data_rows)
    )

# =============================================================================
# API CALL FUNCTION
# =============================================================================

def call_gemma_api(system_prompt, user_prompt):
    """Call Gemma3 27B via OpenRouter API"""
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "google/gemma-3-27b-it",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 1000,
            "top_p": 0.9
        },
        timeout=60
    )

    result = response.json()
    if "choices" in result:
        return result["choices"][0]["message"]["content"]
    else:
        raise Exception(f"API Error: {result}")

# =============================================================================
# MAIN EXECUTION
# =============================================================================

def summarize_all_companies():
    """Generate summaries for all companies in the dataset"""
    df = pd.read_excel(f"{DATA_PATH}/360data.xlsx")

    summaries = {}
    for customer_num in df['CUSTOMER_NUM'].unique():
        company_name = df[df['CUSTOMER_NUM'] == customer_num]['CUSTOMER_NAME'].iloc[0]
        print(f"Processing: {company_name}...")

        user_prompt = prepare_company_prompt(df, customer_num)

        try:
            summary = call_gemma_api(SYSTEM_PROMPT, user_prompt)
            summaries[customer_num] = {
                "company_name": company_name,
                "summary": summary
            }
            print(f"  ✓ Done")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            summaries[customer_num] = {
                "company_name": company_name,
                "summary": f"Error: {str(e)}"
            }

    # Save results
    output_path = f"{BASE_PATH}/summaries_output.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summaries, f, ensure_ascii=False, indent=2)

    print(f"\nResults saved to: {output_path}")
    return summaries

def summarize_single_company(customer_num):
    """Generate summary for a single company"""
    df = pd.read_excel(f"{DATA_PATH}/360data.xlsx")

    user_prompt = prepare_company_prompt(df, customer_num)
    print("=" * 60)
    print("SYSTEM PROMPT:")
    print("=" * 60)
    print(SYSTEM_PROMPT)
    print("\n" + "=" * 60)
    print("USER PROMPT:")
    print("=" * 60)
    print(user_prompt)
    print("\n" + "=" * 60)
    print("GENERATING SUMMARY...")
    print("=" * 60)

    summary = call_gemma_api(SYSTEM_PROMPT, user_prompt)
    print(summary)
    return summary

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        summarize_all_companies()
    elif len(sys.argv) > 1:
        summarize_single_company(int(sys.argv[1]))
    else:
        # Default: summarize first company
        df = pd.read_excel(f"{DATA_PATH}/360data.xlsx")
        first_customer = df['CUSTOMER_NUM'].iloc[0]
        summarize_single_company(first_customer)
