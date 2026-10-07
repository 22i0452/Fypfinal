from pathlib import Path

import openpyxl
import pandas as pd

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
# Read the Excel file
df = pd.read_excel(SAMPLES / "Data_SOAP_notes.xlsx")
print('=== FILE STRUCTURE ===')
print(f'Total rows: {len(df)}')
print(f'Columns: {list(df.columns)}')
print()
print('=== FIRST 5 EXAMPLES ===')
print()
for i in range(min(5, len(df))):
    print(f'--- EXAMPLE {i+1} ---')
    for col in df.columns:
        print(f'{col}:')
        print(df.iloc[i][col])
        print()
    print('='*80)
    print()
