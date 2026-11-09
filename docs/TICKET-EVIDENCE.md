# 티켓 담당·저장 근거 · 티켓모아

환불 처리 단계, 티켓 담당, 저장 위치, 장애 로그 확인 결과를 이 문서 하나에서 본다. 숫자는 시험 원본에서 옮기고, 시험 기대값은 바꾸지 않는다.

**현재 시연 정책:** 로그인·사용자 인증은 의도적으로 제공하지 않는다. 본인 문의 조회와 환불 2단계(고객 확정 후 티켓)를 제공한다. 로그인이 없어 요청의 `user`는 본인 확인이 아니다. 기록의 `requester`와 일치해야 조회되므로 내 이름으로 남의 건은 볼 수 없지만, 다른 사람 이름을 입력하는 사칭은 막지 못한다. 데이터는 모두 가짜이고 연락처는 가려서 답한다. 11/07 팀 결정으로 비로그인 일괄 차단을 되돌렸고, 최신 T행에서 SEC-03~08과 TM-02·03·13이 통과했다(`runs/vm/tm-reg-security-permissions-20261107-094212.json`, `runs/vm/tm-reg-team-20261107-094054.json`).

## 1. 과거 환불 3단계 설계·시험 기록 (현재 제공 기능 아님)

| 단계 | 누가 | 조건 | 남는 것 | 티켓 | 근거 |
| --- | --- | --- | --- | --- | --- |
| 환불 안내 | 규칙(Code) | 본인 예매, 예외 아님 | `/cache` 견적 `pending` (30분) | 없음 (`ticket: null`) | TM-02, `refund_quote_pending_confirm` |
| 환불 요청 티켓 | 규칙(Code) | 같은 예매 + boolean `context.confirm=true` + 재계산 일치 | `/tickets-created`, 견적 `confirmed` | `refund` 1건 | TM-03, `refund_confirmed` |
| 예외 이관 티켓 | 규칙(Code) | 관람 당일, 환불 예정액 30만원 초과 | `/tickets-created` | `refund_exception` 1건 | TM-06 `show_day_cancel`, TM-13 `over_limit` |
| 실제 취소·환불 | 상담원 | 티켓을 받은 뒤 | 이 시스템에 없음 | 해당 없음 | 호출 노드 없음 |

- 티켓 생성은 환불 완료가 아니다. 답변은 "실제 취소와 환불은 상담원이 처리합니다"로 안내한다.
- 워크플로우 전체의 호출 주소에 취소·환불 실행 API가 없다. `security/refund-ontology.json`의 `forbidden_actions`에도 실제 예매 취소와 결제 취소가 있다.
- 실제 환불 실행은 시험하거나 실행한 적이 없다. 상담원이 처리했다는 기록도 이 시스템에는 남지 않는다.

## 2. 티켓 담당

담당은 `lib/common.js`의 `ticketAssignee(category, priority)` 규칙으로 정한다. LLM이나 고객이 보낸 값으로 정하지 않는다.

| 조건 (위에서부터 적용) | 담당 | 해당 티켓 |
| --- | --- | --- |
| `priority=high` | 현장 스태프 | 공연 직전 입장 장애 (WF-12) |
| `category=scalping_report` | 보안팀 | 암표 신고 |
| 그 밖의 모든 경우 | CS 상담원 | `refund`, `refund_exception`, `payment_error`, 상담원 연결, 미분류 `unknown` (WF-02b·03·10) |

- 담당은 역할까지만 정한다. 개인 배정과 처리 상태 변경은 이 시스템 범위 밖이다.
- 응답의 `ticket.assignee`와 저장되는 `title`(`[refund · 담당 CS 상담원] ...`)에 남는다. 데이터 API는 `title, requester, category, priority`만 저장해 별도 담당 칸이 없다.
- 티켓을 만들지 못하면 DLQ 항목의 `assignee`에 남는다.

## 3. 저장 위치

