-- Separate explicit activation scenario. The unchanged closed-set reader then fails.
ALTER TABLE rehearsal.items DROP CONSTRAINT legacy_labels;
INSERT INTO rehearsal.items VALUES (200, 'soso', 'explicit-activation');
