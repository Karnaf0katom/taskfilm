# Reusable brand kit

Keep your brand text and palette in a UTF-8 JSON file:

```json
{
  "schema": "taskfilm-brand/v1",
  "brand": "Northstar",
  "tagline": "Ideas in motion.",
  "palette": {"ink": "#102120", "paper": "#ffffff", "accent": "#f47732"}
}
```

Author either format with the bundled original example:

```bash
taskfilm init examples
taskfilm animate ./northstar-wide --brand-file examples/brand.json --format landscape --silent
taskfilm animate ./northstar-tall --brand-file examples/brand.json --format portrait --silent
```

The `schema` field is required. `brand`, `tagline`, `palette`, and each palette
color are optional. Omitted values keep the existing defaults: Taskfilm,
Editable motion., ink `#142124`, paper `#fff5e5`, accent `#ff613d`.
Explicit `--brand`, `--tagline`, `--ink`, `--paper`, and `--accent` flags override
the file, including flags that explicitly supply those default values.
`--headline` remains the text of the individual animation.

Brand text must contain 1–24 characters and tagline text 1–54 characters.
Blank strings and control characters are rejected; surrounding whitespace is
trimmed. Colors must use six-digit hex notation. Unknown fields and values of
the wrong type are rejected. The resolved ink and paper colors must have at
least 4.5:1 contrast. Validation finishes before output directories are created.

`ANIMATION-PLAN.json` retains the final values in `config` and records
`brand_file.schema`, `brand_file.sha256` (SHA-256 of the exact input bytes),
and `brand_file.resolved` with the final brand, tagline, and palette. The
embedded configuration in `index.html` carries the same values into the film.
The source JSON is read without modification. Invocations without a brand
file keep the existing defaults and omit the `brand_file` record.
