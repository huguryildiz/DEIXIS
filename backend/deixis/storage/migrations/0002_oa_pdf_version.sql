-- Version of the open-access location that oa_pdf_url points to. A PDF is attached to a
-- source version only when this matches the version_label of that source version.
ALTER TABLE source_versions ADD COLUMN oa_pdf_version TEXT;
