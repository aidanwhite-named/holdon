# Hold'on — 텍사스 홀덤 학습 시뮬레이터

봇과 실제로 플레이하면서 포지션 · 에쿼티 · 팟 오즈 · 아웃츠 · 상대 레인지를 실시간으로 배우는 학습용 시뮬레이터.

## 기술 스택 (추천과 이유)

| 영역 | 선택 | 이유 |
|---|---|---|
| 언어 | **Python 3.11+** | 포커 수학/시뮬레이션 생태계, 빠른 프로토타이핑 |
| 족보 판정 | **treys 0.1.8** | 검증된 Cactus Kev 룩업 기반 평가기, 순수 Python(설치 문제 없음), 7장 평가 약 10만 회/초 |
| 에쿼티 | 자체 몬테카를로 (treys 사용) | 상대 수 · 상대 레인지 지정 가능, 표준오차 2,000회 기준 ±1.1%p |
| UI (3단계) | **Streamlit** | 카드/지표/차트 "도우미 카드" UI를 가장 빨리 만듦. `st.fragment(run_every=…)`로 블라인드 타이머 표시 |
| 테스트 | pytest | 규칙(사이드팟·최소레이즈 등) 회귀 방지 |

> 엔진은 UI와 완전히 분리된 **한 액션씩 진행하는 상태 머신**이라 Streamlit의 rerun 모델에 그대로 맞고,
> 나중에 Pygame(게임 느낌) 또는 FastAPI + React(웹 서비스)로 바꿔도 코어는 그대로 쓸 수 있다.
> 속도가 더 필요하면 `eval7`(C 확장)로 `evaluator.raw_score`만 교체하면 된다.

## 프로젝트 구조

```
Hold_on/
├─ main_cli.py              # 1단계 실행 진입점 (터미널 플레이 / 봇 자동 대전)
├─ holdem/                  # UI 독립 코어
│  ├─ config.py             # GameSettings(인원·바이인·블라인드), BotProfile(스타일·실력)
│  ├─ blinds.py             # BlindLevel, 딥스택 구조, 타이머/핸드수 기반 BlindClock
│  ├─ cards.py              # 덱, 카드 파싱/표시 (treys 정수 카드)
│  ├─ evaluator.py          # 족보 판정 래퍼 (HandRank, 한글 족보명)
│  ├─ equity.py             # 몬테카를로 에쿼티, 아웃츠, 위협/넛 분석, 팟 오즈
│  ├─ positions.py          # 2~10인 포지션 이름 (SB, BB, UTG, HJ, CO, BTN …)
│  ├─ pots.py               # 메인/사이드 팟 계산
│  ├─ models.py             # Action, Player, LegalActions, PlayerView, HandResult
│  ├─ engine.py             # 게임 엔진 (베팅 라운드, 쇼다운, 분배)
│  └─ bots/
│     ├─ base.py            # Bot 프로토콜: decide(PlayerView) -> Action
│     └─ rule_bot.py        # 1단계 봇: 에쿼티 + 팟 오즈 + 스타일 파라미터
├─ holdem/ranges.py, charts.py   # (2) 레인지 표기법 · 프리플랍 차트
├─ holdem/coach/                # (2) 실시간 코칭 (아래 표)
├─ holdem/bots/range_bot.py     # (2) 코치 기반 봇
├─ app/                         # (3) 웹 UI
│  ├─ streamlit_app.py          #     화면 구성 (설정 · 테이블 · 액션 · 코칭 탭 · 타이머 · 기록)
│  ├─ session.py                #     GameSession: 엔진+봇+코치, 사람 차례까지 자동 진행, 로그/핸드 요약
│  └─ components.py             #     HTML 컴포넌트 (타원형 테이블, 카드, 13×13 차트, 구성 막대)
└─ tests/                       # 85개 (엔진 규칙 / 에쿼티 / 레인지 / 코칭 / UI 세션 + 헤드리스 앱)
```

## 실행

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

.venv\Scripts\python -m streamlit run app/streamlit_app.py           # 웹 UI → http://localhost:8501

