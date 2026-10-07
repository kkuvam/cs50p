-- Upgrade 2026-10-07 (PostgreSQL). Idempotent; safe to run more than once.
--   1. identity is unique among non-deleted individuals
--   2. users history trigger stops copying password_hash; old copies are blanked
-- Apply (as priya, after a pg_dump):
--   psql -d exomiser -v ON_ERROR_STOP=1 -f scripts/pg/upgrade_20261007.sql
--
-- SQLite equivalent of step 1 (dev databases created before this change):
--   CREATE UNIQUE INDEX IF NOT EXISTS uq_individuals_identity_active
--       ON individuals (identity) WHERE is_deleted = 0;
-- For SQLite step 2, drop and recreate the three users_history_* triggers from app.sql
-- and run: UPDATE users_history SET password_hash = NULL;
-- The index creation fails if two non-deleted individuals share an identity; resolve those first.

begin;

create unique index if not exists uq_individuals_identity_active
    on individuals (identity) where is_deleted = false;

-- identical to users_history_fn in scripts/pg/history.sql
create or replace function users_history_fn() returns trigger language plpgsql as $$
begin
    if TG_OP = 'DELETE' then
        insert into users_history (operation, changed_at, id, email, password_hash, full_name, is_active, is_admin, is_deleted, deleted_at, created_at, updated_at)
        values (TG_OP, now() at time zone 'utc', OLD.id, OLD.email, NULL, OLD.full_name, OLD.is_active, OLD.is_admin, OLD.is_deleted, OLD.deleted_at, OLD.created_at, OLD.updated_at);
        return OLD;
    end if;
    insert into users_history (operation, changed_at, id, email, password_hash, full_name, is_active, is_admin, is_deleted, deleted_at, created_at, updated_at)
    values (TG_OP, now() at time zone 'utc', NEW.id, NEW.email, NULL, NEW.full_name, NEW.is_active, NEW.is_admin, NEW.is_deleted, NEW.deleted_at, NEW.created_at, NEW.updated_at);
    return NEW;
end
$$;

update users_history set password_hash = NULL where password_hash is not null;

commit;
