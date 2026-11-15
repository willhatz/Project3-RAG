# Manually saved sources

Files here are ingested by the `file` method in `sources.yaml`. Use it for official or cited sources
whose websites block automated scripts.

How to add one:
1. Open the page in a browser and copy the article text (title and body only, no menus or ads).
2. Save it here as UTF-8 `.txt` (or save a PDF / `.md` / `.html`).
3. Add an entry in `sources.yaml` with `method: file`, `path`, the original `url`, `title`, `published`
   and `publisher`, so the chatbot cites the real source.
4. Run `python -m ingest --source <id>`.

Pending: `tnh_tamil_warnings.txt`, The New Humanitarian article on Tamil disaster warnings
(the site returns HTTP 403 to scripts).