| 내용 | 위치 | 묶는 값 | 유지 기간 |
| --- | --- | --- | --- |
| 티켓 | 데이터 API `GET /tickets-created` | `key`=`request_id`, `ticket_id` | 메모리, 재시작 또는 `/tickets-reset`까지 |
| 환불 견적 (과거 구현) | 데이터 API `/cache/refund-pending:<user>:<booking_id>` | 사용자, 예매 | 당시 30분; 현재 개인별 견적 경로 미제공 |
| 긴급·장애 알림 | 데이터 API `GET /alerts` | `request_id`, `ticket_id` | 메모리 |
| 실패 대기열 | 데이터 API `GET /dlq` | `item.id`=`request_id` | 메모리 |
| 실행 기록 | 데이터 API `GET /logs?source=live` | `request_id`, `ticket` | 메모리 |
| 시험 원본 | 저장소 `runs/`, `runs/vm/` | 보고서 파일 | 저장소에 영구 |

WF-11처럼 티켓 API가 지연되면 응답은 `ticket: null`과 DLQ로 끝나도, 데이터 API가 지연 뒤 티켓을 저장한다(`T-2047`, `T-2055`). DLQ를 재처리해도 `key`가 같아 새 티켓이 생기지 않으므로 알려진 동작으로 둔다. 재처리 전에 `/tickets-created`에서 `key`를 먼저 찾는다.

연습용 데이터 API는 메모리에만 저장한다. 데이터 API를 재시작하면 티켓과 로그가 사라지므로, 영구 근거는 `runs/vm/`의 스냅샷이다.

## 4. VM 확인 상태

**과거 수정본 배포 기록.** 2026-11-06 VM의 두 공통 시나리오(개인정보 차단 정책이 적용되기 전)는 1회차(03:38~03:40 UTC, 재시작·재색인 직후) **50/51**, 2회차(03:45~03:47 UTC, 재시작 없음) **51/51**이다. 두 결과를 합산하지 않는다. 아래 표는 당시 1회차 기준이며, 현재 비로그인 정책 시험으로 해석하지 않는다.

| 항목 | 결과 |
| --- | --- |
| 배포본 해시 | support `d9ed571daa0d`, handoff `e8b895015bcb`, common `ecadb347d5d8`. 로컬과 일치 |
| 재색인 | 문서 8/8, 42청크, 고객·직원 검색 확인 |
| 공통 17개 × 3회 | **50/51.** 미달은 재시작·재색인 직후 첫 WF-01 8.7초 (기준 8초). 2·3회차는 6.1초, 5.9초 |
| WF-04 로그 | 3/3 `error`, `dependency`, `error_message=ticket_not_created`. 사유 `unregistered_intent`는 유지 |
| 티켓 담당 | 새 티켓 8건의 `title`에 저장. WF-12 `현장 스태프`, TM-13·WF-02b·03·05·09·10·11 `CS 상담원` |
| 응답 `ticket.assignee` | WF-12 `현장 스태프`, TM-13 `CS 상담원` 등 티켓이 있는 응답에서 확인 |
| 기존 티켓 보존 | 전체 초기화 없이 41→49건. `T-2016`(`refund`) 유지 |
| 시험 후 상태 | 장애 설정 모두 `ok`, OpenAI Credential 복구 |

- 2회차: WF-01 6.6/6.2/5.8초, WF-04 로그 3/3 `error`·`ticket_not_created`, 새 티켓 7건에 담당 저장, 전체 티켓 56건, `T-2016` 유지, 장애 설정 모두 `ok`.
- 시험 방법: `cases/common.json` 기대값은 바꾸지 않았다. 기존 티켓을 지우지 않으려고 임시 복사본에서 최상위 `/tickets-reset`만 빼고 요청 ID 앞에 `ev033521-`, `ev034541-`를 붙였다.
- 이번 수정은 로그 분류와 티켓 담당만 바꿨고 WF-01이 지나는 분류·검색·작성 단계는 바꾸지 않았다. 첫 호출의 분류는 3.5초, tech는 4.5초로 2·3회차(분류 1.7~1.8초, tech 3.5~3.8초)보다 길었다. 근본 원인은 확인하지 못했다. 재시작 직후 첫 호출의 간헐 지연은 해결됐다고 쓰지 않는다.
- 담당 규칙이 적용된 환불 티켓은 `refund_exception`(`T-2049`)만 VM에서 확인했다. `refund` 요청 티켓은 같은 코드 경로지만 이번에 새로 만들지 않았다.

