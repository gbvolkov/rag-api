# Test Input Fixtures

Long-form fixture inputs for integration and complex test scenarios live in `tests/fixtures/inputs`.

## Regeneration

Run:

```powershell
python tests/fixtures/generate_inputs.py
```

This creates:

- `long_text.txt`
- `long_markdown.md`
- `long_data.json`
- `long_data.csv`
- `long_table.csv`
- `long_qa.txt`
- `long_document.docx`
- `long_workbook.xlsx`
- `long_tables.pdf`

The generated files are deterministic and designed to stress segmentation/chunking/indexing paths with larger payloads.
