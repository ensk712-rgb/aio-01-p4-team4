# Claude 6차 수정: codex-5 결함 3건과 `workflows/` 승격

2026-11-02. 격리 하네스(mock LLM)에서만 확인했다. 실제 OpenAI 호출은 없고, git 작업도 하지 않았다.

재현 도구는 `verify/repro_claude6.py`다. 수정 전 결과는 `verify/reports/claude6-f80b6d67-http.json`, 수정 후 결과는 `verify/reports/claude6-abeb3e61-http.json`에 있다.

## 결함별 결과

| 결함 | 수정 전 재현 | 수정 내용 | 회귀 케이스 |
| --- | --- | --- | --- |
| 1. 거절된 타인이 소유 기록을 덮어씀 | **일부 재현** | support에 사전 티켓 주인 확인 추가 | `ADV6-owner-*`, `ADV6-noticket-*`, `ADV6-stale-*` |
| 2. channel 연락처 누출 | **누출은 재현 안 됨**, enum 불일치 | 승인 enum으로 교체, 공통 함수로 통일 | `ADV6-channel-*` |
| 3. ops 잘못된 날짜 500 | **재현 안 됨** | 2000년 이전 날짜도 기본값 처리 | `ADV6-ops-*` |

### 1. handoff 중복 소유권

재현 결과:
- **codex-5 원 시나리오(타인이 티켓까지 요청): 재현 안 됨.** handoff의 「소유 기록 복구」가 원 소유자로 되돌린다.
- **타인 요청이 티켓 없이 끝나는 경로: 재현됨.** 김하늘이 티켓을 만들고 cache가 사라진 뒤, 박서준이 같은 ID로 FAQ를 물으면 자동 답변으로 끝나 복구를 지나지 않는다. 소유 기록이 박서준으로 남고, 김하늘의 재전송은 400 `request_id_conflict`가 됐다.

수정 내용:
- support의 「중복 기록 조회」와 「중복 판정」 사이에 `GET /tickets-created`를 읽는 「티켓 주인 조회」 노드를 추가했다(timeout 800ms). 사라지지 않는 티켓 기록을 cache보다 우선한다.
- 티켓 주인이 다른 사용자면 400 `request_id_conflict`로 거절한다. 「소유 기록」 앞에서 끝나므로 거절된 요청은 소유 cache를 쓰지 못한다.
- cache 주인이 달라도 티켓 주인이 요청자 본인이면 새 요청으로 진행해 기록을 되찾는다.
- 조회가 실패하면 cache로만 판단한다. 이때는 handoff의 주인 확인과 「소유 기록 복구」가 그대로 막는다.

**동작 변경:** cache 소실 뒤 타인 요청의 응답이 `200 + 이관 + reason …:request_id_conflict`에서 **400 `request_id_conflict`**로 바뀐다. 그래서 `verify/repro_codex5.py`의 A-foreign-check는 이제 false로 나온다.

### 2. channel 개인정보 누출

재현 결과:
- `web-010-0000-9901`, `010-0000-9901`, `web@example.com`은 이미 `other`로 기록됐다. 누출은 재현되지 않았다.
- 다만 정규식이 네 곳에 복사돼 있었고, enum이 지시와 달랐으며(`mobile`, `chat`, `telegram`, `slack`, `api`), `String()` 변환 때문에 배열 `["web"]`이 `web`으로 통과했다.

수정 내용:
- `lib/common.js`에 `CHANNELS`(web, app, phone, kiosk, email, other)와 `normalizeChannel`을 추가했다. 문자열이 아니거나 목록에 없으면 `other`다.
- `buildLog`가 직접 정규화한다. 입력 검사, 400 기록 조립, 재생 기록 조립, 실행 기록 조립 네 경로 모두 이 함수를 쓴다.
- 단위 테스트 2건을 추가했다.

`security.masked`와의 관계: channel은 가린 것이 아니라 버린 값이므로 masked에 세지 않는다. 회귀 케이스가 응답과 기록의 masked가 같은지 확인한다.

**동작 변경:** `mobile`, `chat`, `telegram`, `slack`, `api`는 이제 `other`로 기록된다.

### 3. ops 잘못된 달력 날짜

재현 결과:
- `2026-99-99`와 `2026-02-30`은 모두 200이고 기간은 오늘로 처리됐다. 500은 재현되지 않았다. codex-5 이후 들어간 `valid()` 검사가 막고 있다.
- 추가 입력 `0000-01-01`은 500은 아니지만 `query_from`이 `-000001-12`로 깨졌다.

