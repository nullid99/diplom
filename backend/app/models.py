import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention={
        'ix': 'ix_%(table_name)s_%(column_0_name)s',
        'uq': 'uq_%(table_name)s_%(column_0_name)s',
        'ck': 'ck_%(table_name)s_%(constraint_name)s',
        'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
        'pk': 'pk_%(table_name)s',
    })


def relative_path_check(column: str) -> str:
    return (
        f"length({column}) > 0 AND position(':' in {column}) = 0 "
        f"AND position(chr(92) in {column}) = 0 "
        f"AND NOT (string_to_array({column}, '/') && ARRAY['', '.', '..'])"
    )


class IdentityCreated:
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class VideoSource(IdentityCreated, Base):
    __tablename__ = 'video_sources'
    name: Mapped[str] = mapped_column(sa.String(255))
    original_filename: Mapped[str] = mapped_column(sa.Text)
    file_path: Mapped[str] = mapped_column(sa.Text)
    file_size_bytes: Mapped[int | None] = mapped_column(sa.BigInteger)
    sha256: Mapped[str | None] = mapped_column(sa.String(64))
    duration_seconds: Mapped[Decimal | None] = mapped_column(sa.Numeric(16, 6))
    width: Mapped[int | None] = mapped_column(sa.Integer)
    height: Mapped[int | None] = mapped_column(sa.Integer)
    fps: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 6))
    container_format: Mapped[str | None] = mapped_column(sa.String(255))
    video_codec: Mapped[str | None] = mapped_column(sa.String(128))
    avg_frame_rate: Mapped[str | None] = mapped_column(sa.String(64))
    r_frame_rate: Mapped[str | None] = mapped_column(sa.String(64))
    observation_zones: Mapped[list] = mapped_column(JSONB, server_default=sa.text("'[]'::jsonb"))
    analysis_runs: Mapped[list['AnalysisRun']] = relationship(back_populates='video_source', passive_deletes='all')
    __table_args__ = (
        sa.CheckConstraint("length(trim(name)) > 0", name='name_nonempty'),
        sa.CheckConstraint("length(original_filename) > 0", name='filename_nonempty'),
        sa.CheckConstraint(relative_path_check('file_path'), name='file_path_relative'),
        sa.CheckConstraint('file_size_bytes >= 0', name='size_nonnegative'),
        sa.CheckConstraint("jsonb_typeof(observation_zones) = 'array'", name='zones_array'),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name='sha256_valid'),
        sa.CheckConstraint('duration_seconds >= 0', name='duration_nonnegative'),
        sa.CheckConstraint('width > 0 AND height > 0', name='dimensions_positive'),
        sa.CheckConstraint('fps > 0', name='fps_positive'),
        sa.Index('ix_video_sources_created_at', 'created_at'),
        sa.Index('ix_video_sources_sha256', 'sha256'),
    )


class ModelVersion(IdentityCreated, Base):
    __tablename__ = 'model_versions'
    name: Mapped[str] = mapped_column(sa.String(255))
    architecture: Mapped[str] = mapped_column(sa.String(128))
    weights_path: Mapped[str] = mapped_column(sa.Text)
    weights_sha256: Mapped[str] = mapped_column(sa.String(64))
    class_mapping: Mapped[dict[str, str]] = mapped_column(JSONB)
    training_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sa.text("'{}'::jsonb"))
    analysis_runs: Mapped[list['AnalysisRun']] = relationship(back_populates='model_version', passive_deletes='all')
    __table_args__ = (
        sa.CheckConstraint("length(trim(name)) > 0 AND length(trim(architecture)) > 0", name='names_nonempty'),
        sa.CheckConstraint(relative_path_check('weights_path'), name='weights_path_relative'),
        sa.CheckConstraint("weights_sha256 ~ '^[0-9a-f]{64}$'", name='sha256_valid'),
        sa.CheckConstraint("jsonb_typeof(class_mapping) = 'object' AND class_mapping <> '{}'::jsonb", name='classes_object'),
        sa.CheckConstraint('firevision_valid_class_mapping(class_mapping)', name='classes_valid'),
        sa.CheckConstraint("jsonb_typeof(training_metadata) = 'object'", name='training_object'),
        sa.Index('ix_model_versions_created_at', 'created_at'),
        sa.Index('ix_model_versions_weights_sha256', 'weights_sha256'),
    )