후속 전체 회귀는 `EXECUTION-RESULT.md`에 별도로 기록한다. 최신은 2026-11-07 18:33~18:43 KST T행: 공통 **51/51**, 팀 **13/13**, 보안 **8/8**, `bench -n 5` p50 5.61초·p95 6.59초(실패 0/5). 재시작·재색인·예열 뒤 측정이다. 같은 워크플로우의 예열 없는 S행은 공통 **50/51**, 차단 정책 시기 R행은 공통 **48/51**, 16:10 O행은 공통 **50/51**, 팀 **11/13**(TM-02·TM-03은 당시 기대값 기준 실패)이며 합치지 않는다.

원본: [공통 50/51](../runs/vm/ticket-evidence-common-20261106-034042.json), [TM-13](../runs/vm/ticket-evidence-tm13-20261106-034045.json), [로그·티켓](../runs/vm/ticket-evidence-logs-tickets-20261106-034045.json). 2회차: [공통 51/51](../runs/vm/ticket-evidence-common-20261106-034742.json), [로그·티켓](../runs/vm/ticket-evidence-logs-tickets-20261106-034742.json).

아래 표는 수정 배포 **전** 읽기 전용 조회 결과다. 원본은 [스냅샷](../runs/vm/failure-log-snapshot-20261106.json)에 있다.

| 장애 경로 | VM `/logs` 기록 | 판정 |
| --- | --- | --- |
| 분류 LLM 멈춤 (WF-10) | `error`, `agents_failed`, `dependency` 6건, 티켓 `T-2039` 등 | 확인 |
| 조회 API 지연 (WF-11) | `error`, `payment_failed`, `dependency` 6건 | 확인 |
| 작성 LLM timeout | `error`, `llm_unavailable`, `dependency` 1건, 티켓 `T-2034`. 측정 중 자연 발생 | 확인 (1건) |
| 검증 품질 거절 | `error`, `verification_failed`, `verification_rejected` 3건. `verification_issues` 보존 | 확인 |
| 근거 없는 정상 이관 대조 | WF-03 `unregistered_intent`는 `success` | 확인 |
| 티켓 API 장애 (WF-04) | **`success`로 기록됨.** 사유가 `unregistered_intent`로 남아 장애로 분류되지 않음 | **버그, 위 재시험에서 수정 확인** |
| 검증 호출 timeout (`verification_timeout`) | 0건 | VM 미확인, 로컬 단위 시험만 |
| 검증 LLM 장애 (`issues: llm_unavailable`) | 당시 0건. 이후 재시작 측정에서 1건 (`error`, `dependency`, `verification_failed`, 티켓 `T-2057`, `runs/vm/wf01-restart-20261106.json`) | 자연 발생 1건 확인. 실패 원인은 미확인 |

당시 `/tickets-created`는 41건이다. 환불 3단계 시험의 `T-2016`(`refund`), `T-2018`·`T-2019`(`refund_exception`)가 카테고리까지 일치한다. 이 티켓들은 담당 규칙 이전에 만들어져 `title`에 담당이 없다.

로컬 단위 시험은 42/42, `flow.py check`는 오류 없음이다. SSH 경로(포트 45622)가 2026-11-06 12:15 KST부터 시간 초과라 이번 배포는 웹 터미널에서 했고, 해시로 로컬과 같음을 확인했다.
