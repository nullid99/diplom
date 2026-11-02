"""Початкова схема FireVision."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    create_validation_functions()

    op.create_table('model_versions',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('architecture', sa.String(length=128), nullable=False),
    sa.Column('weights_path', sa.Text(), nullable=False),
    sa.Column('weights_sha256', sa.String(length=64), nullable=False),
    sa.Column('class_mapping', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('training_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(class_mapping) = 'object' AND class_mapping <> '{}'::jsonb", name=op.f('ck_model_versions_classes_object')),
    sa.CheckConstraint("jsonb_typeof(training_metadata) = 'object'", name=op.f('ck_model_versions_training_object')),
    sa.CheckConstraint("length(weights_path) > 0 AND position(':' in weights_path) = 0 AND position(chr(92) in weights_path) = 0 AND NOT (string_to_array(weights_path, '/') && ARRAY['', '.', '..'])", name=op.f('ck_model_versions_weights_path_relative')),
    sa.CheckConstraint("weights_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_model_versions_sha256_valid')),
    sa.CheckConstraint('firevision_valid_class_mapping(class_mapping)', name=op.f('ck_model_versions_classes_valid')),
    sa.CheckConstraint('length(trim(name)) > 0 AND length(trim(architecture)) > 0', name=op.f('ck_model_versions_names_nonempty')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_versions'))
    )
    op.create_index('ix_model_versions_created_at', 'model_versions', ['created_at'], unique=False)
    op.create_index('ix_model_versions_weights_sha256', 'model_versions', ['weights_sha256'], unique=False)
    op.create_table('video_sources',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('original_filename', sa.Text(), nullable=False),
    sa.Column('file_path', sa.Text(), nullable=False),
    sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('duration_seconds', sa.Numeric(precision=16, scale=6), nullable=True),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('fps', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("length(file_path) > 0 AND position(':' in file_path) = 0 AND position(chr(92) in file_path) = 0 AND NOT (string_to_array(file_path, '/') && ARRAY['', '.', '..'])", name=op.f('ck_video_sources_file_path_relative')),
    sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_video_sources_sha256_valid')),
    sa.CheckConstraint('duration_seconds >= 0', name=op.f('ck_video_sources_duration_nonnegative')),
    sa.CheckConstraint('file_size_bytes >= 0', name=op.f('ck_video_sources_size_nonnegative')),
    sa.CheckConstraint('fps > 0', name=op.f('ck_video_sources_fps_positive')),
    sa.CheckConstraint('length(original_filename) > 0', name=op.f('ck_video_sources_filename_nonempty')),
    sa.CheckConstraint('length(trim(name)) > 0', name=op.f('ck_video_sources_name_nonempty')),
    sa.CheckConstraint('width > 0 AND height > 0', name=op.f('ck_video_sources_dimensions_positive')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_video_sources'))
    )
    op.create_index('ix_video_sources_created_at', 'video_sources', ['created_at'], unique=False)
    op.create_index('ix_video_sources_sha256', 'video_sources', ['sha256'], unique=False)
    op.create_table('analysis_runs',
    sa.Column('video_source_id', sa.Uuid(), nullable=False),
    sa.Column('model_version_id', sa.Uuid(), nullable=False),
    sa.Column('mode', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=24), server_default='pending', nullable=False),
    sa.Column('settings_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('progress', sa.Numeric(precision=6, scale=5), server_default='0', nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('summary_metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('result_paths', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(result_paths) = 'object'", name=op.f('ck_analysis_runs_paths_object')),
    sa.CheckConstraint("jsonb_typeof(settings_snapshot) = 'object'", name=op.f('ck_analysis_runs_settings_object')),
    sa.CheckConstraint("jsonb_typeof(summary_metrics) = 'object'", name=op.f('ck_analysis_runs_metrics_object')),
    sa.CheckConstraint("mode IN ('playback', 'full')", name=op.f('ck_analysis_runs_mode_valid')),
    sa.CheckConstraint("status IN ('pending', 'running', 'stopped', 'completed', 'failed')", name=op.f('ck_analysis_runs_status_valid')),
    sa.CheckConstraint('finished_at IS NULL OR finished_at >= coalesce(started_at, created_at)', name=op.f('ck_analysis_runs_finish_order')),
    sa.CheckConstraint('firevision_valid_result_paths(result_paths)', name=op.f('ck_analysis_runs_paths_relative')),
    sa.CheckConstraint('progress BETWEEN 0 AND 1', name=op.f('ck_analysis_runs_progress_range')),
    sa.CheckConstraint('started_at IS NULL OR started_at >= created_at', name=op.f('ck_analysis_runs_start_order')),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id'], name=op.f('fk_analysis_runs_model_version_id_model_versions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['video_source_id'], ['video_sources.id'], name=op.f('fk_analysis_runs_video_source_id_video_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_analysis_runs'))
    )
    op.create_index(op.f('ix_analysis_runs_model_version_id'), 'analysis_runs', ['model_version_id'], unique=False)
    op.create_index('ix_analysis_runs_status_created_at', 'analysis_runs', ['status', 'created_at'], unique=False)
    op.create_index(op.f('ix_analysis_runs_video_source_id'), 'analysis_runs', ['video_source_id'], unique=False)
    op.create_table('events',
    sa.Column('analysis_run_id', sa.Uuid(), nullable=False),
    sa.Column('feature_type', sa.String(length=16), nullable=False),
    sa.Column('automatic_status', sa.String(length=24), server_default='suspected', nullable=False),
    sa.Column('start_seconds', sa.Numeric(precision=16, scale=6), nullable=False),
    sa.Column('confirmed_seconds', sa.Numeric(precision=16, scale=6), nullable=True),
    sa.Column('end_seconds', sa.Numeric(precision=16, scale=6), nullable=True),
    sa.Column('confidence', sa.Numeric(precision=6, scale=5), nullable=True),
    sa.Column('region', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('frame_path', sa.Text(), nullable=True),
    sa.Column('clip_path', sa.Text(), nullable=True),
    sa.Column('review_status', sa.String(length=24), server_default='unreviewed', nullable=False),
    sa.Column('operator_comment', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(automatic_status = 'suspected' AND confirmed_seconds IS NULL AND end_seconds IS NULL) OR (automatic_status = 'confirmed' AND confirmed_seconds IS NOT NULL AND end_seconds IS NULL) OR (automatic_status = 'completed' AND confirmed_seconds IS NOT NULL AND end_seconds IS NOT NULL)", name=op.f('ck_events_state_times')),
    sa.CheckConstraint("automatic_status IN ('suspected', 'confirmed', 'completed')", name=op.f('ck_events_automatic_status_valid')),
    sa.CheckConstraint("feature_type IN ('fire', 'smoke')", name=op.f('ck_events_feature_valid')),
    sa.CheckConstraint("jsonb_typeof(region) = 'object'", name=op.f('ck_events_region_object')),
    sa.CheckConstraint("length(clip_path) > 0 AND position(':' in clip_path) = 0 AND position(chr(92) in clip_path) = 0 AND NOT (string_to_array(clip_path, '/') && ARRAY['', '.', '..'])", name=op.f('ck_events_clip_path_relative')),
    sa.CheckConstraint("length(frame_path) > 0 AND position(':' in frame_path) = 0 AND position(chr(92) in frame_path) = 0 AND NOT (string_to_array(frame_path, '/') && ARRAY['', '.', '..'])", name=op.f('ck_events_frame_path_relative')),
    sa.CheckConstraint("review_status IN ('unreviewed', 'confirmed', 'false_positive', 'needs_review')", name=op.f('ck_events_review_status_valid')),
    sa.CheckConstraint('confidence BETWEEN 0 AND 1', name=op.f('ck_events_confidence_range')),
    sa.CheckConstraint('confirmed_seconds >= start_seconds', name=op.f('ck_events_confirmation_order')),
    sa.CheckConstraint('end_seconds >= coalesce(confirmed_seconds, start_seconds)', name=op.f('ck_events_end_order')),
    sa.CheckConstraint('start_seconds >= 0', name=op.f('ck_events_start_nonnegative')),
    sa.CheckConstraint('updated_at >= created_at', name=op.f('ck_events_updated_order')),
    sa.ForeignKeyConstraint(['analysis_run_id'], ['analysis_runs.id'], name=op.f('fk_events_analysis_run_id_analysis_runs'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_events'))
    )
    op.create_index('ix_events_automatic_status', 'events', ['automatic_status'], unique=False)
    op.create_index('ix_events_review_status_created_at', 'events', ['review_status', 'created_at'], unique=False)
    op.create_index('ix_events_run_start', 'events', ['analysis_run_id', 'start_seconds'], unique=False)

    create_triggers()

def create_validation_functions():
    op.execute(r"""
        CREATE FUNCTION firevision_valid_result_paths(paths jsonb) RETURNS boolean
        LANGUAGE sql IMMUTABLE STRICT AS $$
        SELECT CASE WHEN jsonb_typeof(paths) <> 'object' THEN false ELSE
          NOT EXISTS (SELECT 1 FROM jsonb_each(paths) AS entry WHERE
            jsonb_typeof(entry.value) <> 'string'
            OR length(entry.value #>> '{}') = 0
            OR position(':' in (entry.value #>> '{}')) > 0
            OR position(chr(92) in (entry.value #>> '{}')) > 0
            OR string_to_array(entry.value #>> '{}', '/') && ARRAY['', '.', '..'])
          END
        $$
    """)
    op.execute(r"""
        CREATE FUNCTION firevision_valid_class_mapping(mapping jsonb) RETURNS boolean
        LANGUAGE sql IMMUTABLE STRICT AS $$
        SELECT CASE WHEN jsonb_typeof(mapping) <> 'object' OR mapping = '{}'::jsonb THEN false ELSE
          NOT EXISTS (SELECT 1 FROM jsonb_each(mapping) AS entry WHERE
            entry.key !~ '^(0|[1-9][0-9]*)$'
            OR jsonb_typeof(entry.value) <> 'string'
            OR length(trim(entry.value #>> '{}')) = 0)
          END
        $$
    """)


def create_triggers():
    op.execute("""
        CREATE FUNCTION firevision_lock_run_settings() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.settings_snapshot IS DISTINCT FROM OLD.settings_snapshot THEN
                RAISE EXCEPTION 'Analysis settings snapshot is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER lock_analysis_run_settings BEFORE UPDATE ON analysis_runs
        FOR EACH ROW EXECUTE FUNCTION firevision_lock_run_settings()
    """)
    op.execute("""
        CREATE FUNCTION firevision_touch_event() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER touch_event_updated_at BEFORE UPDATE ON events
        FOR EACH ROW EXECUTE FUNCTION firevision_touch_event()
    """)


def downgrade():
    op.drop_table('events')
    op.drop_table('analysis_runs')
    op.drop_table('model_versions')
    op.drop_table('video_sources')
    op.execute('DROP FUNCTION firevision_touch_event()')
    op.execute('DROP FUNCTION firevision_lock_run_settings()')
    op.execute('DROP FUNCTION firevision_valid_class_mapping(jsonb)')
    op.execute('DROP FUNCTION firevision_valid_result_paths(jsonb)')
