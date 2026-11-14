# AXIOM metadata extraction validation

The validation harness compares automatic condition extraction against a source-grounded, agent-drafted review set. Each label stores an exact quotation and passage locator. Labels were drafted from source text without an extractor output column in the drafting view. This does not establish independent annotation: the AI assistant drafted the labels and the user has not signed off.

## Frozen protocol

Sample membership is chosen from passage tokens, before reading labels. The sample contains 33 chunks; 28 are labelled, with 57 field labels across 11 sources and six experiment groups. The remaining chunks have no scoreable label. There are 39 eligible and 18 explicitly ineligible labels. Missing information in a source is not an extraction error. Numeric tolerances and matching rules are fixed in `src/axiom/extraction_validation.py`; repeated identical values are deduplicated on both the reference and extracted sides. No extractor code was changed in response to this label set, so it is not a tuned result on the recorded sample.

## Recorded results

See [results.json](../runs/axiom/extraction_validation/results.json) and the reviewer sheet [REVIEW.md](../runs/axiom/extraction_validation/REVIEW.md). At commit `5eb61c8`, overall precision was 0.8182, recall 0.6923 and F1 0.75. By field, precision/recall was oxygen 0.9/0.6, pressure 1.0/0.8, flow 0.6429/0.8182, and temperature 1.0/0.3333. Numeric agreement was 1.0 with maximum absolute error 0.0 on matched values. Four exclusion violations were flow thresholds treated as eligible conditions; six false positives and twelve misses were listed. These values describe this fixed sample only.

No holdout claim is made: the small fixed corpus did not provide an independent holdout large enough to retain the required diversity. There is no human-reviewed metadata and no independent second annotator. The dashboard badges distinguish automatic extraction from agent-drafted labels; human-reviewed status remains absent until the user completes the review sheet.

Review required: inspect the 57 field labels and their quotations/locators, with particular attention to the 18 ineligible labels, all extractor disagreements, and the proposed inclusion/exclusion of thresholds. Add reviewer name/date and decisions only after that review. This is not a request to certify unfamiliar combustion science; domain interpretation should remain provisional pending a qualified reviewer.
