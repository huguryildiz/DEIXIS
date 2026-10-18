-- Spend ledger repricing (D111): a call booked with no cost because its model was not in the price list gets a cost once
-- a later list names that model. The row keeps when that happened and the date of the list used, so a cost that was not
-- known when the call was made stays told apart from one priced at the time. NULL on every row priced when written.
ALTER TABLE spend_ledger ADD COLUMN repriced_at TEXT;
ALTER TABLE spend_ledger ADD COLUMN repriced_price_list TEXT;