수정 내용: `valid()`가 2000년 이전 날짜도 거절해 오늘로 처리한다.

## 승격

- `build.mjs`는 저장소 뿌리 `workflows/`에 쓴다. `compose.yml`, `up.sh`, `reload.sh`, `render.mjs`, 옛 점검 도구 2개의 경로도 바꿨고, `drafts/n8n/workflows/`는 삭제했다.
- 생성 결과는 10개 파일, 216노드다(「티켓 주인 조회」 1개 추가). 노드 type/typeVersion은 새 종류가 없다. credential id 3개, `http://data-api:8800` 주소, 워크플로우 이름, 웹훅 경로는 그대로다.
- `runner.py`에 `raw_contract`, `log_channel`, `log_rows` 규칙을 추가했다. `--suite all`은 스위트별 보고서도 함께 남긴다. 설명 화면이 스위트별 최신 보고서를 읽기 때문이다.
- 기존 adversarial 케이스와 `cases/*.json`의 기대값은 바꾸지 않았다.

## 최종 실행 결과

`node --test lib/test/*.test.js`는 18/18, `python3 -B test_harness.py`도 18/18 통과했다.

`python3 -B runner.py --suite all --repeat 2`는 **129/129** 통과했다. adversarial은 러너 설계상 순서가 있어 반복 값과 무관하게 1회만 돈다.

| 스위트 | 통과 | 보고서 |
| --- | --- | --- |
| 전체 | 129/129 | `drafts/n8n/verify/reports/all-20261102-152831-721723.json` |
| common (17×2) | 34/34 | `drafts/n8n/verify/reports/common-20261102-152831-792681.json` |
| team (12×2) | 24/24 | `drafts/n8n/verify/reports/team-20261102-152831-823132.json` |
| adversarial (기존 48 + 신규 23) | 71/71 | `drafts/n8n/verify/reports/adversarial-20261102-152831-843348.json` |

하네스는 `./down.sh`로 내렸고, `day65-*`, `day67-*` 컨테이너는 건드리지 않았다. 설명 화면 `ticketmoa-workflows.html`도 다시 만들었다.

## 남은 위험

- **회귀 케이스의 수정 전 실행 없음:** `ADV6-*`는 수정 전 코드에서 돌리지 않았다. 수정 전 실패 근거는 재현 스크립트의 결과뿐이다.
- **지연 증가:** 새 요청마다 `GET /tickets-created`가 1회 늘어난다(실패 시 최대 800ms). 티켓 수에 비례해 응답도 커진다. 모의 환경의 시간 제한 시나리오는 통과했지만, 실서버 부하는 측정하지 않았다.
- **티켓 없는 요청의 소유권:** 티켓이 없으면 내구 기록이 없다. cache 소실 뒤 타인이 먼저 쓰면 원 사용자가 400을 받을 수 있다. 노출되는 정보는 없고 새 ID로 다시 보내면 된다.
- **동시 요청:** GET/POST cache에는 CAS가 없어 동시 소유 예약의 경합을 막지 못한다. 티켓 번호 노출은 handoff 확인이 막는다.
- **cache 소실 뒤 같은 사용자의 다른 질문:** 지문이 티켓에 남지 않아, 같은 ID로 다른 질문을 보내면 기존 티켓이 duplicate로 돌아올 수 있다.
- **enum 변경:** 호출자가 다른 channel 값을 보내면 집계에서 `other`로 합쳐진다. 400 충돌 코드(`request_id_conflict`)는 공통 계약에 없는 코드로, 여전히 리드 확인 대상이다.
- **문서 미반영:** `lib/README.md`의 함수 표에 `normalizeChannel`을 넣지 못했다. 이번 수정 허용 범위 밖이다.
- **mock 한계:** mock 통과는 실제 LLM의 답변 품질, 운영 부하, SDK 내부 재시도를 보증하지 않는다. codex-5의 시간 예산, 저장소 원자성 위험도 그대로다.
- **담당 규칙:** 파일 10개를 `workflows/`에 한꺼번에 올린 것은 지시에 따른 것이다. AGENTS 4절의 담당자별 파일 규칙과는 맞지 않으므로 병합 때 담당자 확인이 필요하다.
