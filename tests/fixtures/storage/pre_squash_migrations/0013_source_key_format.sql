-- D38: work keys change from "Nakano13" to "nakano2013molecular" (first author, four-digit year, first significant
-- title word). Every key is cleared here; at startup `source_keys.assign_missing` gives each work its new key, oldest
-- work first. Frozen report snapshots keep the keys they were frozen with.
UPDATE works SET source_key = NULL, source_key_basis = NULL;
