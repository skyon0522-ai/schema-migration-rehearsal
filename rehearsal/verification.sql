-- query: schema
SELECT EXISTS (SELECT FROM pg_namespace WHERE nspname = :schema);
-- query: type
SELECT t.typtype FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = :schema AND t.typname = 'mood';
-- query: labels
SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = :schema AND t.typname = 'mood' ORDER BY enumsortorder;
-- query: relations
SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :schema AND c.relname IN ('items', 'rollout_marker') ORDER BY c.relname;
-- query: columns
SELECT table_name, column_name, data_type, udt_schema, udt_name, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = :schema AND table_name IN ('items', 'rollout_marker')
ORDER BY table_name, ordinal_position;
-- query: constraints
SELECT c.relname, k.conname, k.contype, pg_get_constraintdef(k.oid), k.convalidated
FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :schema AND c.relname IN ('items', 'rollout_marker')
ORDER BY c.relname, k.conname;
-- query: rows
SELECT to_jsonb(item) FROM rehearsal.items item ORDER BY id;
-- query: marker
SELECT to_jsonb(marker) FROM rehearsal.rollout_marker marker ORDER BY id;
