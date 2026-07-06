# Mission

Build and maintain a CNRS job watcher that retrieves public job offers from `emploi.cnrs.fr`
and extracts thesis/CDD offers related to AI, ML, deep learning, generative AI, and data science.

# Constraints

- Do not scrape private candidate/admin areas.
- Respect `robots.txt` and rate limits.
- Prefer deterministic scraping over browser automation.
- Use browser automation only when HTML fetch is insufficient.
- Store raw HTML snapshots for debugging.
- All parsed fields must be validated with Pydantic.
- LLM classification must return strict JSON matching the schema.
- Never let the LLM decide alone whether an offer exists; the crawler/parser is source of truth.
- Add tests with saved HTML fixtures before changing parsers.

# Output

Generate Markdown and CSV shortlists with:

- title
- contract type
- duration
- education level
- location
- lab
- publication date
- URL
- relevance score
- reason
