"""Source zones, temporal event lifecycle and persisted defaults. Existing runs stay immutable."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision='0004_zones_events'
down_revision='0003_analysis_worker'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('video_sources',sa.Column('observation_zones',JSONB,nullable=False,server_default=sa.text("'[]'::jsonb")))
    op.create_check_constraint(op.f('ck_video_sources_zones_array'),'video_sources',"jsonb_typeof(observation_zones) = 'array'")
    op.create_table('app_settings',sa.Column('key',sa.String(64),primary_key=True),sa.Column('value',JSONB,nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    for name,kind in [('track_key',sa.String(64)),('last_seen_seconds',sa.Numeric(16,6)),('closed_seconds',sa.Numeric(16,6)),('closure_reason',sa.String(32))]:
        op.add_column('events',sa.Column(name,kind,nullable=True))
    op.create_unique_constraint('uq_events_run_track','events',['analysis_run_id','track_key'])
    op.drop_constraint(op.f('ck_events_automatic_status_valid'),'events',type_='check')
    op.drop_constraint(op.f('ck_events_state_times'),'events',type_='check')
    op.create_check_constraint(op.f('ck_events_automatic_status_valid'),'events',"automatic_status IN ('suspected','confirmed','completed','interrupted')")
    op.create_check_constraint(op.f('ck_events_state_times'),'events',"(automatic_status = 'suspected' AND confirmed_seconds IS NULL AND end_seconds IS NULL) OR (automatic_status = 'confirmed' AND confirmed_seconds IS NOT NULL AND end_seconds IS NULL) OR (automatic_status IN ('completed','interrupted') AND confirmed_seconds IS NOT NULL AND (automatic_status = 'interrupted' OR end_seconds IS NOT NULL))")
    op.create_check_constraint(op.f('ck_events_observation_order'),'events','last_seen_seconds >= confirmed_seconds AND closed_seconds >= last_seen_seconds')


def downgrade():
    # Downgrade must not silently discard interrupted lifecycle semantics.
    connection=op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM events WHERE automatic_status='interrupted'")):
        raise RuntimeError('Interrupted events require an explicit export before downgrade.')
    for name in ('ck_events_observation_order','ck_events_state_times','ck_events_automatic_status_valid'):
        op.drop_constraint(op.f(name),'events',type_='check')
    op.create_check_constraint(op.f('ck_events_automatic_status_valid'),'events',"automatic_status IN ('suspected','confirmed','completed')")
    op.create_check_constraint(op.f('ck_events_state_times'),'events',"(automatic_status = 'suspected' AND confirmed_seconds IS NULL AND end_seconds IS NULL) OR (automatic_status = 'confirmed' AND confirmed_seconds IS NOT NULL AND end_seconds IS NULL) OR (automatic_status = 'completed' AND confirmed_seconds IS NOT NULL AND end_seconds IS NOT NULL)")
    op.drop_constraint('uq_events_run_track','events',type_='unique')
    for name in ('track_key','last_seen_seconds','closed_seconds','closure_reason'): op.drop_column('events',name)
    op.drop_table('app_settings')
    op.drop_column('video_sources','observation_zones')
