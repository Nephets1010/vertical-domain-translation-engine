"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-08

创建 VDT-MT 全部表：corpus / term / term_relation / model_version /
translation_job / eval_record / quality_risk / source_provenance。
使用 Base.metadata.create_all 保证与 SQLAlchemy 模型一致且数据库无关。
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

from vdtmt.db.models import Base

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())
    needed = set(Base.metadata.tables.keys())
    # 仅创建尚不存在的表，避免重复
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            table.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(bind=bind, checkfirst=True)
