"""Контейнер, кодек та раціональні частоти кадрів без припущення CFR."""
from alembic import op
import sqlalchemy as sa

revision = '0002_video_metadata'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('video_sources', sa.Column('container_format', sa.String(255), nullable=True))
    op.add_column('video_sources', sa.Column('video_codec', sa.String(128), nullable=True))
    op.add_column('video_sources', sa.Column('avg_frame_rate', sa.String(64), nullable=True))
    op.add_column('video_sources', sa.Column('r_frame_rate', sa.String(64), nullable=True))


def downgrade():
    for name in ('r_frame_rate', 'avg_frame_rate', 'video_codec', 'container_format'):
        op.drop_column('video_sources', name)
