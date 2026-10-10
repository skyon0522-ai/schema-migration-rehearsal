-- Narrow derivation of pinned test SQL: fixed schema qualification and guarded retry.
-- MIT notice: ../components/alembic/LICENSE. Strict state validation precedes execution.
ALTER TYPE rehearsal.mood ADD VALUE IF NOT EXISTS 'soso';
