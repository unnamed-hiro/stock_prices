from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class SimulationConfig:
    initial_capital: float
    commission_rate: float
    slippage_rate: float
    start_date: str
    end_date: str
    benchmark: str


@dataclass
class UniverseConfig:
    file: str
    max_positions: int


@dataclass
class RiskConfig:
    position_size_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    max_holding_days: int
    min_cash_reserve_pct: float


@dataclass
class SuccessCriteria:
    min_win_rate: float
    min_profit_factor: float
    min_sharpe: float
    max_drawdown: float
    min_annual_return: float
    min_trades: int


@dataclass
class AppConfig:
    simulation: SimulationConfig
    universe: UniverseConfig
    risk: RiskConfig
    strategy_name: str
    strategy_params: dict
    success_criteria: SuccessCriteria
    raw: dict = field(default_factory=dict)


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return AppConfig(
        simulation=SimulationConfig(**data["simulation"]),
        universe=UniverseConfig(**data["universe"]),
        risk=RiskConfig(**data["risk"]),
        strategy_name=data["strategy"]["name"],
        strategy_params={k: v for k, v in data["strategy"].items() if k != "name"},
        success_criteria=SuccessCriteria(**data["success_criteria"]),
        raw=data,
    )