class AnalysisRun(IdentityCreated, Base):
    __tablename__ = 'analysis_runs'
    video_source_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey('video_sources.id', ondelete='RESTRICT'), index=True)
    model_version_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey('model_versions.id', ondelete='RESTRICT'), index=True)
    mode: Mapped[str] = mapped_column(sa.String(24))
    status: Mapped[str] = mapped_column(sa.String(24), server_default='pending')
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    progress: Mapped[Decimal] = mapped_column(sa.Numeric(6, 5), server_default='0')
    error_message: Mapped[str | None] = mapped_column(sa.Text)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    summary_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    result_paths: Mapped[dict[str, str] | None] = mapped_column(JSONB(none_as_null=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    worker_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    video_source: Mapped[VideoSource] = relationship(back_populates='analysis_runs')
    model_version: Mapped[ModelVersion] = relationship(back_populates='analysis_runs')
    events: Mapped[list['Event']] = relationship(back_populates='analysis_run', passive_deletes='all')
    __table_args__ = (
        sa.CheckConstraint("mode IN ('playback', 'full')", name='mode_valid'),
        sa.CheckConstraint("status IN ('pending', 'running', 'stopped', 'completed', 'failed')", name='status_valid'),
        sa.CheckConstraint('progress BETWEEN 0 AND 1', name='progress_range'),
        sa.CheckConstraint("jsonb_typeof(settings_snapshot) = 'object'", name='settings_object'),
        sa.CheckConstraint("jsonb_typeof(summary_metrics) = 'object'", name='metrics_object'),
        sa.CheckConstraint("jsonb_typeof(result_paths) = 'object'", name='paths_object'),
        sa.CheckConstraint('firevision_valid_result_paths(result_paths)', name='paths_relative'),
        sa.CheckConstraint('started_at IS NULL OR started_at >= created_at', name='start_order'),
        sa.CheckConstraint('finished_at IS NULL OR finished_at >= coalesce(started_at, created_at)', name='finish_order'),
        sa.Index('ix_analysis_runs_status_created_at', 'status', 'created_at'),
    )


class Event(IdentityCreated, Base):
    __tablename__ = 'events'
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey('analysis_runs.id', ondelete='RESTRICT'))
    feature_type: Mapped[str] = mapped_column(sa.String(16))
    automatic_status: Mapped[str] = mapped_column(sa.String(24), server_default='suspected')
    start_seconds: Mapped[Decimal] = mapped_column(sa.Numeric(16, 6))
    confirmed_seconds: Mapped[Decimal | None] = mapped_column(sa.Numeric(16, 6))
    end_seconds: Mapped[Decimal | None] = mapped_column(sa.Numeric(16, 6))
    confidence: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 5))
    region: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    frame_path: Mapped[str | None] = mapped_column(sa.Text)
    clip_path: Mapped[str | None] = mapped_column(sa.Text)
    review_status: Mapped[str] = mapped_column(sa.String(24), server_default='unreviewed')
    operator_comment: Mapped[str | None] = mapped_column(sa.Text)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    track_key: Mapped[str | None] = mapped_column(sa.String(64))
    last_seen_seconds: Mapped[Decimal | None] = mapped_column(sa.Numeric(16,6))
    closed_seconds: Mapped[Decimal | None] = mapped_column(sa.Numeric(16,6))
    closure_reason: Mapped[str | None] = mapped_column(sa.String(32))
    analysis_run: Mapped[AnalysisRun] = relationship(back_populates='events')
    __table_args__ = (
        sa.CheckConstraint("feature_type IN ('fire', 'smoke')", name='feature_valid'),
        sa.CheckConstraint("automatic_status IN ('suspected', 'confirmed', 'completed', 'interrupted')", name='automatic_status_valid'),
        sa.CheckConstraint("review_status IN ('unreviewed', 'confirmed', 'false_positive', 'needs_review')", name='review_status_valid'),
        sa.CheckConstraint('start_seconds >= 0', name='start_nonnegative'),
        sa.CheckConstraint('confirmed_seconds >= start_seconds', name='confirmation_order'),
        sa.CheckConstraint('end_seconds >= coalesce(confirmed_seconds, start_seconds)', name='end_order'),
        sa.CheckConstraint("(automatic_status = 'suspected' AND confirmed_seconds IS NULL AND end_seconds IS NULL) OR (automatic_status = 'confirmed' AND confirmed_seconds IS NOT NULL AND end_seconds IS NULL) OR (automatic_status IN ('completed','interrupted') AND confirmed_seconds IS NOT NULL AND (automatic_status = 'interrupted' OR end_seconds IS NOT NULL))", name='state_times'),
        sa.UniqueConstraint('analysis_run_id','track_key',name='uq_events_run_track'),
        sa.CheckConstraint('last_seen_seconds >= confirmed_seconds AND closed_seconds >= last_seen_seconds',name='observation_order'),
        sa.CheckConstraint('confidence BETWEEN 0 AND 1', name='confidence_range'),
        sa.CheckConstraint("jsonb_typeof(region) = 'object'", name='region_object'),
        sa.CheckConstraint(relative_path_check('frame_path'), name='frame_path_relative'),
        sa.CheckConstraint(relative_path_check('clip_path'), name='clip_path_relative'),
        sa.CheckConstraint('updated_at >= created_at', name='updated_order'),
        sa.Index('ix_events_run_start', 'analysis_run_id', 'start_seconds'),
        sa.Index('ix_events_automatic_status', 'automatic_status'),
        sa.Index('ix_events_review_status_created_at', 'review_status', 'created_at'),
    )


class AppSetting(Base):
    __tablename__='app_settings'
    key: Mapped[str]=mapped_column(sa.String(64),primary_key=True)
    value: Mapped[dict]=mapped_column(JSONB)
    updated_at: Mapped[datetime]=mapped_column(sa.DateTime(timezone=True),server_default=sa.func.now())
