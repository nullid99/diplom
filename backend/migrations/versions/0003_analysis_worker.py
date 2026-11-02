"""Службові поля черги; предметні стани та незмінний snapshot збережено."""
from alembic import op
import sqlalchemy as sa

revision='0003_analysis_worker'
down_revision='0002_video_metadata'
branch_labels=None
depends_on=None


def upgrade():
    for name in ('cancel_requested_at','heartbeat_at'):
        op.add_column('analysis_runs',sa.Column(name,sa.DateTime(timezone=True),nullable=True))
    op.add_column('analysis_runs',sa.Column('worker_id',sa.Uuid,nullable=True))
    # Захищено не лише HTTP-шлях: джерело, модель і режим теж не змінюються.
    op.execute("""CREATE OR REPLACE FUNCTION firevision_lock_run_settings() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF NEW.settings_snapshot IS DISTINCT FROM OLD.settings_snapshot
        OR NEW.video_source_id IS DISTINCT FROM OLD.video_source_id
        OR NEW.model_version_id IS DISTINCT FROM OLD.model_version_id
        OR NEW.mode IS DISTINCT FROM OLD.mode THEN
        RAISE EXCEPTION 'Analysis input snapshot is immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$""")


def downgrade():
    op.execute("""CREATE OR REPLACE FUNCTION firevision_lock_run_settings() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF NEW.settings_snapshot IS DISTINCT FROM OLD.settings_snapshot THEN
        RAISE EXCEPTION 'Analysis settings snapshot is immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$""")
    for name in ('worker_id','heartbeat_at','cancel_requested_at'):
        op.drop_column('analysis_runs',name)