.venv\Scripts\python main_cli.py                                   # 6인 (나 + 봇 5)
.venv\Scripts\python main_cli.py --players 9 --stack 20000 --level-minutes 5
.venv\Scripts\python main_cli.py --players 4 --bots tag,lag,rock   # 봇 스타일 지정
.venv\Scripts\python main_cli.py --auto --hands 300 --seed 7       # 봇끼리 자동 대전
.venv\Scripts\python -m pytest -q
```

입력: `f` 폴드 · `k` 체크 · `c` 콜 · `r 600` 600까지 레이즈 · `r 75%` 팟의 75% · `a` 올인 · `q` 종료

봇 프리셋: `tag`(정석) · `lag`(공격) · `rock`(초타이트) · `station`(콜링 스테이션) · `fish`(초보) · `maniac`

## 1단계 구현 내용

**엔진 규칙**: 앤티/블라인드, 헤즈업(버튼 = SB, 프리플랍 선행동), BB 옵션, 최소 레이즈 = 직전 풀 레이즈 크기,
불완전 올인 레이즈는 이미 행동한 플레이어에게 재레이즈 권한을 주지 않음, 콜 되지 않은 베팅 반환,
사이드 팟, 스플릿 팟(홀수 칩은 버튼 왼쪽부터), 올인 시 남은 보드 자동 런아웃, 탈락자 건너뛰기, 블라인드 레벨업(시간/핸드 수).

**도우미 수치 (CLI 패널)**: 포지션 · SPR · 현재 족보 · 몬테카를로 에쿼티(승/무/패, 평균 몫 대비 배수) ·
팟 오즈와 +EV/-EV 판정 · 아웃츠(족보별 카드, 다음 카드/리버까지 확률, 2&4 법칙) ·
위협 분석(나를 이기는 상대 콤보 수와 족보별 분포, 넛 순서).

**엔진 사용법 (UI가 붙는 방식)**

```python
engine = GameEngine(GameSettings(num_players=6, starting_stack=10_000))
engine.start_hand()
while engine.hand_in_progress:
    p = engine.current_player()
    view = engine.view_for(p.seat)          # 그 플레이어가 볼 수 있는 정보만
    action = ask_user(view) if p.is_human else bots[p.seat].decide(view)
    engine.apply_action(action)             # 불법 액션이면 IllegalActionError
result = engine.hand.result                 # 팟 분배, 쇼다운 족보, 손익
```

## 2단계 코칭 엔진 (구현 완료)

| 모듈 | 내용 |
|---|---|
| `holdem/ranges.py` | 레인지 표기법(`TT+, A2s+, A5s-A2s, KQo:0.5`) ↔ 콤보, 가중치 레인지, 13×13 그리드 |
| `holdem/charts.py` | 오픈(뒤에 남은 인원 기준) · 3벳 · 콜 · BB 디펜스 · 4벳 · 림프 · 숏스택 푸시 차트 |
| `coach/position_advisor.py` | ① 포지션 특성 · 기본 오픈 레인지 · 운용 팁 · IP/OOP |
| `coach/board.py` | 보드 텍스처(드라이/웻), 메이드 핸드 카테고리, 드로우 판정 |
| `coach/hand_reader.py` | ④ 상대 행동 → 프리플랍 차트 레인지 → 스트리트별 카테고리 가중치로 축소, 구성 비율·대응 가이드 |
| `coach/action_advisor.py` | ③ 추천 액션·사이즈 + 근거 (팟 오즈, 콜 EV, MDF, 블러프 손익분기, SPR, 임플라이드 오즈) |
| `coach/coach.py` | `Coach.analyze(view)` → 도우미 카드 4종 (`CoachReport.cards()` 는 UI 에 그대로 사용) |
| `bots/range_bot.py` | 코치 추천을 따르되 스타일(타이트/공격성/블러프)·실력만큼 벗어나는 봇 (기본) |

CLI 추가 입력: `y` 추천 따르기 · `chart` 내 포지션 오픈 차트 · `--no-coach` 코칭 숨기기 · `--bot-engine rule` 1단계 봇

한계: 차트는 100BB 캐시 기준 근사치(솔버 결과 아님), 핸드 리딩 가중치는 학습용 휴리스틱, 상대 성향(통계) 반영은 아직 없음.

## 3단계 웹 UI (구현 완료)

- **사이드바 설정**: 인원(2~10), 바이인, 블라인드 레벨업(분 / N핸드), 봇 엔진, 코치 시뮬레이션 횟수, 시드, 봇별 스타일
- **블라인드 타이머**: 1초마다 갱신(`st.fragment(run_every=1)`), 일시정지/재개, 레벨업은 다음 핸드부터 적용
- **테이블**: 내 자리를 아래에 둔 타원형 테이블 — 포지션 배지, 스택, 이번 스트리트 액션, 베팅 칩, 딜러 버튼,
  쇼다운 시 카드 공개와 승자 강조
- **액션 패널**: 폴드 / 체크·콜 / 올인 / 추천 따르기 + 사이즈 프리셋(프리플랍 2.5BB·3BB, 포스트플랍 33·50·75%·팟)과 슬라이더
- **단축키**: `F` 폴드 · `K` 체크/콜 · `B` 벳/레이즈 · `A` 올인 · `Y` 추천 따르기 · `N` 다음 핸드
  (Streamlit 이 `C`·`R` 을 예약해 두어 콜은 `K`)
- **코칭**: 상단 요약(포지션 · 에쿼티 · 필요 승률 · 추천) + 탭 ① 포지션(레인지 차트 7종 선택) ② 에쿼티(아웃츠·위협)
  ③ 추천 근거 ④ 핸드 리딩(상대별 레인지 구성 막대) — 사이드바에서 끄면 실전 연습 모드
- **복기**: 핸드 로그, 핸드 기록 표, 누적 손익 차트, 마지막 쇼다운

## 로드맵 (다음 아이디어)

- 상대 성향 통계(VPIP/PFR/3벳%)를 기록해 핸드 리딩 레인지에 반영
- 핸드 히스토리 저장/불러오기, 특정 상황(예: BTN vs BB 3벳 팟) 반복 드릴 모드
- 추천과 내 실제 액션의 차이를 집계하는 '리크(leak) 리포트'
