"""Add account scope to signals and trades.

Revision ID: 0002_account_scoped_trading
Revises: 0001_initial_schema
Create Date: 2026-07-19 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_account_scoped_trading"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signals",
        sa.Column("account_id", sa.String(length=50), nullable=False, server_default="synthetic"),
    )
    op.add_column(
        "trades",
        sa.Column("account_id", sa.String(length=50), nullable=False, server_default="synthetic"),
    )
    op.create_index("idx_signal_account_symbol", "signals", ["account_id", "symbol"], unique=False)
    op.create_index("idx_trade_account_symbol_status", "trades", ["account_id", "symbol", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_trade_account_symbol_status", table_name="trades")
    op.drop_index("idx_signal_account_symbol", table_name="signals")
    op.drop_column("trades", "account_id")
    op.drop_column("signals", "account_id")
