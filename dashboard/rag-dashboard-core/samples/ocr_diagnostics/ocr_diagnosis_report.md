# OCR Diagnostic Report (No Implementation Changes)

## Scope
- Sample PDF analyzed: `/home/quantium/REPOS/RAG_Darovi/samples/C-010.000.1345.00_GMP_BIORESEARCH.pdf`
- Existing extracted output analyzed: `/home/quantium/REPOS/RAG_Darovi/samples/C-010.000.1345.00_GMP_BIORESEARCH.pdf.txt`
- Conversion logic under analysis: `/home/quantium/REPOS/RAG_Darovi/src/converter/pdf_converter.py`
- Pipeline conversion entrypoint under analysis: `/home/quantium/REPOS/RAG_Darovi/src/worker/tasks.py` (`convert_file`)

## Baseline Artifacts
- PDF type: `PDF 1.6`, produced by `KONICA MINOLTA bizhub 360i`, 2 pages, letter size.
- PDF size: ~814 KiB.
- Legacy text output size: 80 chars (very low for a 2-page government document).
- Legacy output pattern:
  - `--- PAGE 1 ---` then `L A I C N E D I F N O C` one char per line.
  - Same pattern for page 2.

## Local Diagnostics (Per Page)
Evidence file: `/home/quantium/REPOS/RAG_Darovi/samples/ocr_diagnostics/local_diagnostics.json`

- Runtime versions:
  - `tesseract 5.5.0`
  - `pdftoppm 25.03.0`
- Page 1:
  - `pdfplumber`: 23 chars, 12 non-whitespace, preview is vertical `L A I C N E D I F N O C`.
  - OCR direct: 5190 chars, 4331 non-whitespace, preview contains meaningful Spanish text (`COFEPRIS`, `ESTADOS UNIDOS MEXICANOS`, etc.).
  - `tables_count=0`, `fallback_gate=false`.
- Page 2:
  - `pdfplumber`: 23 chars, 12 non-whitespace, same vertical pattern.
  - OCR direct: 2544 chars, 2141 non-whitespace, meaningful Spanish body text.
  - `tables_count=0`, `fallback_gate=false`.

Interpretation from evidence:
- The scanned content is OCR-readable.
- `pdfplumber` returns short low-utility text fragments that are non-empty.
- Because text is non-empty, current gate prevents OCR fallback.

## Pipeline Runtime Diagnostics
Evidence file: `/home/quantium/REPOS/RAG_Darovi/samples/ocr_diagnostics/pipeline_diagnostics.json`

- Executed conversion through worker task path (`convert_file.run(...)`) in container runtime with MinIO/PostgreSQL available.
- Result from pipeline conversion matches existing sample output exactly (`outputs_match_exactly=true`).
- Pipeline output remains the short per-character vertical sequence.

Observed structured logs in conversion runtime:
- `task.started` (`convert_file`)
- `converter.pdf.start`
- `task.completed`
- No `converter.pdf.ocr_fallback` event observed in this sample run.

## Cause-Evidence Matrix (Prioritized)
| Priority | Candidate cause | Evidence | Confidence |
|---|---|---|---|
| 1 | OCR fallback gate not activated when low-quality text layer exists | Local diagnostics show `pdfplumber` returns non-empty text (`23 chars`) and `fallback_gate=false` on both pages, while OCR direct returns thousands of chars. | High |
| 2 | Document has a pathological text layer (vertical/fragmented extraction) | `pdfplumber_preview` is `L\\nA\\nI...` despite rich page content recovered by OCR direct. | High |
| 3 | OCR engine/runtime availability issue | Rejected for this case: OCR direct works with high output volume; tesseract/poppler versions available. | High (as a rejected cause) |
| 4 | Pipeline/runtime drift vs local behavior | Rejected for this case: pipeline output exactly reproduces legacy output; same failure shape observed. | High (as a rejected cause) |
| 5 | Table extraction interfering with OCR gate | Rejected for this sample: `tables_count=0` both pages. | High (as a rejected cause) |

## Root-Cause Hypothesis Set (No Remediation Yet)
- Primary explanatory hypothesis: the current fallback decision criterion is too narrow for scanned documents that still expose a non-empty but unusable text layer.
- Secondary explanatory hypothesis: this PDF includes a defective/rotated/fragmented text layer that tricks text extraction into returning non-empty output.

## Uncertainties Remaining
- Whether this failure mode generalizes to other problematic PDFs in production.
- The proportion of low-quality extractions caused by the same gate condition versus other OCR/layout issues.
- Distribution of similar cases by document source, scanner profile, and page layout.

## Next Analytical Step (Backlog, No Changes Implemented)
- Expand this same diagnostics protocol to multiple real PDFs and classify cases by:
  - `non_empty_low_value_text_layer`
  - `empty_text_layer`
  - `ocr_runtime_failure`
  - `layout_specific_failure`
