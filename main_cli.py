"""CLI: 터미널에서 봇과 대전하며 실시간 코칭(포지션 / 에쿼티 / 추천 액션 / 핸드 리딩)을 받는다.

실행 예:
  python main_cli.py                               # 6인 (나 + 봇 5)
  python main_cli.py --players 9 --stack 20000 --level-minutes 5
  python main_cli.py --bots tag,lag,rock --players 4
  python main_cli.py --auto --hands 200            # 봇끼리 자동 대전 (엔진 검증용)
"""

from __future__ import annotations

import argparse
import random
import sys
import time
import unicodedata

from holdem import (
    Action,
    BotProfile,
    GameEngine,
    GameSettings,
    IllegalActionError,
    PlayerView,
    pretty,
)
from holdem.bots import RangeBot, RuleBasedBot
from holdem.coach import Coach, CoachReport
from holdem.config import BOT_PRESETS, MAX_PLAYERS, MIN_PLAYERS, PRESET_DESCRIPTIONS

LINE = "─" * 64


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="텍사스 홀덤 학습 시뮬레이터 (CLI)")
    ap.add_argument("--players", type=int, default=6, help=f"총 인원 {MIN_PLAYERS}~{MAX_PLAYERS} (나 포함)")
    ap.add_argument("--stack", type=int, default=10_000, help="시작 바이인(칩)")
    ap.add_argument("--level-minutes", type=float, default=10.0, help="블라인드 레벨업 주기(분), 0=끔")
    ap.add_argument("--hands-per-level", type=int, default=None, help="N핸드마다 레벨업 (시간과 병행 가능)")
    ap.add_argument("--bots", type=str, default="", help=f"봇 스타일 목록 (쉼표 구분): {', '.join(BOT_PRESETS)}")
    ap.add_argument("--seed", type=int, default=None, help="재현용 난수 시드")
    ap.add_argument("--equity-iters", type=int, default=1500, help="코치 에쿼티 시뮬레이션 횟수")
    ap.add_argument("--bot-engine", choices=("range", "rule"), default="range",
                    help="range = 코칭 엔진 기반 봇(2단계), rule = 에쿼티 기반 기본 봇(1단계)")
    ap.add_argument("--no-coach", action="store_true", help="코칭 카드 숨기기 (실전 연습)")
    ap.add_argument("--delay", type=float, default=0.4, help="봇 액션 사이 지연(초)")
    ap.add_argument("--auto", action="store_true", help="사람 없이 봇끼리 자동 대전")
    ap.add_argument("--hands", type=int, default=100, help="--auto 모드에서 진행할 최대 핸드 수")
    return ap.parse_args()


def build_settings(args: argparse.Namespace) -> GameSettings:
    styles = [s.strip().lower() for s in args.bots.split(",") if s.strip()]
    profiles = [BotProfile.preset(style, name=f"Bot{i + 1}") for i, style in enumerate(styles)]
    hands_per_level = args.hands_per_level
    if args.auto and hands_per_level is None:
        hands_per_level = 15  # 자동 대전은 순식간에 끝나므로 핸드 수 기준 레벨업
    return GameSettings(
        num_players=args.players,
        starting_stack=args.stack,
        level_duration_sec=args.level_minutes * 60 if args.level_minutes > 0 else None,
        hands_per_level=hands_per_level,
        human_seat=None if args.auto else 0,
        bot_profiles=profiles,
        seed=args.seed,
    )


# --------------------------------------------------------------------------- #
# 출력
# --------------------------------------------------------------------------- #
def pad(text: str, width: int, right: bool = False) -> str:
    """한글(전각 2칸)을 고려한 터미널 정렬."""
    cells = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    space = " " * max(0, width - cells)
    return space + text if right else text + space


def render_header(engine: GameEngine) -> None:
    hand = engine.hand
    remaining = engine.blind_clock.seconds_to_next_level()
    timer = f" · 다음 레벨까지 {int(remaining // 60):02d}:{int(remaining % 60):02d}" if remaining else ""
    print(f"\n{'═' * 64}")
    print(f" 핸드 #{hand.number} · 레벨 {hand.level_index + 1} · 블라인드 {hand.level}{timer}")
    print("═" * 64)


def render_table(engine: GameEngine) -> None:
    hand = engine.hand
    print(f"  {'':2}{pad('좌석', 6)}{pad('포지션', 9)}{pad('이름', 10)}{pad('스택', 9, True)}{pad('베팅', 8, True)}  상태")
    for p in engine.players:
        marker = "▶" if hand.to_act == p.seat else " "
        if not p.dealt_in:
            status = "탈락" if p.stack == 0 else "대기"
        elif p.folded:
            status = "폴드"
        elif p.all_in:
            status = "올인"
        else:
            status = ""
        print(f"  {marker} {p.seat:<5}{p.position:<9}{pad(p.name, 10)}{p.stack:>9,}{p.street_bet:>8,}  {status}")
    board = pretty(hand.board) if hand.board else "-"
    print(f"  보드: {board}    팟: {engine.pot:,}")


def coach_panel(report: CoachReport) -> None:
    view = report.view
    print(LINE)
    print(f"  내 홀카드: {pretty(view.hole)}    포지션: {view.position}    SPR: {view.spr:.1f}")
    for line in report.render().splitlines():
        print("  " + line)
    print(LINE)


def print_chart(report: CoachReport) -> None:
    card = report.position
    print(f"\n  {card.open_range.label} {card.open_range.percent():.1%} — [ ] 내 핸드 {card.hand}")
    print("  (오른쪽 위 = 수딧, 대각선 = 페어, 왼쪽 아래 = 오프수트 / # 오픈, . 폴드)")
    for line in card.open_range.render_grid(highlight=card.hand):
        print("  " + line)


