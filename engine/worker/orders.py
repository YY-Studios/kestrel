"""진입 주문 결정 (드라이런) — 순수 로직, 외부 호출 없음.

진입 신호(EntryResult.enter)를 "이런 주문을 넣겠다"는 결정으로 변환한다.
**이 모듈은 실제 주문을 넣지 않는다.** broker 호출·포지션 DB 기록은 다음 단계.

분할매수 1차(기본 40%)만 다룬다. 2·3차·익절·손절은 이후 단계.
"""

from __future__ import annotations

from dataclasses import dataclass

ORDER_FIRST_TRANCHE = 0.40  # 분할매수 1차 비중
ORDER_MAX_POSITIONS = 3     # 동시 보유 한도 (PRD)


@dataclass(frozen=True)
class OrderConfig:
    """자금/배분 설정. 값은 전략 설정/ env에서 주입(ADR-009 config 방향)."""

    total_capital: float
    max_positions: int = ORDER_MAX_POSITIONS
    first_tranche_pct: float = ORDER_FIRST_TRANCHE


@dataclass(frozen=True)
class OrderDecision:
    """진입 주문 결정 결과(드라이런). ordered=False면 reason에 생략 사유."""

    exchange: str
    symbol: str
    ordered: bool
    reason: str
    side: str = "buy"
    quantity: int = 0
    limit_price: float | None = None
    allocation: float = 0.0       # 종목당 배분액
    tranche_amount: float = 0.0   # 1차 금액(배분 × first_tranche_pct)
    tranche_pct: float = ORDER_FIRST_TRANCHE


def decide_buy_order(
    exchange: str,
    symbol: str,
    current_price: float | None,
    *,
    held_symbols: set[str],
    config: OrderConfig,
) -> OrderDecision:
    """진입 신호 종목에 대한 1차 매수 결정. 실제 주문은 하지 않는다(드라이런).

    - 이미 보유 중이면 생략(분할 2·3차는 다음 단계).
    - 보유 종목 수가 한도(max_positions)에 도달했으면 생략.
    - 현재가가 없거나 1차 금액으로 1주도 못 사면 생략.
    그 외엔 1차 금액(= 종목당 배분 × first_tranche_pct) ÷ 현재가 를 내림한 수량으로 결정.
    """
    def skip(reason: str, quantity: int = 0) -> OrderDecision:
        return OrderDecision(exchange, symbol, ordered=False, reason=reason, quantity=quantity)

    if symbol in held_symbols:
        return skip("이미 보유 중")
    if len(held_symbols) >= config.max_positions:
        return skip(f"보유 한도 초과 ({len(held_symbols)}/{config.max_positions})")
    if current_price is None or current_price <= 0:
        return skip("현재가 없음")

    allocation = config.total_capital / config.max_positions
    tranche_amount = allocation * config.first_tranche_pct
    quantity = int(tranche_amount // current_price)  # 정수 주, 내림
    if quantity <= 0:
        return skip("수량 0 (현재가가 1차 금액보다 큼)", quantity=0)

    return OrderDecision(
        exchange=exchange,
        symbol=symbol,
        ordered=True,
        reason="1차 매수",
        side="buy",
        quantity=quantity,
        limit_price=current_price,
        allocation=allocation,
        tranche_amount=tranche_amount,
        tranche_pct=config.first_tranche_pct,
    )


@dataclass(frozen=True)
class StopLossDecision:
    """손절 판정 결과. should_sell=True면 무조건 매도(홀딩·물타기 금지 — ROADMAP)."""

    should_sell: bool
    reason: str
    loss_pct: float | None
    realized_pnl: float | None


def decide_stop_loss(position: dict, current_price: float | None) -> StopLossDecision:
    """손절가 도달 판정: 현재가 ≤ 손절가(stop_price)이면 매도.

    손절은 "항상 실행" — 조건 충족 시 예외 없이 True(조건부 홀딩/재매수 없음).
    데이터 부족(현재가/평단/손절가/수량 없음)이면 판단 불가로 매도하지 않는다.
    (60일선 이탈 손절은 일봉이 필요 — 다음 단계에서 추가.)
    """
    stop = position.get("stop_price")
    avg = position.get("avg_price")
    qty = position.get("quantity")
    if current_price is None or stop is None or avg is None or qty is None:
        return StopLossDecision(False, "판단불가(데이터 부족)", None, None)
    loss_pct = (current_price - avg) / avg if avg else None
    realized_pnl = (current_price - avg) * qty
    if current_price <= stop:
        return StopLossDecision(True, "손절가 도달", loss_pct, realized_pnl)
    return StopLossDecision(False, "손절 미도달", loss_pct, realized_pnl)


@dataclass(frozen=True)
class TakeProfitDecision:
    """익절 판정 결과(손절과 대칭). should_sell=True면 목표가 도달 → 전량 익절."""

    should_sell: bool
    reason: str
    gain_pct: float | None
    realized_pnl: float | None


def decide_take_profit(position: dict, current_price: float | None) -> TakeProfitDecision:
    """익절 판정: 현재가 ≥ 목표가(target_price)이면 매도. 데이터 부족이면 매도하지 않는다.

    이번 단계는 단순 "목표가 도달 시 전량 익절". 트레일링·부분 익절은 1차 이후 고도화(별도).
    """
    target = position.get("target_price")
    avg = position.get("avg_price")
    qty = position.get("quantity")
    if current_price is None or target is None or avg is None or qty is None:
        return TakeProfitDecision(False, "판단불가(데이터 부족)", None, None)
    gain_pct = (current_price - avg) / avg if avg else None
    realized_pnl = (current_price - avg) * qty
    if current_price >= target:
        return TakeProfitDecision(True, "목표가 도달", gain_pct, realized_pnl)
    return TakeProfitDecision(False, "목표가 미도달", gain_pct, realized_pnl)


def format_order_decision(d: OrderDecision) -> str:
    """드라이런 로그 한 줄. 실제 주문이 나가지 않음을 분명히 표기한다."""
    if d.ordered:
        return (
            f"주문 예정(드라이런): {d.exchange}/{d.symbol} {d.quantity}주 매수 "
            f"지정가 ~${d.limit_price} (1차 {d.tranche_pct * 100:.0f}%, 배분 ${d.allocation:.0f}) "
            f"— 실제 주문 안 나감"
        )
    return f"진입 신호이나 주문 안 함: {d.exchange}/{d.symbol} — {d.reason} (드라이런)"
