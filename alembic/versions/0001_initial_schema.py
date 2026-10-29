"""Initial schema for nTrade AI.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-07-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_data",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("date_created", sa.DateTime(), nullable=True),
        sa.Column("date_modified", sa.DateTime(), nullable=True),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("is_closed", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("is_synthetic", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_price_symbol_tf_ts"),
    )
    op.create_index("idx_price_symbol_ts", "price_data", ["symbol", "timestamp"], unique=False)
    op.create_index("idx_price_timeframe", "price_data", ["timeframe"], unique=False)

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("signal_type", sa.String(length=10), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("take_profit", sa.Float(), nullable=False),
        sa.Column("position_size", sa.Float(), nullable=False),
        sa.Column("risk_amount", sa.Float(), nullable=False),
        sa.Column("reward_amount", sa.Float(), nullable=False),
        sa.Column("risk_reward_ratio", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(length=20), nullable=False),
        sa.Column("reasoning", sa.String(length=1000), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")),
        sa.Column("is_manual", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("date_created", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_signal_symbol_type", "signals", ["symbol", "signal_type"], unique=False)
    op.create_index("idx_signal_active", "signals", ["is_active"], unique=False)

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signals.id"), nullable=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("trade_type", sa.String(length=10), nullable=False),
        sa.Column("entry_time", sa.DateTime(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("position_size", sa.Float(), nullable=False),
        sa.Column("exit_time", sa.DateTime(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("exit_reason", sa.String(length=50), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("take_profit", sa.Float(), nullable=False),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("profit_loss", sa.Float(), nullable=True),
        sa.Column("profit_loss_pips", sa.Float(), nullable=True),
        sa.Column("profit_loss_percent", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("date_created", sa.DateTime(), nullable=True),
        sa.Column("date_modified", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
    )
    op.create_index("idx_trade_symbol_status", "trades", ["symbol", "status"], unique=False)
    op.create_index("idx_trade_entry_time", "trades", ["entry_time"], unique=False)

    op.create_table(
        "performance_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("total_trades", sa.Integer(), nullable=True),
        sa.Column("winning_trades", sa.Integer(), nullable=True),
        sa.Column("losing_trades", sa.Integer(), nullable=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("total_profit_loss", sa.Float(), nullable=True),
        sa.Column("gross_profit", sa.Float(), nullable=True),
        sa.Column("gross_loss", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("largest_win", sa.Float(), nullable=True),
        sa.Column("largest_loss", sa.Float(), nullable=True),
        sa.Column("average_win", sa.Float(), nullable=True),
        sa.Column("average_loss", sa.Float(), nullable=True),
        sa.Column("sharpe_ratio", sa.Float(), nullable=True),
        sa.Column("sortino_ratio", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("account_balance", sa.Float(), nullable=True),
        sa.Column("daily_return_percent", sa.Float(), nullable=True),
        sa.Column("date_created", sa.DateTime(), nullable=True),
        sa.Column("date_modified", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("date", name="uq_performance_metrics_date"),
    )
    op.create_index("idx_metrics_date", "performance_metrics", ["date"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_metrics_date", table_name="performance_metrics")
    op.drop_table("performance_metrics")

    op.drop_index("idx_trade_entry_time", table_name="trades")
    op.drop_index("idx_trade_symbol_status", table_name="trades")
    op.drop_table("trades")

    op.drop_index("idx_signal_active", table_name="signals")
    op.drop_index("idx_signal_symbol_type", table_name="signals")
    op.drop_table("signals")

    op.drop_index("idx_price_timeframe", table_name="price_data")
    op.drop_index("idx_price_symbol_ts", table_name="price_data")
    op.drop_table("price_data")