def print_result(engine: GameEngine) -> None:
    hand = engine.hand
    result = hand.result
    print(LINE)
    if result.went_to_showdown:
        print(f"  쇼다운 — 보드 {pretty(hand.board)}")
        for seat, rank in sorted(result.showdown.items(), key=lambda kv: kv[1].score):
            p = engine.players[seat]
            print(f"    {p.name:<10}{pretty(p.hole):<8}  {rank}")
    for award in result.awards:
        names = ", ".join(engine.players[s].name for s in award.winners)
        if award.uncalled_return:
            print(f"  ↩ {names}: 콜 되지 않은 {award.amount:,} 반환")
        elif award.hand_name:
            print(f"  ★ {names} 이(가) {award.amount:,} 획득 ({award.hand_name})")
        else:
            print(f"  ★ {names} 이(가) {award.amount:,} 획득 (상대 전원 폴드)")
    for seat in result.busted:
        print(f"  ✖ {engine.players[seat].name} 탈락")


def print_standings(engine: GameEngine) -> None:
    print(f"\n{'═' * 64}\n 최종 칩 순위 ({engine.hands_played}핸드)")
    for p in sorted(engine.players, key=lambda p: -p.stack):
        style = PRESET_DESCRIPTIONS.get(p.profile.style, "") if p.profile else "사람"
        print(f"  {p.name:<10}{p.stack:>10,}   {style}")


# --------------------------------------------------------------------------- #
# 입력
# --------------------------------------------------------------------------- #
def read_human_action(view: PlayerView, report: CoachReport) -> Action:
    legal = view.legal
    print("  " + legal.describe() + "   [y]추천 따르기  [chart]오픈 차트  [q]종료")
    while True:
        raw = input("  > ").strip().lower()
        if raw in ("y", "yes"):
            print(f"  (추천: {report.recommendation.headline})")
            return report.recommendation.to_action()
        if raw in ("chart", "?"):
            print_chart(report)
            continue
        if raw in ("f", "fold"):
            return Action.fold()
        if raw in ("k", "x", "check"):
            return Action.check()
        if raw in ("c", "call"):
            return Action.call()
        if raw in ("a", "allin", "all-in"):
            return Action.all_in()
        if raw in ("q", "quit", "exit"):
            raise KeyboardInterrupt
        if raw[:1] in ("r", "b"):
            parts = raw.split()
            if len(parts) == 2:
                token = parts[1].replace(",", "")
                try:
                    if token.endswith("%"):
                        fraction = float(token[:-1]) / 100
                        to = view.current_bet + fraction * (view.pot + legal.to_call)
                        return Action.raise_to(int(round(to)))
                    return Action.raise_to(int(token))
                except ValueError:
                    pass
        print("  입력 예: f / k / c / r 600 / r 75% / a / y / chart")


# --------------------------------------------------------------------------- #
# 게임 루프
# --------------------------------------------------------------------------- #
def run(engine: GameEngine, args: argparse.Namespace) -> None:
    base_seed = args.seed if args.seed is not None else random.randrange(1 << 30)
    bot_class = RangeBot if args.bot_engine == "range" else RuleBasedBot
    bots = {
        p.seat: bot_class(p.profile, random.Random(base_seed + p.seat))
        for p in engine.players
        if not p.is_human
    }
    coach = Coach(args.equity_iters, random.Random(base_seed - 1))
    interactive = engine.human is not None
    total_chips = sum(p.stack for p in engine.players)
    started = time.perf_counter()

    while not engine.is_game_over() and (interactive or engine.hands_played < args.hands):
        hand = engine.start_hand()
        if interactive:
            render_header(engine)
            human = engine.human
            print(f"  내 홀카드: {pretty(human.hole)} ({human.position})")
        shown_board = 0

        while engine.hand_in_progress:
            p = engine.current_player()
            view = engine.view_for(p.seat)
            if p.is_human:
                render_table(engine)
                report = coach.analyze(view)
                if not args.no_coach:
                    coach_panel(report)
                while True:
                    try:
                        record = engine.apply_action(read_human_action(view, report))
                        break
                    except IllegalActionError as e:
                        print(f"  ⚠ {e}")
            else:
                record = engine.apply_action(bots[p.seat].decide(view))
                if interactive:
                    time.sleep(args.delay)
            if interactive:
                print(f"  · {record}")
                if len(hand.board) > shown_board and engine.hand_in_progress:
                    shown_board = len(hand.board)
                    print(f"\n  ── {hand.street.label}: {pretty(hand.board)}  (팟 {engine.pot:,}) ──")

        if interactive:
            print_result(engine)
            if not engine.is_game_over() and input("\n  Enter: 다음 핸드 / q: 종료 > ").strip().lower() == "q":
                break
        else:
            winners = {s for a in hand.result.awards for s in a.winners if not a.uncalled_return}
            names = ", ".join(engine.players[s].name for s in sorted(winners)) or "-"
            print(f"#{hand.number:>4}  {str(hand.level):<20} 팟 {engine.pot:>8,}  승자: {names}")

    assert sum(p.stack for p in engine.players) == total_chips, "칩 보존 법칙 위반!"
    print_standings(engine)
    if not interactive:
        print(f"\n  {engine.hands_played}핸드 · {time.perf_counter() - started:.1f}초 · 칩 총량 {total_chips:,} 보존 확인")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    engine = GameEngine(build_settings(args))
    try:
        run(engine, args)
    except (KeyboardInterrupt, EOFError):
        print("\n  게임을 종료합니다.")
        print_standings(engine)


if __name__ == "__main__":
    main()
