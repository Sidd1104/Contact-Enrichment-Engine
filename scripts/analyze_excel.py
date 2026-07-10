#!/usr/bin/env python3
"""
Excel Dataset Analyzer - Phase 1.
Scans and analyzes the Excel sheet to produce statistics, schema info, and data quality insights.
"""

import os
import re
import sys
import pandas as pd
import json


def analyze_excel(file_path):
    print(f"Analyzing: {file_path}")
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found.")
        sys.exit(1)

    # 1. Load Excel File
    xls = pd.ExcelFile(file_path)
    sheet_names = xls.sheet_names
    num_sheets = len(sheet_names)

    # Automatically detect primary sheet: the one with the most cells (rows * cols)
    sheet_stats = []
    for sname in sheet_names:
        # Load only dimensions first to speed up if needed, but read_excel is fine for 10k rows
        df_temp = pd.read_excel(file_path, sheet_name=sname)
        rows, cols = df_temp.shape
        sheet_stats.append({
            "name": sname,
            "rows": rows,
            "cols": cols,
            "cells": rows * cols
        })

    # Sort sheets by number of cells descending
    sheet_stats.sort(key=lambda x: x["cells"], reverse=True)
    primary_sheet = sheet_stats[0]["name"]
    print(f"Sheets found: {sheet_stats}")
    print(f"Automatically detected primary sheet: '{primary_sheet}'")

    # Load primary sheet data
    df = pd.read_excel(file_path, sheet_name=primary_sheet)
    total_rows = len(df)
    total_columns = len(df.columns)
    column_names = list(df.columns)

    # 2. Check for duplicate column names
    dup_cols = []
    seen = set()
    for col in column_names:
        if col in seen:
            dup_cols.append(col)
        seen.add(col)

    # 3. Data type guess and missing values per column
    schema = []
    for col in df.columns:
        empty_count = df[col].isna().sum()
        empty_pct = (empty_count / total_rows) * 100 if total_rows > 0 else 0.0
        
        # Data type guess
        non_null_vals = df[col].dropna()
        if len(non_null_vals) == 0:
            guessed_type = "Empty/Undefined"
        else:
            first_val = non_null_vals.iloc[0]
            # Try to see if it's numeric, datetime, or text
            if pd.api.types.is_integer_dtype(df[col]):
                guessed_type = "Integer"
            elif pd.api.types.is_float_dtype(df[col]):
                guessed_type = "Float"
            elif pd.api.types.is_datetime64_any_dtype(df[col]):
                guessed_type = "Datetime"
            elif pd.api.types.is_bool_dtype(df[col]):
                guessed_type = "Boolean"
            else:
                guessed_type = "String/Text"
                # Check sample of values
                sample = str(first_val).strip()
                if re.match(r'^-?\d+$', sample):
                    guessed_type = "Integer (String)"
                elif re.match(r'^-?\d+\.\d+$', sample):
                    guessed_type = "Float (String)"
                
        schema.append({
            "column": col,
            "guessed_type": guessed_type,
            "empty_count": int(empty_count),
            "missing_percentage": round(empty_pct, 2)
        })

    # 4. Map key domains (heuristics)
    company_cols = []
    website_cols = []
    email_cols = []
    phone_cols = []
    address_cols = []
    city_cols = []
    state_cols = []
    country_cols = []
    zip_cols = []

    for col in column_names:
        c_lower = col.lower().replace("_", " ").replace("-", " ")
        
        # Company Name
        if any(w in c_lower for w in ["company", "firm", "organization", "investor name", "entity"]):
            if not any(w in c_lower for w in ["email", "phone", "website", "domain", "url", "linkedin"]):
                company_cols.append(col)
                
        # Website
        if any(w in c_lower for w in ["website", "web", "url", "domain", "link"]):
            if not any(w in c_lower for w in ["email", "phone", "linkedin", "twitter", "facebook"]):
                website_cols.append(col)
                
        # Email
        if any(w in c_lower for w in ["email", "mail"]):
            if not any(w in c_lower for w in ["phone", "website", "url", "domain"]):
                email_cols.append(col)
                
        # Phone
        if any(w in c_lower for w in ["phone", "telephone", "mobile", "tel"]):
            phone_cols.append(col)
            
        # Address
        if any(w in c_lower for w in ["address", "street"]):
            if not any(w in c_lower for w in ["city", "state", "zip", "country", "pincode"]):
                address_cols.append(col)
                
        # City
        if "city" in c_lower:
            city_cols.append(col)
            
        # State
        if any(w in c_lower for w in ["state", "province", "region"]):
            state_cols.append(col)
            
        # Country
        if "country" in c_lower:
            country_cols.append(col)
            
        # ZIP
        if any(w in c_lower for w in ["zip", "postal", "pincode", "postcode"]):
            zip_cols.append(col)

    # Recommended Primary Key
    rec_pk = "index"
    for col in df.columns:
        if df[col].nunique() == total_rows and df[col].isna().sum() == 0:
            rec_pk = col
            break

    # 5. Duplicate estimation
    # Let's count duplicate rows based on all columns
    all_col_dups = df.duplicated().sum()
    
    dup_companies = 0
    if company_cols:
        # Fill NA so that duplicated counts them
        dup_companies = df.duplicated(subset=[company_cols[0]]).sum()
        
    dup_websites = 0
    if website_cols:
        # Drop NA first to not count multiple empty websites as duplicates
        dup_websites = df[df[website_cols[0]].notna()].duplicated(subset=[website_cols[0]]).sum()
        
    dup_emails = 0
    if email_cols:
        dup_emails = df[df[email_cols[0]].notna()].duplicated(subset=[email_cols[0]]).sum()

    # 6. Data quality metrics for enrichment
    # Check row by row for email and phone missingness.
    # We will treat empty string or common null placeholders as missing.
    def is_empty(val):
        if pd.isna(val):
            return True
        v_str = str(val).strip().lower()
        return v_str in ["", "nan", "null", "none", "n/a", "-"]

    records_needing_enrichment = 0
    records_already_completed = 0
    records_missing_email_only = 0
    records_missing_phone_only = 0
    records_missing_both = 0

    for idx, row in df.iterrows():
        email_missing = True
        for col in email_cols:
            if not is_empty(row[col]):
                email_missing = False
                break
        
        phone_missing = True
        for col in phone_cols:
            if not is_empty(row[col]):
                phone_missing = False
                break
                    
        if email_missing and phone_missing:
            records_missing_both += 1
            records_needing_enrichment += 1
        elif email_missing:
            records_missing_email_only += 1
            records_needing_enrichment += 1
        elif phone_missing:
            records_missing_phone_only += 1
            records_needing_enrichment += 1
        else:
            records_already_completed += 1

    analysis_results = {
        "file_name": os.path.basename(file_path),
        "num_sheets": num_sheets,
        "sheet_names": sheet_names,
        "sheet_stats": sheet_stats,
        "primary_sheet": primary_sheet,
        "total_rows": int(total_rows),
        "total_columns": int(total_columns),
        "column_names": column_names,
        "duplicate_columns": dup_cols,
        "schema": schema,
        "detected_columns": {
            "company_name": company_cols,
            "website": website_cols,
            "email": email_cols,
            "phone": phone_cols,
            "address": address_cols,
            "city": city_cols,
            "state": state_cols,
            "country": country_cols,
            "zip_pincode": zip_cols
        },
        "duplicates": {
            "all_columns": int(all_col_dups),
            "companies": int(dup_companies),
            "websites": int(dup_websites),
            "emails": int(dup_emails)
        },
        "enrichment_status": {
            "total_needing_enrichment": int(records_needing_enrichment),
            "already_completed": int(records_already_completed),
            "missing_email_only": int(records_missing_email_only),
            "missing_phone_only": int(records_missing_phone_only),
            "missing_both": int(records_missing_both)
        },
        "recommendations": {
            "primary_key": rec_pk,
            "search_columns": company_cols + city_cols + state_cols + country_cols,
            "contact_columns": email_cols + phone_cols,
            "output_columns": company_cols + website_cols + ["Enriched Email", "Enriched Phone", "Enriched Contact Name", "Enriched Title", "Enriched LinkedIn", "Verification Source", "Last Updated"]
        }
    }

    # Save details as JSON in scripts/temp_stats.json
    stats_file = "scripts/temp_stats.json"
    with open(stats_file, 'w') as f:
        json.dump(analysis_results, f, indent=4)
        
    print(f"Analysis saved to {stats_file}")


if __name__ == "__main__":
    file_to_analyze = "us_investors_enriched.xlsx"
    analyze_excel(file_to_analyze)
