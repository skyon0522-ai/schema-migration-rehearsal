-- Derived from pinned Alembic PGAutocommitBlockTest; see ../components/alembic/LICENSE.
CREATE SCHEMA rehearsal;
CREATE TYPE rehearsal.mood AS ENUM ('sad', 'ok', 'happy');
CREATE TABLE rehearsal.items (
    id integer PRIMARY KEY,
    mood rehearsal.mood NOT NULL,
    payload text NOT NULL,
    CONSTRAINT legacy_labels CHECK (mood::text IN ('sad', 'ok', 'happy'))
);
INSERT INTO rehearsal.items VALUES (1, 'sad', 'alpha'), (2, 'ok', 'beta'), (3, 'happy', 'gamma');
CREATE TABLE rehearsal.rollout_marker (
    id integer PRIMARY KEY CHECK (id = 1),
    completed boolean NOT NULL CHECK (completed)
);
