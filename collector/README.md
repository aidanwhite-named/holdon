# KB증권 데이터 수집기

장중에 체결·호가·외국계 창구·투자자 추정·프로그램 매매·지수를 모아 `data/YYYYMMDD/`에 CSV로 쌓습니다.

## 준비
1. KB증권 홈페이지 → 고객서비스 → Open API에서 사용 신청 후 appKey/appSecret 발급
2. `config.example.json`을 `config.json`으로 복사하고 키 입력
   (또는 환경변수 `KB_APP_KEY`, `KB_APP_SECRET`). `config.json`은 git에 올라가지 않습니다.
3. `pip install requests`

## 실행
```bash
python collector/collect.py            # 08:55까지 기다렸다가 15:35까지 수집
python collector/collect.py --now      # 바로 시작
python collector/collect.py --mock --now --minutes 1   # 키 없이 파이프라인 테스트
```
30초마다 종목별 수집 건수, 누락량(폴링이 느려 놓친 체결량), 오류 수를 출력합니다.
누락량이 계속 늘면 `intervals.ticks`를 줄이거나 `tick_fetch_count`를 늘리세요.

## 재생 파일 만들기
```bash
python collector/to_replay.py 20261103 005930
```
`viz/replay/20261103_005930.json`이 생기고, `viz/arena3d.html`의 "실데이터 재생"에서 열면
그날 장을 그대로 다시 돌리면서 매매 전략이 어떻게 반응했을지 볼 수 있습니다.

## 주의
- 토큰은 접속한 IP/MAC에 묶입니다. 같은 PC, 같은 네트워크에서 계속 실행하세요.
- 호출 한도가 공개되어 있지 않아 기본 초당 4회로 시작하고, 거부되면 자동으로 늦춥니다.
- 첫 실행 때 `data/날짜/raw/`에 각 API의 실제 응답이 저장됩니다. 필드 형식이 예상과 다르면 이걸 보고 고칩니다.
- 체결 데이터에는 투자자·거래원 정보가 없습니다. 재생 파일의 개인/외인/기관 구분은 외국계 창구와 투자자 추정치의 증가분으로 배분한 추정값입니다.
