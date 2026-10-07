from pathlib import Path

import json
import pandas as pd

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
# Read the Excel file
df = pd.read_excel(SAMPLES / "Data_SOAP_notes.xlsx")

# Display basic info
print("=" * 80)
print("EXCEL FILE STRUCTURE")
print("=" * 80)
print(f"Total rows: {len(df)}")
print(f"Columns: {list(df.columns)}")
print("\n")

# Display first 3 complete examples
print("=" * 80)
print("FIRST 3 EXAMPLES")
print("=" * 80)

for i in range(min(3, len(df))):
    print(f"\n{'='*80}")
    print(f"EXAMPLE {i+1}")
    print('='*80)
    for col in df.columns:
        value = df.iloc[i][col]
        if pd.notna(value):
            print(f"\n{col}:")
            print("-" * 40)
            print(value)
    print("\n")
